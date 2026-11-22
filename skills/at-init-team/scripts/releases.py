"""Check iteration evidence and commit a recoverable local formal publication."""

import json
import re
import tempfile
from datetime import datetime, timezone
from hashlib import file_digest
from pathlib import Path

import portable
import reports
import tasks
from core import (STAGES, Problem, digest, dump, field, git, git_result, inside, now, project,
                  read_json, require, require_repo_root, texts, write)
from release_html import render
from versions import formal_versions, history, order, pending_path, version


def instant(value):
    moment = datetime.fromisoformat(value)
    require(moment.tzinfo is not None, "时间需要带时区")
    return moment


def task_snapshot(root, data):
    rows = []
    for role in data["members"]:
        for task in tasks.role_tasks(root, role).values():
            spec = tasks.effective(task.spec, task.events)
            row = {"id": spec["id"], "title": spec["title"], "role": role["name"],
                   "stage": STAGES[task.stage], "version": spec.get("version")}
            if task.stage == 3:
                review = next((e for e in reversed(task.events) if e["type"] == "move"
                               and e["from"] == STAGES[2] and e["to"] == STAGES[3]), None)
                if review and review.get("actor") and review.get("time") and review.get("evidence"):
                    row["review"] = {"time": review["time"], "actor": review["actor"],
                                     "evidence": texts(review, "evidence")}
            rows.append(row)
    return rows


def check_artifacts(root, data, request, scope):
    items = request.get("artifacts")
    require(isinstance(items, list) and items, "请为本版本至少一条需求提供已核验的交付文件或 Git 提交")
    ids = {r["id"] for r in scope}
    verified = []
    for item in items:
        task = field(item, "task")
        require(task in ids, f"交付证据未对应本版本需求 {task}")
        require(("path" in item) != ("commit" in item), "每份交付证据应选择文件或提交")
        if "path" in item:
            path = inside(root, field(item, "path")).resolve()
            rel = path.relative_to(root).as_posix()
            parts = [p.casefold() for p in path.relative_to(root).parts]
            role_metadata = (len(parts) >= 2 and parts[0] in {r["dir"].casefold() for r in data["members"]}
                             and parts[1] in {"workspace", "agent.md", "memory.md", ".agent"})
            require(path.is_file() and path.stat().st_size and not {".git", ".at-state"}.intersection(parts)
                    and rel.casefold() != "at.json" and not role_metadata,
                    f"交付文件不存在、为空或属于管理记录 {rel}")
            verified.append({"task": task, "path": rel, "sha256": file_hash(path)})
        else:
            sha = field(item, "commit")
            require(re.fullmatch("[0-9a-fA-F]{7,64}", sha), "请提供 Git 提交 SHA")
            repo = inside(root, item.get("repo", data["team_repo"])).resolve()
            require_repo_root(repo)
            resolved = git(repo, "rev-parse", "--verify", sha + "^{commit}")
            require(repo not in {inside(root, r["dir"]).resolve() for r in data["members"]},
                    "角色管理记录的提交不能作为迭代交付")
            require(git(repo, "diff-tree", "--root", "-m", "--no-commit-id", "--name-only", "-r", resolved),
                    "空提交不能作为迭代交付")
            shared = inside(root, data["team_repo"])
            if git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir") == git(
                    shared, "rev-parse", "--path-format=absolute", "--git-common-dir"):
                require(git_result(shared, "merge-base", "--is-ancestor", resolved, "refs/heads/main").returncode == 0,
                        "团队交付提交尚未进入 main")
            verified.append({"task": task, "repo": repo.relative_to(root).as_posix(), "commit": resolved})
    return verified


