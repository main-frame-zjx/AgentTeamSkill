"""Bounded role handoff, deterministic Markdown rendering and recoverable Git writes."""

import difflib
import json
import re
from pathlib import Path

import library
from core import (STAGES, atomic, digest, dump, field, git, inside, now, read_json,
                  require, role_dir, save, write)
from learning import candidate, candidates, check_ref, line
from tasks import DISPLAY_NAME, effective, referenced_tasks, role_tasks
from versions import formal_versions, history as release_history, version


LIMIT = 6656
STATE = ".memory-state.json"
DOC = "Memory.md"
FOCUS = {"current_goal": "主攻目标", "progress": "当前进度", "next_step": "下次第一步"}
OPEN = ("pending", "needs_evidence")


def initial_state():
    return {"format": 1, "focus": {}, "decisions": {}, "risks": {}, "next": {"D": 1, "R": 1},
            "candidates": {}, "outcomes": {}}


def paths(root, role):
    base = role_dir(root, role)
    return inside(base, STATE), inside(base, DOC)


def pending_file(root, role):
    return inside(root, ".at-state", "memory-" + digest(role["dir"].encode()) + ".json")


def short(value, size):
    value = " ".join(str(value).split())
    if len(value.encode()) <= size:
        return value
    return value.encode()[:size - 3].decode("utf-8", "ignore") + "…"


def md(value):
    return re.sub(r"([\\`*_{}\[\]<>|])", r"\\\1", " ".join(value.split()))


def byte_count(text):
    return len(text.encode())


def inline_code(value):
    require("`" not in value, f"机读标识不能含反引号 {value}")
    return f"`{value}`"


def semantic_rows(items):
    return [f"- {key} · {md(item['summary'])}（{inline_code(item['ref'])}）" for key, item in items.items()]


def slice_rows(rows, budget, command):
    suffix = f"- 其余 {len(rows)} 项，详见 `{command}`。"
    shown, used = [], byte_count(suffix) + 1
    for row in rows:
        length = byte_count(row) + 1
        if used + length > budget:
            break
        shown.append(row)
        used += length
    if len(shown) < len(rows):
        shown.append(f"- 其余 {len(rows) - len(shown)} 项，详见 `{command}`。")
    return shown


