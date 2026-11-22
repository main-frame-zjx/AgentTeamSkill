"""Agent Team command line. Each invocation accepts a UTF-8 JSON object."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import records
import guidance
import portable
import releases
import reports
import tasks
import team
import versions
from core import Problem, dump, inside, lock, project, project_root, read_json, require


COMMANDS = {
    "help": guidance.inspect_project, "update-member": team.update_member,
    "init": team.init, "project": lambda root, req: project(root), "add-member": team.add_member,
    "add-tasks": tasks.add_tasks, "list": tasks.list_tasks, "show": tasks.show_task,
    "sync": team.sync, "deliver": team.deliver,
    "meeting-context": records.context, "meeting": records.meeting,
    "set-iteration": versions.set_iteration,
}

RELEASE_COMMANDS = ("release", "release-check", "authorize-publisher", "import-release", "bind-version")

def run(command, start, request):
    require(isinstance(request, dict), "输入必须为 JSON 对象")
    if command == "help":
        return guidance.inspect_project(start, request)
    if command == "init":
        return team.init(start.resolve(), request)
    root = project_root(start, exact=command in ("meeting-context", "meeting"))
    project(root)  # Validate the format before creating any project state.
    state = inside(root, ".at-state")
    state.mkdir(exist_ok=True)
    if command == "verify-bin":
        # Testing an interactive GUI may take minutes; only its final proof is written atomically.
        return portable.verify(root, request, versions.publisher(root, request, start))
    with lock(state / "agent-team.lock"):
        if command == "report-dir":
            return {"path": str(reports.report_directory(root, request, start))}
        if command == "publish":
            return reports.publish(root, request, start)
        if command == "authorize-publisher":
            return versions.authorize(root, request, start)
        if command in RELEASE_COMMANDS:
            actor = versions.publisher(root, request, start)
            if command == "release-check":
                return releases.check(root, request)
            if command == "bind-version":
                return tasks.bind_version(root, request, actor)
            if command == "import-release":
                return releases.import_baseline(root, request, actor)
            return releases.release(root, request, actor)
        if command in ("memory", "library"):
            return records.knowledge(root, request, command)
        if command in ("move", "amend", "note"):
            return tasks.change(root, request, command)
        return COMMANDS[command](root, request)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=sorted([*COMMANDS, *RELEASE_COMMANDS, "publish", "report-dir", "verify-bin", "move", "note", "amend", "memory", "library"]))
    parser.add_argument("--root", default=".", type=Path, help="项目目录（默认当前目录）")
    parser.add_argument("--input", metavar="FILE", help="UTF-8 JSON 文件；使用 - 从标准输入读取")
    args = parser.parse_args()
    try:
        if args.input == "-":
            data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
        else:
            data = read_json(Path(args.input)) if args.input else {}
        print(dump({"ok": True, "result": run(args.command, args.root, data)}), end="")
    except (Problem, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print(dump({"ok": False, "error": str(exc)}), end="")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
