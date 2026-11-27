"""Exercise the actual new-project CLI with isolated role repositories and an offline vault."""

import concurrent.futures
import hashlib
import json
from pathlib import Path

from test_lifecycle import ACTIVE, DONE, NEW, REVIEW, ProjectFixture


class WorkingMemory(ProjectFixture):
    def setUp(self):
        super().setUp()
        self.config = self.cli("init", self.init)
        self.assertEqual(self.cli("library-lint")["notes"], 0)
        self.assertEqual(self.config["format"], "agent-team/v3")
        self.assertFalse((self.root / ".at-state").exists())
        self.owner = "工程师"
        self.role_arg = {"role": self.owner}
        self.person = self.cli("add-member", self.role(self.owner))
        self.repo = self.root / self.person["dir"]
        self.doc = self.repo / "Memory.md"
        self.nav = self.vault / self.config["name"] / "00-项目学习导航.md"
        self.item = {"key": "tutorial", "role": self.owner, "prefix": "Dev", "title": "输入教程",
                     "goal": "完成输入校验", "criteria": ["可复核"], "reviewer": "用户"}

    def read(self):
        return self.cli("memory-read", self.role_arg)

    def patch(self, **kwargs):
        return self.cli("memory-patch", {**self.role_arg, "expected_sha256": self.read()["sha256"], **kwargs})

    def note(self, **kwargs):
        return {**self.role_arg, "trigger": "explicit", "kind": "reusable-pattern", "title": "图标对照",
                "expected_sha256": None, "admission": {"reusable_or_complete": "可用于下一组图标",
                "beginner_value": "理解目标尺寸的影响", "evidence_refs": ["file:public/图标对照.txt"]},
                "meta": {"difficulty": "入门", "summary": "按目标尺寸复核", "tags": ["美术"]},
                "sections": {"problem": "画布上的图标容易分清，缩到背包实际显示的尺寸后，两件道具却看起来相同。",
                             "conclusion": "先用轮廓区分功能，再用颜色表达状态，这样灰度画面也可以辨认。",
                             "steps": "把图标按实际像素放在同一张对照图上，保留与背包一致的背景色和间距。",
                             "verification": "请没有画过图标的人在灰度模式下辨认道具，记录混淆的组合。",
                             "boundaries": "固定尺寸 HUD 可用一张对照图。支持缩放的界面还需逐档复核轮廓。"}, **kwargs}

    def test_bounds_conflicts_and_crash_recovery(self):
        before = self.git(self.repo, "rev-parse", "HEAD")
        self.cli("memory-sync", self.role_arg)
        self.assertEqual(before, self.git(self.repo, "rev-parse", "HEAD"))
        self.assertEqual(self.read()["content"].count("\n## "), 6)
        self.assertNotIn("decisions", self.cli("memory-read", {"view": "handoff"}, root=self.repo))
        items = [{**self.item, "key": str(i), "summary": f"长标题{i}", "title": "测" * 100 + str(i)}
                 for i in range(55)]
        self.cli("add-tasks", {"items": items})
        ref = "version:v1.0"
        self.patch(ops=[{"op": "upsert_decision", "summary": "检查目标尺寸" * 4, "ref": ref} for _ in range(12)] +
                       [{"op": "upsert_risk", "summary": "待验证轮廓", "ref": ref} for _ in range(6)])
        view = self.read()
        self.assertIn("其余", view["content"])
        self.assertEqual(view["content"].encode(), self.doc.read_bytes())
        self.assertLessEqual(view["bytes"], 6656)
        fail = {"expected_sha256": view["sha256"], **self.role_arg, "ops": [
                {"op": "upsert_decision", "summary": "多余条目", "ref": ref}]}
        self.assertIn("12", self.cli("memory-patch", fail, fail=True))
        self.assertEqual(view["sha256"], self.read()["sha256"])
        focus = {"current_goal": "图标", "progress": "已验证", "next_step": "复核小图"}
        params = {**self.role_arg, "expected_sha256": view["sha256"], "focus": focus}
        bad = {**params, "focus": {**focus, "progress": "测" * 300}}
        self.assertIn("800", self.cli("memory-patch", bad, fail=True))
        with concurrent.futures.ThreadPoolExecutor(2) as executor:
            outcomes = list(executor.map(lambda p: self.try_patch(p), [params, {**params, "focus": {**focus, "progress": "第二项"}}]))
        self.assertEqual(sorted(outcomes), [False, True])

        self.doc.write_bytes(self.doc.read_bytes() + "额外人工约定\n".encode())
        draft = self.doc.read_bytes()
        manual = self.read()
        self.assertIn("额外人工约定", manual["manual_diff"])
        self.cli("memory-sync", self.role_arg, fail=True)
        hook = self.repo / ".git/hooks/pre-commit"
        hook.write_bytes(b"#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        merge = {**self.role_arg, "expected_sha256": manual["sha256"], "merge_sha256": manual["manual_sha256"],
                 "ops": [{"op": "upsert_decision", "id": "D01", "summary": "额外人工约定", "ref": ref}]}
        self.cli("memory-patch", merge, fail=True)
        hook.unlink()
        self.cli("memory-patch", merge)
        self.assertIn("额外人工约定", self.read()["decisions"]["D01"]["summary"])
        backup = self.root / ".at-state/memory-originals" / (hashlib.sha256(draft).hexdigest() + ".md")
        self.assertEqual(backup.read_bytes(), draft)
        self.assertEqual(self.git(self.repo, "status", "--porcelain"), "")
        self.patch(ops=[{"op": "retire_decision", "id": "D01"}, {"op": "resolve_risk", "id": "R01"}])
        self.assertIn("额外人工约定", self.cli("memory-history", {**self.role_arg, "query": "D01"})["history"])

    def try_patch(self, payload):
        try:
            self.cli("memory-patch", payload)
            return True
        except AssertionError as exc:
            self.assertIn("记忆已变化", str(exc))
            return False

    def test_note_retry_after_iteration_change_and_obsidian_properties(self):
        (self.root / "public/图标对照.txt").write_text("实际样张", encoding="utf-8")
        self.patch(ops=[{"op": "queue_library", "key": "icons", "kind": "reusable-pattern",
                         "topic": "图标对照", "source": "version:v1.0"}])
        cid = self.read()["candidates"][0]["id"]
        request = self.note(resolve_candidate_id=cid)
        self.doc.write_bytes(self.doc.read_bytes() + "人工现场\n".encode())
        result = self.cli("library-upsert", request)
        self.assertEqual(result["pending"][0]["retry"], "library-upsert")
        self.assertEqual(self.cli("set-iteration", {"version": "v1.1"})["pending_memory"][0]["role"], self.owner)
        manual = self.read()
        self.patch(merge_sha256=manual["manual_sha256"], focus={
                   "current_goal": "核对人工现场", "progress": "样张完成", "next_step": "复核尺寸"})
        resumed = self.cli("library-upsert", request)
        self.assertFalse(resumed["pending"])
        self.assertEqual(result["sha256"], resumed["sha256"])
        name = resumed["path"]
        raw = self.cli("library-read", {**self.role_arg, "path": name})
        self.assertEqual(raw["meta"]["version"], "v1.0")
        doc = self.vault / self.person["library"] / name
        text = doc.read_text(encoding="utf-8").replace('tags: ["美术"]', 'tags:\n  - 美术\n  - 教程')
        text = text.replace('title: "图标对照"', 'title: 图标对照')
        doc.write_text(text, encoding="utf-8")
        result = self.cli("library-index", {**self.role_arg, "query": "教程"})
        self.assertEqual(result["notes"][0]["title"], "图标对照")
        self.assertFalse(result["issues"])
        self.cli("library-upsert", request, fail=True)
        oversized = self.note(title="太长的笔记")
        oversized["sections"]["steps"] = "测试" * 2100
        self.assertIn("超出", self.cli("library-upsert", oversized, fail=True))
        self.assertFalse(doc.with_name("太长的笔记.md").exists())
        (self.root / "public/图标对照.txt").unlink()
        self.assertIn("不存在", self.cli("library-lint")["issues"][0]["error"])

    def test_candidate_acceptance_navigation_retrieval_and_seal(self):
        pm = "项目负责人"
        self.cli("add-member", self.role(pm))
        meeting = {"key": "tank_war", "topic": "输入教程", "opening": "讨论教材",
                   "rounds": [{self.owner: "验证复现步骤", pm: "核对交付"} for _ in range(10)],
                   "decisions": ["按目标尺寸核对"], "user_decisions": [], "open_questions": [], "items": [self.item]}
        self.assertFalse(self.cli("meeting-context")["pending_memory"])
        result = self.cli("meeting", meeting)
        job = result["items"][0]
        ref = "task:" + job["id"]
        minutes = Path(result["minutes"]).relative_to(self.root).as_posix()
        self.patch(ops=[{"op": "upsert_decision", "summary": "按目标尺寸核对", "ref": "meeting:" + minutes}])
        self.assertIn("`meeting:public/meetings/tank_war.md`", self.read()["content"])
        target = {**self.role_arg, "id": job["id"]}
        def move(key, before, after, **extra):
            return self.cli("move", {**target, "key": key, "from": before, "to": after,
                            "actor": "用户" if before == REVIEW else self.owner,
                            "reason": "核对图标", "evidence": ["已核实图标对照"], **extra})
        self.assertIn("content", self.cli("memory-read", {**self.role_arg, "view": "handoff"}))
        self.assertEqual(self.cli("library-index", {**self.role_arg, "query": "图标"})["notes"], [])
        move("start", NEW, ACTIVE)
        items = [{"key": str(i), "kind": "reusable-pattern", "topic": f"图标学习{i}"} for i in range(4)]
        move("submit", ACTIVE, REVIEW, candidates=items)
        reason = "请在相同大小的画布上将轮廓缩放到实际显示尺寸再进行对比确认两个图标的边缘清晰"
        move("return", REVIEW, ACTIVE, reason=reason)
        self.assertIn(reason, self.read()["content"])
        peer_note = self.note(role=pm, title="跨角色验收", trigger="review")
        peer_note["admission"]["evidence_refs"] = [ref]
        self.assertIn("已归档", self.cli("library-upsert", peer_note, fail=True))
        self.patch(ops=[{"op": "upsert_risk", "summary": "轮廓需重拍", "ref": ref}])
        tree = self.repo / "repository/tank_war"
        (tree / "图标样张.txt").write_text("目标尺寸的小图标", encoding="utf-8")
        self.git(tree, "add", "图标样张.txt")
        self.git(tree, "commit", "-m", "Add icon sample")
        tested = self.cli("sync", self.role_arg)["test_this_commit"]
        self.assertEqual((tree / "图标样张.txt").read_text(encoding="utf-8"), "目标尺寸的小图标")
        receipt = self.cli("deliver", {**self.role_arg, "tested_commit": tested, "checks": ["读回目标尺寸样张"]})
        move("resubmit", ACTIVE, REVIEW, candidates=items, evidence=[receipt["commit"]])
        self.patch(focus={"current_goal": "完成教程验收", "progress": "修订样张已送验", "next_step": "复核目标尺寸"})
        (self.root / "public/图标对照.txt").write_text("小图标样张", encoding="utf-8")
        view = self.read()
        self.assertEqual((view["candidates_total"], len(view["candidates"])), (4, 3))
        queue = self.cli("library-index", {**self.role_arg, "task_id": job["id"]})["candidates"]
        extra = next(c for c in queue if c not in view["candidates"])
        request = self.note(trigger="review", resolve_candidate_id=extra["id"])
        request["admission"]["evidence_refs"].append(ref)
        self.cli("library-upsert", request, fail=True)
        archive = Path(move("passed", REVIEW, DONE)["path"])
        archived = archive.read_bytes()
        nav_before = self.nav.read_bytes()
        self.nav.write_text("用户导航草稿", encoding="utf-8")
        partial = self.cli("library-upsert", request)
        self.assertIn("note", partial["completed"])
        self.assertEqual(partial["pending"][0]["retry"], "library-lint")
        self.assertEqual(self.nav.read_text(encoding="utf-8"), "用户导航草稿")
        self.nav.write_bytes(nav_before)
        self.cli("library-lint", {"rebuild_moc": True})
        self.assertFalse(self.cli("library-upsert", request)["pending"])
        self.assertEqual(archive.read_bytes(), archived)
        notes = self.cli("library-index", {**self.role_arg, "query": "目标尺寸"})["notes"]
        self.assertEqual(len(notes), 1)
        info = self.cli("library-read", {**self.role_arg, "path": notes[0]["path"]})
        self.assertIn("固定尺寸 HUD", info["body"])
        self.assertEqual(self.cli("library-index", {"role": pm, "query": "目标尺寸"})["notes"], [])
        self.assertEqual(len(self.cli("library-index", {**self.role_arg, "version": "v1.0"})["candidates"]), 3)
        minor = next(c for c in queue if c["id"] != extra["id"])
        self.patch(ops=[{"op": "assess_candidate", "id": minor["id"], "status": "dismissed", "reason": "一次性微调"}])
        (self.root / "public/tank_war/rules.txt").write_text("匹配规则", encoding="utf-8")
        other = self.note(role=pm, kind="system-design", trigger="milestone")
        other["trigger"] = "review"
        other["admission"]["evidence_refs"] = ["code:rules.txt", ref]
        other["sections"].update(design="按设备分组", tradeoffs="按设备绑定可避免串扰")
        ambiguous = {**other, "meta": {**other["meta"], "prerequisites": ["[[图标对照]]"]}}
        self.assertIn("重名", self.cli("library-upsert", ambiguous, fail=True))
        other["meta"]["prerequisites"] = [f"[[{self.config['name']}/{self.person['dir']}/{notes[0]['path'][:-3]}]]"]
        duplicate = self.cli("library-upsert", other)
        self.assertEqual(duplicate["duplicate_title_warnings"], [{"role": self.owner, "path": notes[0]["path"]}])
        all_notes = self.cli("library-index", {"scope": "project", "query": "图标"})
        self.assertEqual({r["role"] for r in all_notes["notes"]}, {self.owner, pm})
        self.assertEqual(all_notes["candidates"], [])
        scoped = self.cli("library-index", {**self.role_arg, "scope": "project", "task_id": job["id"]})
        self.assertEqual(len(scoped["notes"]), 2)
        self.assertEqual(len(scoped["candidates"]), 2)
        self.assertEqual(self.cli("library-read", {"role": pm, "path": duplicate["path"]})["meta"]["evidence"][-1], ref)
        nav = self.nav.read_text(encoding="utf-8")
        self.assertIn("AT_工程师/可复用方案/图标对照|", nav)
        self.assertIn("AT_项目负责人/系统设计/图标对照|", nav)
        health = self.cli("library-lint")
        self.assertEqual((health["notes"], health["issues"], len(health["duplicate_titles"])), (2, [], 1))
        updated = {**request, "expected_sha256": info["sha256"]}
        updated["sections"] = {**request["sections"], "boundaries": "同尺寸 HUD 使用，测试 [[缺失笔记]]"}
        self.assertIn("缺失笔记", self.cli("library-upsert", updated, fail=True))
        self.assertEqual(self.cli("library-read", {**self.role_arg, "path": notes[0]["path"]})["sha256"], info["sha256"])
        self.cli("library-upsert", {**updated, "title": "越界/标题"}, fail=True)
        self.cli("library-read", {**self.role_arg, "path": "../别人.md"}, fail=True)

        payload = {"actor": pm, "actor_confirmed": True, "version": "v1.0", "kind": "user", "request_id": "guide",
                   "overview": "可以完成教程", "highlights": ["教程入口"], "capabilities": ["打开教程"],
                   "limitations": ["本地"], "next_steps": [], "how_to": ["选择教程"],
                   "artifacts": [{"task": job["id"], "path": "public/图标对照.txt"}]}
        released = self.cli("release", payload)
        self.assertEqual(released["memory_tag"], "memory/v1.0")
        self.assertIn("已正式发布：v1.0", self.doc.read_text(encoding="utf-8"))
        sealed = self.git(self.repo, "rev-parse", "refs/tags/memory/v1.0")
        self.cli("set-iteration", {"version": "v1.1", "goal": "准备下一关"})
        self.assertIn("准备下一关", self.doc.read_text(encoding="utf-8"))
        self.assertNotIn("v1.0", self.cli("project").get("version_goals", {}))
        for ref in ("version:1.0", "version:v1.0"):
            self.patch(ops=[{"op": "queue_library", "key": "retrospective", "kind": "system-design",
                             "topic": "封版回顾", "source": ref}])
        past = self.cli("library-index", {**self.role_arg, "version": "1.0", "query": "封版回顾"})["candidates"]
        self.assertEqual([c["source"] for c in past], ["version:v1.0"])
        self.cli("add-tasks", {"items": [{**self.item, "key": "next", "title": "下一关教程"}]})
        revision = self.cli("release", {**payload, "request_id": "revision", "action": "new", "previous_revision": 1})
        self.assertEqual(revision["revision"], 2)
        records = json.loads((self.root / ".at-state/releases.json").read_text(encoding="utf-8"))
        for key in ("baseline", "scope", "changes", "artifacts", "stages"):
            self.assertEqual(records[0][key], records[1][key], key)
        self.assertEqual(sealed, self.git(self.repo, "rev-parse", "refs/tags/memory/v1.0"))
        self.assertNotIn("准备下一关", self.cli("memory-history", {**self.role_arg, "version": "v1.0"})["content"])

    def test_note_admission_and_wikilinks_before_write(self):
        (self.root / "public/图标对照.txt").write_text("样张", encoding="utf-8")
        first = self.note(title="目标_尺寸")
        self.cli("library-upsert", first)
        self.assertIn("`可复用方案/目标_尺寸.md`", self.read()["content"])
        draft = self.note()
        folder = self.vault / self.person["library"] / "可复用方案"
        clean = self.nav.read_bytes()
        tests = [
            ({"sections": {k: "短" for k in draft["sections"]}, "meta": {**draft["meta"], "summary": "摘要" * 150}}, "300"),
            ({"meta": {**draft["meta"], "prerequisites": ["目标_尺寸"]}}, "双链"),
            ({"meta": {**draft["meta"], "prerequisites": ["[[[目标_尺寸]]]"]}}, "双链"),
            ({"meta": {**draft["meta"], "prerequisites": ["[[缺失读物]]"]}}, "缺失读物"),
            ({"meta": {**draft["meta"], "status": "superseded", "replacement": "目标_尺寸"}}, "双链"),
            ({"meta": {**draft["meta"], "status": "superseded", "replacement": "[[缺失替代]]"}}, "缺失替代"),
        ]
        for heading in ("# 自拟标题", "  ## 假章节"):
            tests.append(({"sections": {**draft["sections"], "steps": "开始\r\n" + heading}}, "三级"))
        for extra, message in tests:
            with self.subTest(extra=extra):
                self.assertIn(message, self.cli("library-upsert", {**draft, **extra}, fail=True))
                self.assertFalse((folder / "图标对照.md").exists())
                self.assertEqual(self.nav.read_bytes(), clean)
                self.assertFalse(list((self.root / ".at-state/learning-writes").glob("*.json")))
        draft["sections"]["steps"] += "\n### 验证顺序\n参考 [[目标_尺寸]]。"
        draft["meta"].update(prerequisites=["[[目标_尺寸|基础图例]]"], status="superseded",
                             replacement="[[可复用方案/目标_尺寸]]")
        self.cli("library-upsert", draft)
        self.assertFalse(self.cli("library-lint")["issues"])
        doc = folder / "图标对照.md"
        doc.write_text(doc.read_text(encoding="utf-8") + "\n[[已移走的样张]]", encoding="utf-8")
        self.assertIn("已移走的样张", self.cli("library-lint")["issues"][0]["error"])

    def test_project_index_and_navigation_with_missing_directories(self):
        other = self.cli("add-member", self.role("美术"))
        missing = self.vault / other["library"]
        for directory in missing.iterdir():
            directory.rmdir()
        missing.rmdir()
        (self.root / "public/图标对照.txt").write_text("样张", encoding="utf-8")
        result = self.cli("library-upsert", self.note())
        self.assertIn("navigation", result["completed"])
        self.assertFalse(result["pending"])
        for expected in (other["dir"], other["dir"] + "/系统设计"):
            health = self.cli("library-lint", {"rebuild_moc": True})
            self.assertIn(expected, {issue["path"] for issue in health["issues"]})
            self.assertIn(result["path"][:-3], self.nav.read_text(encoding="utf-8"))
            indexed = self.cli("library-index", {"scope": "project"})
            self.assertEqual([n["role"] for n in indexed["notes"]], [self.owner])
            (missing / "可复用方案").mkdir(parents=True, exist_ok=True)
        self.assertIn("scope", self.cli("library-index", {**self.role_arg, "scope": "other"}, fail=True))

    def test_memory_timestamp_identifiers_and_historical_goal(self):
        self.cli("add-tasks", {"items": [self.item]})
        (self.root / "public/tank_war/input_router.py").write_text("routes = {}", encoding="utf-8")
        state = self.repo / ".memory-state.json"
        def updated():
            return json.loads(state.read_bytes())["updated_at"]
        before = updated()
        self.patch(ops=[{"op": "upsert_risk", "summary": "由输入组确认，回归通过后解除", "ref": "code:input_router.py"}])
        stamp = updated()
        self.assertGreater(stamp, before)
        doc = self.doc.read_text(encoding="utf-8")
        self.assertIn("`code:input_router.py`", doc)
        self.assertIn(stamp, doc)
        self.assertEqual(doc.splitlines(), [row.rstrip() for row in doc.splitlines()])
        head = self.git(self.repo, "rev-parse", "HEAD")
        self.cli("memory-sync", self.role_arg)
        self.assertEqual((self.read()["content"], updated(), self.git(self.repo, "rev-parse", "HEAD")), (doc, stamp, head))
        self.cli("set-iteration", {"version": "1.0", "goal": "输入校验"})
        self.cli("set-iteration", {"version": "1.1"})
        self.patch(ops=[{"op": "upsert_decision", "summary": "延续输入校验", "ref": "version:1.0"}])
        self.assertEqual(self.read()["decisions"]["D01"]["ref"], "version:1.0")
        self.assertIn("未登记", self.cli("memory-patch", {**self.role_arg, "expected_sha256": self.read()["sha256"],
                      "ops": [{"op": "upsert_decision", "summary": "未知版本", "ref": "version:9.0"}]}, fail=True))

    def test_history_query_budget(self):
        for revision in range(6):
            ops = [{"op": "upsert_decision", "summary": f"共识 {revision} {i} " + "保持边界" * 10, "ref": "version:v1.0",
                    **({"id": f"D{i+1:02}"} if revision else {})} for i in range(10)]
            self.patch(ops=ops)
        history = self.cli("memory-history", {**self.role_arg, "query": "共识", "limit": 6})
        self.assertTrue(history["truncated"])
        self.assertLessEqual(len(history["history"].encode()), 8192)
        self.assertNotIn("�", history["history"])
        self.assertFalse(self.cli("memory-history", {**self.role_arg, "query": "共识", "limit": 1})["truncated"])

    def test_work_context_etag_and_role_directory_guard(self):
        other = "美术"
        art = self.cli("add-member", self.role(other))
        art_dir = self.root / art["dir"]
        (self.repo / ".agent/check.md").write_text("# 个人技能", encoding="utf-8")
        task = self.cli("add-tasks", {"items": [self.item]})[0]
        first = self.cli("work-context", {}, root=self.repo, cwd=self.repo)
        self.assertEqual(first["role"], self.owner)
        self.assertIn("content", first["agent"])
        self.assertIn("content", first["memory"])
        self.assertEqual(first["personal_skills"], [".agent/check.md"])
        self.assertEqual([t["id"] for t in first["tasks"]], [task["id"]])
        self.assertTrue(first["worktree"]["clean"])
        self.assertTrue(first["worktree"]["branch_matches"])
        self.assertEqual(first["worktree"]["behind_origin_main"], 0)

        cached = self.cli("work-context", {
            "agent_sha256": first["agent"]["sha256"],
            "memory_sha256": first["memory"]["sha256"],
        }, root=self.repo, cwd=self.repo)
        self.assertTrue(cached["agent"]["unchanged"])
        self.assertNotIn("content", cached["agent"])
        self.assertTrue(cached["memory"]["unchanged"])
        self.assertNotIn("content", cached["memory"])

        etag_read = self.cli("memory-read", {"view": "handoff", "if_none_match": first["memory"]["sha256"]},
                             root=self.repo, cwd=self.repo)
        self.assertTrue(etag_read["unchanged"])
        self.assertNotIn("content", etag_read)

        self.doc.write_bytes(self.doc.read_bytes() + "手动备注\n".encode())
        dirty_mem = self.cli("memory-read", {"view": "handoff", "if_none_match": first["memory"]["sha256"]},
                             root=self.repo, cwd=self.repo)
        self.assertNotIn("unchanged", dirty_mem)
        self.assertIn("手动备注", dirty_mem["manual_diff"])

        tree = self.repo / "repository/tank_war"
        (tree / "wip.txt").write_text("draft", encoding="utf-8")
        dirty_ctx = self.cli("work-context", {"agent_sha256": first["agent"]["sha256"]},
                             root=self.repo, cwd=self.repo)
        self.assertFalse(dirty_ctx["worktree"]["clean"])
        self.assertEqual(dirty_ctx["worktree"]["dirty_count"], 1)
        (tree / "wip.txt").unlink()

        self.assertIn("不能代办", self.cli("work-context", {"role": self.owner}, root=self.root, cwd=art_dir, fail=True))
        self.assertIn("不能代办", self.cli("work-context", {"role": self.owner}, root=art_dir, fail=True))
        self.assertIn("不能代办", self.cli("sync", {"role": self.owner}, root=self.root, cwd=art_dir, fail=True))
        synced = self.cli("sync", {}, root=self.repo, cwd=self.repo)
        self.assertIn("test_this_commit", synced)
        self.assertIn("不能代办", self.cli("deliver", {
            "role": self.owner, "tested_commit": synced["test_this_commit"], "checks": ["ok"]
        }, root=self.root, cwd=art_dir, fail=True))
