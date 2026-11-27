import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "skills"
NAMES = {p.parent.name for p in SOURCE.glob("at-*/SKILL.md")}


def directory_link(link, target):
    if os.name == "nt":
        subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)


class Uninstall(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="at-uninstall-qa-")
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve()
        self.cwd = self.home / "工作 项目"
        self.cwd.mkdir()
        self.codex = self.home / ".codex"
        self.dsh = self.home / ".dsh"
        self.shared = self.home / ".agents/skills"
        self.env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home),
                        CODEX_HOME=str(self.codex), DSH_HOME=str(self.dsh), DSH_AGENTS_HOME=str(self.shared.parent),
                        TMP=str(self.home), TEMP=str(self.home), TMPDIR=str(self.home), PYTHONUTF8="1")
        self.host = "dsh"
        self.runner = SOURCE / "at-uninstall/scripts/uninstall.py"
        self.session = "uninstall-test"

    def cli(self, *args, expected=0):
        p = subprocess.run([sys.executable, "-B", "-X", "utf8", str(self.runner), *map(str, args)],
                           cwd=self.cwd, env=self.env, capture_output=True, encoding="utf-8", timeout=35)
        self.assertEqual(p.returncode, expected, p.stdout + p.stderr)
        result = json.loads(p.stdout)
        if result.get("challenge"):
            self.challenge = result["challenge"]
        return result

    def install(self, root):
        subprocess.run([sys.executable, "-B", str(REPO / "install.py"), "--dest", str(root)],
                       env=self.env, check=True, capture_output=True)

    def prepare(self, *extra):
        r = self.cli("prepare", "--host", self.host, "--cwd", self.cwd, "--session", self.session, *extra)
        self.assertEqual(set(r["names"]), NAMES)
        self.runner = Path(r["runner"])
        self.assertTrue(self.runner.is_relative_to(self.home))
        self.assertFalse(self.runner.is_relative_to(self.cwd))

    def view(self, *paths):
        return {"host": self.host, "cwd": str(self.cwd), "session": self.session, "challenge": self.challenge,
                "complete": True, "skills": [{"name": p.parent.name if p.name == "SKILL.md" else p.stem,
                                              "path": str(p.resolve())} for p in paths]}

    def inspect(self, data, command="inventory", expected=0):
        file = self.runner.parent / "snapshot.json"
        file.write_text(json.dumps(data), encoding="utf-8")
        return self.cli(command, "--snapshot", file, expected=expected)

    def test_offline_mcp_inventory_and_verify(self):
        self.host = "codex"
        self.codex.mkdir()
        marker = self.codex / "agent-team-chat-install.json"
        marker.write_text("[]")
        self.env["PATH"] = str(self.home)
        self.prepare()
        for command in ("inventory", "verify"):
            result = self.inspect(self.view(), command, 2)
            self.assertEqual(len(result["rows"]), 16)
            self.assertEqual(result["mcp"], "error")
            self.assertFalse(result["done"] or result["complete"])
            self.assertTrue(any("agent-team-chat" in e for e in result["errors"]))
        self.assertTrue(marker.exists())

    def test_evidence_and_shared_flat_entry(self):
        self.shared.mkdir(parents=True)
        flat = self.shared / "at-work.md"
        original = (SOURCE / "at-work/SKILL.md").read_bytes() + b"\nlocal notes\n"
        flat.write_bytes(original)
        unrelated = self.shared / "at-else.md"
        unrelated.write_text("---\nname: at-else\ndescription: Other\n---\n# AT_else\n")
        self.prepare()
        initial = self.view(flat)
        self.assertTrue(self.inspect(initial)["entries"][0]["shared"])
        self.assertFalse(self.cli("apply")["changes"])
        self.assertEqual(flat.read_bytes(), original)
        self.assertFalse(self.inspect(initial, "verify", 2)["complete"])  # stale challenge
        incomplete = {**self.view(), "complete": False}
        self.assertTrue(all(r["status"] == "未能验证" for r in self.inspect(incomplete, "verify", 2)["rows"]))
        self.inspect(self.view(flat))
        change = self.cli("apply", "--allow-shared", flat)["changes"][0]
        self.assertEqual(Path(change["backup"]).read_bytes(), original)
        probes = {n: {"code": "SKILL_NOT_FOUND"} for n in NAMES}
        probes["at-work"] = {"code": "SKILL_NOT_MODEL_INVOCABLE"}
        result = self.inspect({**self.view(), "probes": probes}, "verify", 1)
        self.assertFalse(result["done"])
        probes["at-work"] = {"code": "UNKNOWN"}
        self.assertFalse(self.inspect({**self.view(), "probes": probes}, "verify", 2)["complete"])
        probes["at-work"] = {"code": "SKILL_NOT_FOUND"}
        result = self.inspect({**self.view(), "probes": probes}, "verify")
        self.assertEqual(len(result["rows"]), 16)
        self.assertTrue(result["done"])
        self.assertTrue(unrelated.exists())
        self.assertFalse(self.cli("apply")["changes"])

    def test_link_checkout_and_conflicting_origin(self):
        root = self.dsh / "skills"
        root.mkdir(parents=True)
        # A checkout copy and a private link into it; never link a destructive test to the actual repository.
        clone = self.home / "下载的仓库"
        shutil.copytree(SOURCE, clone / "skills", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(REPO / "install.py", clone / "install.py")
        target = clone / "skills/at-help"
        link = root / "at-help"
        directory_link(link, target)
        entry = target / "SKILL.md"
        before = entry.read_bytes()
        collision = root / "at-work.md"
        collision.write_text("---\nname: at-work\ndescription: Another project\n---\n# Other\n")
        self.prepare("--root", clone / "skills")
        rows = self.inspect(self.view(entry, collision))["entries"]
        self.assertEqual(sorted(r["action"] for r in rows), ["detach", "host", "host"])
        self.cli("apply")
        self.assertFalse(link.exists())
        self.assertEqual(entry.read_bytes(), before)
        self.assertTrue(collision.is_file())
        self.assertFalse(self.inspect(self.view(entry, collision), "verify", 1)["done"])

    def test_independent_links_and_a_link_shared_by_both_hosts(self):
        dsh_link = self.dsh / "skills/at-help"
        codex_link = self.codex / "skills/at-help"
        for link in (dsh_link, codex_link):
            link.parent.mkdir(parents=True)
        target = self.home / "original/at-help"
        shutil.copytree(SOURCE / "at-help", target)
        directory_link(dsh_link, target)
        directory_link(codex_link, dsh_link)
        self.prepare()
        entry = dsh_link / "SKILL.md"
        self.assertTrue(self.inspect(self.view(entry))["entries"][0]["shared"])
        self.assertFalse(self.cli("apply")["changes"])
        if codex_link.is_symlink():
            codex_link.unlink()
        else:
            codex_link.rmdir()
        directory_link(codex_link, target)
        self.assertFalse(self.inspect(self.view(entry))["entries"][0]["shared"])
        self.assertEqual(len(self.cli("apply")["changes"]), 1)
        self.assertTrue((codex_link / "SKILL.md").is_file())
        self.assertTrue(self.inspect(self.view(), "verify")["done"])

    @unittest.skipUnless(shutil.which("codex"), "requires Codex App Server")
    def test_codex_scanning_checkout_requires_live_confirmation_after_unbinding(self):
        self.host = "codex"
        self.codex.mkdir()
        clone = self.home / "源码"
        shutil.copytree(SOURCE, clone / "skills", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(REPO / "install.py", clone / "install.py")
        source = clone / "skills"
        previous = {p: p.read_bytes() for p in source.rglob("SKILL.md")}
        self.prepare("--codex-extra", source)
        initial = self.cli("inventory")
        self.assertEqual(len(initial["entries"]), 16, initial["errors"])
        self.assertEqual({e["action"] for e in initial["entries"]}, {"host"})
        self.assertFalse(self.cli("apply")["changes"])
        # Omitting a caller-supplied root locally cannot establish its removal on the calling client.
        self.assertFalse(self.cli("verify", "--removed-extra", source, expected=2)["complete"])
        self.assertEqual(previous, {p: p.read_bytes() for p in source.rglob("SKILL.md")})

    @unittest.skipUnless(shutil.which("codex"), "requires Codex App Server")
    def test_real_codex_partial_and_reinstall(self):
        self.host = "codex"
        dest = self.codex / "skills"
        self.install(dest)
        # Leave just the ten skills shipped before the three additions and the uninstaller.
        for name in ("at-help", "at-update-team-member", "at-start-board", "at-uninstall", "at-receive-message", "at-reply-message"):
            (dest / name / "SKILL.md").unlink()
        (self.codex / "config.toml").write_text('[[skills.config]]\nname = "at-work"\nenabled = false\n')
        self.prepare()
        initial = self.cli("inventory")
        self.assertEqual(len(initial["entries"]), 10)
        self.assertTrue(all(Path(r["source"]).is_relative_to(dest) for r in initial["entries"]))
        self.assertEqual(len(self.cli("apply")["changes"]), 10)
        self.assertTrue(self.cli("verify")["done"])
        self.install(dest)
        self.assertEqual(len(self.cli("verify", expected=1)["entries"]), 16)
        self.assertEqual(len(self.cli("apply")["changes"]), 15)
        self.assertEqual([e["name"] for e in self.cli("verify", expected=1)["entries"]], ["at-uninstall"])
        self.assertEqual(self.cli("apply")["changes"][0]["name"], "at-uninstall")
        self.assertTrue(self.cli("verify")["done"])
        self.assertTrue((dest / "at-start-board/scripts/start-board.ps1").is_file())

    @unittest.skipUnless(os.environ.get("AT_TEST_DSH_MODULES"), "requires official Harness registry/provider packages")
    def test_real_dsh_scoped_catalog_and_shadowed_copy(self):
        dest = self.dsh / "skills"
        self.install(dest)
        project = self.cwd / ".dsh/skills"
        shutil.copytree(dest / "at-work", project / "at-work")
        other = self.codex / "skills/at-work"
        shutil.copytree(dest / "at-work", other)
        self.prepare()
        proc = subprocess.Popen(["node", str(REPO / "tests/dsh_uninstall_host.mjs"), os.environ["AT_TEST_DSH_MODULES"],
                                 str(self.cwd), str(dest), str(project), str(self.runner.with_name("dsh-snapshot.mjs"))],
                                cwd=self.cwd, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                encoding="utf-8")
        def close():
            proc.stdin.close()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            proc.stdout.close()
        self.addCleanup(close)
        def snapshot(expected):
            deadline = time.monotonic() + 8
            while True:
                proc.stdin.write(self.challenge + "\n")
                proc.stdin.flush()
                view = json.loads(proc.stdout.readline())
                observed = {r["name"]: Path(r["path"]) for r in view["skills"]}
                if view["complete"] and observed == expected:
                    return view
                self.assertLess(time.monotonic(), deadline, observed)
                time.sleep(0.1)
        paths = {n: dest / n / "SKILL.md" for n in NAMES}
        paths["at-work"] = project / "at-work/SKILL.md"
        self.inspect(snapshot(paths))
        self.assertEqual(len(self.cli("apply")["changes"]), 15)
        paths = {n: dest / n / "SKILL.md" for n in ("at-work", "at-uninstall")}
        self.inspect(snapshot(paths), "verify", 1)
        self.assertEqual([r["name"] for r in self.cli("apply")["changes"]], ["at-work"])
        del paths["at-work"]
        self.inspect(snapshot(paths), "verify", 1)
        self.assertEqual([r["name"] for r in self.cli("apply")["changes"]], ["at-uninstall"])
        self.assertTrue(self.inspect(snapshot({}), "verify")["done"])
        self.assertTrue((other / "SKILL.md").is_file())
        self.install(dest)
        self.assertEqual(len(self.inspect(snapshot({n: dest/n/"SKILL.md" for n in NAMES}), "verify", 1)["entries"]), 16)
