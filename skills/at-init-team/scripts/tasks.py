"""Canonical Markdown requests and append-only events. All calls run under the project lock."""

import json
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from versions import open_version, version

from core import (STAGES, dump, field, inside, member, now, project, require, role_dir,
                  save, texts, write)


EDGES = {(0, 1), (1, 2), (2, 3), (2, 1)}
TASK_ID = re.compile(r"AT-[0-9a-f]{32}")
DISPLAY_NAME = re.compile(r"AT-([A-Za-z]+)([0-9]{5})-(.+)\.md")


def task_filename(prefix, number, summary):
    require(isinstance(prefix, str) and re.fullmatch(r"[A-Za-z]{1,24}", prefix),
            "需求前缀须为 1–24 个英文字母")
    require(1 <= number <= 99999, "角色的五位需求流水号已用尽")
    summary = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", summary)
    summary = " ".join(summary.split()).strip(" .-")
    require(len(summary) <= 40 and re.search(r"[\u3400-\u9fff]", summary),
            "请通过 summary 提供 40 字以内、包含中文的需求概括")
    return f"AT-{prefix}{number:05d}-{summary}.md"


@dataclass
class StoredTask:
    path: Path
    spec: dict
    events: list
    stage: int
    raw: str

    def stage_paths(self):
        return [inside(self.path.parent.parent, s, self.path.name) for s in STAGES]


def block(value):
    return "```json\n" + dump(value) + "```\n"


def parse(path):
    raw = path.read_bytes().decode("utf-8")
    # Events are independent blocks. JSON strings escape embedded Markdown newlines.
    matches = re.findall(r"^```json\n(.+?)\n```\n", raw, re.M | re.S)
    require(bool(matches), f"需求文件格式错误 {path}")
    spec, *events = [json.loads(s) for s in matches]
    require(TASK_ID.fullmatch(spec["id"]) and spec["format"] == "agent-team/task-v1", f"需求标识不符 {path}")
    require(path.stem == spec["id"] or DISPLAY_NAME.fullmatch(path.name), f"需求文件名无效 {path}")
    require(raw == initial(spec) + "".join("\n" + block(e) for e in events), f"需求格式或历史损坏 {path}")
    state = 0
    for e in events:
        if e["type"] == "move":
            target = STAGES.index(e["to"])
            require(e["from"] == STAGES[state] and (state, target) in EDGES, f"流转历史不一致 {path}")
            state = target
    return StoredTask(path, spec, events, state, raw)


def initial(spec):
    return f"# {spec['id']} · {spec['title']}\n\n## 需求\n\n" + block(spec) + "\n## 追加记录\n"


def role_tasks(root, role, *, repair=True):
    ws = inside(role_dir(root, role), "workspace")
    files = sorted(p for stage in STAGES for p in inside(ws, stage).glob("*.md"))
    tasks = {}
    numbers = set()
    for path in files:
        try:
            task = parse(inside(ws, path.parent.name, path.name))
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"{path}: {exc}") from exc
        task_id = task.spec["id"]
        require(task.spec["owner"] == role["name"], f"所有者与目录不符 {path}")
        require(task_id not in tasks, f"重复需求编号 {task_id}")
        name = DISPLAY_NAME.fullmatch(path.name)
        if name:
            prefix, number, summary = name.groups()
            require(prefix == role.get("task_prefix") and task_filename(prefix, int(number), summary) == path.name,
                    f"需求文件名与角色配置不一致 {path}")
            require(number not in numbers, f"角色需求流水号重复 {path}")
            numbers.add(number)
        if path.parent.name != STAGES[task.stage]:
            require(repair, f"需求位置与流转记录不一致，请核查 {path}")
            # Resume a move interrupted between appending its event and renaming the file.
            require(task.events and task.events[-1]["type"] == "move"
                    and task.events[-1]["from"] == path.parent.name, "需求目录与流转历史不一致")
            target = task.stage_paths()[task.stage]
            require(not target.exists(), f"目标文件已存在 {target}")
            task.path = path.rename(target)
        tasks[task_id] = task
    return tasks


def locate(root, role, request):
    tasks = role_tasks(root, role)
    path = None
    if "path" in request:
        path = (root / field(request, "path")).resolve()
    if "id" in request or path is None:
        task_id = field(request, "id")
        require(task_id in tasks, f"该角色没有需求 {task_id}")
        task = tasks[task_id]
        require(path is None or task.path == path, "需求编号与路径不一致")
        return task
    for task in tasks.values():
        if task.path == path:
            return task
    raise ValueError(f"该角色没有需求文件 {path}")