def file_hash(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


KINDS = ("bin", "user", "dev")


def release_kind(request):
    kind = field(request, "kind")
    require(kind in KINDS, "请选择 bin（Windows 程序）、user（用户指南）或 dev（甲方总览）")
    return kind


def recorded_kind(record):
    # Earlier HTML reports carried an audience. They remain accessible at their actual path.
    return record.get("kind") or {"owner": "dev", "player": "user"}.get(record.get("audience"))


def latest_for(records, kind, target):
    return next((r for r in reversed(records) if recorded_kind(r) == kind and r["version"] == target), None)


def summary(row):
    if not row:
        return None
    return {"kind": recorded_kind(row), "version": row["version"], "revision": row.get("revision", 1),
            "time": row["time"], "entry": row["entry"]}


def check(root, request):
    data = project(root)
    target = version(request.get("version", data.get("current_version")))
    kind = release_kind(request)
    records = history(root)
    seals = formal_versions(records)
    last = seals[max(seals, key=order)] if seals else None
    seal = seals.get(target)
    latest = latest_for(records, kind, target)
    revision = latest.get("revision", 1) + 1 if latest else 1
    rows = task_snapshot(root, data)
    scope = [r for r in rows if r["version"] == target]
    baseline = last
    if kind == "dev":
        baseline = next((r for r in reversed(records) if recorded_kind(r) == "dev" and
                         order(r["version"]) <= order(target)), None)
    changes = [r for r in rows if r.get("review") and r["version"] and order(r["version"]) <= order(target)
               and (not baseline or instant(r["review"]["time"]) > instant(baseline.get("as_of", baseline["time"])))]
    changes.sort(key=lambda r: (order(r["version"]), r["review"]["time"], r["id"]))
    issues = []
    verified = []
    counts = {s: sum(r["stage"] == s for r in rows) for s in STAGES}
    baseline_summary = summary(baseline)
    if kind != "dev" and seal and seal.get("scope"):
        scope, changes, verified = seal["scope"], seal["changes"], seal["artifacts"]
        baseline_summary = seal["baseline"]
    elif kind != "dev":
        if last and order(target) <= order(last["version"]):
            issues.append(f"目标版本 {target} 须高于上次正式发布 {last['version']}")
        if not scope:
            issues.append(f"{target} 尚无已绑定需求")
        issues.extend(f"{r['id']} {r['title']}（{r['stage']}）缺少归档验收证据" for r in scope if not r.get("review"))
        if scope and not any(r["version"] == target for r in changes):
            issues.append("本版本缺少自上次正式发布以来新通过验收的需求")
        try:
            verified = check_artifacts(root, data, request, scope)
        except (Problem, OSError) as exc:
            issues.append(str(exc))
    pending = None
    receipt_path = pending_path(root) / "receipt.json"
    if receipt_path.is_file():
        row = read_json(receipt_path)
        if not any(r["entry"] == row["entry"] for r in records):
            pending = {"kind": recorded_kind(row), "version": row["version"], "request_id": row.get("request_id")}
            if (pending["kind"], pending["version"]) != (kind, target):
                issues.append(f"请先恢复未完成的发布 {pending['kind']} {pending['version']}")
    if not pending and inside(root, "publish", kind, target, f"r{revision}").exists():
        issues.append(f"{kind}/{target}/r{revision} 已被其他内容占用")
    return {"project": data["name"], "kind": kind, "version": target, "revision": revision,
            "as_of": now(), "latest": summary(latest), "pending": pending, "baseline": baseline_summary,
            "ready": not issues, "issues": issues, "scope": scope, "changes": changes, "artifacts": verified,
            "unversioned": [r for r in rows if not r["version"]], "stages": counts}


def import_baseline(root, request, actor):
    require(request.get("user_confirmed") is True, "仅可导入用户明确指定的历史正式报告")
    target = version(field(request, "version"))
    entry = inside(inside(root, "publish"), field(request, "entry")).resolve()
    require(entry.is_file() and entry.suffix.lower() == ".html" and entry.stat().st_size,
            "请选择 publish 中已有的正式报告 HTML 入口")
    stamp = instant(field(request, "time")).astimezone(timezone.utc)
    require(stamp <= instant(now()), "历史发布时间不能晚于当前时间")
    row = {"version": target, "time": stamp.isoformat(), "actor": actor, "imported": True,
           "entry": entry.relative_to(root).as_posix(), "sha256": file_hash(entry)}
    past = history(root)
    if row in past:
        return row
    require(not formal_versions(past) and not pending_path(root).exists(), "仅能在首次正式发布前导入一个基线")
    write(root / ".at-state/releases.json", dump([*past, row]))
    return row


def complete_legacy(root, pending, receipt, past):
    public = inside(root, "publish")
    target = receipt["version"]
    assets, entry = inside(public, target), inside(public, target + ".html")
    staged_assets, staged_entry = pending / target, pending / "index.html"
    components = [(staged_assets, assets), (staged_entry, entry)]
    for source, dest in components:
        require(source.exists() != dest.exists(), f"发布文件缺失或目标已被占用 {dest}")
    bundle = staged_assets if staged_assets.exists() else assets
    page = staged_entry if staged_entry.exists() else entry
    require(bundle.is_dir() and reports.bundle_files(bundle) == receipt["asset_hashes"] and
            page.is_file() and file_hash(page) == receipt["entry_sha256"], "发布文件与已核验的快照不符")
    for source, dest in components:
        if source.exists():
            source.rename(dest)
    record = {**receipt, "time": now()}
    write(root / ".at-state/releases.json", dump([*past, record]))
    return record


def saved_result(root, row, existing):
    entry = inside(root, row["entry"])
    if "files" in row:
        bundle = inside(root, row["bundle"])
        require(entry.is_file() and portable.distribution_files(bundle) == row["files"],
                f"交付物丢失或已修改 {bundle}")
    else:
        require(entry.is_file() and file_hash(entry) == row.get("entry_sha256", row.get("sha256")),
                f"已发布的入口丢失或已修改 {entry}")
        if "assets" in row:
            bundle = inside(root, row["assets"])
            require(bundle.is_dir() and reports.bundle_files(bundle) == row["asset_hashes"], f"素材丢失或已修改 {bundle}")
        else:
            bundle = entry.parent
    return {**summary(row), "entry": str(entry), "bundle": str(bundle), "existing": existing,
            "verification": row.get("verification")}


def content_fingerprint(request):
    routing = {"kind", "version", "actor", "actor_confirmed", "request_id"}
    payload = {k: v for k, v in request.items() if k not in routing}
    return digest(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()) if payload else None


def check_retry(row, fingerprint):
    require(not fingerprint or not row.get("request_sha256") or row["request_sha256"] == fingerprint,
            "相同 request_id 的发布内容不同，请使用原输入重试")


def finish(root, pending, receipt, past):
    if "files" not in receipt:
        row = complete_legacy(root, pending, receipt, past)
    else:
        staging = pending / "bundle"
        final = inside(root, receipt["bundle"])
        require(staging.is_dir() != final.exists(), f"发布目录缺失或目标已被占用 {final}")
        require(portable.distribution_files(staging if staging.exists() else final) == receipt["files"],
                "待恢复的发布文件与快照不符")
        if staging.exists():
            final.parent.mkdir(parents=True, exist_ok=True)
            staging.rename(final)
        row = {**receipt, "time": now()}
        write(inside(root, ".at-state", "releases.json"), dump([*past, row]))
    (pending / "receipt.json").unlink()
    pending.rmdir()
    return saved_result(root, row, False)


def release(root, request, actor):
    target = version(request.get("version", project(root).get("current_version")))
    kind = release_kind(request)
    past = history(root)
    pending = pending_path(root)
    receipt_path = pending / "receipt.json"
    request_id = request.get("request_id")
    fingerprint = content_fingerprint(request)
    if receipt_path.is_file():
        row = read_json(receipt_path)
        if any(r["entry"] == row["entry"] for r in past):
            receipt_path.unlink()
        else:
            require((recorded_kind(row), row["version"], row.get("request_id")) == (kind, target, request_id),
                    f"请先重试未完成的 {recorded_kind(row)} {row['version']}（{row.get('request_id')}）")
            check_retry(row, fingerprint)
            return finish(root, pending, row, past)
    if pending.exists():
        pending.rmdir()
    if request_id is not None:
        require(isinstance(request_id, str) and request_id.strip(), "request_id 应为非空文本")
        prior = next((r for r in past if r.get("request_id") == request_id), None)
        if prior:
            require((prior["kind"], prior["version"]) == (kind, target), "request_id 已用于其他发布")
            check_retry(prior, fingerprint)
            return saved_result(root, prior, True)
    latest = latest_for(past, kind, target)
    action = request.get("action")
    require(action in (None, "reuse", "new"), "action 应为 reuse 或 new")
    if action == "reuse":
        require(latest, "该类别和版本尚无可沿用的成果")
        require(request.get("previous_revision", latest.get("revision", 1)) == latest.get("revision", 1),
                "最新修订已变化，请重新展示已有成果并确认")
        return saved_result(root, latest, True)
    if latest and action is None:
        return {"needs_choice": True, "latest": summary(latest)}
    if latest or "previous_revision" in request:
        expected = latest.get("revision", 1) if latest else 0
        require(type(request.get("previous_revision")) is int and request["previous_revision"] == expected,
                "最新修订已变化，请重新展示已有成果并确认")
    field(request, "request_id")
    result = check(root, request)
    require(result["ready"], "\n".join(result["issues"]))
    folder = f"publish/{kind}/{target}/r{result['revision']}"
    with tempfile.TemporaryDirectory(dir=pending.parent) as temp:
        prepared = Path(temp) / "publication"
        staging = prepared / "bundle"
        prepared.mkdir()
        receipt = {k: result[k] for k in ("kind", "version", "revision", "as_of", "baseline", "scope",
                                          "changes", "artifacts", "stages")}
        if kind == "bin":
            entry, receipt["verification"] = portable.package(root, staging, request, target)
            files = portable.distribution_files(staging)
        else:
            render(staging, root, result, request)
            files = reports.check_bundle(staging)
            entry = "index.html"
        receipt.update(actor=actor, request_id=request_id, request_sha256=fingerprint,
                       bundle=folder, entry=folder + "/" + entry, files=files)
        write(prepared / "receipt.json", dump(receipt))
        prepared.rename(pending)
    return finish(root, pending, receipt, past)
