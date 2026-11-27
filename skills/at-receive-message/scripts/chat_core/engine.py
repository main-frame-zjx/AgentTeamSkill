"""Role communication use cases. All mutations in a call share one Store transaction."""
from contextlib import nullcontext
import json
import os
from pathlib import Path, PureWindowsPath
import re

from core import field, inside, lock, member, now, project, project_root, require
from versions import context_role
from .store import GROUP_FORMAT, PRIORITY, filename, opened
from .tasks_bridge import brief, can_notify, matches_event, notification, snapshots


def identity(data, name):
    return "用户" if name == "用户" else member(data, name)["name"]


def model_info(role, value):
    if role == "用户":
        return "human", "human", "user"
    source = "agent_self_report"
    if value in (None, "auto"):
        source = "env"
        value = next((os.environ[k] for k in ("AT_AGENT_MODEL", "CODEX_MODEL", "OPENAI_MODEL",
                     "GEMINI_MODEL", "ANTHROPIC_MODEL", "DSH_MODEL") if os.environ.get(k, "").strip()), None)
    require(isinstance(value, str) and 0 < len(value.strip()) <= 160, "请提供实际模型或已知系列")
    value = value.strip()
    for pattern, family in ((r"gemini", "gemini"), (r"claude", "claude"), (r"deepseek|dsh", "deepseek"),
                            (r"gpt|codex|\bo[134]\b", "gpt")):
        if re.search(pattern, value, re.I):
            return value, family, source
    return value, "other", source


def references(root, items, warnings):
    require(isinstance(items, list) and len(items) <= 10, "每条消息最多引用 10 个文件")
    result = []
    for ref in items:
        path = field(ref, "path").replace("\\", "/")
        parts = path.split("/")
        require(not PureWindowsPath(path).anchor and ":" not in path and
                not any(p in ("", ".", "..") or p.casefold() == ".git" for p in parts), "请使用项目内相对文件路径")
        target = inside(root, path)
        if not target.is_file():
            warnings.append(f"引用文件当前不存在：{path}")
        normalized = {"path": path}
        if "note" in ref:
            normalized["note"] = field(ref, "note")
            require(len(normalized["note"]) <= 60, "文件说明最多 60 字")
        if "lines" in ref:
            lines = field(ref, "lines")
            require(re.fullmatch(r"[1-9]\d*(?:-[1-9]\d*)?", lines) and
                    int(lines.split("-")[0]) <= int(lines.split("-")[-1]), "引用行号无效")
            normalized["lines"] = lines
        result.append(normalized)
    return result


def group_id(request):
    require(("task_id" in request) != ("group_id" in request), "须提供 task_id 或 group_id 其中一项")
    gid = "task:" + field(request, "task_id") if "task_id" in request else field(request, "group_id")
    filename(gid)
    return gid


def group_for(store, gid, tasks, role, title=None):
    require(gid not in store.errors, store.errors.get(gid))
    if gid.startswith("task:"):
        require(gid[5:] in tasks, store.task_errors.get(gid[5:], f"需求不存在或读取失败 {gid[5:]}，请查看 groups 的 warnings"))
    if gid not in store.groups:
        kind, identifier = gid.split(":", 1)
        if kind == "task":
            title = tasks[identifier]["title"]
        require(title, "请先创建专题群")
        store.groups[gid] = {"format": GROUP_FORMAT, "group_id": gid, "kind": kind,
                             "task_id": identifier if kind == "task" else None, "title": title,
                             "created_at": now(), "created_by": role, "archived": False, "messages": []}
        store.dirty.add(gid)
    return store.groups[gid]


