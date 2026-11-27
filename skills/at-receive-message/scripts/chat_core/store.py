"""The durable journal is the commit point. Readers overlay it without recovering files."""
from contextlib import contextmanager
from pathlib import Path
import re

from core import dump, inside, lock, now, read_json, require, write

FORMAT = "agent-team/chat-v1"
GROUP_FORMAT = "agent-team/chat-group-v1"
PRIORITY = {"review_rejected": 0, "review_request": 1, "review_feedback": 2, "collab_request": 2, "info_sync": 3}
GROUP_ID = re.compile(r"(?:task:AT-[a-f0-9]{32}|topic:[a-z0-9][a-z0-9-]{0,47})")


def directory(root, data):
    name = "at-chat" if Path(data["team_repo"]).name.casefold() == "chat" else "chat"
    return inside(root, "public", name)


def filename(group_id):
    require(isinstance(group_id, str) and GROUP_ID.fullmatch(group_id), "无效群组编号")
    return group_id.replace(":", "__") + ".json"


def empty_meta(data):
    return {"format": FORMAT, "project_id": data["id"], "next_seq": 1,
            "updated_at": None, "revision": 0, "groups": []}


def initialize(root, data):
    base = directory(root, data)
    (base / "groups").mkdir(parents=True)
    write(base / "meta.json", dump({**empty_meta(data), "updated_at": now()}))


def check_meta(meta, project_id):
    require(isinstance(project_id, str) and project_id.strip() and isinstance(meta, dict)
            and meta.get("format") == FORMAT and meta.get("project_id") == project_id, "通讯库与当前项目标识不符")
    require(type(meta["next_seq"]) is int and meta["next_seq"] > 0 and isinstance(meta["groups"], list),
            "通讯索引损坏")
    seen = set()
    for item in meta["groups"]:
        gid = item["group_id"]
        require(item["file"] == filename(gid) and gid not in seen, "通讯群索引损坏")
        seen.add(gid)


def check_group(group, gid, next_seq):
    require(group["format"] == GROUP_FORMAT and group["group_id"] == gid and
            isinstance(group["messages"], list), "群组格式或编号异常")
    require(isinstance(group["title"], str) and group["kind"] == gid.split(":", 1)[0]
            and group["task_id"] == (gid[5:] if gid.startswith("task:") else None), "群组元信息异常")
    previous = 0
    for msg in group["messages"]:
        seq = msg["seq"]
        require(type(seq) is int and previous < seq < next_seq, "消息序号须为递增正整数且小于 next_seq")
        previous = seq
        require(msg["group_id"] == gid and msg["kind"] in PRIORITY and msg["id"] == f"MSG-{msg['seq']:06d}"
                and isinstance(msg["to"], list) and msg["to"] and isinstance(msg["recipients"], dict)
                and set(msg["to"]) == set(msg["recipients"]) and isinstance(msg["body"], str)
                and all(isinstance(msg[k], str) for k in ("sender", "sender_model", "created_at", "model_family", "idempotency_key"))
                and msg["overall_status"] in ("handled", "pending", "partial") and "reply_to" in msg
                and isinstance(msg["refs"], list) and all(isinstance(ref["path"], str) for ref in msg["refs"]) and all(r["status"] in ("handled", "pending")
                for r in msg["recipients"].values()), "群消息结构异常")
        states = {r["status"] for r in msg["recipients"].values()}
        require(msg["overall_status"] == (next(iter(states)) if len(states) == 1 else "partial"), "群消息状态不一致")


