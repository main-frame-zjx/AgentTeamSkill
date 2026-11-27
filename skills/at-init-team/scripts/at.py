"""Agent Team command line. Each invocation accepts a UTF-8 JSON object."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import records
import guidance
import knowledge
import library
import portable
import releases
import reports
import tasks
import team
import versions
from core import STAGES, Problem, dump, inside, lock, project, project_root, read_json, require


COMMANDS = {
    "help": guidance.inspect_project, "update-member": team.update_member,
    "init": team.init, "project": lambda root, req: project(root), "add-member": team.add_member,
    "add-tasks": tasks.add_tasks, "list": tasks.list_tasks, "show": tasks.show_task,
    "sync": team.sync, "deliver": team.deliver,
    "meeting-context": records.context, "meeting": records.meeting,
    "set-iteration": versions.set_iteration,
}

RELEASE_COMMANDS = ("release", "release-check", "authorize-publisher")

def run(command, start, request):
    require(isinstance(request, dict), "输入必须为 JSON 对象")
    if command == "help":
        return guidance.inspect_project(start, request)
    if command == "init":
        return team.init(start.resolve(), request)
    root = project_root(start, exact=command in ("meeting-context", "meeting"))
    data = project(root)
    if command == "project":
        return data
    state = inside(root, ".at-state")
    probe = command in ("work-context", "memory-read", "memory-history", "library-read", "library-index") or (
        command == "library-lint" and not request.get("rebuild_moc"))
    if probe and not (state / "agent-team.lock").exists():
        # Newly initialized projects have no lock file until their first writer.
        return knowledge.command(root, data, command, request, start)
    state.mkdir(exist_ok=True)
    if command == "verify-bin":
        # Testing an interactive GUI may take minutes; only its final proof is written atomically.
        return portable.verify(root, request, versions.publisher(root, request, start))
    with lock(state / "agent-team.lock"):
        data = project(root)
        if command in knowledge.COMMANDS:
            return knowledge.command(root, data, command, request, start)
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
            result = releases.release(root, request, actor)
            if result.get("entry") and result["kind"] != "dev":
                knowledge.seal(root, data, result)
            return result
        if command == "meeting-context":
            result = records.context(root, request)
            result["pending_memory"] = knowledge.sync_roles(root, data, data["members"])
            return result
        if command in ("move", "amend", "note"):
            result = tasks.change(root, request, command)
            if command in ("move", "amend"):
                from chat_api import notification, snapshot
                current = notification(snapshot(root, tasks.parse(Path(result["path"]))))
                result["notification"] = current if current and current["event_key"] == request["key"] else None
        elif command in ("sync", "deliver"):
            result = COMMANDS[command](root, request, start)
        else:
            result = COMMANDS[command](root, request)
        if command == "add-member":
            try:
                library.rebuild(project(root))
            except knowledge.MAINTENANCE_ERRORS as exc:
                return {**result, "pending_navigation": {"retry": "library-lint", "rebuild_moc": True, "error": str(exc)}}
        if command in ("set-iteration", "meeting", "add-tasks", "move", "amend", "note", "sync", "deliver"):
            data = project(root)
            if command == "add-tasks":
                names = {item["role"] for item in result}
            elif command in ("meeting", "set-iteration"):
                names = {r["name"] for r in data["members"]}
            else:
                target_role = request.get("role") or versions.context_role(root, data, start)
                names = {target_role} if target_role else set()
            pending = knowledge.sync_roles(root, data, [r for r in data["members"] if names.intersection((r["name"], r["dir"]))])
            if pending and isinstance(result, list):
                for item in result:
                    item["pending_memory"] = [p for p in pending if p["role"] == item["role"]]
            elif pending:
                result["pending_memory"] = pending
            if command == "move" and request.get("to") == STAGES[3]:
                result["candidate_review"] = {"role": request["role"], "task_id": result["id"]}
        return result


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=sorted([*COMMANDS, *RELEASE_COMMANDS, *knowledge.COMMANDS,
                        "publish", "report-dir", "verify-bin", "move", "note", "amend"]))
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
