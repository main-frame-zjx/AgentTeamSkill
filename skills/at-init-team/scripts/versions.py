"""Version identities, formal release history and registered publication roles."""

import re
from pathlib import Path

from core import dump, field, inside, member, project, read_json, require, role_dir, write


def version(value):
    require(isinstance(value, str) and len(value) <= 64
            and re.fullmatch(r"[vV]?[0-9]+(?:\.[0-9]+)*", value.strip()),
            "请指定数字版本，例如 v1.0 或 v1.10.2")
    parts = [int(p) for p in value.strip().lstrip("vV").split(".")]
    while len(parts) > 2 and parts[-1] == 0:
        parts.pop()
    if len(parts) == 1:
        parts.append(0)
    return "v" + ".".join(map(str, parts))


def order(value):
    return tuple(map(int, version(value)[1:].split(".")))


def history(root):
    path = inside(root, ".at-state", "releases.json")
    return read_json(path) if path.exists() else []


def pending_path(root):
    return inside(root, ".at-state", "release-pending")


def formal_versions(records):
    """First formal publication seals the version. Further channels and revisions reuse it."""
    seals = {}
    for row in records:
        if row.get("kind") != "dev":
            seals.setdefault(row["version"], row)
    return seals


def open_version(root, target):
    seals = formal_versions(history(root))
    if seals:
        require(order(target) > max(map(order, seals)), "目标版本已经发布或早于最近一次正式发布")
    receipt = pending_path(root) / "receipt.json"
    if receipt.is_file():
        row = read_json(receipt)
        if row.get("kind") != "dev":
            require(order(target) > order(row["version"]), "该版本正在发布，请先完成发布重试")


def set_iteration(root, request):
    data = project(root)
    target = version(field(request, "version"))
    open_version(root, target)
    data["current_version"] = target
    write(root / "AT.json", dump(data))
    return {"current_version": target}


def context_role(root, data, start):
    cwd = Path.cwd().resolve()
    if not cwd.is_relative_to(root):
        origin = next((p for p in (cwd, *cwd.parents) if (p / "AT.json").is_file()), None)
        if origin:
            require(not any(cwd.is_relative_to(role_dir(origin, r).resolve()) for r in project(origin)["members"]),
                    "当前角色属于另一个项目。请切换到目标项目对应角色的 AI 会话；发布请由项目负责人执行。")
    found = {role["name"] for role in data["members"] for path in (cwd, start)
             if path.resolve().is_relative_to(role_dir(root, role).resolve())}
    require(len(found) <= 1, "当前目录与指定的角色目录不一致。发布项目成果请切换到项目负责人的 AI 会话执行。")
    return next(iter(found), None)


def publisher(root, request, start):
    data = project(root)
    current = context_role(root, data, start)
    managers = [r["name"] for r in data["members"]
                if r["name"] == "项目负责人" or r["name"] in data.get("release_managers", [])]
    redirect = "请切换到项目负责人的 AI 会话执行。可发布角色：" + ("、".join(managers) or "尚未登记")
    require(not current or current in managers, f"当前角色 {current} 无发布权限。{redirect}")
    identity = request.get("actor", current)
    require(identity, "请先向用户确认本次执行发布的管理角色。" + redirect)
    actor = next((r["name"] for r in data["members"] if identity in (r["name"], r["dir"])), None)
    require(actor in managers, f"角色 {identity} 无发布权限。{redirect}")
    require(not current or current == actor, f"当前角色 {current} 与指定执行人不符。{redirect}")
    in_role = Path.cwd().resolve().is_relative_to(role_dir(root, member(data, actor)).resolve())
    if not in_role:
        require("actor" in request and request.get("actor_confirmed") is True,
                "请先由用户确认以 " + actor + " 身份执行，再传 actor 和 actor_confirmed=true。" + redirect)
    return actor


def authorize(root, request, start):
    data = project(root)
    current = context_role(root, data, start)
    require(current is None or current == "项目负责人" or current in data.get("release_managers", []),
            "请从项目根目录或已登记的管理角色处理授权")
    require(request.get("user_confirmed") is True, "需要用户明确指定该管理角色")
    name = member(data, field(request, "role"))["name"]
    managers = data.setdefault("release_managers", [])
    if name not in managers:
        managers.append(name)
        write(root / "AT.json", dump(data))
    return {"release_managers": managers}
