"""Installer checks; set AT_TEST_BOARD_START=1 for a cold Windows/Node/npm smoke test."""

import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import unittest
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


class BoardInstallation(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="at-board-")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.dest = self.base / "中文 技能目录"
        self.install()
        self.skill = self.dest / "at-start-board"
        self.board = self.skill / "assets/board"

    def install(self):
        subprocess.run([sys.executable, "-B", str(ROOT / "install.py"), "--dest", str(self.dest)],
                       check=True, capture_output=True)

    def test_installed_runtime_is_complete_and_repeatable(self):
        self.install()
        self.assertEqual(len(list(self.dest.glob("at-*/SKILL.md"))), 13)
        cli = self.dest / "at-init-team/scripts/at.py"
        output = subprocess.check_output([sys.executable, "-B", str(cli), "help", "--root", str(self.base)])
        self.assertEqual(len(json.loads(output)["result"]["catalog"]), 13)
        self.assertTrue((self.board / "package-lock.json").is_file())
        self.assertTrue((self.board / "src/App.vue").is_file())
        self.assertTrue((self.board / "server/start.mjs").is_file())
        self.assertFalse((self.board / "dist").exists())
        self.assertFalse((self.board / "node_modules").exists())

    @unittest.skipUnless(os.name == "nt" and os.environ.get("AT_TEST_BOARD_START") == "1",
                         "requires Windows, Node 22.12+ and npm install access")
    def test_cold_start_shortcut_restart_reuse_and_port_conflict(self):
        desktop = self.base / "临时 桌面"
        desktop.mkdir()
        env = dict(os.environ, LOCALAPPDATA=str(self.base / "AppData"),
                   npm_config_cache=str(self.base / "npm-cache"), npm_config_update_notifier="false")
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
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
        launch = ["-File", str(script), "-NoBrowser", "-DesktopDirectory", str(desktop), "-Port", str(port)]
        url = f"http://127.0.0.1:{port}"
        run(launch)
        with urlopen(url, timeout=3) as page:
            self.assertIn(b'id="app"', page.read())
        self.assertEqual(len(servers), 1)
        self.install()
        run(launch)
        self.assertEqual(len(servers), 1)
        self.assertEqual([p.name for p in desktop.iterdir()], ["AgentTeamBoard.lnk"])
        env["AT_TEST_LINK"] = str(desktop / "AgentTeamBoard.lnk")
        read_link = "$link=(New-Object -ComObject WScript.Shell).CreateShortcut($env:AT_TEST_LINK); "
        stop(next(iter(servers)))
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
