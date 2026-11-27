"""Personal learning notes, their project navigation and offline checks."""

import json
import re
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from core import digest, field, inside, require, segment, texts, write
from learning import KINDS, check_ref, line
from tasks import referenced_tasks, role_tasks
from versions import version


NAV = "00-项目学习导航.md"
LEVELS = ("入门", "进阶", "专题")
MIN_BODY = 300
LIMIT = 12 * 1024
WIKI = re.compile(r"\[\[([^\[\]\r\n]+)\]\]")
COMMON = (("problem", "要解决的问题"), ("conclusion", "结论"))
BY_KIND = {"system-design": (("design", "设计与结构"), ("tradeoffs", "方案取舍")),
           "reusable-pattern": (("steps", "复用步骤"), ("verification", "验证方法"))}


def project_folder(data):
    vault = Path(data["vault"])
    require(vault.is_dir(), f"无法访问 Obsidian 库 {vault}")
    path = inside(vault, segment(data["name"]))
    require(path.resolve() == path, f"项目笔记目录已重定向 {path}")
    return path


def folder(data, role):
    path = inside(project_folder(data), segment(role["dir"]))
    require(path.resolve() == path, f"个人笔记目录已重定向 {path}")
    return path


def note_path(base, name):
    require("`" not in name, f"笔记路径不能含反引号 {name}")
    parts = name.replace("\\", "/").split("/")
    require(len(parts) == 2 and parts[0] in KINDS.values() and parts[1].endswith(".md"),
            "笔记路径应为 系统设计/标题.md 或 可复用方案/标题.md")
    return inside(base, *[segment(p) for p in parts])


def property_value(value):
    """Read the scalar and list forms used by Obsidian Properties."""
    value = value.strip()
    if value.startswith('"') or value == "[]" or (value.startswith("[") and not value.startswith("[[")):
        try:
            return json.loads(value)
        except ValueError:
            require(value.startswith("[") and value.endswith("]"), "无效属性值 " + value)
            return [property_value(v) for v in value[1:-1].split(",")]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def properties(stream, path):
    require(stream.readline(16).decode("utf-8-sig").rstrip("\r\n") == "---", f"笔记缺少规范元数据 {path.name}")
    meta = {}
    key = None
    while True:
        raw_line = stream.readline(LIMIT + 1)
        require(raw_line and stream.tell() <= LIMIT, f"笔记属性缺少结束标记或超过上限 {path.name}")
        row = raw_line.decode().strip()
        if row == "---":
            break
        if not row or row.startswith("#"):
            continue
        if row.startswith("- "):
            require(isinstance(meta.get(key), list), f"数组属性无效 {row}")
            meta[key].append(property_value(row[2:]))
        else:
            key, mark, value = row.partition(":")
            require(mark and key not in meta, f"笔记属性无效 {row}")
            meta[key] = property_value(value) if value.strip() else []
    require(meta.get("type") in KINDS and
            meta.get("difficulty") in LEVELS and meta.get("status") in ("active", "superseded"),
            f"无效的笔记分类、难度或状态 {path.name}")
    for k in ("title", "summary", "role", "version"):
        line(meta, k)
    for k in ("tags", "prerequisites"):
        texts(meta, k, allow_empty=True)
    texts(meta, "evidence")
    version(meta["version"])
    if meta["status"] == "superseded":
        line(meta, "replacement")
    return meta


def scan(data, roles):
    notes, issues = [], []
    for role in roles:
        base = folder(data, role)
        if not base.is_dir():
            issues.append({"path": role["dir"], "error": "角色笔记库目录缺失", "kind": "missing_directory"})
            continue
        for category in KINDS.values():
            directory = inside(base, category)
            if not directory.is_dir():
                issues.append({"path": f"{role['dir']}/{category}", "error": "笔记分类目录缺失", "kind": "missing_directory"})
                continue
            for path in sorted(directory.glob("*.md")):
                rel = path.relative_to(base).as_posix()
                try:
                    with note_path(base, rel).open("rb") as stream:
                        meta = properties(stream, path)
                    require(meta["role"] == role["name"] and meta["title"] == path.stem and
                            KINDS[meta["type"]] == category, "文件位置与标题、类型或角色不符")
                    notes.append({**meta, "path": rel, "directory": role["dir"]})
                except (ValueError, KeyError, OSError, TypeError) as exc:
                    issues.append({"path": f"{role['dir']}/{rel}", "error": str(exc)})
    return notes, issues


