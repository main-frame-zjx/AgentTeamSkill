"""Exercise the public MCP, crash boundary, real Markdown transitions and installer."""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_lifecycle import ProjectFixture

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/at-receive-message/scripts"
sys.path.insert(0, str(SCRIPTS))
from chat_core.engine import run
from chat_core.store import initialize


class Client:
    def __init__(self, case, roots=False):
        self.p = subprocess.Popen([sys.executable, "-B", "-X", "utf8", str(SCRIPTS / "at_chat_mcp.py")],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, encoding="utf-8")
        case.addCleanup(self.close)
        self.number = 0
        assert self.rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {"roots": {}} if roots else {}})["protocolVersion"] == "2025-11-25"
        self.write({"method": "notifications/initialized"})

    def write(self, msg):
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", **msg}) + "\n")
        self.p.stdin.flush()

    def rpc(self, method, params):
        self.number += 1
        self.write({"method": method, "id": self.number, "params": params})
        reply = json.loads(self.p.stdout.readline())
        assert reply["id"] == self.number, reply
        return reply["result"]

    def tool(self, name, root, **fields):
        result = self.rpc("tools/call", {"name": "chat_" + name, "arguments": {"working_dir": str(root), **fields}})
        return result if result.get("isError") else result["structuredContent"]

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=5)
        self.p.stdout.close()
        self.p.stderr.close()


