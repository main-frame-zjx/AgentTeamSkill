"""Read-only, loopback-only server for the AgentTeam developer handbook."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit
import webbrowser


HERE = Path(__file__).resolve().parent
SKILLS = HERE.parent / "skills"
ASSETS = {
    "/": ("index.html", "text/html"),
    "/style.css": ("style.css", "text/css"),
    "/reader.js": ("reader.js", "text/javascript"),
    "/catalog.mjs": ("catalog.mjs", "text/javascript"),
    "/vendor/js-yaml.mjs": ("vendor/js-yaml.mjs", "text/javascript"),
    "/vendor/markdown-it.min.js": ("vendor/markdown-it.min.js", "text/javascript"),
    "/skill-relation.json": ("skill-relation.json", "application/json"),
    "/mark.svg": ("mark.svg", "image/svg+xml"),
}


def skill_documents(root):
    """Read the current entry documents for navigation and full-text search."""
    documents = []
    for path in sorted(root.glob("*/SKILL.md")):
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            continue
        try:
            markdown = resolved.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            continue  # A skill may have been moved since the directory scan.
        documents.append({"document": path.relative_to(root).as_posix(), "markdown": markdown})
    return documents


class Handbook(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        if sys.stderr is not None:  # pythonw has no console streams.
            super().log_message(format, *args)

    def do_GET(self):
        route = unquote(urlsplit(self.path).path)
        try:
            if route == "/api/health":
                data = json.dumps({"app": "agent-team-handbook", "version": 1, "pid": os.getpid()}).encode()
                mime = "application/json"
            elif route == "/api/skill-documents":
                data = json.dumps(skill_documents(SKILLS), ensure_ascii=False).encode("utf-8")
                mime = "application/json"
            elif route in ASSETS:
                name, mime = ASSETS[route]
                data = (HERE / name).read_bytes()
            elif route.startswith("/docs/"):
                relative = Path(route.removeprefix("/docs/"))
                path = (SKILLS / relative).resolve()
                if not path.is_relative_to(SKILLS) or path.suffix.lower() != ".md":
                    self.send_error(404)
                    return
                mime = "text/plain"
                data = path.read_bytes()
            else:
                self.send_error(404)
                return
        except (OSError, ValueError, RuntimeError):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; "
                         "base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8764, help="TCP port (0 selects a free port)")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--strict-port", action="store_true", help="Fail if the requested port is occupied")
    args = parser.parse_args()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handbook)
    except OSError:
        # A second checkout or another developer tool may be using the default.
        if args.strict_port or args.port != 8764:
            raise
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handbook)
    with server:
        address = f"http://127.0.0.1:{server.server_port}/"
        print(f"AgentTeam 技能手册  {address}\n按 Ctrl+C 或关闭窗口可停止服务。", flush=True)
        if not args.no_browser:
            webbrowser.open(address)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