def read(data, role, request):
    name = field(request, "path")
    path = note_path(folder(data, role), name)
    raw = path.read_bytes()
    stream = BytesIO(raw)
    meta = properties(stream, path)
    return {"path": name, "meta": meta, "body": stream.read().decode().replace("\r\n", "\n"),
            "sha256": digest(raw), "bytes": len(raw)}


def link_targets(data, notes):
    targets = defaultdict(set)
    for note in notes:
        path = f"{data['name']}/{note['directory']}/{note['path'][:-3]}"
        for alias in (path, note["path"][:-3], note["title"]):
            targets[alias].add(path)
    return targets


def link_issues(meta, body, targets):
    links = set(WIKI.findall(body))
    for raw in [*meta["prerequisites"], *([meta["replacement"]] if "replacement" in meta else [])]:
        match = WIKI.fullmatch(raw)
        if not match or not match[1].split("|")[0].split("#")[0].strip():
            yield f"需要指向笔记的双链 {raw}"
        else:
            links.add(match[1])
    for link in sorted(links):
        note, pipe, alias = link.partition("|")
        if pipe and (not alias.strip() or "|" in alias):
            yield f"无效双链 [[{link}]]"
            continue
        target = note.split("#", 1)[0].removesuffix(".md")
        if target and len(targets.get(target, ())) != 1:
            yield f"链接目标缺失或重名 [[{link}]]"


def prepare(root, data, role, request, tasks, notes):
    kind, title = field(request, "kind"), segment(line(request, "title"))
    require(kind in KINDS and not re.search(r"[\[\]#^|]", title), "无效的学习笔记类型或标题")
    meta_in, sections = request.get("meta"), request.get("sections")
    require(isinstance(meta_in, dict) and isinstance(sections, dict), "需要 meta 与 sections 对象")
    admission = request.get("admission")
    require(isinstance(admission, dict), "需要说明内容价值与可核实证据")
    field(admission, "reusable_or_complete")
    field(admission, "beginner_value")
    evidence = texts(admission, "evidence_refs")
    sources = referenced_tasks(root, data, role, tasks, evidence)
    for ref in evidence:
        check_ref(root, data, sources, ref)
    status = meta_in.get("status", "active")
    require(status in ("active", "superseded"), "无效笔记状态")
    difficulty = field(meta_in, "difficulty")
    require(difficulty in LEVELS, "难度应为入门、进阶或专题")
    meta = {"title": title, "type": kind, "role": role["name"],
            "version": version(meta_in.get("version", data["current_version"])), "difficulty": difficulty,
            "status": status, "summary": line(meta_in, "summary"), "evidence": evidence}
    for k in ("tags", "prerequisites"):
        meta[k] = texts(meta_in, k, True) if k in meta_in else []
    if status == "superseded":
        meta["replacement"] = line(meta_in, "replacement")
    else:
        require("replacement" not in meta_in, "仅被替代的笔记可设置 replacement")
    body = [f"# {title}", "> " + meta["summary"]]
    body_bytes = 0
    for key, heading in (*COMMON, *BY_KIND[kind], ("boundaries", "适用边界与避坑")):
        section = field(sections, key)
        for row in section.splitlines():
            require(not re.match(r"^ {0,3}#{1,2}(?:\s|$)", row), f"章节 {key} 中只允许三级及以下标题")
            if not re.match(r"^ {0,3}#{3,6}(?:\s|$)", row):
                body_bytes += len("".join(row.split()).encode())
        body.extend(["## " + heading, section])
    require(body_bytes >= MIN_BODY, f"必填章节正文仅 {body_bytes} 字节，至少需要 {MIN_BODY} 字节")
    targets = link_targets(data, notes)
    relative = f"{KINDS[kind]}/{title}"
    # Adding a namesake makes an existing short link ambiguous as soon as the note is saved.
    for alias in (title, relative):
        if alias in targets:
            targets[alias].add(f"{data['name']}/{role['dir']}/{relative}")
    problems = list(link_issues(meta, "\n\n".join(body), targets))
    require(not problems, "；".join(problems))
    body.extend(["## 验证证据", "\n".join("- " + ref for ref in evidence)])
    if meta["prerequisites"]:
        body.extend(["## 前置阅读", "\n".join("- " + link for link in meta["prerequisites"])])
    if status == "superseded":
        body.extend(["## 后续方案", meta["replacement"]])
    header = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items())
    content = f"---\n{header}\n---\n\n" + "\n\n".join(body) + "\n"
    size = len(content.encode())
    require(size <= LIMIT, f"笔记超出 {size - LIMIT} 字节，请精简或拆分")
    archived = {ref[5:] for ref in evidence if ref.startswith("task:") and sources[ref[5:]].stage == 3}
    return content, archived


