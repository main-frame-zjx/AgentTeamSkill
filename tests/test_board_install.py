"""Installer checks; set AT_TEST_BOARD_START=1 for a cold Windows/Node/npm smoke test."""

import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "requires Windows Shell links")
class DesktopShortcutTests(unittest.TestCase):
    def test_shortcut_only_migration_and_repeat(self):
        with tempfile.TemporaryDirectory(prefix="at-shortcuts-") as temp:
            desktop = Path(temp)
            tools = ROOT / "tools/windows"
            env = dict(os.environ, AT_DESKTOP=str(desktop), AT_TOOLS=str(tools),
                       AT_PREVIOUS=str(ROOT / "skills/at-start-board/scripts/start-board.ps1"))
            shell = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "RemoteSigned"]

            def com(script):
                header = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
                          "$ws=New-Object -ComObject WScript.Shell; ")
                return subprocess.check_output(shell + ["-Command", header + script], env=env, encoding="utf-8")

            com("""
                $old=$ws.CreateShortcut((Join-Path $env:AT_DESKTOP 'AgentTeamBoard.lnk'))
                $old.TargetPath=Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
                $old.Description='Open Agent Team Board'
                $old.WorkingDirectory=Split-Path $env:AT_PREVIOUS
                $old.Arguments='-NoProfile -ExecutionPolicy RemoteSigned -WindowStyle Hidden -File "' +
                    $env:AT_PREVIOUS + '" -FromShortcut -Port 47361'
                $old.Save()
                $vbs=$ws.CreateShortcut((Join-Path $env:AT_DESKTOP 'Agent Team Board.lnk'))
                $vbs.TargetPath=Join-Path $env:SystemRoot 'System32/wscript.exe'
                $vbs.Arguments='//Nologo "'+(Join-Path $env:AT_TOOLS 'desktop-services.vbs')+'" board'
                $vbs.Save()
            """)
            generate = shell + ["-File", str(tools / "set-desktop-shortcuts.ps1"),
                                "-DesktopDirectory", str(desktop)]
            subprocess.run(generate, check=True, capture_output=True)
            first = {p.name: p.stat().st_mtime_ns for p in desktop.iterdir()}
            subprocess.run(generate, check=True, capture_output=True)
            self.assertEqual(first, {p.name: p.stat().st_mtime_ns for p in desktop.iterdir()})
            expected = {"AgentTeam 技能看板": ("AgentTeamHandbook.exe", "handbook"),
                        "Agent Team Board": ("AgentTeamBoard.exe", "board"),
                        "AgentTeamStopService": ("AgentTeamStopService.exe", "stop")}
            rows = json.loads(com("""
                $links=foreach($item in Get-ChildItem -LiteralPath $env:AT_DESKTOP) {
                    $link=$ws.CreateShortcut($item.FullName)
                    [pscustomobject]@{name=$item.BaseName;target=$link.TargetPath;icon=$link.IconLocation;
                        directory=$link.WorkingDirectory;arguments=$link.Arguments}
                }
                ConvertTo-Json -InputObject @($links) -Compress
            """))
            self.assertEqual(set(expected), {r["name"] for r in rows})
            for r in rows:
                exe, action = expected[r["name"]]
                self.assertEqual(Path(r["target"]), tools / exe)
                self.assertEqual(Path(r["directory"]), tools)
                self.assertEqual(r["icon"], str(tools / "icons" / f"agentteam-{action}.ico") + ",0")
                self.assertEqual(r["arguments"], "")
            # A different program using the historical name must survive.
            com("""
                $other=$ws.CreateShortcut((Join-Path $env:AT_DESKTOP 'AgentTeamBoard.lnk'))
                $other.TargetPath=Join-Path $env:SystemRoot 'notepad.exe'
                $other.Save()
            """)
            subprocess.run(generate, check=True, capture_output=True)
            self.assertTrue((desktop / "AgentTeamBoard.lnk").is_file())
            com("""
                $other=$ws.CreateShortcut((Join-Path $env:AT_DESKTOP 'Agent Team Board.lnk'))
                $other.TargetPath=Join-Path $env:SystemRoot 'notepad.exe'
                $other.Save()
            """)
            conflict = subprocess.run(generate, capture_output=True)
            self.assertNotEqual(conflict.returncode, 0)
            self.assertTrue(com("$ws.CreateShortcut((Join-Path $env:AT_DESKTOP 'Agent Team Board.lnk')).TargetPath")
                            .strip().endswith("notepad.exe"))


