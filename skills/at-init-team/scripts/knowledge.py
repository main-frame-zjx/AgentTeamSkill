"""CLI integration of role memory, project milestones and personal learning notes."""

import json
import subprocess

from pathlib import Path

import library
import memory
from core import (STAGES, digest, dump, field, git, git_result, inside, member, read_json, require,
                  require_repo_root, role_dir, segment, write)
from learning import KINDS, candidates, line
from tasks import DISPLAY_NAME, effective, role_tasks
from versions import context_role, formal_versions, history, version


COMMANDS = ("work-context", "memory-read", "memory-sync", "memory-patch", "memory-history",
            "library-index", "library-read", "library-upsert", "library-lint")
MAINTENANCE_ERRORS = (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError)


def sync_roles(root, data, roles):
    repairs = []
    for role in roles:
        try:
            memory.update(root, data, role)
        except MAINTENANCE_ERRORS as exc:
            repairs.append({"role": role["name"], "retry": "memory-sync", "error": str(exc)})
    return repairs


def upsert(root, data, role, request, tasks, queue):
    cid = request.get("resolve_candidate_id")
    trigger = request.get("trigger", "review")
    require(trigger in ("review", "milestone", "explicit"), "未知入库时机")
    if cid is not None:
        require(isinstance(cid, str) and cid in queue, "未知候选 ID")
    kind, title = field(request, "kind"), segment(line(request, "title"))
    require(kind in KINDS, "未知笔记类型")
    name = f"{KINDS[kind]}/{title}.md"
    path = library.note_path(library.folder(data, role), name)
    signature = digest(json.dumps(request, sort_keys=True, ensure_ascii=False).encode())
    note_key = digest((role["dir"] + "/" + name).casefold().encode())
    pending = inside(root, ".at-state", "learning-writes", note_key + ".json")
    job = read_json(pending) if pending.exists() else None
    resuming = job is not None and job["signature"] == signature
    notes, issues = library.scan(data, data["members"])
    duplicates = [n for n in notes if n["role"] != role["name"] and n["title"].casefold() == title.casefold()]
    if resuming and path.is_file() and path.read_bytes() == job["content"].encode():
        content = job["content"]
    else:
        if job and not resuming:
            current_hash = digest(path.read_bytes()) if path.is_file() else None
            require("expected_sha256" in request and request["expected_sha256"] == current_hash and
                    cid == job["request"].get("resolve_candidate_id"),
                    f"此笔记有未完成写入，请按 {pending} 中的 request 重试或重读合并同一候选")
        content, archived = library.prepare(root, data, role, request, tasks, notes)
        if resuming:
            # Dependencies have just been rechecked. Keep the original iteration in the frozen text.
            content = job["content"]
        if trigger == "review":
            require(archived, "验收入库应引用已归档的需求")
            if cid and queue[cid]["source"].startswith("task:"):
                require(queue[cid]["source"][5:] in archived, "候选所属需求尚未验收或未被引用")
    if cid and queue[cid]["status"] in ("published", "merged"):
        require(queue[cid]["path"] == name, "此候选已指向另一篇笔记")
    changed = library.check_write(path, request, content)
    if not resuming:
        for other in KINDS.values():
            if other != KINDS[kind]:
                require(not library.note_path(library.folder(data, role), f"{other}/{title}.md").exists(),
                        f"个人库在 {other} 中已有同名笔记，请阅读原文后更新")
        write(pending, dump({"signature": signature, "request": request, "content": content}))
    if changed:
        write(path, content)
    sha = digest(content.encode())
    result = {"path": name, "sha256": sha, "completed": ["note"], "pending": []}
    if duplicates:
        result["duplicate_title_warnings"] = [{"role": n["role"], "path": n["path"]} for n in duplicates]
    if issues:
        result["library_issues"] = issues
    try:
        result["navigation"] = library.rebuild(data)
        result["completed"].append("navigation")
    except MAINTENANCE_ERRORS as exc:
        result["pending"].append({"retry": "library-lint", "rebuild_moc": True, "error": str(exc)})
    try:
        outcome = None
        if cid and queue[cid]["status"] not in ("published", "merged"):
            status = "merged" if request.get("expected_sha256") else "published"
            outcome = {"id": cid, "status": status, "path": name, "reason": "已核实并写入个人库"}
        memory.update(root, data, role, outcome=outcome)
        result["completed"].append("memory")
        pending.unlink()
    except MAINTENANCE_ERRORS as exc:
        result["pending"].append({"retry": "library-upsert", "use_original_input": True, "error": str(exc)})
    return result


