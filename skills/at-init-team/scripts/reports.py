"""Bundle a local HTML report while preserving all relative resource paths."""

import html
import re
import shutil
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from core import digest, field, inside, member, project, require, require_repo_root, role_dir, segment, write
from team import prepare_report_dir
from versions import context_role


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
        self.css = []
        self.in_style = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        require(tag != "base", "请使用相对路径，移除 HTML base 元素")
        self.in_style = tag == "style"
        for key in ("src", "href", "poster", "data"):
            if attrs.get(key) and (key != "data" or tag == "object"):
                self.urls.append((attrs[key], tag == "a" and key == "href"))
        if attrs.get("srcset"):
            # Data URLs may contain commas; only split after descriptor or URL followed by whitespace.
            candidates = re.findall(r"(?:^|,\s*)(data:\S+|[^,\s]+)(?:\s+[^,]+)?", attrs["srcset"])
            self.urls.extend((url.rstrip(","), False) for url in candidates)
        if attrs.get("style"):
            self.css.append(attrs["style"])

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            self.css.append(data)


def bundle_files(base):
    files = {}
    for p in base.rglob("*"):
        require(not p.is_symlink() and p.resolve().is_relative_to(base.resolve()), f"报告含外部链接 {p}")
        if p.is_file():
            files[p.relative_to(base).as_posix()] = digest(p.read_bytes())
    return files


def check_bundle(base):
    files = bundle_files(base)
    require("index.html" in files, "报告源目录需要 index.html")
    for name in files:
        path = base / name
        if path.suffix.lower() not in (".html", ".htm", ".css"):
            continue
        body = path.read_text(encoding="utf-8-sig")
        parser = References()
        if path.suffix.lower() == ".css":
            parser.css.append(body)
        else:
            parser.feed(body)
            parser.close()
        for css in parser.css:
            css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
            urls = re.findall(r"""url\(\s*['"]?([^)'"]+?)['"]?\s*\)""", css, re.I)
            urls += re.findall(r"""@import\s+['"]([^'"]+)['"]""", css, re.I)
            parser.urls.extend((url, False) for url in urls)
        for raw, link in parser.urls:
            url = urlsplit(raw.strip())
            if url.scheme == "data" or (link and url.scheme in ("http", "https", "mailto", "tel")):
                continue
            require(not url.scheme and not url.netloc and not url.path.startswith(("/", "\\")),
                    f"{name} 含无法离线装载的引用 {raw}")
            if url.path:
                target = (path.parent / unquote(url.path)).resolve()
                require(target.is_relative_to(base) and target.is_file(), f"{name} 的引用无效 {raw}")
    return files


def report_directory(root, request, start):
    data = project(root)
    current = context_role(root, data, start)
    identity = request.get("role", current)
    require(identity, "从项目根整理阶段报告时请指定 role")
    role = member(data, identity)
    require(not current or role["name"] == current, f"当前角色 {current} 只能整理自己的阶段报告")
    base = role_dir(root, role)
    require_repo_root(base)
    return prepare_report_dir(base, register=True)


def publish(root, request, start):
    name = segment(field(request, "name"))
    source = Path(field(request, "source")).resolve()
    public = report_directory(root, request, start)
    require(source.is_dir() and not source.is_relative_to(public) and not public.is_relative_to(source),
            "请选择独立的报告暂存目录")
    assets, entry = inside(public, name), inside(public, name + ".html")
    url = quote(name, safe="") + "/index.html"
    title = html.escape(name)
    launcher = (f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>{title}</title>'
                f'<meta http-equiv="refresh" content="0;url={url}"><a href="{url}">{title}</a></html>\n')
    files = check_bundle(source)
    if entry.exists():
        require(entry.read_text(encoding="utf-8") == launcher, "报告入口已用于其他内容")
    if assets.exists():
        require(assets.is_dir() and files == bundle_files(assets), "同名报告内容已变化，请使用新版本名称")
    else:
        staging = inside(root, ".at-state")
        staging.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=staging) as tmp:
            copy = Path(tmp) / "bundle"
            shutil.copytree(source, copy)
            require(check_bundle(copy) == files, "报告源在打包期间发生变化")
            copy.rename(assets)
    write(entry, launcher)
    return {"entry": str(entry), "bundle": str(assets), "files": len(files)}
