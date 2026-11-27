"""Local JSON CLI for the same use cases as the stdio MCP server."""
import argparse
import json
from pathlib import Path
import sys

from chat_core.engine import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices="receive send handle settle groups history summary create-group reopen workflow".split())
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--input", help="UTF-8 JSON 文件，或 - 表示标准输入")
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read() if args.input == "-" else Path(args.input).read_bytes() if args.input else b"{}"
        result = {"ok": True, "result": run(args.command, args.root, json.loads(raw.decode("utf-8-sig")))}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result = {"ok": False, "error": str(exc)}
    sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False) + "\n").encode())
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