def memory_view(root, data, role, *, view=None, if_none_match=None):
    if if_none_match is not None:
        require(isinstance(if_none_match, str) and if_none_match.strip(), "if_none_match 应为非空哈希")
    result = memory.read(root, data, role)
    state = memory.current(root, role)[0]
    if (if_none_match is not None and if_none_match == result["sha256"]
            and "manual_diff" not in result and "recovery" not in result
            and digest(result["content"].encode()) == state["rendered_sha256"]):
        return {"role": result["role"], "sha256": result["sha256"], "bytes": result["bytes"], "unchanged": True,
                "candidates_total": result["candidates_total"], "stale_hints": result["stale_hints"],
                "quota": result["quota"], "library_issues": result["library_issues"]}
    if view == "handoff":
        for key in ("focus", "decisions", "risks", "candidates"):
            result.pop(key)
    return result


def work_context(root, data, request, start):
    current = context_role(root, data, start)
    identity = request.get("role", current)
    require(identity, "在项目根目录开工请指定 role")
    role = member(data, identity)
    require(not current or role["name"] == current,
            f"当前处于 {current} 目录，不能代办 {role['name']} 的工作，请切换到项目根或目标角色目录")
    base = role_dir(root, role)
    agent_path = inside(base, "Agent.md")
    require(agent_path.is_file() and agent_path.resolve() == agent_path, f"找不到角色档案 {agent_path}")
    agent_raw = agent_path.read_bytes()
    agent_sha = digest(agent_raw)
    known_agent = request.get("agent_sha256")
    if known_agent is not None:
        require(isinstance(known_agent, str) and known_agent.strip(), "agent_sha256 应为非空哈希")
    agent = {"path": str(agent_path), "sha256": agent_sha}
    if known_agent == agent_sha:
        agent["unchanged"] = True
    else:
        agent["content"] = agent_raw.decode("utf-8-sig")
    mem = memory_view(root, data, role, view="handoff", if_none_match=request.get("memory_sha256"))
    skills_dir = inside(base, ".agent")
    personal_skills = sorted(p.relative_to(base).as_posix() for p in skills_dir.rglob("*")
                             if p.is_file() and p.name != ".gitkeep") if skills_dir.is_dir() else []
    wanted = {STAGES[0], STAGES[1]}
    active_tasks = []
    for task in sorted(role_tasks(root, role, repair=False).values(), key=lambda t: t.path.name):
        if STAGES[task.stage] in wanted:
            spec = effective(task.spec, task.events)
            match = DISPLAY_NAME.fullmatch(task.path.name)
            code = "".join(match.groups()[:2]) if match else ""
            active_tasks.append({"id": task.spec["id"], "code": code, "title": task.spec["title"],
                                 "stage": STAGES[task.stage], "path": str(task.path),
                                 "reviewer": spec["reviewer"], "version": spec["version"]})
    tree = inside(base, "repository", Path(data["team_repo"]).name)
    worktree = {"path": str(tree), "expected_branch": role["branch"], "exists": tree.is_dir()}
    if tree.is_dir() and (tree / ".git").exists():
        branch = git(tree, "branch", "--show-current")
        status = [row for row in git(tree, "status", "--porcelain").splitlines() if row]
        behind = git_result(tree, "rev-list", "--count", "HEAD..refs/remotes/origin/main")
        worktree.update({"branch": branch, "branch_matches": branch == role["branch"],
                         "head": git(tree, "rev-parse", "--short", "HEAD"),
                         "clean": not status, "dirty_count": len(status), "dirty_files": status[:20],
                         "behind_origin_main": int(behind.stdout.strip()) if behind.returncode == 0 else None})
    from chat_api import chat_run
    communications = chat_run("workflow", start, {"role": role["name"]})
    return {**communications, "role": role["name"], "version": data["current_version"], "agent": agent, "memory": mem,
            "personal_skills": personal_skills, "tasks": active_tasks, "worktree": worktree}