def view(root, data, role, state, tasks, *, previous_state=None):
    table, counts = [], [0] * len(STAGES)
    for task in sorted(tasks.values(), key=lambda t: ({1: 0, 2: 1, 0: 2, 3: 3}[t.stage], t.path.name)):
        counts[task.stage] += 1
        if task.stage == 3:
            continue
        name = DISPLAY_NAME.fullmatch(task.path.name)
        code = "".join(name.groups()[:2])
        spec = effective(task.spec, task.events)
        latest = task.events[-1]["reason"] if task.events else ""
        table.append(f"- {STAGES[task.stage]} · {inline_code(code)} · {md(short(spec['title'], 100))} · "
                     f"{spec['version']} · {md(short(spec['reviewer'], 40))}"
                     + (" · " + md(short(latest, 120)) if latest else ""))
    version_now = data["current_version"]
    tree = inside(role_dir(root, role), "repository", Path(data["team_repo"]).name)
    head = git(tree, "rev-parse", "--short", "HEAD")
    branch = git(tree, "branch", "--show-current")
    goal = data.get("version_goals", {}).get(version_now, "")
    seals = formal_versions(release_history(root))
    released = "、".join(list(seals)[-3:]) + f"（共 {len(seals)} 版）" if seals else "暂无"
    overview = [f"- {version_now}" + (" " + md(short(goal, 210)) if goal else ""),
                "- " + " · ".join(f"{s} {c}" for s, c in zip(STAGES, counts)),
                f"- 代码工作树 {inline_code(branch)} @ {inline_code(head)}", f"- 已正式发布：{released}"]
    focus = [f"- {label}：{md(state['focus'][key])}" for key, label in FOCUS.items() if key in state["focus"]]
    decisions, risks = semantic_rows(state["decisions"]), semantic_rows(state["risks"])
    for label, rows, cap, count in (("焦点", focus, 800, 3), ("决定", decisions, 2200, 12), ("风险", risks, 1200, 6)):
        size = byte_count("\n".join(rows))
        require(size <= cap and len(rows) <= count,
                f"{label}配额 {len(rows)}/{count} 条、{size}/{cap} 字节。请精简或合并：{[r.split(' · ')[0] for r in rows]}")
    issues = []
    try:
        notes, issues = library.scan(data, [role])
    except (ValueError, OSError) as exc:
        notes = []
        issues = [{"error": str(exc)}]
    note_rows = [f"- {inline_code(n['path'])} · {md(short(n['summary'], 84))}"
                 for n in notes if n["status"] == "active"]
    if issues:
        note_rows.append("- 个人库部分内容不可读取，请用 `library-lint` 核对。")
    queue = [c for c in candidates(tasks, state).values() if c["status"] in OPEN]
    def priority(c):
        task = tasks.get(c["source"].removeprefix("task:"))
        return ({3: 0, 2: 1, 1: 2, 0: 3}[task.stage] if task else 4, c["source"], c["id"])
    queue.sort(key=priority)
    preview = [f"- 候选 {c['id']} · {md(short(c['topic'], 90))}" for c in queue[:3]]
    if len(queue) > 3:
        preview.append(f"- 另有 {len(queue) - 3} 条候选，详见 `library-index`。")
    def render(task_lines, note_lines):
        blocks = [("角色概况", [*overview, f"- 最近更新：{state['updated_at']}"]), ("活跃需求", task_lines), ("当前工作焦点", focus),
                  ("生效决定", decisions), ("风险与跨角色依赖", risks),
                  ("个人知识索引与候选", note_lines + preview)]
        return "# " + md(role["name"]) + "的工作记忆\n\n" + "\n\n".join(
            f"## {i}. {title}\n\n" + ("\n".join(rows) or "暂无") for i, (title, rows) in enumerate(blocks, 1)) + "\n"
    available = LIMIT - byte_count(render([], [])) - 24
    task_lines = slice_rows(table, max(0, available * 2 // 3), "list")
    note_lines = slice_rows(note_rows, max(0, available - byte_count("\n".join(task_lines))), "library-index")
    rendered = render(task_lines, note_lines)
    if previous_state is not None and (state["rendered_sha256"] != digest(rendered.encode())
                                       or dump(state) != previous_state):
        state["updated_at"] = now()
        rendered = render(task_lines, note_lines)
    require(byte_count(rendered) <= LIMIT, f"记忆超出 {byte_count(rendered) - LIMIT} 字节，请精简语义条目")
    entries = {**state["decisions"], **state["risks"]}
    sources = referenced_tasks(root, data, role, tasks, [row["ref"] for row in entries.values()])
    stale = [key for key, row in entries.items() if row["ref"].startswith("task:") and
             row["ref"][5:] in sources and sources[row["ref"][5:]].stage == 3]
    return rendered, {"candidates_total": len(queue), "candidates": queue[:3], "stale_hints": stale,
                      "quota": {"decisions": len(decisions), "risks": len(risks), "limit_bytes": LIMIT},
                      "library_issues": issues}


def initialize(root, data, role):
    state_path, doc = paths(root, role)
    state = initial_state()
    state["updated_at"] = read_json(state_path)["updated_at"] if state_path.exists() else now()
    rendered, _ = view(root, data, role, state, {})
    state["rendered_sha256"] = digest(rendered.encode())
    for path, content in ((state_path, dump(state)), (doc, rendered)):
        if path.exists():
            require(path.read_bytes() == content.encode(), f"建角重试遇到已修改的文件 {path}")
        else:
            write(path, content)
    return [state_path, doc]


def current(root, role):
    sp, doc = paths(root, role)
    raw, actual = sp.read_bytes(), doc.read_bytes()
    state = read_json(sp)
    require(state.get("format") == 1, "角色记忆状态格式无效")
    return state, digest(raw + b"\0" + actual), actual


def read(root, data, role):
    state, token, actual = current(root, role)
    pending = pending_file(root, role)
    job = read_json(pending) if pending.exists() else None
    if job:
        state = json.loads(job["state"])
    tasks = role_tasks(root, role, repair=False)
    rendered, stats = view(root, data, role, state, tasks)
    result = {"role": role["name"], "sha256": token, "content": rendered, "bytes": byte_count(rendered),
              "focus": state["focus"], "decisions": state["decisions"], "risks": state["risks"], **stats}
    if job:
        result["recovery"] = "先执行 memory-sync 恢复中断的记忆提交"
    if state["rendered_sha256"] != digest(actual) and not (job and job["before"][1] == digest(actual)):
        base = role_dir(root, role)
        if job:
            old = job["doc"]
            result["recovery"] = "中断后 Memory.md 已被手改，请按 manual_diff 合并并传 merge_sha256"
        else:
            revision = git(base, "log", "-1", "--format=%H", "--", STATE)
            old = git(base, "show", revision + ":" + DOC)
        result["manual_sha256"] = digest(actual)
        result["manual_diff"] = "\n".join(difflib.unified_diff(old.splitlines(), actual.decode("utf-8-sig").splitlines(),
                                                              fromfile="上次提交", tofile="当前原稿", lineterm=""))
    return result


def recover(root, role):
    pending = pending_file(root, role)
    if not pending.exists():
        return
    job = read_json(pending)
    for path, new, old in zip(paths(root, role), (job["state"], job["doc"]), job["before"], strict=True):
        raw = path.read_bytes()
        if raw != new.encode():
            require(digest(raw) == old, f"恢复时遇到额外的手工修改，请保留并合并 {path}")
            write(path, new)
    save(role_dir(root, role), paths(root, role), "Update working memory")
    pending.unlink()


def persist(root, role, state, rendered, token):
    state["rendered_sha256"] = digest(rendered.encode())
    before = [p.read_bytes() for p in paths(root, role)]
    require(digest(b"\0".join(before)) == token, "维护期间文件发生变化，请重新读取")
    after = [dump(state), rendered]
    if any(old != new.encode() for old, new in zip(before, after)):
        job = {"state": after[0], "doc": rendered, "before": [digest(b) for b in before]}
        write(pending_file(root, role), dump(job))
        recover(root, role)


def update(root, data, role, request=None, *, outcome=None):
    state, token, actual = current(root, role)
    pending = pending_file(root, role)
    if pending.exists():
        job = read_json(pending)
        if digest(actual) not in (job["before"][1], digest(job["doc"].encode())):
            require(request is not None and request.get("merge_sha256") == digest(actual) and
                    request.get("expected_sha256") == token, "中断后发现手改，请按 memory-read 的差异合并")
            state_path, _ = paths(root, role)
            require(digest(state_path.read_bytes()) in (job["before"][0], digest(job["state"].encode())),
                    "结构化状态也已被外部修改，请核对中断记录")
            state = json.loads(job["state"])
        else:
            recover(root, role)
            state, token, actual = current(root, role)
    tasks = role_tasks(root, role, repair=False)
    if request is not None:
        # Retrying the exact operation after a failed commit or lost response is harmless.
        signature = digest(dump(request).encode())
        if state.get("last_patch") == signature and state["rendered_sha256"] == digest(actual):
            return read(root, data, role)
        require(token == request.get("expected_sha256"), "记忆已变化，请重新 memory-read 后合并")
    if digest(actual) != state["rendered_sha256"]:
        require(request is not None and request.get("merge_sha256") == digest(actual),
                "Memory.md 有手改，先 memory-read 查看差异，合并后传 merge_sha256")
        backup = inside(root, ".at-state", "memory-originals", digest(actual) + ".md")
        atomic(backup, actual)
    previous = dump(state)
    if request is not None:
        require(not (request.keys() - {"role", "expected_sha256", "merge_sha256", "focus", "ops"}), "未知记忆更新字段")
        if "focus" in request:
            focus = request["focus"]
            require(isinstance(focus, dict) and (not focus or set(focus) == set(FOCUS)), "焦点须包含三个字段或为空对象")
            state["focus"] = {k: line(focus, k) for k in focus}
        operations = request.get("ops", [])
        require(isinstance(operations, list), "ops 应为数组")
        for op in operations:
            apply_op(root, data, role, tasks, state, op)
        if previous != dump(state):
            state["last_patch"] = signature
    if outcome:
        record_outcome(data, role, tasks, state, outcome)
    rendered, stats = view(root, data, role, state, tasks, previous_state=previous)
    persist(root, role, state, rendered, token)
    return {"role": role["name"], "sha256": current(root, role)[1], "bytes": byte_count(rendered), **stats}


def record_outcome(data, role, tasks, state, op):
    identifier = field(op, "id")
    require(identifier in candidates(tasks, state), f"未知候选 {identifier}")
    status = field(op, "status")
    require(status in ("published", "merged", "needs_evidence", "dismissed"), "无效候选评估结果")
    result = {"status": status, "reason": line(op, "reason")}
    if status in ("published", "merged"):
        result["path"] = field(op, "path")
        library.read(data, role, result)
    state["outcomes"][identifier] = result


def apply_op(root, data, role, tasks, state, op):
    require(isinstance(op, dict), "记忆操作应为对象")
    action = field(op, "op")
    if action == "queue_library":
        ref = field(op, "source")
        require(ref.startswith(("meeting:", "version:")), "需求候选请通过 note 或送验 move 随需求登记")
        check_ref(root, data, tasks, ref, milestone=True)
        if ref.startswith("version:"):
            ref = "version:" + version(ref[8:])
        row = candidate(ref, op)
        prior = state["candidates"].get(row["id"], {})
        row["version"] = version(ref[8:]) if ref.startswith("version:") else prior.get("version", data["current_version"])
        state["candidates"][row["id"]] = row
        return
    if action == "assess_candidate":
        record_outcome(data, role, tasks, state, op)
        return
    groups = {"upsert_decision": ("decisions", "D"), "retire_decision": ("decisions", "D"),
              "upsert_risk": ("risks", "R"), "resolve_risk": ("risks", "R")}
    require(action in groups, f"未知记忆操作 {action}")
    group, prefix = groups[action]
    items = state[group]
    key = op.get("id")
    if key is not None:
        require(isinstance(key, str) and key in items, f"未知条目 {key}")
    if action.startswith("upsert"):
        item = {"summary": line(op, "summary"), "ref": line(op, "ref")}
        sources = referenced_tasks(root, data, role, tasks, [item["ref"]])
        check_ref(root, data, sources, item["ref"], milestone=True)
        if key is None:
            key = f"{prefix}{state['next'][prefix]:02}"
            state["next"][prefix] += 1
        items[key] = item
    else:
        require(key in items, "移除条目需要现有 ID")
        del items[key]


def history(root, role, request):
    base = role_dir(root, role)
    if "version" in request:
        tag = "memory/" + version(field(request, "version"))
        return {"tag": tag, "content": git(base, "show", tag + ":" + DOC)}
    limit = request.get("limit", 5)
    require(type(limit) is int and 1 <= limit <= 50, "limit 应为 1–50")
    args = ["log", f"-{limit}", "--format=%H %s"]
    if "query" in request:
        args.extend(["-G" + re.escape(line(request, "query")), "--patch", "--unified=0"])
    history = git(base, *args, "--", DOC).encode()
    cap = 8 * 1024
    return {"history": history[:cap].decode("utf-8", "ignore"), "truncated": len(history) > cap}