def send_one(store, data, tasks, role, model, item, warnings):
    gid = group_id(item)
    group = group_for(store, gid, tasks, role)
    kind, body, key = (field(item, k) for k in ("kind", "body", "idempotency_key"))
    require(kind in PRIORITY and len(body) <= 1500, "消息类型无效或正文超过 1500 字")
    require(isinstance(item.get("to"), list) and item["to"] and all(isinstance(r, str) for r in item["to"]), "请明确指定接收者")
    recipients = list(dict.fromkeys(identity(data, n) for n in item["to"]))
    content = {"kind": kind, "sender": role, "to": recipients, "body": body,
               "refs": references(store.root, item.get("refs", []), warnings), "reply_to": item.get("reply_to"),
               "event_key": item.get("event_key")}
    for old in group["messages"]:
        if key == old["idempotency_key"] or key in old.get("idempotency_aliases", []):
            require(all(old.get(k) == v for k, v in content.items() if k != "event_key" or v is not None), "同一幂等键对应不同消息")
            return old, True
    require(role not in recipients and not {"*", "all"}.intersection(recipients), "接收者须为其他指定角色")
    if kind in ("review_request", "review_rejected"):
        task = tasks.get(group["task_id"])
        actual = notification(task) if task else None
        require(actual and actual["kind"] == kind, "当前需求没有对应的送验或退回事件")
        require(can_notify(actual, task, role), "请由需求负责人或本次流转的操作人发送提醒")
        require(actual["to"][0] in recipients, f"请包含本次提醒的接收者 {actual['to'][0]}")
        require(content["event_key"] in (None, actual["event_key"]), "流转事件已变化")
        content["event_key"] = actual["event_key"]
        for old in group["messages"]:
            if matches_event(old, actual):
                require(all(old.get(k) == v for k, v in content.items()),
                        f"本次流转已通知，见 {old['id']}；追加协作可另发协作提醒")
                old.setdefault("idempotency_aliases", []).append(key)
                store.dirty.add(gid)
                return old, True
    if content["reply_to"] is not None:
        require(any(m["id"] == content["reply_to"] and role in m["to"] for m in group["messages"]),
                "回复须指向同群发给自己的消息")
    seq = store.take_sequence()
    msg = {**content, "id": f"MSG-{seq:06d}", "seq": seq, "group_id": gid, "created_at": now(),
           "sender_model": model[0], "model_family": model[1], "model_source": model[2],
           "idempotency_key": key, "overall_status": "pending",
           "recipients": {r: {"status": "pending"} for r in recipients}}
    group["messages"].append(msg)
    store.dirty.add(gid)
    return msg, False


def overall(msg):
    states = {r["status"] for r in msg["recipients"].values()}
    return next(iter(states)) if len(states) == 1 else "partial"


def settlement(store, data, tasks, role, request, reopen=False):
    model = model_info(role, request.get("model"))
    messages = {m["id"]: m for g in store.groups.values() for m in g["messages"]}
    sent, handled, deferred, warnings = [], [], [], list(store.warnings)
    sends, handles = request.get("send", []), request.get("handle", [])
    require(isinstance(sends, list) and isinstance(handles, list), "send 和 handle 必须为数组")
    batch_replies = {}
    for item in sends:
        msg, duplicate = send_one(store, data, tasks, role, model, item, warnings)
        sent.append({"message_id": msg["id"], "group_id": msg["group_id"], "duplicate": duplicate})
        if msg["reply_to"]:
            batch_replies.setdefault(msg["reply_to"], set()).add(msg["id"])
    seen = set()
    for item in handles:
        mid = field(item, "message_id")
        msg = messages.get(mid)
        require(mid not in seen and msg and role in msg["recipients"], "消息不在本角色的收件箱或重复核销")
        seen.add(mid)
        gid = msg["group_id"]
        group_for(store, gid, tasks, role)
        rec = msg["recipients"][role]
        if reopen:
            require(rec["status"] == "handled", "仅可重开已处理消息")
            msg.setdefault("audit", []).append({"action": "reopen", "role": role, "at": now(), "model": model[0],
                                                "reason": field(item, "note"), "previous": dict(rec)})
            rec.clear()
            rec["status"] = "pending"
        else:
            resolution = field(item, "resolution")
            require(resolution in ("accepted", "resolved", "noted", "replied", "deferred"), "处理结论无效")
            note = field(item, "note")
            new_links = batch_replies.get(mid, set())
            require(not new_links or resolution in ("replied", "deferred"), "已关联回复，请选择 replied 或 deferred")
            if rec["status"] == "handled":
                require(new_links.issubset(rec.get("reply_message_ids", [rec.get("reply_message_id")])),
                        "本次回复与已核销的回复不同")
                require(rec["resolution"] == resolution and rec["resolution_note"] == note, "已处理记录与此次决定不同")
                handled.append({"message_id": mid, **rec})
                continue
            replies = [m["id"] for m in store.groups[gid]["messages"] if m["sender"] == role and m["reply_to"] == mid]
            if resolution == "deferred":
                block = {"note": note, "reply_message_ids": replies, "model": model[0],
                         "model_family": model[1], "model_source": model[2]}
                if not all(rec.get("blocked", {}).get(k) == v for k, v in block.items()):
                    rec["blocked"] = {**block, "at": now()}
                    msg.setdefault("audit", []).append({"action": "deferred", "role": role, **rec["blocked"]})
                    store.dirty.add(gid)
                deferred.append({"message_id": mid, **rec})
                continue
            require(resolution != "replied" or replies, "replied 须有本人发出的同群关联回复")
            links = replies if resolution == "replied" else []
            decision = {"resolution": resolution, "resolution_note": note,
                        "reply_message_id": next(iter(links), None), "reply_message_ids": links}
            rec.pop("blocked", None)
            rec.update(decision, status="handled", handled_at=now(), handled_by_model=model[0],
                       handled_model_family=model[1], handled_model_source=model[2])
        msg["overall_status"] = overall(msg)
        store.dirty.add(msg["group_id"])
        handled.append({"message_id": mid, **rec})
    remaining = sum(1 for g in store.groups.values() for m in g["messages"]
                    if m["recipients"].get(role, {}).get("status") == "pending")
    return {"role": role, "model": model[0], "handled": handled, "sent": sent,
            "remaining_pending": remaining, "deferred": deferred, "warnings": warnings}


