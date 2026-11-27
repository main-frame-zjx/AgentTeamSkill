"""Knowledge candidates and verifiable references shared by memory and the personal library."""

import re
from pathlib import Path

from core import digest, field, git, inside, require
from versions import formal_versions, history, version


KINDS = {"system-design": "系统设计", "reusable-pattern": "可复用方案"}


def line(data, key):
    value = field(data, key)
    require(len(value.splitlines()) == 1 and "\x00" not in value, f"{key} 应为单行")
    return value


def relative_file(base, name):
    path = Path(name.replace("\\", "/"))
    require(not path.is_absolute() and not path.drive and not path.root and
            all(p.casefold() not in ("..", ".git", ".at-state") for p in path.parts),
            f"需要目录内的相对文件路径 {name}")
    file = inside(base, path)
    require(file.is_file(), f"引用文件不存在 {name}")
    return file


def check_ref(root, data, tasks, ref, *, milestone=False):
    require(isinstance(ref, str), "证据引用应为文本")
    kind, sep, value = ref.partition(":")
    require(sep and value, f"引用需要类型前缀 {ref}")
    if kind == "task":
        require(value in tasks, f"项目没有需求 {value}")
    elif kind == "meeting":
        folder = "meeting-notes" if Path(data["team_repo"]).name.casefold() == "meetings" else "meetings"
        require(value.startswith(f"public/{folder}/") and value.endswith(".md"), f"无效会议纪要 {value}")
        relative_file(root, value)
    elif kind == "file":
        relative_file(root, value)
    elif kind == "code":
        relative_file(inside(root, data["team_repo"]), value)
    elif kind == "commit":
        require(re.fullmatch(r"[a-fA-F0-9]{7,64}", value), "请使用 Git 提交 SHA")
        git(inside(root, data["team_repo"]), "rev-parse", "--verify", value + "^{commit}")
    elif kind == "version" and milestone:
        target = version(value)
        require(target == data["current_version"] or target in data.get("version_goals", {})
                or target in formal_versions(history(root)),
                f"未登记的里程碑版本 {value}")
    else:
        raise ValueError(f"不支持的引用类型 {ref}")


def candidate(source, raw):
    require(isinstance(raw, dict), "候选须为对象")
    key = line(raw, "key")
    kind = field(raw, "kind")
    require(kind in KINDS, f"未知候选类型 {kind}")
    topic = line(raw, "topic")
    require(len(topic.encode()) <= 240, "候选主题超过 240 字节")
    identifier = "C-" + digest((source + "\n" + key).encode())[:20]
    return {"id": identifier, "source": source, "key": key, "kind": kind, "topic": topic}


def task_candidates(task):
    result = {}
    for event in task.events:
        for item in event.get("candidates", []):
            result[item["id"]] = item
    return result


def candidates(tasks, state):
    rows = dict(state["candidates"])
    for task in tasks.values():
        rows.update(task_candidates(task))
    return {key: {**row, **state["outcomes"].get(key, {"status": "pending"})}
            for key, row in rows.items()}
