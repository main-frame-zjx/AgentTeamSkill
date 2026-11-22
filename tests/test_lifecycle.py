"""Integration tests with a local bare remote, isolated vault and the actual global-style CLI."""

import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid


CLI = Path(os.environ.get("AT_TEST_CLI") or Path(__file__).resolve().parents[1] /
           "skills/at-init-team/scripts/at.py")
ROLES = ["项目负责人", "资深策划", "高级工程师", "专业美术"]
NEW, ACTIVE, REVIEW, DONE = "1新需求", "2处理中", "3待验收", "4已归档"


class RepositoryNaming(unittest.TestCase):
    def test_remote_names(self):
        sys.path.insert(0, str(CLI.parent))
        try:
            from team import repository_name
        finally:
            sys.path.pop(0)
        for remote, expected in [
            ("https://github.com/main-frame-zjx/tank_war.git", "tank_war"),
            ("https://github.com/owner/Tank-War.v2/", "Tank-War.v2"),
            ("ssh://git@github.com:22/owner/tank_war.git", "tank_war"),
            ("git@github.com:owner/tank_war.git", "tank_war"),
            ("git@host:tank_war.git", "tank_war"),
            ("file:///tmp/my%20game.git", "my game"),
            (r"F:\local\tank_war.git", "tank_war"),
            ("/local/tank_war/.git", "tank_war"),
            ("https://github.com/owner/.github.git", ".github"),
        ]:
            with self.subTest(remote=remote):
                self.assertEqual(repository_name(remote), expected)
        for bad in ("https://github.com/", "ssh://host/../", "https://host/owner/a%2Fb.git", "https://host/CON.git"):
            with self.subTest(remote=bad), self.assertRaises(ValueError):
                repository_name(bad)


class ProjectFixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="at-lifecycle-")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.env = dict(os.environ, GIT_AUTHOR_NAME="Agent Team Test", GIT_AUTHOR_EMAIL="test@example.invalid",
                        GIT_COMMITTER_NAME="Agent Team Test", GIT_COMMITTER_EMAIL="test@example.invalid",
                        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", PYTHONDONTWRITEBYTECODE="1")
        self.root, self.vault = self.base / "坦克 大战", self.base / "测试库"
        self.remote = self.base / "tank_war.git"
        self.root.mkdir()
        self.vault.mkdir()
        self.git(self.base, "init", "--bare", "-b", "main", self.remote)
        self.init = {"name": "坦克大战", "vault": str(self.vault), "remote": str(self.remote)}

    def git(self, repo, *args):
        proc = subprocess.run(["git", "-C", str(repo), *map(str, args)], capture_output=True,
                              env=self.env, encoding="utf-8", errors="replace", check=True)
        return proc.stdout.strip()

    def cli(self, cmd, data=None, fail=False, root=None, cwd=None):
        proc = subprocess.run([sys.executable, "-B", "-X", "utf8", str(CLI), cmd, "--root",
                               str(root or self.root), "--input", "-"], input=json.dumps(data or {}),
                              cwd=cwd, env=self.env, encoding="utf-8", capture_output=True, timeout=90)
        try:
            result = json.loads(proc.stdout)
        except ValueError:
            self.fail(proc.stderr + proc.stdout)
        if fail:
            self.assertNotEqual(proc.returncode, 0, result)
            self.assertFalse(result["ok"])
            return result["error"]
        self.assertEqual(proc.returncode, 0, result)
        return result["result"]

    def role(self, name):
        return {"name": name, "persona": name + "负责本专业", "focus": ["实现交付"], "workflow": ["阅读需求", "验证交付"]}

    def make_project_fixture(self):
        """Build the post-init layout directly, inside an unrelated parent repository."""
        self.git(self.base, "init", "-b", "main")
        self.git(self.base, "commit", "--allow-empty", "-m", "Parent baseline")
        (self.base / "unrelated.txt").write_text("staged by someone else", encoding="utf-8")
        self.git(self.base, "add", "unrelated.txt")
        self.parent_head = self.git(self.base, "rev-parse", "HEAD")
        self.parent_index = self.git(self.base, "ls-files", "--stage")
        main = self.root / "public/tank_war"
        main.parent.mkdir()
        self.git(self.root, "clone", self.remote, main)
        self.git(main, "commit", "--allow-empty", "-m", "Team baseline")
        self.git(main, "push", "-u", "origin", "main")
        (self.root / "publish").mkdir()
        config = {**self.init, "id": str(uuid.uuid4()), "format": "agent-team/v2",
                  "team_repo": "public/tank_war", "current_version": "v1.0", "members": []}
        (self.root / "AT.json").write_text(json.dumps(config), encoding="utf-8")
        self.addCleanup(self.check_parent_repository)

    def check_parent_repository(self):
        self.assertFalse((self.root / ".git").exists())
        self.assertEqual(self.git(self.base, "rev-parse", "HEAD"), self.parent_head)
        self.assertEqual(self.git(self.base, "ls-files", "--stage"), self.parent_index)

class Lifecycle(ProjectFixture):
    def test_empty_and_failed_initialization(self):
        (self.root / ".hidden").touch()
        self.cli("init", self.init, fail=True)
        self.assertEqual([p.name for p in self.root.iterdir()], [".hidden"])
        (self.root / ".hidden").unlink()
        self.cli("init", {**self.init, "version": "draft"}, fail=True)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(self.git(self.remote, "for-each-ref"), "")
        self.cli("init", {**self.init, "remote": str(self.base / "missing.git")}, fail=True)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(self.cli("init", self.init)["format"], "agent-team/v2")
        self.assertEqual({p.name for p in self.root.iterdir()}, {"AT.json", "public", "publish"})
        self.assertEqual(self.cli("project")["current_version"], "v1.0")
        self.assertEqual({p.name for p in (self.root / "publish").iterdir()}, {"bin", "user", "dev"})
        self.assertEqual({p.name for p in (self.root / "public").iterdir()}, {"tank_war"})
        self.assertEqual(self.git(self.remote, "rev-parse", "main"),
                         self.git(self.root / "public/tank_war", "rev-parse", "HEAD"))

    def test_existing_remote_and_member_retry(self):
        seed = self.base / "seed"
        self.git(self.base, "clone", self.remote, seed)
        (seed / "README.md").write_text("Existing game", encoding="utf-8")
        self.git(seed, "add", "README.md")
        self.git(seed, "commit", "-m", "Existing game")
        self.git(seed, "push", "origin", "main")
        config = self.cli("init", {**self.init, "version": "2.10"})
        self.assertEqual(self.cli("project")["current_version"], "v2.10")
        self.assertEqual(config["team_repo"], "public/tank_war")
        main = self.root / "public/tank_war"
        self.assertEqual(self.git(main, "rev-parse", "HEAD"), self.git(seed, "rev-parse", "HEAD"))
        self.git(main, "remote", "set-url", "origin", self.base / "unavailable")
        self.cli("add-member", self.role(ROLES[0]), fail=True)
        self.assertEqual(self.cli("project")["members"], [])
        self.git(main, "remote", "set-url", "origin", self.remote)
        role = self.cli("add-member", self.role(ROLES[0]))
        repos = self.root / role["dir"] / "repository"
        self.assertTrue((repos / "tank_war/README.md").is_file())
        personal = repos / "个人分析"
        personal.mkdir()
        self.git(personal, "init", "-b", "main")
        (personal / "分析.md").write_text("独立任务", encoding="utf-8")
        self.git(personal, "add", "分析.md")
        self.git(personal, "commit", "-m", "Save independent task")
        self.assertEqual(self.git(personal, "remote"), "")
        self.assertEqual(self.git(repos.parent, "status", "--porcelain"), "")

    def test_registration_commit_before_membership(self):
        self.make_project_fixture()
        template = self.base / "template"
        hook = template / "hooks/pre-commit"
        hook.parent.mkdir(parents=True)
        hook.write_bytes(b"#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        self.env["GIT_TEMPLATE_DIR"] = str(template)
        self.cli("add-member", self.role(ROLES[0]), fail=True)
        self.assertEqual(self.cli("project")["members"], [])
        base = self.root / ("AT_" + ROLES[0])
        (base / ".git/hooks/pre-commit").unlink()
        self.cli("add-member", self.role(ROLES[0]))
        self.assertEqual(self.git(base, "rev-list", "--count", "HEAD"), "1")
        self.assertEqual(len(self.cli("project")["members"]), 1)

    def test_team_lifecycle(self):
        self.make_project_fixture()
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            roles = list(pool.map(lambda n: self.cli("add-member", self.role(n)), ROLES))
        self.assertEqual(len(self.cli("project")["members"]), 4)
        self.assertEqual(len({r["branch"] for r in roles}), 4)
        for name, role in zip(ROLES, roles):
            path = self.root / role["dir"]
            self.assertEqual(Path(self.git(path, "rev-parse", "--show-toplevel")).resolve(), path)
            self.assertEqual(self.git(path, "remote"), "")
            self.assertIn("Memory.md", self.git(path, "ls-files"))
            self.assertTrue((path / ".agent").is_dir())
            self.assertTrue((self.vault / role["library"]).is_dir())
            self.assertEqual({p.name for p in (path / "workspace").iterdir()}, {NEW, ACTIVE, REVIEW, DONE})
            self.assertEqual(self.git(path / "repository/tank_war", "branch", "--show-current"), role["branch"])
            self.assertEqual(self.cli("add-member", self.role(name)), role)
        ctx = self.cli("meeting-context")
        self.assertEqual(ctx["host"], ROLES[0])
        self.cli("meeting-context", root=self.root / "public", fail=True)
        meeting = {"key": "m1", "topic": "坦克大战首轮玩法", "opening": "确定碰撞、地图及美术分工",
                   "rounds": [{n: f"{n}的第{i}轮意见" for n in ROLES} for i in range(1, 11)],
                   "decisions": ["验证四方向撞墙"], "user_decisions": ["用户选择四向移动"],
                   "open_questions": [], "items": [
                       {"key": "task-" + str(i), "role": n, "prefix": ["PM", "Design", "Dev", "Art"][i], "title": n + "交付",
                        "goal": "检查墙体交接", "criteria": ["可以复现", "可以交接"]} for i, n in enumerate(ROLES)]}
        self.cli("meeting", {**meeting, "rounds": meeting["rounds"][:9]}, fail=True)
        self.assertFalse((self.root / "public/meetings").exists())
        # Simulate a later owner's commit failing after the first owner has already committed.
        first_owner = self.root / roles[0]["dir"]
        second_hook = self.root / roles[1]["dir"] / ".git/hooks/pre-commit"
        second_hook.write_bytes(b"#!/bin/sh\nexit 1\n")
        second_hook.chmod(0o755)
        self.cli("meeting", meeting, fail=True)
        partial_head = self.git(first_owner, "rev-parse", "HEAD")
        self.assertEqual(self.git(first_owner, "rev-list", "--count", "HEAD"), "2")
        second_hook.unlink()
        calls = [meeting, dict(meeting)]
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            first, repeated = pool.map(lambda m: self.cli("meeting", m), calls)
        self.assertEqual(first, repeated)
        self.assertEqual(self.git(first_owner, "rev-parse", "HEAD"), partial_head)
        for item, role in zip(first["items"], roles):
            base = self.root / role["dir"]
            tracked = self.git(base, "-c", "core.quotepath=false", "ls-files", "--", "workspace")
            self.assertIn(Path(item["path"]).name, tracked)
            self.assertEqual(tracked.count("AT-"), 1)
        self.assertEqual(len(first["items"]), 4)
        self.assertIn(first["items"][2]["id"], Path(first["minutes"]).read_text(encoding="utf-8"))
        who, item = ROLES[2], first["items"][2]
        target = {"role": who, "id": item["id"]}
        original = Path(item["path"]).read_bytes()
        self.cli("add-tasks", {"items": [{**meeting["items"][2], "key": "meeting/m1/task-2",
                                         "role": ROLES[1]}]}, fail=True)
        self.assertEqual(len(self.cli("list", {"role": who, "stages": [NEW, ACTIVE]})), 1)

        def move(key, actor, before, after, fail=False, evidence=None):
            return self.cli("move", {**target, "actor": actor, "key": key, "reason": "场景验证",
                                     "from": before, "to": after, "evidence": evidence or ["场景检查"]}, fail)

        owner_repo = self.root / roles[2]["dir"]
        hook = owner_repo / ".git/hooks/pre-commit"
        hook.write_bytes(b"#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        move("start", who, NEW, ACTIVE, fail=True)
        hook.unlink()
        move("start", who, NEW, ACTIVE)
        self.assertEqual(self.git(owner_repo, "status", "--porcelain"), "")
        self.assertFalse(Path(item["path"]).exists())
        self.cli("amend", {**target, "actor": ROLES[0], "key": "amend-1", "reason": "补充约束",
                           "changes": {"criteria": ["四个方向停止", "贴墙可移动"]}})
        role_repo = self.root / roles[2]["dir"] / "repository/tank_war"
        art_repo = self.root / roles[3]["dir"] / "repository/tank_war"
        initial_code = ("def move(position, delta, walls):\n"
                        "    candidate = (position[0] + delta[0], position[1] + delta[1])\n"
                        "    if candidate in walls or (position[0] + 1, position[1]) in walls:\n"
                        "        return position\n"
                        "    return candidate\n")
        for tree, name, content in [(role_repo, "movement.py", initial_code),
                                    (art_repo, "tiles.json", '{"wall":"#444444"}')]:
            (tree / name).write_text(content, encoding="utf-8")
            self.git(tree, "add", "--", name)
            self.git(tree, "commit", "-m", name)
        four_walls = ("from movement import move\n"
                      "for d in [(1,0),(-1,0),(0,1),(0,-1)]:\n"
                      "    assert move((0,0),d,{d}) == (0,0)\n")
        slide = "from movement import move\nassert move((0,0),(0,1),{(1,0)}) == (0,1)"

        def check_game(repo, code):
            return subprocess.run([sys.executable, "-B", "-c", code], cwd=repo, env=self.env,
                                  capture_output=True).returncode
        stale = self.cli("sync", {"role": who})["test_this_commit"]
        art = self.cli("sync", {"role": ROLES[3]})["test_this_commit"]
        self.cli("deliver", {"role": ROLES[3], "tested_commit": art, "checks": ["检查地块"]})
        self.cli("deliver", {"role": who, "tested_commit": stale, "checks": ["旧提交"]}, fail=True)
        synced = self.cli("sync", {"role": who})["test_this_commit"]
        self.assertEqual(json.loads((role_repo / "tiles.json").read_bytes())["wall"], "#444444")
        self.assertEqual(check_game(role_repo, four_walls), 0)
        delivered = self.cli("deliver", {"role": who, "tested_commit": synced, "checks": ["移动检查"]})
        self.assertEqual(delivered["commit"], self.git(self.remote, "rev-parse", "main"))
        self.assertEqual(self.git(owner_repo, "ls-files", "--", "repository"), "")
        self.assertTrue((self.root / ".at-state/agent-team.lock").is_file())
        move("send", who, ACTIVE, REVIEW, evidence=[synced, "四个方向撞墙测试通过"])
        main = self.root / "public/tank_war"
        self.assertNotEqual(check_game(main, slide), 0)
        move("bad-reviewer", who, REVIEW, DONE, fail=True)
        move("return", ROLES[0], REVIEW, ACTIVE, evidence=[synced, "右侧有墙时向上移动失败"])
        fixed_code = initial_code.replace(" or (position[0] + 1, position[1]) in walls", "")
        (role_repo / "movement.py").write_text(fixed_code, encoding="utf-8")
        self.git(role_repo, "commit", "-am", "Allow movement along a wall")
        fixed = self.cli("sync", {"role": who})["test_this_commit"]
        self.assertEqual(check_game(role_repo, four_walls + slide), 0)
        self.cli("deliver", {"role": who, "tested_commit": fixed, "checks": ["四向撞墙及沿墙移动通过"]})
        self.assertNotEqual(fixed, synced)
        self.cli("note", {**target, "actor": who, "key": "fix", "reason": "修正贴墙问题"})
        move("send-again", who, ACTIVE, REVIEW, evidence=[fixed, "修订版自测通过"])
        self.assertEqual(self.git(main, "rev-parse", "HEAD"), fixed)
        self.assertEqual(check_game(main, four_walls + slide), 0)
        evidence = [fixed, "在交付提交复验两个验收条件通过"]
        final = move("accept", ROLES[0], REVIEW, DONE, evidence=evidence)
        self.assertEqual(move("accept", ROLES[0], REVIEW, DONE, evidence=evidence), final)
        raw = Path(final["path"]).read_bytes()
        self.assertTrue(raw.startswith(original))
        # Simulate termination after the last event write but before the atomic directory move.
        old_location = Path(final["path"]).parents[1] / REVIEW / Path(final["path"]).name
        Path(final["path"]).rename(old_location)
        repaired = self.cli("show", target)
        self.assertEqual(repaired["stage"], DONE)
        self.assertEqual(Path(final["path"]).read_bytes(), raw)
        self.assertEqual(repaired["current"]["criteria"], ["四个方向停止", "贴墙可移动"])
        self.assertEqual(len(self.cli("list", {"role": who, "stages": [NEW, ACTIVE]})), 0)
        self.assertEqual(len(self.cli("meeting", meeting)["items"]), 4)

        memory = self.cli("memory", {"role": who})
        new_memory = self.cli("memory", {"role": who, "expected_sha256": memory["sha256"], "content": "碰撞已验收"})
        self.assertLess(new_memory["bytes"], 10240)
        self.cli("memory", {"role": who, "expected_sha256": memory["sha256"], "content": "旧稿覆盖"}, fail=True)
        self.assertTrue(self.cli("memory", {"role": who, "expected_sha256": new_memory["sha256"],
                                            "content": "多" * 3500})["over_memory_target"])
        note = {"role": who, "path": "技术/碰撞.md", "content": "四个方向均已覆盖", "expected_sha256": None}
        self.cli("library", note)
        self.assertEqual(self.cli("library", {"role": who, "path": note["path"]})["content"].strip(), note["content"])
        self.cli("library", {**note, "path": "../他人.md"}, fail=True)
        self.assertIn("多" * 3500, self.git(owner_repo, "show", "HEAD:Memory.md"))
        self.assertEqual(self.git(owner_repo, "status", "--porcelain"), "")

    def test_task_version_from_nested_directory(self):
        self.cli("init", self.init)
        role = self.cli("add-member", self.role(ROLES[1]))
        nested = self.root / role["dir"] / "workspace" / NEW
        item = {"key": "rules", "role": role["name"], "prefix": "Design", "title": "对战规则",
                "goal": "明确胜负条件", "criteria": ["覆盖平局"]}
        initial = self.cli("add-tasks", {"items": [item]}, root=nested)[0]
        self.assertEqual(initial["version"], "v1.0")
        batch = {"version": "1.2", "items": [{**item, "key": "score"}, {**item, "key": "draw", "version": "1.3"}]}
        assigned = self.cli("add-tasks", batch, root=nested)
        for row, expected in zip([initial, *assigned], ["v1.0", "v1.2", "v1.3"], strict=True):
            self.assertEqual(row["version"], expected)
            details = self.cli("show", {"id": row["id"], "role": row["role"]}, root=nested)
            self.assertEqual(details["original"]["version"], expected)
        self.cli("set-iteration", {"version": "2.0"})
        self.assertEqual(self.cli("add-tasks", {"items": [item]}, root=nested)[0], initial)
        new = self.cli("add-tasks", {"items": [{**item, "key": "next"}]}, root=nested)[0]
        self.assertEqual(new["version"], "v2.0")

    def test_readable_task_names(self):
        self.make_project_fixture()
        designer, artist = ROLES[1], ROLES[3]
        for name in (designer, artist):
            self.cli("add-member", self.role(name))
        item = {"key": "rule", "role": designer, "prefix": "Design", "title": "Five-minute match",
                "summary": "据点:首领/规则", "goal": "形成可试玩规则", "criteria": ["首领可以交战"]}
        def add(*items, fail=False):
            return self.cli("add-tasks", {"items": list(items)}, fail=fail)

        first, second = add(item, {**item, "key": "next"})
        self.assertEqual(Path(first["path"]).name, "AT-Design00001-据点-首领-规则.md")
        self.assertEqual(Path(second["path"]).name, "AT-Design00002-据点-首领-规则.md")
        self.assertEqual(add({**item, "summary": "另一种概括"})[0], first)
        self.assertEqual(self.cli("add-member", self.role(designer))["task_prefix"], "Design")
        add({**item, "key": "art", "role": artist, "prefix": "design"}, fail=True)
        art = add({**item, "key": "art", "role": artist, "prefix": "Art"})[0]
        self.assertTrue(Path(art["path"]).name.startswith("AT-Art00001-"))
        by_path = {"role": designer, "path": str(Path(first["path"]).relative_to(self.root))}
        self.assertEqual(self.cli("show", by_path)["original"]["id"], first["id"])
        self.cli("show", {**by_path, "id": second["id"]}, fail=True)
        moved = self.cli("move", {**by_path, "key": "start", "from": NEW, "to": ACTIVE,
                                  "actor": designer, "reason": "开工"})
        self.assertEqual(Path(moved["path"]).name, Path(first["path"]).name)
        self.assertEqual(add(item)[0]["path"], moved["path"])
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda k: add({**item, "key": k})[0]["path"], ["third", "fourth"]))
        self.assertEqual(sorted(Path(p).name[:14] for p in results), ["AT-Design00003", "AT-Design00004"])
        # Existing UUID-named documents remain accessible by their embedded ID.
        old_path = Path(second["path"]).with_name(second["id"] + ".md")
        Path(second["path"]).rename(old_path)
        self.assertEqual(self.cli("show", {"role": designer, "id": second["id"]})["path"], str(old_path))

    def test_offline_report(self):
        self.make_project_fixture()
        role, other = ROLES[:2]
        for who in (role, other):
            self.cli("add-member", self.role(who))
        base = self.root / ("AT_" + role)
        self.assertEqual(self.git(base, "ls-files", "report"), "report/.gitkeep")
        (base / "report/.gitkeep").unlink()
        (base / "report").rmdir()
        (base / ".gitignore").write_text("/repository/\ncustom.tmp\n", encoding="utf-8")
        self.git(base, "commit", "-am", "Simulate pre-report layout")
        source = self.base / "report"
        source.mkdir()
        (source / "layout.css").write_text("#ok {color:green}", encoding="utf-8")
        (source / "index.html").write_text(
            '<meta charset="utf-8"><link rel="stylesheet" href="layout.css"><p id="ok">game report</p>'
            '<script src="check.js"></script>', encoding="utf-8")
        req = {"name": "坦克 v1", "source": str(source), "role": role}
        self.cli("publish", req, fail=True)
        (source / "check.js").write_text(
            "if(getComputedStyle(document.querySelector('p')).color==='rgb(0, 128, 0)')"
            "document.body.dataset.verified='offline-success';", encoding="utf-8")
        result = self.cli("publish", req)
        inferred = {k: v for k, v in req.items() if k != "role"}
        self.cli("publish", inferred, fail=True)
        self.cli("publish", {**req, "role": other}, root=self.root, cwd=base, fail=True)
        self.assertEqual(self.cli("publish", inferred, root=base, cwd=base), result)
        self.assertEqual(Path(result["entry"]).parent, base / "report")
        self.assertEqual(self.cli("report-dir", cwd=base)["path"], str(base / "report"))
        self.assertIn("custom.tmp", (base / ".gitignore").read_text())
        self.assertEqual(self.git(base, "ls-files", "report"), "report/.gitkeep")
        self.assertEqual(self.git(base, "status", "--porcelain"), "")
        self.assertEqual(self.cli("publish", req), result)
        entry = Path(result["entry"])
        self.assertEqual(list(entry.parent.glob("*.html")), [entry])
        (source / "layout.css").write_text("body {color:blue}", encoding="utf-8")
        self.cli("publish", req, fail=True)
        edge = Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe"
        browser = str(edge) if edge.is_file() else shutil.which("chromium")
        if browser:
            proc = subprocess.run([browser, "--headless", "--disable-gpu", "--no-first-run",
                                   "--disable-background-networking", "--host-resolver-rules=MAP * ~NOTFOUND",
                                   "--user-data-dir=" + str(self.base / "edge"), "--virtual-time-budget=3000",
                                   "--dump-dom", entry.as_uri()], capture_output=True, timeout=45)
            self.assertIn(b'data-verified="offline-success"', proc.stdout, (proc.stdout, proc.stderr[-1000:]))


if __name__ == "__main__":
    unittest.main()
