"""Role knowledge and meeting records."""

from pathlib import Path

from core import (digest, dump, field, inside, member, project, read_json, require, role_dir,
                  save, segment, texts, write)
from tasks import plan_tasks, write_tasks


def knowledge(root, request, kind):
    data = project(root)
    role = member(data, field(request, "role"))
    if kind == "memory":
        path = inside(role_dir(root, role), "Memory.md")
    else:
        name = field(request, "path")
        parts = name.replace("\\", "/").split("/")
        require(all(segment(s) for s in parts) and name.lower().endswith(".md"), "笔记路径应是相对 .md 文件")
        path = inside(Path(data["vault"]), segment(data["name"]), segment(role["dir"]), *parts)
    prior = path.read_bytes() if path.exists() else None
    old_hash = digest(prior) if prior is not None else None
    if "content" in request:
        content = field(request, "content") + "\n"
        new = content.encode("utf-8")
        if prior != new:
            require("expected_sha256" in request and request["expected_sha256"] == old_hash,
                    "内容已变化或缺少 expected_sha256，请重新读取并合并")
            write(path, content)
        if kind == "memory":
            save(role_dir(root, role), [path], f"Update memory for {role['name']}")
        prior = new
    size = len(prior) if prior is not None else 0
    return {"path": str(path), "sha256": digest(prior) if prior is not None else None, "bytes": size,
            "over_memory_target": kind == "memory" and size > 10 * 1024,
            "content": prior.decode("utf-8-sig") if prior is not None and "content" not in request else None}


def context(root, request):
    data = project(root)
    require(len(data["members"]) >= 2, "会议需要主持人及至少一位其他角色")
    host = member(data, request.get("host", "项目负责人"))
    roles = [{"name": r["name"], "agent": str(role_dir(root, r) / "Agent.md"),
              "memory": str(role_dir(root, r) / "Memory.md")} for r in data["members"]]
    return {"host": host["name"], "roles": roles}


def meeting(root, request):
    ctx = context(root, request)
    data = project(root)
    meeting_id = segment(field(request, "key"))
    topic, opening = field(request, "topic"), field(request, "opening")
    rounds = request.get("rounds")
    require(isinstance(rounds, list) and len(rounds) >= 10, "至少需要 10 轮全员发言")
    names = [r["name"] for r in ctx["roles"]]
    lines = [f"# {topic}", f"主持人：{ctx['host']}", "## 主持人开场", opening]
    for i, statements in enumerate(rounds, 1):
        require(isinstance(statements, dict) and set(statements) == set(names), f"第 {i} 轮需要每个角色发言")
        lines.append(f"## 第 {i} 轮")
        lines.extend(f"### {n}\n\n{field(statements, n)}" for n in names)
    for key, title in [("decisions", "会议决议"), ("user_decisions", "用户裁决"), ("open_questions", "待决事项")]:
        entries = texts(request, key, allow_empty=True)
        lines.extend(["## " + title, "\n".join("- " + item for item in entries) or "无"])
    actions = request.get("items")
    require(isinstance(actions, list), "items 必须是数组")
    folder = "meeting-notes" if Path(data["team_repo"]).name.casefold() == "meetings" else "meetings"
    path = inside(root, "public", folder, meeting_id + ".md")
    actions = [{**item, "key": f"meeting/{meeting_id}/{field(item, 'key')}",
                "source": path.relative_to(root).as_posix()} for item in actions]
    pending = inside(root, ".at-state", "meeting-" + meeting_id + ".json")
    default = data.get("current_version")
    if pending.exists():
        snapshot = read_json(pending)
        require(snapshot.get("request", snapshot) == request, "请使用原会议输入重试")
        default = snapshot.get("current_version", default)
    jobs, configured = plan_tasks(root, {**data, "current_version": default}, actions,
                                  request.get("version")) if actions else ([], False)
    lines.extend(["## 分派需求", "\n".join(f"- {j.spec['id']} · {j.owner['name']} · {j.spec['title']}"
                                      for j in jobs) or "无"])
    content = "\n\n".join(lines) + "\n"
    # Bind the entire batch before its first write so a changed retry cannot silently drop an item.
    if path.exists():
        require(path.read_text(encoding="utf-8") == content, "会议编号已用于不同内容")
    if not path.exists() and not pending.exists():
        write(pending, dump({"request": request, "current_version": default}))
    assigned = write_tasks(root, data, jobs, configured)
    if not path.exists():
        write(path, content)
    pending.unlink(missing_ok=True)
    return {"minutes": str(path), "items": assigned}
