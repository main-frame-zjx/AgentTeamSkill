"""HTTP and file-mode browser tests share a real, local project snapshot."""
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "chat-visual"))
import serve
from chat_core.engine import run
from chat_core.store import initialize
from tasks import initial, block
from core import STAGES


class Viewer(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="at-chat-网页")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / "坦克"
        data = {"format": "agent-team/v3", "id": "viewer-test", "name": "坦克大战",
                "team_repo": "public/game", "current_version": "v1.0", "members": [
                    {"name": "工程师", "dir": "AT_工程师", "task_prefix": "Dev"},
                    {"name": "验收人", "dir": "AT_验收人", "task_prefix": "QA"}]}
        self.root.mkdir()
        (self.root / "AT.json").write_text(json.dumps(data), encoding="utf-8")
        initialize(self.root, data)
        for r in data["members"]:
            for stage in STAGES:
                (self.root / r["dir"] / "workspace" / stage).mkdir(parents=True)
        self.task_id = "AT-" + "a"*32
        self.filename = "AT-Dev00001-坦克碰撞.md"
        base = self.root / "AT_工程师/workspace"
        spec = {"id": self.task_id, "format": "agent-team/task-v1", "version": "v1.0", "owner": "工程师",
                "reviewer": "验收人", "title": "坦克碰撞", "goal": "检查碰撞边界", "criteria": ["墙边停止"]}
        raw = initial(spec)
        self.old = "AT_工程师/workspace/" + STAGES[0] + "/" + self.filename
        (self.root / self.old).write_bytes(raw.encode())
        run("send", self.root, {"sender": "工程师", "sender_model": "gpt-series", "kind": "collab_request",
                               "task_id": self.task_id, "to": ["验收人","用户"], "body": "请核对碰撞接口",
                               "refs": [{"path": self.old, "lines": "1-2"}], "idempotency_key": "check"})
        event = {"type": "move","from": STAGES[0], "to": STAGES[1], "actor": "工程师",
                 "key": "start", "reason": "实施"}
        (base / STAGES[1] / self.filename).write_bytes((raw+"\n"+block(event)).encode())
        (self.root / self.old).unlink()
        env = patch.dict(os.environ, LOCALAPPDATA=str(self.base / "app"))
        env.start()
        self.addCleanup(env.stop)
        self.server = serve.ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        self.server.registry = serve.Registry(self.root)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.key = self.server.registry.state()["active"]
        self.api = "/api/projects/" + self.key
        self.post_headers = {"Origin": f"http://127.0.0.1:{self.server.server_port}", "X-Chat-Request": "1"}

    def http(self, route, headers=None, method="GET"):
        c = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            c.request(method, route, headers=headers or {})
            res = c.getresponse()
            return res.status, res.read(), res.getheader("ETag")
        finally:
            c.close()

    def test_http_snapshot_and_switch(self):
        s, raw, etag = self.http(self.api+"/snapshot")
        self.assertEqual(s, 200)
        view = json.loads(raw)
        self.assertEqual(view["pending_total"], run("summary", self.root, {})["pending_total"])
        self.assertEqual(view["groups"][0]["task"]["stage"], STAGES[1])
        self.assertEqual(self.http(self.api+"/snapshot", {"If-None-Match":etag})[0],304)
        self.assertEqual(self.http("/api/health", {"Host":"invalid"})[0],403)
        self.assertEqual(self.http("/api/projects/pick", {"Origin":"https://invalid.example"}, "POST")[0],403)
        for bad in ("../AT.json",".git/config","C:/test.md"):
            self.assertEqual(self.http(self.api+"/file?path="+quote(bad))[0],400)
        self.assertEqual(self.http(self.api+"/file?path="+quote(self.old))[0],400)
        self.assertEqual(self.http(self.api+"/file?path="+quote(view["groups"][0]["task"]["path"]))[0],200)
        second = self.base/"另一个项目"
        second.mkdir()
        data = json.loads((self.root/"AT.json").read_bytes()) | {"id":"other", "name":"另一个项目","members":[]}
        (second/"AT.json").write_text(json.dumps(data))
        initialize(second,data)
        registry = self.server.registry.select(folder=second)
        self.assertEqual(len(registry["projects"]),2)
        self.assertEqual(json.loads(self.http(self.api+"/select",self.post_headers,method="POST")[1])["active"],self.key)
        group = next((self.root/"public/chat/groups").glob("*.json"))
        group.write_bytes(b"{")
        self.assertTrue(json.loads(self.http(self.api+"/snapshot")[1])["warnings"])

    def test_registry_and_empty_project(self):
        for headers in ({}, {"Origin": self.post_headers["Origin"]}, {"X-Chat-Request": "1"}):
            self.assertEqual(self.http(self.api + "/select", headers, "POST")[0], 403)
        board = self.server.registry.board
        board.parent.mkdir(parents=True)
        ghost = self.base / "失效项目"
        board.write_text(json.dumps({"projects": [{"root": str(ghost), "id": "old"}]}))
        row = self.server.registry.state()["unavailable"][0]
        endpoint = "/api/projects/" + row["id"] + "/remove"
        self.assertFalse(json.loads(self.http(endpoint, self.post_headers, "POST")[1])["unavailable"])
        self.assertTrue(board.exists())
        self.assertFalse(serve.Registry(self.root).state()["unavailable"])
        (self.root / "public/chat").rename(self.base / "backup")
        result = json.loads(self.http(self.api + "/overview")[1])
        self.assertEqual((result["initialized"], result["groups"], result["pending_total"]), (False, [], 0))
        self.assertFalse((self.root / "public/chat").exists())

    def test_picker_mutex_and_group_detail(self):
        opened, release = threading.Event(), threading.Event()
        def choose():
            opened.set()
            release.wait(4)
            return ""
        def pick():
            return self.http("/api/projects/pick", self.post_headers, "POST")[0]
        from concurrent.futures import ThreadPoolExecutor
        with patch.object(serve, "pick_folder", choose), ThreadPoolExecutor(1) as pool:
            first = pool.submit(pick)
            try:
                self.assertTrue(opened.wait(2))
                self.assertEqual(pick(), 409)
                self.assertEqual(self.http("/api/health")[0], 200)
            finally:
                release.set()
            self.assertEqual(first.result(), 200)
        with patch.object(serve, "pick_folder", return_value=""):
            self.assertEqual(pick(), 200)
        group = json.loads(self.http(self.api + "/overview")[1])["groups"][0]
        self.assertNotIn("messages", group)
        self.assertTrue(group["last_preview"])
        detail = json.loads(self.http(self.api + "/groups/" + quote(group["group_id"]))[1])
        self.assertEqual(detail["messages"][0]["body"], group["last_preview"])

    @unittest.skipUnless(os.environ.get("AT_CHAT_PLAYWRIGHT"), "set AT_CHAT_PLAYWRIGHT to an installed Playwright package")
    def test_browser_http_and_file(self):
        cancelled = threading.Event()
        original = serve.Handler.reply

        def reply(handler, status, *args, **kwargs):
            if status == 409:
                cancelled.set()
            return original(handler, status, *args, **kwargs)

        def choose():
            if not cancelled.wait(6):
                raise RuntimeError("并发选择器验收超时")
            return ""

        with patch.object(serve.Handler, "reply", reply), patch.object(serve, "pick_folder", choose):
            subprocess.run(["node", str(ROOT/"chat-visual/tests/browser.cjs"), str(self.root),
                            f"http://127.0.0.1:{self.server.server_port}/", sys.executable], check=True, timeout=90,
                           env={**os.environ, "AT_CHAT_TEST_PICKER": "1"})
