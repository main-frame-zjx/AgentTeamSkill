"""Build the offline, audience-specific body of a formal release."""

import shutil
from html import escape
from pathlib import Path

from core import field, inside, require, texts, write


STYLESHEET = Path(__file__).resolve().parents[2] / "at-publish/assets/report.css"


def bullets(items):
    return "<ul>" + "".join(f"<li>{escape(s)}</li>" for s in items) + "</ul>"


def section(title, content):
    return f"<section><h2>{escape(title)}</h2>{content}</section>"


def status_chart(assets, counts):
    total = sum(counts.values())
    bars = []
    for index, (stage, n) in enumerate(counts.items()):
        y = index * 44 + 14
        width = round(320 * n / max(1, total))
        bars.append(f'<text x="0" y="{y+14}">{escape(stage[1:])}</text>'
                    f'<rect x="84" y="{y}" width="320" height="14" rx="6" fill="#dce8e4"/>'
                    f'<rect x="84" y="{y}" width="{width}" height="14" rx="6" fill="#147968"/>'
                    f'<text x="418" y="{y+14}">{n}</text>')
    write(assets / "progress.svg", '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 485 184" '
          'font-family="sans-serif" font-size="15" fill="#173c36">' + "".join(bars) + "</svg>")


def gallery(root, assets, pictures):
    require(isinstance(pictures, list), "images 必须是图片数组")
    figures = []
    for i, item in enumerate(pictures, 1):
        src = inside(root, field(item, "path"))
        caption = field(item, "caption")
        ext = src.suffix.lower()
        require(ext in (".png", ".jpg", ".jpeg", ".webp", ".gif") and src.is_file(),
                f"找不到可离线打包的图片 {src}")
        with src.open("rb") as stream:
            header = stream.read(12)
        signatures = {".png": header.startswith(b"\x89PNG\r\n\x1a\n"), ".jpg": header.startswith(b"\xff\xd8\xff"),
                      ".jpeg": header.startswith(b"\xff\xd8\xff"), ".gif": header[:6] in (b"GIF87a", b"GIF89a"),
                      ".webp": header[:4] == b"RIFF" and header[8:12] == b"WEBP"}
        require(signatures[ext], f"图片内容与扩展名不符 {src}")
        name = f"figure-{i}{ext}"
        shutil.copyfile(src, assets / name)
        figures.append(f'<figure><img src="assets/{name}" alt="{escape(caption)}">'
                       f'<figcaption>{escape(caption)}</figcaption></figure>')
    return "".join(figures)


def render(stage, root, result, request):
    kind = result["kind"]
    title = "用户指南" if kind == "user" else "甲方项目总览"
    assets = stage / "assets"
    assets.mkdir(parents=True)
    shutil.copyfile(STYLESHEET, assets / "report.css")
    images = gallery(root, assets, request.get("images", []))
    overview = f'<p>{escape(field(request, "overview"))}</p>'
    sections = [section("项目介绍" if kind == "user" else "项目整体情况", overview)]
    if kind == "user":
        steps = "".join("<li>" + escape(item) + "</li>" for item in texts(request, "how_to"))
        sections += [section("可以做什么", bullets(texts(request, "capabilities"))),
                     section("开始使用", "<ol>" + steps + "</ol>" + images)]
        if request.get("highlights"):
            sections.append(section("版本变化", bullets(texts(request, "highlights"))))
    else:
        counts = result["stages"]
        status_chart(assets, counts)
        caption = "、".join(f"{stage[1:]} {n} 项" for stage, n in counts.items())
        sections.append(section("项目进度", '<figure class="chart"><img src="assets/progress.svg" '
                                f'alt="{escape(caption)}"><figcaption>全部登记需求，共 {sum(counts.values())} 项。'
                                f'{escape(caption)}。</figcaption></figure>'))
        highlights = bullets(texts(request, "highlights")) if request.get("highlights") else ""
        if highlights or images:
            sections.append(section("关键进展", highlights + images))
        if result["changes"]:
            prior = result["baseline"]
            heading = f"自 {prior['version']} 上次总览以来通过验收" if prior else "截至本次汇报已通过验收"
            sections.append(section(heading, bullets([r["version"] + " · " + r["title"] for r in result["changes"]])))
        rows = []
        for row in result["scope"]:
            review = row.get("review")
            evidence = bullets(review["evidence"]) if review else ""
            rows.append(f'<article><h3>{escape(row["title"])}</h3><p>{escape(row["role"])} · '
                        f'{escape(row["stage"][1:])}</p>{evidence}</article>')
        sections.append(section("目标版本需求", "".join(rows) or "<p>该版本尚无已登记需求。</p>"))
        for key, label in [("blockers", "当前阻塞"), ("decisions", "待决事项"), ("next_steps", "下一步方向")]:
            items = texts(request, key, allow_empty=True)
            sections.append(section(label, bullets(items) if items else "<p>暂无已记录事项。</p>"))
    if request.get("limitations"):
        sections.append(section("已知限制", bullets(texts(request, "limitations"))))
    project = escape(result["project"])
    target, revision = result["version"], result["revision"]
    stamp = escape(result["as_of"])
    page = (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{project} · {target} r{revision} {title}</title><link rel="stylesheet" href="assets/report.css">'
            f'</head><body><main><header><p>{project} / {title}</p><h1>{target}</h1>'
            f'<p>修订 r{revision} · <time datetime="{stamp}">{stamp[:10]} {stamp[11:19]} UTC</time></p>'
            '</header>' + "".join(sections) + '</main></body></html>\n')
    write(stage / "index.html", page)
