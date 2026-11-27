"""Line-delimited UTF-8 stdio MCP. Only RPC frames are written to stdout."""
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
from urllib.request import url2pathname

from chat_core.engine import run
from chat_core.store import PRIORITY

VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
TEXT = {"type": "string", "minLength": 1}
INT = {"type": "integer", "minimum": 0}
LIMIT = {"type": "integer", "minimum": 1, "maximum": 200}
FLAG = {"type": "boolean"}


def obj(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def array(item):
    return {"type": "array", "items": item}


def enum(values):
    return {"type": "string", "enum": list(values)}


REF = obj({"path": TEXT, "lines": TEXT, "note": TEXT}, ["path"])
SEND = obj({"task_id": TEXT, "group_id": TEXT, "kind": enum(PRIORITY), "to": array(TEXT), "body": TEXT,
            "refs": array(REF), "reply_to": TEXT, "event_key": TEXT, "idempotency_key": TEXT},
           ["kind", "to", "body", "idempotency_key"])
HANDLE = obj({"message_id": TEXT, "resolution": enum(("replied", "resolved", "accepted", "noted", "deferred")), "note": TEXT},
             ["message_id", "resolution", "note"])


def tool(name, description, fields, required=(), write=False):
    return {"name": "chat_" + name, "description": description,
            "inputSchema": obj({"working_dir": TEXT, "role": TEXT, **fields}, ["working_dir", *required]),
            "annotations": {"readOnlyHint": not write, "idempotentHint": True, "openWorldHint": False}}


TOOLS = {t["name"]: t for t in (
    tool("receive", "按优先级读取角色待办；用 next_cursor 翻页。", {"limit": LIMIT, "cursor": TEXT, "include_recent_context": {**INT, "maximum": 10}}),
    tool("settle", "一次核销已完成的收件并发送定向消息。", {"model": TEXT, "handle": array(HANDLE), "send": array(SEND)}, ["model"], True),
    tool("groups", "浏览需求群、专题群与项目待办。", {"only_pending": FLAG, "include_archived": FLAG, "version": TEXT}),
    tool("history", "查看一群的消息和关联需求。", {"task_id": TEXT, "group_id": TEXT, "status": enum(("pending", "handled", "partial")), "limit": LIMIT, "offset": INT}),
    tool("create_group", "创建具名专题群。", {"slug": TEXT, "title": TEXT}, ["slug", "title"], True))}


def validate(value, schema):
    kind = schema["type"]
    expected = {"string": str, "integer": int, "object": dict, "array": list, "boolean": bool}[kind]
    if type(value) != expected or ("enum" in schema and value not in schema["enum"]):
        raise ValueError(f"无效参数，期望 {kind}")
    if kind == "string" and len(value.strip()) < schema.get("minLength", 0):
        raise ValueError("文本参数不能为空")
    if kind == "integer" and not schema.get("minimum", value) <= value <= schema.get("maximum", value):
        raise ValueError("整数参数超出允许范围")
    if kind == "object":
        if not set(schema["required"]) <= value.keys() or value.keys() - schema["properties"].keys():
            raise ValueError("工具参数缺失或含未知字段")
        for key, item in value.items():
            validate(item, schema["properties"][key])
    if kind == "array":
        for item in value:
            validate(item, schema["items"])


class Server:
    def __init__(self, output):
        self.output = output
        self.version = None
        self.ready = False
        self.check_roots = False
        self.waiting = {}
        self.serial = 0

    def emit(self, **frame):
        self.output.write((json.dumps({"jsonrpc": "2.0", **frame}, ensure_ascii=False) + "\n").encode())
        self.output.flush()

    def error(self, rid, code, message):
        self.emit(id=rid, error={"code": code, "message": message})

    def call(self, rid, name, args, roots=None):
        try:
            path = Path(args["working_dir"])
            if not path.is_absolute():
                raise ValueError("working_dir 必须是会话的绝对目录")
            if self.check_roots and not isinstance(roots, list):
                raise ValueError("宿主工作区查询失败，请重试")
            if roots:
                allowed = []
                for r in roots or []:
                    if not isinstance(r, dict) or not isinstance(r.get("uri"), str):
                        raise ValueError("宿主工作区信息无效，请重试")
                    uri = urlsplit(r["uri"])
                    if uri.scheme == "file" and uri.netloc in ("", "localhost"):
                        boundary = Path(url2pathname(uri.path))
                        if boundary.is_absolute():
                            allowed.append(boundary.resolve())
                if not allowed:
                    raise ValueError("宿主未提供有效的本机工作区，请核对后重试")
                if not any(path.resolve().is_relative_to(r) for r in allowed):
                    raise ValueError("working_dir 不在宿主工作区内")
            result = run(name.removeprefix("chat_").replace("_", "-"), path, args)
            reply = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
            if self.version in VERSIONS[:2]:
                reply["structuredContent"] = result
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            reply = {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
        self.emit(id=rid, result=reply)

    def frame(self, msg):
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return self.error(None, -32600, "Invalid Request")
        rid, method = msg.get("id"), msg.get("method")
        if method is None and isinstance(rid, str) and rid in self.waiting:
            call = self.waiting.pop(rid)
            result = msg.get("result")
            return self.call(*call, roots=result.get("roots") if isinstance(result, dict) and "error" not in msg else None)
        if not isinstance(method, str):
            return self.error(None, -32600, "Invalid Request")
        if "id" in msg and type(rid) not in (int, str):
            return self.error(None, -32600, "Invalid request ID")
        if "id" not in msg:
            if method == "notifications/initialized" and self.version:
                self.ready = True
            return
        params = msg.get("params", {})
        try:
            if method == "initialize":
                wanted = params["protocolVersion"]
                self.version = wanted if wanted in VERSIONS else VERSIONS[0]
                self.check_roots = isinstance((params.get("capabilities") or {}).get("roots"), dict)
                result = {"protocolVersion": self.version, "capabilities": {"tools": {}},
                          "serverInfo": {"name": "agent-team-chat", "version": "1.0.0"}}
            elif method == "ping":
                result = {}
            elif not self.ready:
                return self.error(rid, -32002, "Server not initialized")
            elif method == "tools/list":
                result = {"tools": list(TOOLS.values())}
            elif method == "tools/call":
                name, args = params["name"], params.get("arguments", {})
                if not isinstance(name, str) or name not in TOOLS:
                    raise ValueError(f"未知的通讯工具 {name}")
                validate(args, TOOLS[name]["inputSchema"])
                if self.check_roots:
                    self.serial += 1
                    token = f"roots-{self.serial}"
                    self.waiting[token] = (rid, name, args)
                    return self.emit(id=token, method="roots/list", params={})
                return self.call(rid, name, args)
            else:
                return self.error(rid, -32601, "Method not found")
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            return self.error(rid, -32602, str(exc))
        self.emit(id=rid, result=result)


if __name__ == "__main__":
    server = Server(sys.stdout.buffer)
    sys.stdout = sys.stderr
    for line in sys.stdin.buffer:
        try:
            frame = json.loads(line)
        except (ValueError, UnicodeError):
            server.error(None, -32700, "Parse error")
            continue
        server.frame(frame)
