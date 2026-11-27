"""Read-only role communications viewer, served exclusively on the loopback interface."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from pathlib import Path, PureWindowsPath
import subprocess
import sys
import threading
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills/at-receive-message/scripts"))
from chat_core.engine import overview
from chat_core.store import directory, opened
from chat_core.tasks_bridge import snapshots
from core import dump, inside, project, read_json, require, write

LIMIT = 256 * 1024
TEXT = set(".md .py .ts .js .mjs .vue .json .yaml .yml .txt .css .html .cs .cpp .h .ps1 .sh .toml .ini".split())
ASSETS = {"/" + n: HERE / n for n in ("index.html", "style.css", "app.js", "local.js", "ui.js")}
ASSETS["/tools/windows/icons/agentteam-chat.ico"] = HERE.parent / "tools/windows/icons/agentteam-chat.ico"
MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".ico": "image/x-icon"}
ASSETS["/"] = HERE / "index.html"
ASSETS["/dev-visual/vendor/markdown-it.min.js"] = HERE.parent / "dev-visual/vendor/markdown-it.min.js"


def snapshot(root, *, detail=True, group_id=None):
    data = project(root)
    tasks, warnings, _ = snapshots(root, data)
    info = {"name": data["name"], "id": data["id"], "current_version": data["current_version"],
            "root": str(root), "roles": [r["name"] for r in data["members"]] + ["用户"],
            "has_chat": True, "chat_dir": directory(root, data).relative_to(root).as_posix()}
    with opened(root, data) as store:
        info["has_chat"] = store.initialized
        store.warnings.extend(warnings)
        view = overview(store, data, tasks)
        for group in view["groups"]:
            g = store.groups[group["group_id"]]
            task = tasks.get(g["task_id"])
            if group_id == g["group_id"]:
                return {**group, "messages": g["messages"], "task": task}
            if detail:
                group.update(messages=g["messages"], task=task)
            else:
                group["detail_tag"] = hashlib.sha256(dump([g, task]).encode()).hexdigest()
        require(group_id is None, store.errors.get(group_id, "群组不存在"))
        stats = {k: view[k] for k in ("groups_total", "pending_total", "by_role")}
        stats["messages_total"] = sum(g["message_count"] for g in view["groups"])
        stats["models_seen"] = sorted({m["sender_model"] for g in store.groups.values() for m in g["messages"]})
        return {**view, "project": info, "stats": stats}


def preview(root, raw, lines=None):
    require(not PureWindowsPath(raw).anchor and ":" not in raw and "\\" not in raw and
            not any(p in ("", ".", "..") or p.casefold() == ".git" for p in raw.split("/")), "非法文件路径")
    path = inside(root, raw).resolve()
    require(path.suffix.lower() in TEXT and ".git" not in [s.casefold() for s in path.parts], "仅支持项目内文本")
    with path.open("rb") as f:
        content = f.read(LIMIT + 1)
    import codecs
    truncated = len(content) > LIMIT
    value = codecs.getincrementaldecoder("utf-8-sig")().decode(content[:LIMIT], final=not truncated)
    require("\0" not in value, "仅支持 UTF-8 文本")
    highlight = None
    if lines:
        require(re.fullmatch(r"[1-9]\d*(?:-[1-9]\d*)?", lines), "行号无效")
        ends = lines.split("-")
        highlight = [int(ends[0]), int(ends[-1])]
        require(highlight[0] <= highlight[1], "行号范围无效")
    return {"path": raw, "content": value, "truncated": truncated, "highlight": highlight,
            "total_lines": None if truncated else len(value.splitlines())}


def pick_folder():
    # Tk owns the main thread of a short-lived process. The server can keep serving other tabs.
    result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(HERE / "picker.py")],
                            capture_output=True, encoding="utf-8",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    require(result.returncode == 0, "无法打开项目选择器，请检查本机桌面环境")
    return result.stdout.strip()


def project_key(root):
    return hashlib.sha256(os.path.normcase(str(root)).encode()).hexdigest()[:24]


class Registry:
    def __init__(self, initial=None):
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local/share")
        self.board = local / "AgentTeamBoard/projects.json"
        self.config = local / "AgentTeamChat/projects.json"
        self.initial = initial
        self.guard = threading.RLock()
        self.selected = None
        self.picking = threading.Lock()

    def state(self):
        with self.guard:
            own = read_json(self.config) if self.config.exists() else {}
            board = read_json(self.board) if self.board.exists() else {}
            paths = ([self.initial] if self.initial else []) + own.get("paths", [])
            paths.extend(row["root"] for row in sorted(board.get("projects", []), key=lambda row: row["id"] != board.get("active")))
            rows, unavailable = {}, {}
            hidden = set(own.get("hidden", []))
            for candidate in paths:
                root = Path(candidate).resolve()
                key = project_key(root)
                if key in rows or key in unavailable or key in hidden:
                    continue
                try:
                    data = project(root)
                    rows[key] = {"id": key, "name": data["name"], "root": str(root)}
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    unavailable[key] = {"id": key, "name": root.name, "root": str(root), "error": str(exc)}
            active = self.selected or (None if self.initial else own.get("active"))
            return {"projects": list(rows.values()), "active": active if active in rows else next(iter(rows), None),
                    "unavailable": list(unavailable.values()),
                    "warnings": [r["root"] + ": " + r["error"] for r in unavailable.values()]}

    def select(self, key=None, folder=None):
        with self.guard:
            own = read_json(self.config) if self.config.exists() else {"paths": []}
            if folder:
                root = Path(folder).resolve()
                project(root)
                if str(root) not in own["paths"]:
                    own["paths"].append(str(root))
                key = project_key(root)
                own["hidden"] = [k for k in own.get("hidden", []) if k != key]
            else:
                self.root(key)
            self.selected = own["active"] = key
            write(self.config, dump(own))
            return self.state()

    def remove(self, key):
        with self.guard:
            listing = self.state()
            require(any(r["id"] == key for r in listing["projects"] + listing["unavailable"]), "未登记项目")
            own = read_json(self.config) if self.config.exists() else {}
            own["paths"] = [p for p in own.get("paths", []) if project_key(Path(p).resolve()) != key]
            own["hidden"] = sorted(set(own.get("hidden", [])) | {key})
            if own.get("active") == key or self.selected == key:
                self.selected = own["active"] = None
            write(self.config, dump(own))
            return self.state()

    def root(self, key):
        row = next((r for r in self.state()["projects"] if r["id"] == key), None)
        require(row, "未登记项目")
        return Path(row["root"])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, content=b"", mime="application/json; charset=utf-8", etag=None):
        self.send_response(status)
        for name, value in {"Content-Type": mime, "Content-Length": str(len(content)), "Cache-Control": "no-store",
                            "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"}.items():
            self.send_header(name, value)
        if etag:
            self.send_header("ETag", etag)
        self.end_headers()
        if content:
            self.wfile.write(content)

    def dispatch(self, method):
        host = f"127.0.0.1:{self.server.server_port}"
        origin = self.headers.get("Origin")
        if (self.headers.get("Host") != host or (origin is not None and origin != "http://" + host)
                or (method == "POST" and (origin is None or self.headers.get("X-Chat-Request") != "1"))):
            return self.reply(403)
        url = urlsplit(self.path)
        path = unquote(url.path)
        parts = path.strip("/").split("/")
        registry = self.server.registry
        try:
            if method == "GET" and path in ASSETS:
                asset = ASSETS[path]
                return self.reply(200, asset.read_bytes(), MIME[asset.suffix])
            if method == "GET" and path == "/api/health":
                result = {"app": "agent-team-chat", "version": 1, "pid": os.getpid()}
            elif method == "GET" and path == "/api/projects":
                result = registry.state()
            elif method == "POST" and path == "/api/projects/pick":
                if not registry.picking.acquire(blocking=False):
                    return self.reply(409, json.dumps({"error": "已有项目选择窗口"}).encode())
                try:
                    folder = pick_folder()
                    result = registry.select(folder=folder) if folder else {**registry.state(), "cancelled": True}
                finally:
                    registry.picking.release()
            elif method == "POST" and len(parts) == 4 and parts[:2] == ["api", "projects"] and parts[3] == "remove":
                result = registry.remove(parts[2])
            elif len(parts) >= 4 and parts[:2] == ["api", "projects"]:
                root = registry.root(parts[2])
                route = parts[3:]
                if method == "POST" and route == ["select"]:
                    result = registry.select(parts[2])
                elif method == "GET" and route == ["file"]:
                    query = parse_qs(url.query)
                    result = preview(root, query["path"][0], query.get("lines", [None])[0])
                elif method == "GET" and route in (["overview"], ["snapshot"]):
                    result = snapshot(root, detail=route == ["snapshot"])
                elif method == "GET" and len(route) == 2 and route[0] == "groups":
                    result = snapshot(root, detail=False, group_id=route[1])
                else:
                    return self.reply(404)
            else:
                return self.reply(404)
            body = json.dumps(result, ensure_ascii=False).encode()
            tag = '"' + hashlib.sha256(body).hexdigest() + '"'
            if method == "GET" and tag == self.headers.get("If-None-Match"):
                return self.reply(304, etag=tag)
            self.reply(200, body, etag=tag)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            self.reply(400, json.dumps({"error": str(exc)}, ensure_ascii=False).encode())

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=47362)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--strict-port", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        if args.strict_port:
            raise
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.registry = Registry(args.project)
    url = f"http://127.0.0.1:{server.server_port}/"
    if sys.stdout:
        print(url, flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    with server:
        server.serve_forever()


if __name__ == "__main__":
    main()