def command(root, data, name, request, start):
    if name == "library-lint":
        return library.lint(root, data, request)
    if name == "work-context":
        return work_context(root, data, request, start)
    if name == "memory-sync" and request.get("all") is True:
        return {"pending": sync_roles(root, data, data["members"])}
    inferred = next((r["name"] for r in data["members"] if start.resolve().is_relative_to(role_dir(root, r))), None)
    identity = request.get("role", inferred)
    if name == "library-index":
        scope = request.get("scope", "role")
        require(scope in ("role", "project"), "scope 须为 role 或 project")
        if scope == "project" and identity is None:
            return index(data, data["members"], request, {}, {})
    role = member(data, identity)
    if name == "memory-read":
        return memory_view(root, data, role, view=request.get("view"), if_none_match=request.get("if_none_match"))
    if name == "memory-sync":
        return memory.update(root, data, role)
    if name == "memory-patch":
        return memory.update(root, data, role, request)
    if name == "memory-history":
        return memory.history(root, role, request)
    if name == "library-read":
        return library.read(data, role, request)
    tasks = role_tasks(root, role, repair=False)
    queue = candidates(tasks, memory.current(root, role)[0])
    if name == "library-upsert":
        return upsert(root, data, role, request, tasks, queue)
    return index(data, data["members"] if scope == "project" else [role], request, tasks, queue)


def index(data, roles, request, tasks, queue):
    query = request.get("query", "")
    require(isinstance(query, str), "query 应为文本")
    notes, issues = library.scan(data, roles)
    matches = [n for n in notes if query.casefold() in " ".join([n["title"], n["summary"], *n["tags"]]).casefold()]
    rows = list(queue.values())
    if "task_id" in request:
        rows = [r for r in rows if r["source"] == "task:" + field(request, "task_id")]
    if query:
        rows = [r for r in rows if query.casefold() in r["topic"].casefold()]
    if "version" in request:
        target = version(request["version"])
        rows = [r for r in rows if r["source"] == "version:" + target or r.get("version") == target or
                (r["source"].startswith("task:") and
                 tasks[r["source"][5:]].spec["version"] == target)]
    if not request.get("include_resolved"):
        rows = [r for r in rows if r["status"] in memory.OPEN]
    return {"notes": matches, "candidates": rows, "issues": issues}


def capture_heads(root, data):
    warnings = sync_roles(root, data, data["members"])
    heads = {}
    for role in data["members"]:
        try:
            repo = role_dir(root, role)
            require_repo_root(repo)
            heads[role["name"]] = git(repo, "rev-parse", "--verify", "HEAD^{commit}")
        except MAINTENANCE_ERRORS as exc:
            warnings.append({"role": role["name"], "snapshot_unavailable": True, "error": str(exc)})
    return {"memory_heads": heads, "memory_warnings": warnings}


def seal(root, data, result):
    """Always use the role commits captured in the original formal release receipt."""
    sealed = formal_versions(history(root))[result["version"]]
    tag = "memory/" + result["version"]
    result["first_formal_revision"] = (sealed["kind"] == result["kind"] and
                                       sealed["revision"] == result["revision"])
    if result["first_formal_revision"]:
        result["candidate_review"] = [{"role": name, "version": result["version"]} for name in sealed["memory_heads"]]
    pending = []
    for name, head in sealed["memory_heads"].items():
        try:
            repo = role_dir(root, member(data, name))
            require_repo_root(repo)
            previous = git_result(repo, "rev-parse", "--verify", "refs/tags/" + tag)
            if previous.returncode:
                git(repo, "tag", tag, head)
            else:
                require(previous.stdout.strip() == head, f"已有标签 {tag} 指向不同提交")
        except MAINTENANCE_ERRORS as exc:
            pending.append({"role": name, "retry": "release", "error": str(exc)})
    result["memory_tag"] = tag
    if sealed.get("memory_warnings"):
        result["memory_warnings"] = sealed["memory_warnings"]
    if result["first_formal_revision"]:
        pending.extend(sync_roles(root, data, data["members"]))
    if pending:
        result["pending_memory"] = pending
    try:
        result["library_health"] = library.lint(root, data, {})
    except MAINTENANCE_ERRORS as exc:
        result["library_health"] = {"retry": "library-lint", "error": str(exc)}