def prepare_items(data, items):
    require(isinstance(items, list) and items, "items 必须为非空需求数组")
    planned = []
    seen = set()
    for item in items:
        key = field(item, "key")
        require(key not in seen, f"同一批次重复 key {key}")
        seen.add(key)
        owner = member(data, field(item, "role"))
        reviewer = item.get("reviewer", "项目负责人")
        if reviewer not in ("用户", "项目负责人"):
            reviewer = member(data, reviewer)["name"]
        title = field(item, "title")
        require("\n" not in title and "\r" not in title, "标题应为单行")
        task_id = "AT-" + uuid.uuid5(uuid.UUID(data["id"]), key).hex
        spec = {"format": "agent-team/task-v1", "id": task_id, "key": key, "title": title,
                "owner": owner["name"], "reviewer": reviewer, "goal": field(item, "goal"),
                "criteria": texts(item, "criteria"), "source": item.get("source", "用户")}
        planned.append((owner, spec))
    return planned


@dataclass
class PlannedTask:
    owner: dict
    spec: dict
    path: Path
    create: bool


def plan_tasks(root, data, items, batch_version=None):
    specs = prepare_items(data, items)
    existing = {}
    highest = defaultdict(int)
    prefix_owners = {}
    for role in data["members"]:
        prefix = role.get("task_prefix")
        if prefix:
            require(prefix.casefold() not in prefix_owners, f"项目内的需求前缀重复 {prefix}")
            prefix_owners[prefix.casefold()] = role["name"]
        for task_id, task in role_tasks(root, role).items():
            require(task_id not in existing, f"项目内重复需求编号 {task_id}")
            existing[task_id] = task
            name = DISPLAY_NAME.fullmatch(task.path.name)
            if name:
                highest[role["name"]] = max(highest[role["name"]], int(name.group(2)))

    jobs = []
    configured = False
    for item, (owner, spec) in zip(items, specs):
        task_id = spec["id"]
        prefix = owner.get("task_prefix")
        if prefix and "prefix" in item:
            require(prefix == item["prefix"], f"{owner['name']} 已使用前缀 {prefix}")
        explicit = item.get("version")
        if explicit is None:
            explicit = batch_version
        if task_id in existing:
            task = existing[task_id]
            require({k: v for k, v in task.spec.items() if k != "version"} == spec,
                    f"需求 key 已有不同内容 {spec['key']}")
            current = effective(task.spec, task.events)
            if explicit is not None:
                require(version(explicit) == current.get("version"),
                        f"已有需求版本不同 {spec['key']}")
            jobs.append(PlannedTask(owner, current, task.path, False))
            continue
        spec["version"] = version(explicit if explicit is not None else data.get("current_version"))
        open_version(root, spec["version"])
        if not prefix:
            prefix = field(item, "prefix")
            require(prefix.casefold() not in prefix_owners, f"需求前缀已被其他角色使用 {prefix}")
            prefix_owners[prefix.casefold()] = owner["name"]
            owner["task_prefix"] = prefix
            configured = True
        highest[owner["name"]] += 1
        summary = field(item, "summary") if "summary" in item else spec["title"]
        filename = task_filename(prefix, highest[owner["name"]], summary)
        path = inside(role_dir(root, owner), "workspace", STAGES[0], filename)
        require(not path.exists(), f"需求文件已存在 {path}")
        jobs.append(PlannedTask(owner, spec, path, True))
    return jobs, configured


def write_tasks(root, data, jobs, configured):
    if configured:
        write(root / "AT.json", dump(data))
    result = []
    by_repo = defaultdict(list)
    for job in jobs:
        if job.create:
            write(job.path, initial(job.spec))
        by_repo[role_dir(root, job.owner)].append(job.path)
        result.append({"id": job.spec["id"], "role": job.owner["name"], "version": job.spec.get("version"),
                       "path": str(job.path)})
    for repo, paths in by_repo.items():
        save(repo, paths, "Register work items")
    return result


def add_tasks(root, request):
    data = project(root)
    jobs, configured = plan_tasks(root, data, request.get("items"), request.get("version"))
    return write_tasks(root, data, jobs, configured)


