"""Locate filesystem registrations and detach only their discovery entries."""

import json
import os
from pathlib import Path
import re
import stat
import uuid

from catalogs import NAMES


def locations(host, cwd):
    home = Path.home()
    project = next((p for p in (cwd, *cwd.parents) if (p / ".git").exists()), cwd)
    codex = [Path(os.environ.get("CODEX_HOME") or home / ".codex") / "skills", home / ".agents/skills"]
    for parent in (cwd, *cwd.parents):
        codex.append(parent / ".agents/skills")
        if parent == project:
            break
    dsh = [project / ".dsh/skills", project / ".agents/skills",
           Path(os.environ.get("DSH_HOME") or home / ".dsh") / "skills",
           Path(os.environ.get("DSH_AGENTS_HOME") or home / ".agents") / "skills"]
    return (codex, dsh) if host == "codex" else (dsh, codex)


def is_link(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def source_checkout(path):
    return next((p for p in (path, *path.parents) if (p / "install.py").is_file()
                 and (p / "skills/at-init-team/scripts/at.py").is_file()), None)


def identity(path):
    content = path.read_text(encoding="utf-8-sig")
    header = re.match(r"\A---\n(.*?)\n---(?:\n|$)", content, re.S)
    match = header and re.search(r"""^name:\s*['"]?([\w-]+)['"]?\s*$""", header[1], re.M)
    name = match[1] if match else None
    if name not in NAMES:
        return name, False
    manifest = path.parent / ".agentteam-install.json"
    if path.name == "SKILL.md" and manifest.is_file():
        files = json.loads(manifest.read_text(encoding="utf-8-sig"))["files"]
        if name == path.parent.name and "SKILL.md" in files:
            return name, True
    heading = "# " + name.replace("at-", "AT_", 1).replace("-", "_")
    return name, heading in content.splitlines()


def direct_entries(root, flat):
    if root.is_dir():
        for item in root.iterdir():
            if item.is_dir():
                entry = item / "SKILL.md"
                if entry.is_file():
                    yield entry
            elif flat and item.suffix.lower() == ".md" and item.is_file():
                yield item


def find_entries(state, skills):
    if not skills:
        return []
    roots = [Path(r) for r in state["roots"]]
    entries = {p for r in roots for p in direct_entries(r, state["host"] == "dsh")}
    # Codex can return nested entries; only act inside confirmed discovery roots.
    for row in skills:
        p = Path(row["path"]) if row.get("path") else None
        if p and p.is_absolute() and p.name == "SKILL.md" and p.is_file() and inside_registration_roots(p, roots):
            entries.add(p)
    by_name = {}
    for path in entries:
        try:
            name, owned = identity(path)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if name in NAMES:
            by_name.setdefault(name, []).append((path, owned))
    found = []
    for row in skills:
        name, origin = row["name"], row.get("path")
        matches = by_name.get(name, [])
        if row.get("scope") in ("system", "admin", "plugin") or row.get("source") in ("runtime", "bundled") or (
                state["host"] == "dsh" and row.get("provider") not in (None, "filesystem")
                and row.get("source") not in ("custom", "project-dsh", "project-agents", "user-agents", "user-dsh")):
            matches = []
        elif origin and Path(origin).is_absolute():
            real = Path(origin).resolve()
            matches = [(p, owned) for p, owned in matches if p.resolve() == real]
        else:
            matches = []
        if not matches:
            found.append({"name": name, "source": origin or row.get("provider") or "宿主清单",
                          "action": "host", "reason": "核对宿主登记来源或补充实际扫描根，再解除该项注册"})
        for path, owned in matches:
            action, reason = "detach", ""
            if not owned:
                action, reason = "host", "同名入口的 AgentTeam 归属未确认"
            elif not inside_registration_roots(path, roots):
                action, reason = "host", "入口通过上级链接越过扫描目录；请解除注册来源"
            elif source_checkout(path) or source_checkout(path.resolve()):
                if not is_link(path) and not is_link(path.parent):
                    action, reason = "host", "宿主直接扫描源码；请解除对应扫描配置，保留下载仓库"
            found.append({"name": name, "source": str(path), "action": action, "reason": reason})
    return found


def link_or_file(path):
    if path.name == "SKILL.md" and is_link(path.parent):
        return path.parent
    return path


def inside_registration_roots(path, roots):
    target = link_or_file(path)
    return any(Path(os.path.abspath(target)).is_relative_to(r) and target.parent.resolve().is_relative_to(r.resolve())
               for r in roots)


def follows_link(path, wanted):
    """Check intermediate links as well as their final destination."""
    for _ in range(40):
        for prefix in (*reversed(path.parents), path):
            if not is_link(prefix):
                continue
            if prefix.parent.resolve() / prefix.name == wanted:
                return True
            dest = os.path.normpath(os.readlink(prefix))
            if os.name == "nt":
                dest = dest.removeprefix("\\\\?\\")
                if dest.startswith("UNC\\"):
                    dest = "\\\\" + dest[4:]
            path = prefix.parent / dest / path.relative_to(prefix)
            break
        else:
            return False
    raise ValueError(f"链接层级过多，请核对 {path}")


def shared_with(path, other_roots):
    target = link_or_file(path)
    location = target.parent.resolve() / target.name
    for other in other_roots:
        if location.is_relative_to(other.resolve()):
            return str(other)
        for alias in direct_entries(other, True):
            if alias.resolve() == path.resolve() and (not is_link(target) or follows_link(alias, location)):
                return str(alias)
    return None


def detach(path, name):
    current_name, owned = identity(path)
    if current_name != name or not owned:
        raise ValueError("注册入口在操作前发生变化，请重新盘点")
    target = link_or_file(path)
    if source_checkout(target.parent) or source_checkout(target.parent.resolve()):
        raise ValueError("此入口位于源码仓库；请从宿主解除扫描配置")
    if is_link(target):
        destination = str(target.resolve(strict=True))
        if target.is_symlink():
            target.unlink()
        elif target.is_dir() and getattr(target.lstat(), "st_reparse_tag", 0) == stat.IO_REPARSE_TAG_MOUNT_POINT:
            os.rmdir(target)  # Remove only the Windows junction.
        else:
            raise ValueError("不能安全识别此重解析点，请通过宿主解除注册")
        return {"link": str(target), "target": destination}
    if not target.is_file() or source_checkout(target.resolve()):
        raise ValueError("预期为源码仓库外的安装入口")
    backup = target.with_name(target.name + ".at-unregistered-" + uuid.uuid4().hex)
    target.rename(backup)
    return {"entry": str(target), "backup": str(backup)}
