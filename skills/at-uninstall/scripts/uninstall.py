"""Make a recoverable uninstall inventory, detach entries, and verify against the host."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

from catalogs import NAMES, read_view
from entries import detach, find_entries, inside_registration_roots, link_or_file, locations, shared_with


HERE = Path(__file__).resolve().parent
STATE = HERE / "run.json"


def write_json(path, data):
    with tempfile.NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", delete=False) as out:
        json.dump(data, out, ensure_ascii=False, indent=2)
    try:
        os.replace(out.name, path)
    finally:
        Path(out.name).unlink(missing_ok=True)


@contextmanager
def run_lock():
    with (HERE / "run.lock").open("a+b") as file:
        file.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield  # Closing also releases the lock after an exception or interruption.


def prepare(args):
    cwd = args.cwd.resolve(strict=True)
    if not cwd.is_dir() or (args.host == "dsh" and not args.session):
        raise ValueError("请指定原工作目录，DSH 还需指定当前会话 ID")
    roots, other = locations(args.host, cwd)
    roots = list(dict.fromkeys(p.absolute() for p in [*roots, *args.root, *args.codex_extra]))
    other = list(dict.fromkeys(p.absolute() for p in [*other, *args.other_root]))
    temp = Path(tempfile.gettempdir()).resolve()
    if any(temp.is_relative_to(p.resolve()) for p in roots + other):
        raise ValueError("请选择技能发现目录以外的 TEMP 目录")
    run = Path(tempfile.mkdtemp(prefix="at-uninstall-", dir=temp))
    for name in ("uninstall.py", "catalogs.py", "entries.py", "dsh-snapshot.mjs"):
        shutil.copyfile(HERE / name, run / name)
    state = {"host": args.host, "session": args.session or "", "cwd": str(cwd), "roots": list(map(str, roots)),
             "other": list(map(str, other)), "extra": [str(p.absolute()) for p in args.codex_extra],
             "challenge": uuid.uuid4().hex, "phase": "inventory", "names": list(NAMES), "socket": args.codex_socket,
             "host_home": str(roots[0]) if args.host == "codex" else str(Path(os.environ.get("DSH_HOME") or Path.home() / ".dsh").resolve()),
             "observed": {}, "pending": [], "changes": []}
    write_json(run / "run.json", state)
    return {"runner": str(run / "uninstall.py"), "challenge": state["challenge"], "names": list(NAMES)}


def fingerprint(path):
    return [str(path.resolve(strict=True)), str(link_or_file(path)), hashlib.sha256(path.read_bytes()).hexdigest()]


def inspect(state, args):
    state["roots"] = list(dict.fromkeys([*state["roots"], *(str(p.absolute()) for p in args.root)]))
    state["other"] = list(dict.fromkeys([*state["other"], *(str(p.absolute()) for p in args.other_root)]))
    for removed in args.removed_extra:
        state["extra"] = [p for p in state["extra"] if Path(p) != removed.absolute()]
        if not state["socket"]:
            state["live_evidence"] = True
    # Invalidate a previous mutation plan even if this observation fails.
    state["pending"] = []
    state["phase"] = "observe"
    write_json(STATE, state)
    try:
        view = read_view(state, args.snapshot)
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as error:
        view = {"complete": False, "skills": [], "errors": [str(error)]}
    try:
        entries = find_entries(state, view["skills"])
    except (OSError, ValueError, TypeError) as exc:
        entries = [{"name": row["name"], "source": row.get("path") or "宿主清单",
                    "action": "host", "reason": str(exc)} for row in view["skills"]]
    other_roots = list(map(Path, state["other"]))
    for entry in entries:
        if entry["action"] == "detach":
            path = Path(entry["source"])
            try:
                entry["fingerprint"] = fingerprint(path)
                entry["shared"] = shared_with(path, other_roots)
            except (OSError, ValueError) as exc:
                entry.update(action="host", reason=str(exc))
    rows = []
    for name in NAMES:
        sources = sorted({entry["source"] for entry in entries if entry["name"] == name})
        if sources:
            known = state["observed"].setdefault(name, [])
            known.extend(s for s in sources if s not in known)
            status = "仍有残留" if args.command == "verify" else "已注册"
        elif not view["complete"]:
            status = "未能验证"
        elif state["observed"].get(name):
            status = "已移除并验证"
        else:
            status = "原本未注册，已验证"
        rows.append({"name": name, "before": state["observed"].get(name, []), "after": sources, "status": status})
    done = view["complete"] and not entries
    if view["complete"]:
        state["pending"] = entries
        state["phase"] = "done" if done else "apply"
    state["challenge"] = uuid.uuid4().hex
    write_json(STATE, state)
    return {"host": state["host"], "cwd": state["cwd"], "session": state["session"],
            "verified": args.command == "verify", "done": done, "complete": view["complete"],
            "errors": view.get("errors"), "rows": rows,
            "entries": [{k: v for k, v in row.items() if k != "fingerprint"} for row in entries],
            "challenge": state["challenge"]}


def apply(state, args):
    if state["phase"] == "done":
        return {"changes": [], "message": "已完成；可再次 verify"}
    if state["phase"] != "apply":
        raise ValueError("请先取得原宿主完整的新清单，再处理登记入口")
    pending = state["pending"]
    others = any(row["name"] != "at-uninstall" for row in pending)
    state["phase"] = "observe"
    state["challenge"] = uuid.uuid4().hex
    write_json(STATE, state)
    changed, remaining = [], []
    allowed = {p.absolute() for p in args.allow_shared}
    handled = set()
    for row in pending:
        if row["name"] == "at-uninstall" and others:
            continue
        path = Path(row["source"])
        if row["action"] != "detach":
            remaining.append(row)
            continue
        if path in handled:
            continue
        handled.add(path)
        try:
            if not inside_registration_roots(path, list(map(Path, state["roots"]))) or fingerprint(path) != row["fingerprint"]:
                raise ValueError("入口已改变，请重新盘点")
            shared = shared_with(path, list(map(Path, state["other"])))
            if shared and path not in allowed:
                raise ValueError(f"入口与另一个宿主共享：{shared}")
            change = {"name": row["name"], **detach(path, row["name"])}
            state["changes"].append(change)
            write_json(STATE, state)
            changed.append(change)
        except (ValueError, OSError, KeyError) as exc:
            remaining.append({"name": row["name"], "source": str(path), "reason": str(exc)})
    return {"changes": changed, "remaining": remaining, "next": "verify", "challenge": state["challenge"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("prepare")
    start.add_argument("--host", choices=("codex", "dsh"), required=True)
    start.add_argument("--cwd", type=Path, required=True)
    start.add_argument("--session")
    start.add_argument("--root", type=Path, action="append", default=[])
    start.add_argument("--other-root", type=Path, action="append", default=[])
    start.add_argument("--codex-extra", type=Path, action="append", default=[])
    start.add_argument("--codex-socket", help="原活动 Codex App Server 的控制套接字")
    for name in ("inventory", "verify"):
        observe = sub.add_parser(name)
        observe.add_argument("--snapshot", type=Path)
        observe.add_argument("--root", type=Path, action="append", default=[])
        observe.add_argument("--other-root", type=Path, action="append", default=[])
        observe.add_argument("--removed-extra", type=Path, action="append", default=[])
    sub.add_parser("apply").add_argument("--allow-shared", action="append", type=Path, default=[])
    args = parser.parse_args()
    if args.command == "prepare":
        return prepare(args)
    if not STATE.is_file():
        raise ValueError("请从 prepare 返回的独立 runner 继续")
    with run_lock():
        state = json.loads(STATE.read_text(encoding="utf-8"))
        if state["host"] == "codex":
            current_home = locations("codex", Path(state["cwd"]))[0][0].absolute()
        else:
            current_home = Path(os.environ.get("DSH_HOME") or Path.home() / ".dsh").resolve()
        if current_home != Path(state["host_home"]):
            raise ValueError("当前宿主配置目录已改变，请在原配置环境中复查")
        return apply(state, args) if args.command == "apply" else inspect(state, args)


if __name__ == "__main__":
    try:
        result = main()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("complete") is False:
            sys.exit(2)
        if result.get("verified") and not result["done"]:
            sys.exit(1)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        sys.exit(str(exc))