def effective(spec, events):
    current = dict(spec)
    for e in events:
        if e["type"] == "amend":
            current.update(e["changes"])
        elif e["type"] == "note" and "version" in e:
            current["version"] = e["version"]
    return current


def list_tasks(root, request):
    role = member(project(root), field(request, "role"))
    wanted = request.get("stages", list(STAGES))
    require(isinstance(wanted, list) and all(s in STAGES for s in wanted), "未知需求状态")
    rows = []
    for task in sorted(role_tasks(root, role).values(), key=lambda t: t.path.name):
        if STAGES[task.stage] in wanted:
            current = effective(task.spec, task.events)
            rows.append({"id": task.spec["id"], "title": task.spec["title"], "stage": STAGES[task.stage],
                         "path": str(task.path), "reviewer": current["reviewer"], "version": current.get("version")})
    return rows


def show_task(root, request):
    role = member(project(root), field(request, "role"))
    task = locate(root, role, request)
    return {"original": task.spec, "current": effective(task.spec, task.events), "events": task.events,
            "stage": STAGES[task.stage], "path": str(task.path)}


def bind_version(root, request, actor):
    data = project(root)
    target = version(field(request, "version"))
    reason = field(request, "reason")
    items = request.get("items")
    require(isinstance(items, list) and items, "请选择要补登记版本的需求")
    selected = {}
    for row in items:
        role = member(data, field(row, "role"))
        task = locate(root, role, row)
        previous = effective(task.spec, task.events).get("version")
        require(previous in (None, target), f"{task.spec['id']} 已有版本 {previous}")
        if previous is None:
            open_version(root, target)
        selected[task.spec["id"]] = (role, task, previous)
    paths = defaultdict(list)
    for role, task, previous in selected.values():
        if previous is None:
            event = {"type": "note", "key": "version/" + uuid.uuid4().hex, "actor": actor,
                     "time": now(), "reason": f"补登记至 {target}。{reason}", "version": target}
            write(task.path, task.raw + "\n" + block(event))
        paths[role_dir(root, role)].append(task.path)
    for repo, files in paths.items():
        save(repo, files, "Bind work items to " + target)
    return {"version": target, "ids": list(selected)}


def change(root, request, kind):
    data = project(root)
    role = member(data, field(request, "role"))
    task = locate(root, role, request)
    paths, spec, events, stage, raw = task.stage_paths(), task.spec, task.events, task.stage, task.raw
    actor = field(request, "actor")
    if actor != "用户":
        actor = member(data, actor)["name"]
    event = {"type": kind, "key": field(request, "key"), "actor": actor, "reason": field(request, "reason")}
    if kind == "move":
        before, after = field(request, "from"), field(request, "to")
        require(before in STAGES and after in STAGES and (STAGES.index(before), STAGES.index(after)) in EDGES,
                "不允许该状态转换")
        event.update({"from": before, "to": after})
        if before == STAGES[2] or after == STAGES[2]:
            event["evidence"] = texts(request, "evidence")
    elif kind == "amend":
        changes = request.get("changes")
        require(isinstance(changes, dict) and changes and not (changes.keys() - {"goal", "criteria", "reviewer"}),
                "可修订字段为 goal、criteria、reviewer")
        updated = {}
        if "goal" in changes:
            updated["goal"] = field(changes, "goal")
        if "criteria" in changes:
            updated["criteria"] = texts(changes, "criteria")
        if "reviewer" in changes:
            r = field(changes, "reviewer")
            updated["reviewer"] = "用户" if r == "用户" else member(data, r)["name"]
        event["changes"] = updated
    prior = next((e for e in events if e["key"] == event["key"]), None)
    if prior:
        require({k: v for k, v in prior.items() if k != "time"} == event, "相同事件 key 的内容不同")
    else:
        require(stage != 3, "需求已经归档")
        if kind == "move":
            require(STAGES[stage] == event["from"], "当前状态已变化，请重新读取需求")
            owner = effective(spec, events)["reviewer"] if stage == 2 else role["name"]
            require(actor in (owner, "用户"), f"此步骤由 {owner} 执行")
        event["time"] = now()
        write(paths[stage], raw + "\n" + block(event))
        if kind == "move":
            target = STAGES.index(event["to"])
            require(not paths[target].exists(), "目标已有同编号需求")
            paths[stage].rename(paths[target])
            stage = target
    save(role_dir(root, role), paths, f"{kind} {spec['id']}")
    return {"id": spec["id"], "stage": STAGES[stage], "path": str(paths[stage])}
