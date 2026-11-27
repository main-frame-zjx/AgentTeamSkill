"""Exercise formal publication from the same temporary project and CLI as the role workflow."""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

from test_lifecycle import ACTIVE, CLI, DONE, NEW, REVIEW, ProjectFixture

sys.path.insert(0, str(CLI.parent))
try:
    import at
    import releases
finally:
    sys.path.pop(0)


class Publications(ProjectFixture):
    def setUp(self):
        super().setUp()
        self.make_project_fixture()
        self.pm, self.dev = "项目负责人", "工程师"
        for name in [self.pm, self.dev]:
            self.cli("add-member", self.role(name))
        self.asset = self.root / "public/地图.txt"
        self.asset.write_text("教程起点（2, 3）", encoding="utf-8")
        self.items = {"key": "map", "role": self.dev, "prefix": "Dev", "title": "地图教程",
                      "goal": "从教程进入地图", "criteria": ["出现起点提示"]}
        self.state = self.root / ".at-state/releases.json"

    def add(self, key, target=None):
        row = {**self.items, "key": key, "title": "地图" + key}
        if target:
            row["version"] = target
        return self.cli("add-tasks", {"items": [row]})[0]

    def accept(self, item):
        for i, (before, after) in enumerate(zip((NEW, ACTIVE, REVIEW), (ACTIVE, REVIEW, DONE))):
            self.cli("move", {"role": self.dev, "id": item["id"], "actor": self.pm if after == DONE else self.dev,
                              "reason": "已核对教程起点", "key": str(i), "from": before, "to": after,
                              "evidence": ["public/地图.txt 中的起点可加载"]})

    def payload(self, item, target, kind="user"):
        return {"actor": self.pm, "actor_confirmed": True, "version": target, "kind": kind, "request_id": f"{kind}-{target}",
                "overview": "目前可以进入教程地图。", "highlights": ["出现新的起点提示。"],
                "capabilities": ["可以载入本地地图"], "limitations": ["仅有教程地图"], "next_steps": [],
                "blockers": ["地图仍待评审"], "decisions": ["下一张地图的主题"],
                "how_to": ["从主菜单选择教程"], "artifacts": [{"task": item["id"], "path": "public/地图.txt"}]}

    def verify_offline(self, entry, expected_images):
        edge = Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe"
        browser = str(edge) if edge.is_file() else shutil.which("chromium")
        if not browser:
            return
        # Open the original entry in a local frame; inspect the loaded DOM without changing the report.
        probe = self.base / "probe.html"
        probe.write_text('<iframe src="' + entry.as_uri() + '"></iframe><script>'
                         'window.onload=()=>{const d=document.querySelector("iframe").contentDocument;'
                         'if(d.images.length===' + str(expected_images) + ' && [...d.images].every(i=>i.naturalWidth>0)'
                         ' && getComputedStyle(d.body).marginTop==="0px" && d.querySelector("main section"))'
                         ' document.body.dataset.loaded="yes"}</script>', encoding="utf-8")
        proc = subprocess.run([browser, "--headless", "--disable-gpu", "--no-first-run", "--allow-file-access-from-files",
                               "--disable-background-networking", "--host-resolver-rules=MAP * ~NOTFOUND",
                               "--user-data-dir=" + str(self.base / "edge"), "--virtual-time-budget=3000",
                               "--dump-dom", probe.as_uri()], capture_output=True, timeout=45)
        self.assertIn(b'data-loaded="yes"', proc.stdout, proc.stderr[-1000:])

    def test_publication_identity_before_kind_or_payload(self):
        pm = self.root / ("AT_" + self.pm)
        dev = self.root / ("AT_" + self.dev)
        req = {"actor": self.pm, "kind": "dev"}
        self.assertIn("actor_confirmed", self.cli("release-check", req, fail=True, cwd=self.root))
        self.assertIn("actor_confirmed", self.cli("release-check", req, fail=True, cwd=self.root, root=pm))
        self.cli("release-check", {"kind": "dev"}, cwd=pm)
        confirmed = {**req, "actor_confirmed": True}
        self.cli("release-check", confirmed, cwd=self.root)
        for operation in ("release", "release-check", "verify-bin"):
            self.assertIn("AI 会话", self.cli(operation, confirmed, cwd=dev, fail=True))
        self.assertIn("AI 会话", self.cli("release", confirmed, cwd=dev, root=pm, fail=True))
        self.assertFalse(self.state.exists())

    def test_scope_roles_and_report_history(self):
        self.cli("release-check", {"actor": self.pm, "actor_confirmed": True}, fail=True)
        empty = self.cli("release-check", {"actor": self.pm, "actor_confirmed": True, "kind": "user"})
        self.assertFalse(empty["ready"])
        self.assertIsNone(empty["baseline"])
        first, second = self.add("一", "1.9"), self.add("二", "v1.09.0")
        self.accept(first)
        payload = self.payload(first, "v1.9")
        self.assertIn(second["id"], self.cli("release", payload, fail=True))
        self.assertFalse(self.state.exists())
        self.accept(second)
        self.cli("release", {**payload, "actor": self.dev}, fail=True)
        self.cli("release", payload, root=self.root / ("AT_" + self.dev), fail=True)
        self.cli("authorize-publisher", {"role": self.dev, "user_confirmed": True},
                 root=self.root / ("AT_" + self.dev), fail=True)
        self.cli("release", {**payload, "artifacts": [{"task": first["id"], "path": "public/缺失.txt"}]}, fail=True)
        self.cli("release", {**payload, "artifacts": []}, fail=True)
        self.assertEqual(list((self.root / "publish").glob("*/*")), [])
        source = self.base / "progress"
        source.mkdir()
        (source / "index.html").write_text("<p>测试报告</p>", encoding="utf-8")
        self.cli("publish", {"role": self.dev, "name": "日常汇报", "source": str(source)})
        self.assertIsNone(self.cli("release-check", payload)["baseline"])
        screenshot = self.root / "public/示例.png"
        screenshot.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
                                                "/x8AAwMCAO+aen8AAAAASUVORK5CYII="))
        payload["images"] = [{"path": "public/示例.png", "caption": "路径 <示例>"}]
        first_report = self.cli("release", payload)
        entry = Path(first_report["entry"])
        image = Path(first_report["bundle"]) / "assets/figure-1.png"
        self.assertEqual(image.read_bytes(), screenshot.read_bytes())
        body = entry.read_text(encoding="utf-8")
        self.assertIn("路径 &lt;示例&gt;", body)
        self.assertNotIn("public/地图.txt", body)
        self.verify_offline(entry, 1)
        self.assertTrue(self.cli("release", {"actor": self.pm, "actor_confirmed": True, "version": "1.9.0", "kind": "user",
                                             "action": "reuse"})["existing"])
        self.add("跨版", "1.9.1")
        intermediate = self.cli("list", {"role": self.dev, "stages": [NEW]})[0]
        self.accept(intermediate)
        newest = self.add("新", "1.10")
        self.accept(newest)
        repo = self.root / "public/tank_war"
        (repo / "map.txt").write_text("教程", encoding="utf-8")
        self.git(repo, "add", "map.txt")
        self.git(repo, "commit", "-m", "Add tutorial map")
        payload = self.payload(newest, "v1.10")
        payload["artifacts"] = [{"task": newest["id"], "commit": self.git(repo, "rev-parse", "HEAD")}]
        check = self.cli("release-check", payload)
        self.assertTrue(check["ready"], check)
        self.assertEqual([r["version"] for r in check["changes"]], ["v1.9.1", "v1.10"])
        second_entry = Path(self.cli("release", payload)["entry"])
        text = second_entry.read_text(encoding="utf-8")
        self.assertIn("从主菜单选择教程", text)
        self.assertNotIn("public/地图.txt", text)
        self.verify_offline(second_entry, 0)
        self.assertEqual([r["version"] for r in json.loads(self.state.read_text(encoding="utf-8"))], ["v1.9", "v1.10"])
        self.cli("add-tasks", {"items": [{**self.items, "version": "1.09"}]}, fail=True)

    def test_default_version_replay_and_authorization(self):
        first = self.cli("add-tasks", {"items": [self.items]})[0]
        self.accept(first)
        self.cli("set-iteration", {"version": "2.0"})
        replay = self.cli("add-tasks", {"items": [self.items]})[0]
        self.assertEqual((replay["id"], replay["version"]), (first["id"], "v1.0"))
        self.cli("authorize-publisher", {"role": "不存在", "user_confirmed": True}, fail=True)
        self.cli("add-member", self.role("制作人"))
        self.cli("authorize-publisher", {"role": "制作人"}, fail=True)
        self.cli("authorize-publisher", {"role": "制作人", "user_confirmed": True})
        check = self.cli("release-check", {**self.payload(first, "v1.0"), "actor": "制作人"})
        self.assertTrue(check["ready"], check["issues"])
        current_item = self.add("默认")
        self.assertEqual(self.cli("show", {"role": self.dev, "id": current_item["id"]})["current"]["version"], "v2.0")
        meeting = {"key": "m", "topic": "项目评审", "opening": "版本", "rounds": [
            {r: "同意" for r in [self.pm, self.dev, "制作人"]} for _ in range(10)],
            "decisions": [], "user_decisions": [], "open_questions": [], "version": "2.2",
            "items": [{**self.items, "key": "a"}, {**self.items, "key": "b", "version": "2.1"}]}
        assigned = self.cli("meeting", meeting)
        self.cli("set-iteration", {"version": "3"})
        self.assertEqual(assigned, self.cli("meeting", meeting))
        items = [self.cli("show", {"role": self.dev, "id": i["id"]})["current"] for i in assigned["items"]]
        self.assertEqual([r["version"] for r in items], ["v2.2", "v2.1"])
        self.assertEqual(self.add("默认"), current_item)

    def test_interruption_after_files_installed(self):
        item = self.add("新")
        self.accept(item)
        req = self.payload(item, "1.0")
        original = releases.write
        def fail_history(path, value):
            if path == self.state:
                raise OSError("simulated interruption")
            original(path, value)
        with patch.object(releases, "write", fail_history), self.assertRaises(OSError):
            at.run("release", self.root, req)
        self.assertFalse(self.state.exists())
        self.assertTrue((self.root / "publish/user/v1.0/r1/index.html").is_file())
        self.cli("add-tasks", {"items": [{**self.items, "version": "1.0"}]}, fail=True)
        self.cli("release", {"version": "2.0", "actor": self.pm, "actor_confirmed": True, "kind": "user"}, fail=True)
        recovered = self.cli("release", {"actor": self.pm, "actor_confirmed": True, "version": "1.0", "kind": "user",
                                         "request_id": req["request_id"]})
        self.assertFalse(recovered["existing"])
        self.assertFalse((self.root / ".at-state/release-pending").exists())
        self.assertEqual(len(json.loads(self.state.read_text(encoding="utf-8"))), 1)

    def test_dev_snapshot_binary_guide_and_revisions(self):
        item = self.add("教程")
        dev = self.payload(item, "1.0", "dev")
        dev.pop("artifacts")
        self.cli("release", {**dev, "actor": self.dev}, fail=True)
        first = self.cli("release", dev)
        original = Path(first["entry"])
        original_bytes = original.read_bytes()
        self.assertEqual(original.relative_to(self.root).as_posix(), "publish/dev/v1.0/r1/index.html")
        self.assertIn("新需求", original_bytes.decode())
        self.verify_offline(original, 1)
        second = self.add("扩展")
        guide = self.payload(item, "1.0")
        self.assertIn(item["id"], self.cli("release", guide, fail=True))
        self.accept(item)
        self.accept(second)
        source = self.root / "public/build"
        source.mkdir()
        if os.name != "nt":
            self.skipTest("Windows 程序迁移测试需要 Windows")
        # Build a Windows console app when the compiler is installed. Its search requires an external data file.
        compiler = shutil.which("gcc")
        if compiler:
            code = self.base / "search.c"
            code.write_text('#include <stdio.h>\n#include <string.h>\n'
                            'int main(int n, char **v) {\n'
                            '    if (n != 3) return 2;\n'
                            '    FILE *f = fopen(v[2], "r");\n'
                            '    if (!f) return 3;\n'
                            '    char line[256];\n'
                            '    while (fgets(line, sizeof line, f)) {\n'
                            '        if (strstr(line, v[1])) { fputs(line, stdout); fclose(f); return 0; }\n'
                            '    }\n    fclose(f); return 1;\n}\n', encoding="ascii")
            build = subprocess.run([compiler, code.name, "-o", "Search.exe"], cwd=self.base, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            shutil.copy2(self.base / "Search.exe", source / "Search.exe")
        else:
            shutil.copy2(Path(os.environ["SystemRoot"]) / "System32/findstr.exe", source / "Search.exe")
        (source / "data").mkdir()
        resource = source / "data/example.txt"
        resource.write_text("tutorial-match\n", encoding="ascii")
        probe = {"actor": self.pm, "actor_confirmed": True, "version": "v1.0", "source": "public/build", "entry": "Search.exe",
                 "feature": "检索随包文本", "args": ["tutorial", r"data\example.txt"], "expect": "tutorial-match",
                 "build_evidence": "测试程序与教程资源的发行目录"}
        self.cli("verify-bin", {**probe, "expect": "not-present"}, fail=True)
        proof = self.cli("verify-bin", probe)
        binary = self.payload(item, "1.0", "bin")
        binary["bin_check"] = proof["id"]
        resource.write_text("changed\n", encoding="ascii")
        self.cli("release", binary, fail=True)
        self.assertEqual(list((self.root / "publish/bin").iterdir()), [])
        resource.write_text("tutorial-match\n", encoding="ascii")
        built = self.cli("release", binary)
        self.assertEqual(Path(built["entry"]).relative_to(self.root).as_posix(), "publish/bin/v1.0/r1/Search.exe")
        self.assertTrue(built["verification"]["architecture"])
        moved = self.base / "portable copy"
        shutil.copytree(built["bundle"], moved)
        self.assertIn(b"tutorial-match", subprocess.check_output([str(moved / "Search.exe"), *probe["args"]], cwd=moved))
        guide.pop("artifacts")  # The already accepted version supplies its evidence.
        user = self.cli("release", guide)
        self.assertEqual(Path(user["entry"]).relative_to(self.root).as_posix(), "publish/user/v1.0/r1/index.html")
        self.cli("add-tasks", {"items": [self.items]}, fail=True)
        choice = self.cli("release", {"kind": "dev", "version": "1", "actor": self.pm, "actor_confirmed": True})
        self.assertTrue(choice["needs_choice"])
        self.assertEqual(choice["latest"]["revision"], 1)
        reuse = self.cli("release", {"kind": "dev", "actor": self.pm, "actor_confirmed": True, "action": "reuse"})
        self.assertEqual(reuse["entry"], first["entry"])
        update = {**dev, "request_id": "second-review", "action": "new", "previous_revision": 1}
        revised = self.cli("release", update)
        self.assertEqual(Path(revised["entry"]).relative_to(self.root).as_posix(), "publish/dev/v1.0/r2/index.html")
        self.assertIn("已归档", Path(revised["entry"]).read_text(encoding="utf-8"))
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertTrue(self.cli("release", update)["existing"])
        self.cli("release", {**update, "overview": "不同的总结"}, fail=True)
        self.cli("release", {**update, "request_id": "different"}, fail=True)
        self.assertFalse((self.root / "publish/dev/v1.0/r3").exists())
        self.cli("add-tasks", {"items": [self.items]}, fail=True)  # Recent dev snapshot did not reopen v1.0.