def page_size(request):
    value = request.get("limit", 30)
    require(type(value) is int and 1 <= value <= 200, "limit 范围为 1–200")
    return value


def receive(store, tasks, role, request):
    limit = page_size(request)
    context = request.get("include_recent_context", 2)
    require(type(context) is int and 0 <= context <= 10, "上下文数量范围为 0–10")
    ceiling, after = store.meta["next_seq"] - 1, (-1, 0)
    if request.get("cursor"):
        token = json.loads(request["cursor"])
        require(isinstance(token, list) and len(token) == 5 and token[:2] == [store.meta["project_id"], role]
                and all(type(x) is int for x in token[2:]), "收件游标无效")
        ceiling, after = token[2], tuple(token[3:])
    rows = []
    for group in store.groups.values():
        for index, msg in enumerate(group["messages"]):
            if msg["seq"] <= ceiling and msg["recipients"].get(role, {}).get("status") == "pending":
                rows.append(((PRIORITY[msg["kind"]], msg["seq"]), group, index, msg))
    eligible = sorted((r for r in rows if r[0] > after), key=lambda r: r[0])
    result = []
    for (priority, seq), g, i, m in eligible[:limit]:
        recent = g["messages"][max(0, i-context):i]
        result.append({**m, "priority": priority, "group_title": g["title"], "group_kind": g["kind"],
                       "task_snapshot": brief(tasks.get(g["task_id"])), "recent_context": [
                           {k: p[k] for k in ("id", "sender", "kind")} | {"preview": p["body"][:120]} for p in recent]})
    more = len(eligible) > limit
    cursor = json.dumps([store.meta["project_id"], role, ceiling, *eligible[limit-1][0]]) if more else None
    return {"role": role, "pending_total": len(rows), "returned": len(result), "truncated": more,
            "next_cursor": cursor, "messages": result, "initialized": store.initialized, "warnings": store.warnings}


def overview(store, data, tasks):
    counts = {name: {"pending": 0, "by_kind": {}, "oldest_pending_at": None} for name in [*(r["name"] for r in data["members"]), "用户"]}
    groups, pending = [], []
    for g in store.groups.values():
        task = tasks.get(g["task_id"])
        items = []
        for m in g["messages"]:
            for recipient, rec in m["recipients"].items():
                if rec["status"] == "pending":
                    c = counts.setdefault(recipient, {"pending": 0, "by_kind": {}, "oldest_pending_at": None})
                    c["oldest_pending_at"] = min(c["oldest_pending_at"] or m["created_at"], m["created_at"])
                    c["pending"] += 1
                    c["by_kind"][m["kind"]] = c["by_kind"].get(m["kind"], 0) + 1
                    items.append({"message_id": m["id"], "group_id": g["group_id"], "recipient": recipient,
                                  "kind": m["kind"], "sender": m["sender"], "sender_model": m["sender_model"],
                                  "preview": m["body"][:160], "priority": PRIORITY[m["kind"]], "created_at": m["created_at"]})
        pending.extend(items)
        groups.append({k: v for k, v in g.items() if k != "messages"} |
                      {"task": brief(task), "archived": bool(task and task["stage"] == "4已归档") or g["archived"],
                       "message_count": len(g["messages"]), "pending_count": len(items),
                       "last_preview": g["messages"][-1]["body"][:160] if g["messages"] else "",
                       "last_message_at": g["messages"][-1]["created_at"] if g["messages"] else None})
    return {"initialized": store.initialized, "groups_total": len(groups), "pending_total": len(pending), "by_role": counts,
            "groups": groups, "pending_items": sorted(pending, key=lambda p: (p["priority"], p["created_at"])),
            "warnings": store.warnings}