class BoardInstallation(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="at-board-")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.dest = self.base / "中文 技能目录"
        self.source = ROOT
        self.install()
        self.skill = self.dest / "at-start-board"
        self.board = self.skill / "assets/board"

    def install(self):
        subprocess.run([sys.executable, "-B", str(self.source / "install.py"), "--dest", str(self.dest)],
                       check=True, capture_output=True)

    def test_installed_runtime_is_complete_and_repeatable(self):
        self.install()
        self.assertEqual(len(list(self.dest.glob("at-*/SKILL.md"))), 14)
        manifest = json.loads((self.skill / ".agentteam-install.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(manifest["source_root"]), self.source)
        cli = self.dest / "at-init-team/scripts/at.py"
        output = subprocess.check_output([sys.executable, "-B", str(cli), "help", "--root", str(self.base)])
        self.assertEqual(len(json.loads(output)["result"]["catalog"]), 14)
        self.assertTrue((self.board / "package-lock.json").is_file())
        self.assertTrue((self.board / "src/App.vue").is_file())
        self.assertTrue((self.board / "server/start.mjs").is_file())
        self.assertFalse((self.board / "dist").exists())
        self.assertFalse((self.board / "node_modules").exists())

    @unittest.skipUnless(os.name == "nt" and os.environ.get("AT_TEST_BOARD_START") == "1",
                         "requires Windows, Node 22.12+ and npm install access")
    def test_cold_start_shortcut_restart_reuse_and_port_conflict(self):
        # Build and run from a separate checkout, including its handbook and GUI launchers.
        self.source = self.base / "中文 源码"
        for folder in ("board", "skills", "dev-visual", "tools/windows"):
            shutil.copytree(ROOT / folder, self.source / folder,
                            ignore=shutil.ignore_patterns("dist", "node_modules", "__pycache__"))
        shutil.copy2(ROOT / "install.py", self.source)
        self.install()
        desktop = self.base / "临时 桌面"
        desktop.mkdir()
        env = dict(os.environ, LOCALAPPDATA=str(self.base / "AppData"),
                   npm_config_cache=str(self.base / "npm-cache"), npm_config_update_notifier="false")
        with socket.socket() as reserve, socket.socket() as second:
            reserve.bind(("127.0.0.1", 0))
            second.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
            handbook_port = second.getsockname()[1]
        script = self.skill / "scripts/start-board.ps1"
        shell = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "RemoteSigned"]

        def run(args, ok=True):
            p = subprocess.run(shell + args, cwd=self.base, env=env, capture_output=True,
                               stdin=subprocess.DEVNULL, timeout=360)
            output = (p.stdout + p.stderr).decode(errors="replace")
            for pid in re.findall(r"Server PID: (\d+)", output):
                servers.add(int(pid))
            if ok:
                self.assertEqual(p.returncode, 0, output)
            else:
                self.assertNotEqual(p.returncode, 0, output)
            return output

        servers = set()
        def stop(pid):
            os.kill(pid, 15)
            servers.remove(pid)
        def cleanup():
            for pid in list(servers):
                try:
                    stop(pid)
                except OSError as error:
                    if getattr(error, "winerror", None) != 87:
                        raise
        self.addCleanup(cleanup)
        launch = ["-File", str(script), "-NoBrowser", "-DesktopDirectory", str(desktop),
                  "-HandbookPort", str(handbook_port), "-Port", str(port)]
        url = f"http://127.0.0.1:{port}"
        run(launch)
        with urlopen(url, timeout=3) as page:
            self.assertIn(b'id="app"', page.read())
        self.assertEqual(len(servers), 2)
        with urlopen(f"http://127.0.0.1:{handbook_port}/api/health", timeout=3) as response:
            handbook_pid = json.load(response)["pid"]
        self.assertIn(handbook_pid, servers)
        self.install()
        run(launch)
        self.assertEqual(len(servers), 2)
        self.assertEqual({p.name for p in desktop.iterdir()},
                         {"Agent Team Board.lnk", "AgentTeam 技能看板.lnk", "AgentTeamStopService.lnk"})
        env["AT_TEST_LINK"] = str(desktop / "Agent Team Board.lnk")
        read_link = "$link=(New-Object -ComObject WScript.Shell).CreateShortcut($env:AT_TEST_LINK); "
        stop(next(pid for pid in servers if pid != handbook_pid))
        # Execute the exact .lnk command line, with browser UI suppressed for the test.
        run(["-Command", read_link + "$p=Start-Process -FilePath $link.TargetPath -ArgumentList "
             "($link.Arguments+' -NoBrowser') -WorkingDirectory $link.WorkingDirectory -WindowStyle Hidden "
             "-PassThru; $p.WaitForExit(); exit $p.ExitCode"])
        with urlopen(url + "/api/health", timeout=3) as health:
            self.assertEqual(json.load(health)["app"], "agent-team-board")
        # The shortcut started a detached server; identify only this sandbox's listener.
        pid = int(run(["-Command", f"(Get-NetTCPConnection -State Listen -LocalPort {port}).OwningProcess"]).strip())
        servers.add(pid)
        stop(pid)
        with socket.socket() as other:
            other.bind(("127.0.0.1", 0))
            other.listen()
            self.assertIn("in use", run([*launch[:-1], str(other.getsockname()[1])], ok=False))
