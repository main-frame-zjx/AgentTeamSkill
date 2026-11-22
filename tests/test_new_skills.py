import concurrent.futures
import hashlib
import json
from pathlib import Path

from test_lifecycle import ACTIVE, DONE, NEW, REVIEW, ProjectFixture


class HelpAndProfiles(ProjectFixture):
    def test_empty_occupied_and_invalid(self):
        empty = self.cli("help")
        self.assertEqual(empty["recommendation"]["skill"], "at-init-team")
        self.assertEqual(len(empty["catalog"]), 14)
        self.assertEqual(list(self.root.iterdir()), [])
        (self.root / ".hidden").touch()
        self.assertEqual(self.cli("help")["status"], "outside")
        manifest = self.root / "AT.json"
        manifest.write_text("{", encoding="utf-8")
        invalid = self.cli("help")
        self.assertEqual((invalid["status"], invalid["path"]), ("invalid", str(manifest)))
        manifest.write_text(json.dumps({"format": "agent-team/v2", "name": "缺少仓库", "members": []}))
        self.assertEqual(self.cli("help")["status"], "invalid")
        self.assertFalse((self.root / ".at-state").exists())

    def test_guidance_follows_stage_role_and_version_without_repair(self):
        self.make_project_fixture()
        help_for = lambda root=None: self.cli("help", root=root)
        self.assertEqual(help_for()["recommendation"]["skill"], "at-add-team-member")
        self.assertFalse((self.root / ".at-state").exists())
        lead, dev = "项目负责人", "工程师"
        self.cli("add-member", self.role(lead))
        self.assertEqual(help_for()["recommendation"]["skill"], "at-add-worklist")
        role = self.cli("add-member", self.role(dev))
        directory = self.root / role["dir"]
        self.assertEqual(help_for()["recommendation"]["skill"], "at-team-discuss")
        def add(key, owner, prefix):
            return self.cli("add-tasks", {"items": [{"key": key, "role": owner, "prefix": prefix, "title": "检查接口",
                            "goal": "确保接口可用", "criteria": ["回归通过"], "reviewer": lead}]})[0]
        job = add("job", dev, "Dev")
        spare = add("spare", dev, "Dev")
        def move(item, before, after, actor):
            return self.cli("move", {"role": dev, "id": item["id"], "key": before, "actor": actor,
                                     "from": before, "to": after, "evidence": ["测试通过"], "reason": "已核实"})
        self.assertEqual(help_for()["recommendation"]["skill"], "at-work")
        move(job, NEW, ACTIVE, dev)
        submitted = move(job, ACTIVE, REVIEW, dev)
        self.assertEqual(help_for()["recommendation"]["skill"], "at-review-work")
        scoped = help_for(directory / "workspace")
        self.assertEqual(scoped["current_role"], dev)
        self.assertIn(spare["id"], scoped["recommendation"]["example"])
        self.assertIn(job["id"], help_for(self.root / ("AT_" + lead))["recommendation"]["example"])
        # A legacy filename with an interrupted move must not get silently renamed by help.
        old_dir = directory / "workspace" / ACTIVE
        moved = Path(submitted["path"])
        legacy = old_dir / (job["id"] + ".md")
        moved.rename(legacy)
        snapshot = lambda: {p: hashlib.sha256(p.read_bytes()).digest() for p in self.root.rglob("*")
                            if p.is_file() and ".git" not in p.parts}
        before = snapshot()
        invalid = help_for()
        self.assertEqual(invalid["status"], "invalid")
        self.assertIn(str(legacy), invalid["error"])
        self.assertEqual(before, snapshot())
        legacy.rename(moved.with_name(legacy.name))
        valid = snapshot()
        self.assertEqual(help_for()["counts"][REVIEW], 1)
        self.assertEqual(valid, snapshot())
        move(job, REVIEW, DONE, lead)
        move(spare, NEW, ACTIVE, dev)
        move(spare, ACTIVE, REVIEW, dev)
        move(spare, REVIEW, DONE, lead)
        self.assertEqual(help_for()["recommendation"]["skill"], "at-publish")
        (self.root / ".at-state/releases.json").write_text(json.dumps([{"kind":"bin", "version":"v1.0"}]))
        self.assertEqual(help_for()["recommendation"]["skill"], "at-team-discuss")

    def test_update_preserves_custom_text_and_recovers_failed_commit(self):
        self.make_project_fixture()
        name = "项目负责人"
        self.cli("add-member", self.role(name))
        repo = self.root / ("AT_" + name)
        profile = repo / "Agent.md"
        original = profile.read_text(encoding="utf-8") + "\n## 用户自定义\n\n保留这一段。\n"
        profile.write_bytes(b"\xef\xbb\xbf" + original.replace("\n", "\r\n").encode("utf-8"))
        self.git(repo, "add", "Agent.md")
        self.git(repo, "commit", "-m", "Custom section")
        unrelated = repo / "unrelated.txt"
        unrelated.write_text("independent change", encoding="utf-8")
        self.git(repo, "add", unrelated.name)
        old = self.cli("update-member", {"role": name})
        updated = old["content"].replace("实现交付", "每周五汇总风险")
        payload = {"role": name, "expected_sha256": old["sha256"],
                   "content": updated.replace("\r\n", "\n")}
        hook = repo / ".git/hooks/pre-commit"
        hook.write_bytes(b"#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        self.cli("update-member", payload, fail=True)
        hook.unlink()
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            saved, retry = pool.map(lambda _: self.cli("update-member", payload), range(2))
        self.assertEqual(saved, retry)
        self.assertEqual(profile.read_bytes(), b"\xef\xbb\xbf" + updated.encode("utf-8"))
        self.assertEqual(self.git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", saved["commit"]), "Agent.md")
        self.assertEqual(self.git(repo, "diff", "--cached", "--name-only"), unrelated.name)
        self.cli("update-member", {**payload, "content": old["content"] + "另一个调整"}, fail=True)
        self.assertEqual(self.cli("update-member", {"role": name})["sha256"], saved["sha256"])
        self.assertEqual(self.git(repo, "rev-list", "--count", "HEAD"), "3")
        with profile.open("ab") as manual:
            manual.write(b"\r\nUser draft.\r\n")
        draft = self.cli("update-member", {"role": name})
        noop = self.cli("update-member", {"role": name, "content": draft["content"], "expected_sha256": draft["sha256"]})
        self.assertIsNone(noop["commit"])
        self.assertEqual(self.git(repo, "rev-list", "--count", "HEAD"), "3")