def workflow(store, tasks, role):
    missing, reviews = [], []
    for task in tasks.values():
        if task["stage"] == "3待验收" and task["reviewer"] == role:
            reviews.append(brief(task))
        reminder = notification(task)
        gid = "task:" + task["id"]
        if reminder and can_notify(reminder, task, role) and role not in reminder["to"] and gid not in store.errors:
            messages = store.groups.get(gid, {}).get("messages", [])
            if not any(matches_event(m, reminder) for m in messages):
                missing.append({**reminder, "actor": role})
    return {"pending_reviews": reviews, "missing_notifications": missing}


def run(command, start, request):
    require(isinstance(request, dict), "输入必须是 JSON 对象")
    start = Path(start).resolve(strict=True)
    require(start.is_dir(), "working_dir 必须是目录")
    root = project_root(start)
    data = project(root)
    current = context_role(root, data, start, purpose="通讯")
    provided = request.get("role", request.get("sender", current))
    role = identity(data, provided) if provided is not None else None
    require(not current or role == current, "当前目录与指定角色不符")
    writes = command in ("send", "handle", "settle", "reopen", "create-group")
    require(role or not (writes or command in ("receive", "workflow")), "请在项目根显式指定角色")
    # Match the task writer's lock order so a review cannot be reassigned between
    # validating its transition and committing its notification.
    sends = [request] if command == "send" else request.get("send", [])
    guard = nullcontext()
    if writes and isinstance(sends, list) and any(isinstance(item, dict) and item.get("kind") in
            ("review_request", "review_rejected") for item in sends):
        state = inside(root, ".at-state")
        state.mkdir(exist_ok=True)
        guard = lock(state / "agent-team.lock")
    with guard, opened(root, data, writes) as store:
        tasks, warnings, store.task_errors = snapshots(root, data) if command != "summary" else ({}, [], {})
        store.warnings.extend(warnings)
        if command == "receive":
            return receive(store, tasks, role, request)
        if command == "create-group":
            gid = "topic:" + field(request, "slug")
            filename(gid)
            title = field(request, "title")
            g = group_for(store, gid, tasks, role, title)
            require(g["title"] == title, "专题群已经存在且标题不同")
            return {"group_id": gid, "title": title}
        if command == "send":
            request = {"model": request.get("sender_model"), "send": [request]}
        if command in ("handle", "reopen"):
            request = {"model": request.get("model"), "handle": request["items"]}
        if writes:
            return settlement(store, data, tasks, role, request, command == "reopen")
        if command == "history":
            gid = group_id(request)
            require(gid in store.groups, store.errors.get(gid, "群组不存在"))
            g = store.groups[gid]
            status = request.get("status")
            require(status in (None, "partial", "handled", "pending"), "未知状态")
            rows = [m for m in g["messages"] if not status or m["overall_status"] == status]
            offset = request.get("offset", 0)
            require(type(offset) is int and offset >= 0, "offset 须为非负整数")
            end = offset + page_size(request)
            return {"group_id": gid, "task": tasks.get(g["task_id"]), "messages": rows[offset:end],
                    "next_offset": end if end < len(rows) else None, "warnings": store.warnings}
        view = overview(store, data, tasks)
        if command == "workflow":
            return {**workflow(store, tasks, role), "initialized": store.initialized, "inbox_summary": view["by_role"][role], "warnings": view["warnings"]}
        if command == "groups":
            version = field(request, "version") if "version" in request else None
            view["groups"] = [g for g in view["groups"] if (not request.get("only_pending") or g["pending_count"])
                              and (request.get("include_archived", True) or not g["archived"])
                              and (not version or (g["task"] or {}).get("version") == version)]
            return view
        require(command == "summary", "未知通讯命令")
        return {k: v for k, v in view.items() if k not in ("groups", "pending_items")}
