"""Exercise actual Codex stdio registrations in a disposable CODEX_HOME."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OfflineInstall(unittest.TestCase):
    def test_default_without_codex_and_venv_interpreter(self):
        import venv
        with tempfile.TemporaryDirectory(prefix="离线安装-") as tmp:
            base = Path(tmp)
            env = dict(os.environ, CODEX_HOME=str(base / "home"), PATH=str(base), PYTHONUTF8="1")
            venv.EnvBuilder(with_pip=False).create(base / "venv")
            python = base / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            args = [str(python), "-B", str(ROOT / "install.py")]
            result = subprocess.run(args, env=env, capture_output=True, encoding="utf-8", check=True)
            self.assertIn("MCP 尚未注册", result.stderr)
            self.assertEqual(len(list((base / "home/skills").glob("at-*/SKILL.md"))), 16)
            config = subprocess.check_output([*args, "--print-mcp-config"], env=env, encoding="utf-8")
            spec = json.loads(config)["mcpServers"]["agent-team-chat"]
            self.assertFalse(Path(spec["command"]).is_relative_to(base / "venv"))
            self.assertTrue(Path(spec["command"]).is_file())


@unittest.skipUnless(shutil.which("codex"), "requires the Codex CLI")
class Registration(unittest.TestCase):
    def test_registration_lifecycle_and_foreign_name(self):
        with tempfile.TemporaryDirectory(prefix="通讯安装-") as tmp:
            home = Path(tmp)/"codex"
            home.mkdir()
            env = dict(os.environ, CODEX_HOME=str(home), PYTHONUTF8="1")
            dest = home/"skills"
            def cmd(*args, success=True):
                p = subprocess.run(args, cwd=tmp, env=env, capture_output=True, encoding="utf-8", timeout=35)
                self.assertEqual(p.returncode == 0, success, p.stderr)
                return p.stdout
            installer = [sys.executable, "-B", str(ROOT/"install.py")]
            cli = [shutil.which("codex"), "mcp"]
            spec = json.loads(cmd(*installer, "--print-mcp-config"))["mcpServers"]["agent-team-chat"]
            self.assertFalse(dest.exists())
            cmd(*installer,"--no-mcp")
            self.assertFalse(json.loads(cmd(*cli,"list","--json")))
            for _ in range(2):
                cmd(*installer)
                entry = json.loads(cmd(*cli,"get","agent-team-chat","--json"))
                self.assertEqual(entry["transport"]["args"],spec["args"])
            remove = [sys.executable, "-B", "-c",
                      "import sys; sys.path.insert(0, sys.argv[1]); import chat_registration as r; r.remove()",
                      str(dest/"at-uninstall/scripts")]
            cmd(*remove)
            self.assertFalse(json.loads(cmd(*cli,"list","--json")))
            cmd(*cli,"add","agent-team-chat","--","foreign-command")
            cmd(*installer,success=False)
            cmd(*remove)
            self.assertEqual(json.loads(cmd(*cli,"get","agent-team-chat","--json"))["transport"]["command"],"foreign-command")
