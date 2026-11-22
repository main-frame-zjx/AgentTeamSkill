"""Read-only discovery for AT_help, including before a project exists."""

from pathlib import Path

from core import STAGES, field, inside, project, require, role_dir
from tasks import effective, role_tasks
from versions import formal_versions, history, version


def catalog():
    rows = []
    for skill in sorted(Path(__file__).resolve().parents[2].glob("at-*/SKILL.md")):
        lines = skill.read_text(encoding="utf-8-sig").splitlines()
        if not lines or lines[0] != "---" or "---" not in lines[1:]:
            continue
        fields = dict(line.split(": ", 1) for line in lines[1:lines.index("---", 1)] if ": " in line)
        if fields.get("name") == skill.parent.name and fields.get("description"):
            rows.append({"name": fields["name"], "description": fields["description"]})
    return rows


def recommendation(skill, reason, prompt):
    return {"skill": skill, "reason": reason, "example": f"${skill} {prompt}" if skill else prompt}


def suggest(rows, names, current_role, target, released):
    if not names:
        return recommendation("at-add-team-member", "项目尚未登记角色。", "添加一位项目负责人。")
    if not rows:
        if len(names) == 1:
            return recommendation("at-add-worklist", "已有一位角色，可以分派首项明确需求。",
                                  f"为{names[0]}创建第一项需求。")
        return recommendation("at-team-discuss", f"{len(names)} 位角色已登记，项目还没有需求。", "召开首次项目会议，确定本轮分工。")

    for stage in (STAGES[2], STAGES[1], STAGES[0]):
        for row in rows:
            if row["stage"] != stage:
                continue
            review = stage == STAGES[2]
            actor = row["reviewer"] if review else row["role"]
            if current_role and actor != current_role:
                continue
            verb = "验收" if review else ("续做" if stage == STAGES[1] else "领取")
            return recommendation("at-review-work" if review else "at-work",
                                  f"{row['role']}的《{row['title']}》处于{stage}。",
                                  f"请{actor}{verb}《{row['title']}》（{row['id']}）。")

    if current_role and any(r["stage"] != STAGES[3] for r in rows):
        return recommendation("at-start-board", f"{current_role}暂无可领取、续做或验收的事项，其他角色仍有任务。",
                              "查看全队进度和角色分工。")
    if released:
        if len(names) >= 2:
            return recommendation("at-team-discuss", f"{target} 已正式发布。", "商定下一轮版本目标与分工。")
        return recommendation("at-add-worklist", f"{target} 已正式发布。", "为下一个迭代登记需求。")
    if target and any(r["version"] == target for r in rows):
        return recommendation("at-publish", f"{target} 的需求均已归档，可由管理角色核查发布条件。",
                              f"核查 {target} 的交付材料和发布条件。")
    return recommendation("at-manage-workspace", "已有归档需求，当前迭代尚无可确认的版本需求。",
                          "查看归档需求的版本归属。")


def inspect_project(start, request):
    start = start.resolve()
    result = {"catalog": catalog(), "directory": str(start)}
    root = next((p for p in (start, *start.parents) if (p / "AT.json").exists()), None)
    if root is None:
        empty = start.is_dir() and not any(start.iterdir())
        advice = (recommendation("at-init-team", "当前目录为空，可以原地初始化。", "在当前目录初始化项目。")
                  if empty else recommendation(None, "当前位置不是可初始化的空目录。",
                                               "请切换到含 AT.json 的项目根目录，或新建一个空目录后使用 $at-init-team。"))
        return {**result, "status": "empty" if empty else "outside", "recommendation": advice}

    check_path = root / "AT.json"
    try:
        data = project(root)
        for key in ("id", "name", "vault", "team_repo", "remote"):
            field(data, key)
        require(isinstance(data.get("members"), list), "members 应为数组")
        target = version(data["current_version"]) if data.get("current_version") else None
        names, rows = [], []
        current_role = None
        for role in data["members"]:
            check_path = root / "AT.json"
            name = field(role, "name")
            require(name not in names, f"重复登记角色 {name}")
            names.append(name)
            base = role_dir(root, role)
            if start.is_relative_to(base):
                current_role = name
            for stage in STAGES:
                check_path = inside(base, "workspace", stage)
                require(check_path.is_dir(), "缺少角色需求目录")
            check_path = base / "workspace"
            for task in role_tasks(root, role, repair=False).values():
                check_path = task.path
                spec = effective(task.spec, task.events)
                rows.append({"id": spec["id"], "title": spec["title"], "role": name,
                             "stage": STAGES[task.stage], "reviewer": spec["reviewer"],
                             "version": version(spec["version"]) if spec.get("version") else None})
        check_path = root / ".at-state" / "releases.json"
        releases = history(root)
        require(isinstance(releases, list), "发布记录应为数组")
        released = target in formal_versions(releases)
        counts = {stage: sum(r["stage"] == stage for r in rows) for stage in STAGES}
        return {**result, "status": "project", "root": str(root), "name": data["name"], "roles": names,
                "current_role": current_role, "version": target, "released": released, "tasks": rows,
                "counts": counts, "recommendation": suggest(rows, names, current_role, target, released)}
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        return {**result, "status": "invalid", "root": str(root), "path": str(check_path), "error": str(exc),
                "recommendation": recommendation(None, "项目记录需要核对。", f"请检查 {check_path}。")}