class ChatLifecycle(ProjectFixture):
    def test_review_loop(self):
        self.cli("init", self.init)
        owner, reviewer = "工程师", "项目负责人"
        for role in (owner, reviewer):
            self.cli("add-member", self.role(role))
        item = {"key": "collision", "role": owner, "prefix": "Dev", "title": "碰撞检测",
                "goal": "墙体阻挡", "criteria": ["碰撞测试通过"]}
        task = self.cli("add-tasks", {"items": [item]})[0]["id"]
        a, b = [self.root / ("AT_" + r) for r in (owner, reviewer)]
        client = Client(self)
        self.assertEqual(len(client.rpc("tools/list", {})["tools"]), 5)
        self.assertTrue(client.tool("receive", a, role=reviewer)["isError"])
        self.assertEqual(client.rpc("ping", {}), {})

        def move(actor, before, after, key):
            self.cli("move", {"role": owner, "actor": actor, "id": task, "key": key,
                              "from": before, "to": after, "reason": key, "evidence": ["实际测试"]})

        def notify(actor, directory, model, reply=None):
            missing = run("workflow", directory, {})["missing_notifications"]
            self.assertEqual(len(missing), 1)
            row = {k: v for k, v in missing[0].items() if k not in ("reason", "actor")}
            row["body"] = missing[0]["reason"]
            handles = []
            if reply:
                row["reply_to"] = reply
                handles.append({"message_id": reply, "resolution": "replied", "note": row["body"]})
            req = {"model": model, "handle": handles, "send": [row]}
            first = client.tool("settle", directory, **req)
            self.assertFalse(first.get("isError"), first)
            self.assertTrue(client.tool("settle", directory, **req)["sent"][0]["duplicate"])
            self.assertFalse(run("workflow", directory, {})["missing_notifications"])
            return first["sent"][0]["message_id"]

        move(owner, "1新需求", "2处理中", "开始")
        move(owner, "2处理中", "3待验收", "初验")
        startup = self.cli("work-context", root=a)
        self.assertEqual(startup["missing_notifications"][0]["event_key"], "初验")
        self.assertEqual(self.cli("work-context", root=b)["pending_reviews"][0]["id"], task)
        first = notify(owner, a, "gpt-series")
        self.assertEqual(self.cli("help", root=b)["recommendation"]["skill"], "at-work")
        self.assertEqual(self.cli("work-context", root=b)["inbox_summary"]["pending"], 1)
        inbox = client.tool("receive", b)
        self.assertEqual(inbox["messages"][0]["id"], first)
        move(reviewer, "3待验收", "2处理中", "打回")
        rejection = notify(reviewer, b, "gemini-series", first)
        move(owner, "2处理中", "3待验收", "复验")
        second = notify(owner, a, "gpt-series", rejection)
        move(reviewer, "3待验收", "4已归档", "通过")
        result = client.tool("settle", b, model="gemini-series", handle=[
            {"message_id": second, "resolution": "accepted", "note": "通过并归档"}])
        self.assertEqual(result["remaining_pending"], 0)
        history = client.tool("history", b, task_id=task)
        self.assertEqual([m["overall_status"] for m in history["messages"]], ["handled"] * 3)
        self.assertEqual(history["task"]["stage"], "4已归档")
        self.assertEqual(client.tool("groups", b)["pending_total"], 0)


    def test_reassignment_backfill_and_custom_keys(self):
        self.cli("init", self.init)
        owner, previous, current, cc = "工程师", "项目负责人", "策划", "美术"
        for role in (owner, previous, current, cc):
            self.cli("add-member", self.role(role))
        task = self.cli("add-tasks", {"items": [{"key": "accept", "role": owner, "prefix": "Dev",
            "title": "角色验收", "goal": "按人通知", "criteria": ["能够复验"]}]})[0]["id"]
        def move(actor, before, after, key):
            return self.cli("move", {"role": owner, "actor": actor, "id": task, "key": key,
                "from": before, "to": after, "reason": key, "evidence": ["测试记录"]})
        def client_for(role):
            client = Client(self)
            return lambda tool, **req: client.tool(tool, self.root / ("AT_" + role), **req)
        engineer, manager, reviewer = map(client_for, (owner, previous, current))
        move(owner, "1新需求", "2处理中", "开始")
        move(owner, "2处理中", "3待验收", "初验")
        request = {"task_id": task, "kind": "review_request", "body": "请验收", "to": [previous, cc],
                   "idempotency_key": "first"}
        first = engineer("settle", model="gpt", send=[request])["sent"][0]["message_id"]
        self.assertFalse(run("workflow", self.root, {"role": owner})["missing_notifications"])
        alias = dict(request, idempotency_key="alternate")
        self.assertEqual(engineer("settle", model="gpt", send=[alias])["sent"][0],
                         {"message_id": first, "group_id": "task:" + task, "duplicate": True})
        self.assertTrue(engineer("settle", model="gpt", send=[dict(alias, body="变更")])["isError"])
        amend = self.cli("amend", {"role": owner, "actor": previous, "id": task, "key": "改派",
            "reason": "由策划复核", "changes": {"reviewer": current}})
        self.assertEqual(amend["notification"]["actor"], previous)
        assigned = dict(request, to=[current, cc], idempotency_key="handoff", reply_to=first)
        result = manager("settle", model="gemini", send=[assigned],
                         handle=[{"message_id": first, "resolution": "replied", "note": "已移交"}])
        mid = result["sent"][0]["message_id"]
        self.assertFalse(run("workflow", self.root, {"role": owner})["missing_notifications"])
        move(current, "3待验收", "2处理中", "退回")
        self.assertTrue(manager("settle", model="gemini", send=[assigned])["sent"][0]["duplicate"])
        returned = reviewer("settle", model="gemini", send=[dict(request, kind="review_rejected",
                            to=[owner, cc], idempotency_key="return", reply_to=mid)],
                            handle=[{"message_id": mid, "resolution": "replied", "note": "需返工"}])
        self.assertEqual(len(returned["sent"]), 1)
        move(owner, "2处理中", "3待验收", "复验")
        resubmission = dict(request, to=[current], idempotency_key="second", reply_to=returned["sent"][0]["message_id"])
        again = engineer("settle", model="gpt", send=[resubmission], handle=[{
            "message_id": resubmission["reply_to"], "resolution": "replied", "note": "已修复"}])
        move(current, "3待验收", "4已归档", "通过")
        accepted = reviewer("settle", model="gemini", handle=[{"message_id": again["sent"][0]["message_id"],
                                                               "resolution": "accepted", "note": "验收通过"}])
        self.assertEqual((accepted["remaining_pending"], accepted["sent"]), (0, []))
        self.assertEqual(run("receive", self.root, {"role": cc})["pending_total"], 3)

    def test_legacy_reads_and_lazy_first_writers(self):
        self.cli("init", self.init)
        self.cli("add-member", self.role("工程师"))
        area = self.root / "public/chat"
        area.rename(self.base / "backup")
        self.assertEqual(self.cli("help")["status"], "project")
        self.assertFalse(self.cli("work-context", root=self.root / "AT_工程师")["initialized"])
        self.assertFalse(run("groups", self.root, {})["initialized"])
        self.assertFalse(area.exists())
        self.assertFalse((self.root / ".at-state/chat.lock").exists())
        def create(i):
            return run("create-group", self.root, {"role": "工程师", "slug": f"topic-{i}", "title": "协作"})
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            list(pool.map(create, range(4)))
        self.assertEqual(run("summary", self.root, {})["groups_total"], 4)
        (area / "meta.json").rename(self.base / "saved-meta.json")
        self.assertIn("meta.json", self.cli("help")["path"])
        with self.assertRaisesRegex(ValueError, "已有数据"):
            create(5)


    def test_self_review_and_user_review(self):
        self.cli("init", self.init)
        role = "工程师"
        self.cli("add-member", self.role(role))
        directory = self.root / ("AT_" + role)
        for reviewer in (role, "用户"):
            item = {"key": reviewer, "role": role, "prefix": "Dev", "title": "交付核验",
                    "goal": "能够复核", "criteria": ["报告齐全"], "reviewer": reviewer}
            task = self.cli("add-tasks", {"items": [item]})[0]["id"]
            for before, after in (("1新需求", "2处理中"), ("2处理中", "3待验收")):
                result = self.cli("move", {"role": role, "actor": role, "id": task, "key": after,
                                           "from": before, "to": after, "reason": "核验", "evidence": ["报告"]})
            if reviewer == role:
                self.assertIsNone(result["notification"])
                startup = self.cli("work-context", root=directory)
                self.assertEqual(startup["pending_reviews"][0]["id"], task)
                self.assertEqual(startup["missing_notifications"], [])
                continue
            reminder = result["notification"]
            send = {k: v for k, v in reminder.items() if k not in ("actor", "reason")}
            out = run("settle", directory, {"model":"gpt-series", "send":[{**send, "body":"请本人验收"}]})
            self.assertEqual(run("receive", self.root, {"role":"用户"})["pending_total"], 1)
            self.cli("move", {"role": role, "actor": reviewer, "id": task, "key": "通过", "from": "3待验收",
                              "to": "4已归档", "reason": "本人确认", "evidence": ["报告"]})
            done = run("handle", self.root, {"role": reviewer, "model": "ignored", "items":[
                {"message_id":out["sent"][0]["message_id"], "resolution":"accepted", "note":"本人确认"}]})
            self.assertEqual(done["handled"][0]["handled_by_model"], "human")