def check_write(path, request, content):
    prior = path.read_bytes() if path.exists() else None
    expected = digest(prior) if prior is not None else None
    require("expected_sha256" in request, "请提供 expected_sha256，新笔记传 null")
    if prior != content.encode():
        require(request["expected_sha256"] == expected, "笔记已变化，请重读合并")
        return True
    return False


def navigation(data, notes):
    path = inside(project_folder(data), NAV)
    marker = f"<!-- AgentTeam: learning navigation v1 {data['id']} -->"
    if path.exists():
        prior = path.read_text(encoding="utf-8-sig")
        require(marker in prior.splitlines()[:2], f"导航位置已被其他文档占用 {path}")
    rows = [marker, "# " + data["name"] + " · 项目学习导航"]
    for level in LEVELS:
        group = sorted((n for n in notes if n["difficulty"] == level and n["status"] == "active"),
                       key=lambda n: (n["title"], n["directory"], n["path"]))
        if group:
            rows.append("## " + level)
            for n in group:
                target = f"{data['name']}/{n['directory']}/{n['path'][:-3]}"
                link = f"[[{target}|{n['title']}]]"
                if re.search(r"[\[\]#^|]", target):
                    relative = quote(f"{n['directory']}/{n['path']}", safe="/")
                    link = f"[{n['title']}]({relative})"
                rows.append(f"- {link} · {n['role']} · {n['summary']}")
    content = "\n\n".join(rows) + "\n"
    if not path.exists() or path.read_bytes() != content.encode():
        write(path, content)
    return str(path)


def rebuild(data):
    notes, issues = scan(data, data["members"])
    errors = [issue for issue in issues if issue.get("kind") != "missing_directory"]
    require(not errors, f"请先修复笔记元数据再重建导航 {errors}")
    return navigation(data, notes)


def lint(root, data, request):
    notes, issues = scan(data, data["members"])
    targets = link_targets(data, notes)
    titles = defaultdict(list)
    for n in notes:
        titles[n["title"].casefold()].append(f"{data['name']}/{n['directory']}/{n['path'][:-3]}")
    for role in data["members"]:
        tasks = role_tasks(root, role, repair=False)
        for n in (n for n in notes if n["role"] == role["name"]):
            ref_path = f"{role['dir']}/{n['path']}"
            try:
                note = read(data, role, n)
            except (ValueError, OSError) as exc:
                issues.append({"path": ref_path, "error": str(exc)})
                continue
            if note["bytes"] > LIMIT:
                issues.append({"path": ref_path, "error": f"超过 {LIMIT} 字节"})
            sources = referenced_tasks(root, data, role, tasks, n["evidence"])
            for ref in n["evidence"]:
                try:
                    check_ref(root, data, sources, ref)
                except (ValueError, OSError) as exc:
                    issues.append({"path": ref_path, "error": str(exc)})
            issues.extend({"path": ref_path, "error": error} for error in link_issues(n, note["body"], targets))
    result = {"notes": len(notes), "issues": issues,
              "duplicate_titles": [paths for paths in titles.values() if len(paths) > 1]}
    if request.get("rebuild_moc"):
        result["navigation"] = rebuild(data)
    return result
