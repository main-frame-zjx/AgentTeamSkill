"""Read the canonical request Markdown without triggering workspace repairs."""
from collections import defaultdict

from core import STAGES, inside, require, role_dir
from tasks import DISPLAY_NAME, effective, parse, validate_task_name


def snapshot(root, task):
    for event in task.events:
        require(isinstance(event, dict) and all(isinstance(event.get(k), str) and event[k].strip()
                for k in ("type", "actor", "key", "reason")), "需求流转或追加记录缺少事件信息")
    spec = effective(task.spec, task.events)
    require(all(isinstance(spec.get(k), str) and spec[k].strip() for k in
                ("id", "owner", "reviewer", "version", "title", "goal"))
            and isinstance(spec.get("criteria"), list) and all(isinstance(c, str) for c in spec["criteria"]),
            "需求字段或验收条件无效")
    prefix, number, _ = DISPLAY_NAME.fullmatch(task.path.name).groups()
    return {k: spec[k] for k in ("id", "owner", "reviewer", "version", "title", "goal", "criteria")} | {
        "original_reviewer": task.spec["reviewer"], "code": prefix + number, "stage": STAGES[task.stage], "events": task.events,
        "path": task.path.relative_to(root).as_posix()}


def diagnostic(root, path, error):
    location = path.relative_to(root).as_posix()
    detail = error.strerror if isinstance(error, OSError) else str(error)
    detail = detail.replace(str(path), location).replace(str(root) + "/", "").replace(str(root) + chr(92), "")
    detail = detail.replace(chr(92), "/")
    return f"{location}: {detail}"


def snapshots(root, data):
    result, warnings, invalid = {}, [], {}
    by_id, by_number = defaultdict(list), defaultdict(list)
    for member in data["members"]:
        ws = role_dir(root, member) / "workspace"
        for stage in STAGES:
            folder = ws / stage
            try:
                paths = sorted(inside(root, folder).iterdir())
            except (OSError, ValueError) as exc:
                warnings.append(diagnostic(root, folder, exc))
                continue
            for path in paths:
                if path.suffix.lower() != ".md":
                    continue
                task = None
                try:
                    task = parse(inside(folder, path.name))
                    number = validate_task_name(task, member)
                    by_id[task.spec["id"]].append(path)
                    by_number[(member["name"], number)].append((task.spec["id"], path))
                    require(stage == STAGES[task.stage], "需求位置与流转记录不符")
                    item = snapshot(root, task)
                    result[item["id"]] = item
                except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
                    reason = diagnostic(root, path, exc)
                    warnings.append(reason)
                    if task is not None:
                        invalid[task.spec["id"]] = reason
    for task_id, paths in by_id.items():
        if len(paths) > 1:
            result.pop(task_id, None)
            invalid[task_id] = "重复需求编号 " + task_id + " · " + "、".join(p.relative_to(root).as_posix() for p in paths)
            warnings.append(invalid[task_id])
    for rows in by_number.values():
        if len(rows) > 1:
            for task_id, path in rows:
                result.pop(task_id, None)
                invalid[task_id] = diagnostic(root, path, "角色需求流水号重复")
                warnings.append(invalid[task_id])
    return result, warnings, invalid


def notification(task):
    reviewer = task["original_reviewer"]
    event = move = None
    for entry in task["events"]:
        if entry["type"] == "move":
            event = move = entry
        elif entry.get("changes", {}).get("reviewer", reviewer) != reviewer:
            reviewer = entry["changes"]["reviewer"]
            if move and move["to"] == STAGES[2]:
                event = entry
    if not move:
        return None
    if task["stage"] == STAGES[2]:
        kind, target = "review_request", task["reviewer"]
        if target == task["owner"]:
            return None
    elif move["from"] == STAGES[2] and move["to"] == STAGES[1]:
        kind, target, event = "review_rejected", task["owner"], move
        if target == event["actor"]:
            return None
    else:
        return None
    return {"task_id": task["id"], "kind": kind, "to": [target],
            "actor": event["actor"] if event["actor"] != target else task["owner"],
            "event_key": event["key"], "idempotency_key": f"{kind}/{task['id']}/{event['key']}",
            "reason": event["reason"], "refs": [{"path": task["path"]}]}


def can_notify(reminder, task, role):
    return role == reminder["actor"] or (reminder["kind"] == "review_request" and role == task["owner"])


def matches_event(message, reminder):
    return (message["kind"] == reminder["kind"] and message.get("event_key") == reminder["event_key"]
            and reminder["to"][0] in message["to"])


def brief(task):
    return {k: v for k, v in task.items() if k not in ("events", "criteria", "goal", "original_reviewer")} if task else None