class Storage(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="角色通讯-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.data = {"format": "agent-team/v3", "id": "example", "current_version": "v1.0",
                     "team_repo": "public/Chat", "members": [{"name": n, "dir": "AT_" + n} for n in "甲乙丙"]}
        (self.root / "AT.json").write_text(json.dumps(self.data), encoding="utf-8")
        initialize(self.root, self.data)
        for name in "甲乙丙":
            (self.root / ("AT_" + name)).mkdir()
        for slug in ("one", "two"):
            run("create-group", self.root, {"role": "甲", "slug": slug, "title": slug})
        self.item = {"group_id": "topic:one", "kind": "collab_request", "to": ["乙", "丙"], "body": "请核对接口"}

    def settle(self, key):
        return run("settle", self.root, {"role": "甲", "model": "gpt-series",
                                        "send": [{**self.item, "idempotency_key": str(key)}]})

    def test_blocked_and_historical_replies(self):
        mid = self.settle("start")["sent"][0]["message_id"]
        def settle(**args):
            return run("settle", self.root, {"role": "乙", "model": "gemini", **args})
        def handle(resolution, note):
            return [{"message_id": mid, "resolution": resolution, "note": note}]
        response = dict(self.item, to=["甲"], reply_to=mid, idempotency_key="clarify")
        with self.assertRaisesRegex(ValueError, "其他指定角色"):
            settle(send=[dict(response, to=["乙", "甲"])])
        first = settle(send=[response])["sent"][0]["message_id"]
        blocked = settle(handle=handle("deferred", "等接口确认"))
        self.assertEqual((blocked["handled"], blocked["remaining_pending"]), ([], 1))
        self.assertEqual(blocked["deferred"], settle(handle=handle("deferred", "等接口确认"))["deferred"])
        pending = run("receive", self.root, {"role": "乙"})["messages"][0]["recipients"]["乙"]
        self.assertEqual(pending["blocked"]["reply_message_ids"], [first])
        second = settle(send=[dict(response, idempotency_key="confirm", body="接口已确认")])["sent"][0]["message_id"]
        row = settle(handle=handle("replied", "已确认"))["handled"][0]
        self.assertEqual(row["reply_message_ids"], [first, second])
        self.assertEqual(settle(handle=handle("replied", "已确认"))["handled"][0], row)
        self.assertEqual(run("receive", self.root, {"role": "丙"})["pending_total"], 1)

    def test_multi_reply_atomicity_and_no_reuse_of_bad_sequence(self):
        mid = self.settle("source")["sent"][0]["message_id"]
        send = [{**self.item, "reply_to": mid, "idempotency_key": n, "to": ["甲"]} for n in ("a", "b")]
        request = {"role": "乙", "model": "gemini", "send": send,
                   "handle": [{"message_id": mid, "resolution": "replied", "note": "已回复"}]}
        result = run("settle", self.root, request)
        self.assertEqual(result["handled"][0]["reply_message_ids"], [m["message_id"] for m in result["sent"]])
        self.assertEqual(run("settle", self.root, request)["handled"], result["handled"])
        path = self.root / "public/at-chat/groups/topic__one.json"
        group = json.loads(path.read_bytes())
        group["messages"][0].update(seq=4, id="MSG-000004")
        path.write_text(json.dumps(group), encoding="utf-8")
        self.assertTrue(run("summary", self.root, {})["warnings"])
        with self.assertRaisesRegex(ValueError, "next_seq"):
            run("settle", self.root, {"role": "甲", "model": "gpt", "send": [
                {**self.item, "group_id": "topic:two", "idempotency_key": "next"}]})
        self.assertEqual(run("history", self.root, {"group_id": "topic:two"})["messages"], [])

    def test_isolate_malformed_task_and_duplicate_group_sequences(self):
        self.settle("good")
        folder = self.root / "AT_丙/workspace/1新需求"
        folder.mkdir(parents=True)
        (folder / "未写完.md").write_text("未完成", encoding="utf-8")
        result = self.settle("also-good")
        self.assertTrue(any("未写完.md" in w for w in result["warnings"]))
        self.assertFalse(any(str(self.root) in w for w in result["warnings"]))
        self.assertEqual(run("receive", self.root, {"role": "乙"})["pending_total"], 2)
        run("settle", self.root, {"role": "甲", "model": "gpt", "send": [
            {**self.item, "group_id": "topic:two", "idempotency_key": "second-group"}]})
        path = self.root / "public/at-chat/groups/topic__two.json"
        group = json.loads(path.read_bytes())
        group["messages"][0].update(seq=1, id="MSG-000001")
        path.write_text(json.dumps(group), encoding="utf-8")
        result = run("summary", self.root, {})
        self.assertEqual((result["pending_total"], len(result["warnings"])), (0, 2))
        with self.assertRaises(ValueError):
            self.settle("ambiguous")

    def test_pages_and_concurrent_senders(self):
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            list(pool.map(self.settle, range(35)))
        first = run("receive", self.root, {"role": "乙"})
        self.settle("later")
        second = run("receive", self.root, {"role": "乙", "cursor": first["next_cursor"]})
        self.assertEqual(len({m["id"] for m in first["messages"] + second["messages"]}), 35)
        self.assertEqual(second["returned"], 5)
        mid = first["messages"][0]["id"]
        run("handle", self.root, {"role": "乙", "model": "gemini", "items": [
            {"message_id": mid, "note": "已完成", "resolution": "resolved"}]})
        self.assertEqual(run("summary", self.root, {})["pending_total"], 71)
        msg = run("history", self.root, {"group_id": "topic:one"})["messages"][0]
        self.assertEqual(msg["overall_status"], "partial")
        run("reopen", self.root, {"role": "乙", "model": "gemini", "items": [{"message_id": mid, "note": "需复核"}]})
        self.assertEqual(run("summary", self.root, {})["pending_total"], 72)

    def test_concurrent_cli_and_rejected_batch(self):
        def invoke(i):
            args = {"role": "甲", "model": "gpt-series", "send": [{**self.item, "idempotency_key": str(i)}]}
            p = subprocess.run([sys.executable, "-B", str(SCRIPTS/"at_chat.py"), "settle", "--root",
                                str(self.root), "--input", "-"], input=json.dumps(args).encode(),
                               capture_output=True, check=True, timeout=40)
            return json.loads(p.stdout)["result"]["sent"][0]["message_id"]
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            ids = list(pool.map(invoke, range(30)))
        self.assertEqual(sorted(ids), [f"MSG-{n:06d}" for n in range(1,31)])
        for modification in ({"refs":[{"path":"../outside.md"}]}, {"body":"x"*1501}, {"to":["未知"]}):
            with self.assertRaises(ValueError):
                run("settle", self.root, {"role":"甲", "model":"gpt-series", "send":[
                    {**self.item, "idempotency_key":"valid"}, {**self.item, **modification, "idempotency_key":"bad"}]})
        self.assertEqual(run("summary", self.root, {})["pending_total"], 60)

    def test_mcp_checks_host_roots_and_survives_invalid_json(self):
        client = Client(self)
        print("invalid json", file=client.p.stdin)
        client.p.stdin.flush()
        self.assertEqual(json.loads(client.p.stdout.readline())["error"]["code"], -32700)
        # A fresh session advertises client-provided roots.
        client = Client(self, roots=True)
        for path, rejected in ((self.root / "AT_乙", True), (self.root / "AT_甲", False)):
            client.write({"method":"tools/call", "id":12, "params":{"name":"chat_receive",
                                                                    "arguments":{"working_dir":str(path)}}})
            query = json.loads(client.p.stdout.readline())
            self.assertEqual(query["method"],"roots/list")
            client.write({"id":query["id"], "result":{"roots":[{"uri":(self.root/"AT_甲").as_uri()}]}})
            reply = json.loads(client.p.stdout.readline())
            self.assertEqual(bool(reply["result"].get("isError")),rejected)

    def test_mcp_schema_and_empty_roots(self):
        from io import BytesIO
        from at_chat_mcp import Server, TOOLS, validate
        for capabilities in (None, {"roots": None}):
            stream = BytesIO()
            server = Server(stream)
            server.frame({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2025-11-25", "capabilities": capabilities}})
            server.frame({"jsonrpc": "2.0", "method": "notifications/initialized"})
            server.frame({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "chat_receive", "arguments": {"working_dir": str(self.root / "AT_乙")}}})
            server.frame({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "missing"}})
            init, inbox, unknown = map(json.loads, stream.getvalue().splitlines())
            self.assertEqual(init["result"]["protocolVersion"], "2025-11-25")
            self.assertEqual(inbox["result"]["structuredContent"]["pending_total"], 0)
            self.assertIn("未知的通讯工具", unknown["error"]["message"])
        for name, fields in (("receive", {"limit": -5}), ("history", {"status": "closed"}),
                             ("groups", {"version": ""}), ("receive", {"include_recent_context": 11})):
            with self.assertRaises(ValueError):
                validate({"working_dir": str(self.root), **fields}, TOOLS["chat_" + name]["inputSchema"])
        client = Client(self, roots=True)
        for frame, rejected in (({"result": {"roots": []}}, False), ({"error": {"code": -32603}}, True)):
            client.write({"id": 14, "method": "tools/call", "params": {"name": "chat_receive",
                          "arguments": {"working_dir": str(self.root / "AT_甲")}}})
            query = json.loads(client.p.stdout.readline())
            client.write({"id": query["id"], **frame})
            self.assertEqual(bool(json.loads(client.p.stdout.readline())["result"].get("isError")), rejected)

    def test_crash_after_first_group_replace(self):
        first = self.settle("old")["sent"][0]["message_id"]
        request = {"role": "乙", "model": "gemini", "handle": [{"message_id": first, "resolution": "resolved", "note": "完成"}],
                   "send": [{**self.item, "group_id": "topic:two", "to": ["甲"], "idempotency_key": "next"}]}
        script = """import os, sys, json
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from chat_core import store
from chat_core.engine import run
original = store.write
def crash(path, content):
    original(path, content)
    if path.parent.name == 'groups':
        os._exit(47)
store.write = crash
run('settle', Path(sys.argv[2]), json.loads(sys.argv[3]))
"""
        p = subprocess.run([sys.executable, "-B", "-c", script, str(SCRIPTS), str(self.root), json.dumps(request)])
        self.assertEqual(p.returncode, 47)
        journal = self.root / ".at-state/chat-transaction.json"
        self.assertTrue(journal.is_file())
        self.assertEqual(run("receive", self.root, {"role": "甲"})["pending_total"], 1)
        self.assertEqual(run("receive", self.root, {"role": "乙"})["pending_total"], 0)
        self.assertTrue(journal.is_file())
        self.assertTrue(run("settle", self.root, request)["sent"][0]["duplicate"])
        self.assertFalse(journal.exists())
        group = self.root / "public/at-chat/groups/topic__two.json"
        group.write_bytes(b"{")
        self.assertTrue(run("summary", self.root, {})["warnings"])
        with self.assertRaises(ValueError):
            run("settle", self.root, request)
        self.assertEqual(group.read_bytes(), b"{")
        meta = self.root / "public/at-chat/meta.json"
        obj = json.loads(meta.read_bytes())
        obj["project_id"] = "other"
        meta.write_text(json.dumps(obj))
        with self.assertRaisesRegex(ValueError, "项目标识"):
            run("summary", self.root, {})