class Store:
    def __init__(self, root, data, writing):
        self.root = root
        self.base = directory(root, data)
        self.meta_path = inside(root, self.base, "meta.json")
        self.journal = inside(root, ".at-state", "chat-transaction.json")
        self.groups = {}
        self.dirty = set()
        self.errors = {}
        pending = None
        if self.journal.exists():
            pending = read_json(self.journal)
            require(isinstance(pending, dict) and isinstance(pending.get("meta"), dict)
                    and isinstance(pending.get("groups"), dict), "通讯事务日志损坏")
        self.initialized = pending is not None or self.meta_path.exists()
        if self.initialized:
            self.meta = pending["meta"] if pending is not None else read_json(self.meta_path)
        else:
            require(not self.base.exists() or all(p.name == "groups" and p.is_dir() and not any(p.iterdir())
                                                  for p in self.base.iterdir()),
                    f"{self.meta_path.relative_to(root).as_posix()} 缺失，通讯目录已有数据，请核查索引")
            self.meta = empty_meta(data)
        self.warnings = []
        check_meta(self.meta, data["id"])
        overlay = {}
        if pending is not None:
            overlay = pending["groups"]
            ids = {row["group_id"] for row in self.meta["groups"]}
            require(isinstance(overlay, dict) and overlay.keys() <= ids, "通讯事务索引损坏")
            for gid, group in overlay.items():
                check_group(group, gid, self.meta["next_seq"])
        self.sequence_owners = {}
        ambiguous = set()
        for row in self.meta["groups"]:
            gid = row["group_id"]
            try:
                group = overlay[gid] if gid in overlay else read_json(self.group_path(gid))
                # Even a quarantined group may claim a message ID used by a healthy group.
                if isinstance(group, dict) and isinstance(group.get("messages"), list):
                    for msg in group["messages"]:
                        seq = msg.get("seq") if isinstance(msg, dict) else None
                        if type(seq) is int and seq > 0:
                            owner = self.sequence_owners.setdefault(seq, gid)
                            if owner != gid:
                                ambiguous.update((owner, gid))
                check_group(group, gid, self.meta["next_seq"])
                self.groups[gid] = group
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                detail = exc.strerror if isinstance(exc, OSError) else str(exc)
                relative = (self.base / "groups" / filename(gid)).relative_to(root).as_posix()
                detail = detail.replace(str(root) + chr(92), "").replace(str(root) + "/", "").replace(chr(92), "/")
                self.errors[gid] = f"{relative}: {detail}"
        for gid in sorted(ambiguous):
            self.errors[gid] = f"{self.group_path(gid).relative_to(root).as_posix()}: 跨群消息序号重复"
            self.groups.pop(gid, None)
        if pending is not None and writing:
            require(not (overlay.keys() & self.errors.keys()), "通讯事务与群记录冲突，请先核查事务日志")
            self.materialize(pending)
        self.warnings.extend(self.errors.values())

    def take_sequence(self):
        seq = self.meta["next_seq"]
        require(seq not in self.sequence_owners, f"通讯索引的 next_seq {seq} 已被群文件使用，请核查索引")
        self.meta["next_seq"] += 1
        return seq

    def group_path(self, gid):
        return inside(self.root, self.base, "groups", filename(gid))

    def materialize(self, transaction):
        for gid, group in transaction["groups"].items():
            write(self.group_path(gid), dump(group))
        write(self.meta_path, dump(transaction["meta"]))
        self.journal.unlink()

    def commit(self):
        if not self.dirty:
            return
        self.meta["updated_at"] = now()
        self.meta["revision"] = self.meta.get("revision", 0) + 1
        rows = {r["group_id"]: r for r in self.meta["groups"]}
        for gid in self.dirty:
            group = self.groups[gid]
            row = {k: group[k] for k in ("group_id", "kind", "task_id", "title", "created_at", "archived")}
            last = group["messages"][-1] if group["messages"] else None
            rows[gid] = {**row, "file": filename(gid), "last_message_at": last and last["created_at"]}
        self.meta["groups"] = [rows[k] for k in sorted(rows)]
        transaction = {"meta": self.meta, "groups": {gid: self.groups[gid] for gid in sorted(self.dirty)}}
        write(self.journal, dump(transaction))
        self.materialize(transaction)


@contextmanager
def opened(root, data, writing=False):
    path = inside(root, ".at-state", "chat.lock")
    if not writing and not path.exists():
        # No writer has yet started. Recheck after taking the snapshot to handle a racing first send.
        try:
            initial = Store(root, data, False)
        except OSError:
            if not path.exists():
                raise
        else:
            if not path.exists():
                yield initial
                return
    if writing:
        path.parent.mkdir(exist_ok=True)
    with lock(path, wait=30):
        store = Store(root, data, writing)
        yield store
        if writing:
            store.commit()
