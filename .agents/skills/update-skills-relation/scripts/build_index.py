"""Build the developer handbook index from an AI-reviewed JSON manifest on stdin."""

import json
from pathlib import Path
import re
import sys
import tempfile

try:
    import yaml
except ModuleNotFoundError:
    sys.exit("生成索引需要 PyYAML，可用 python -m pip install PyYAML 安装。")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def markdown(root, relative):
    path = (root / relative).resolve()
    require(path.is_relative_to(root) and path.suffix.lower() == ".md",
            f"文档须位于 skills/ 内：{relative}")
    return path.read_text(encoding="utf-8-sig")


def inventory(root):
    documents = {}
    require(root.is_dir(), f"找不到技能目录：{root}")
    for path in sorted(root.glob("*/SKILL.md")):
        relative = path.relative_to(root).as_posix()
        content = markdown(root, relative)
        lines = content.splitlines()
        require(lines and lines[0] == "---" and "---" in lines[1:], f"缺少 frontmatter：{relative}")
        meta = yaml.safe_load("\n".join(lines[1:lines.index("---", 1)]))
        require(isinstance(meta, dict), f"无效 frontmatter：{relative}")
        name, description = meta.get("name"), meta.get("description")
        require(isinstance(name, str) and name.strip() and name not in documents,
                f"名称缺失或重名：{relative}")
        require(isinstance(description, str) and description.strip(), f"缺少简介：{relative}")
        documents[name] = {"name": name, "description": description, "document": relative}
    return documents


def build(root, review):
    documents = inventory(root)
    categories, rows = review["categories"], review["skills"]
    require(isinstance(categories, list) and all(isinstance(c, str) and c.strip() for c in categories),
            "categories 应为类别名数组")
    require(len(set(categories)) == len(categories), "类别名重复")
    names = [row["name"] for row in rows]
    require(len(names) == len(set(names)), "同一技能出现多次")
    require(set(names) == documents.keys(), f"技能清单与目录不符：{sorted(set(names) ^ documents.keys())}")
    require({row["category"] for row in rows} == set(categories), "类别缺失或存在空类别")
    skills = []
    for row in rows:
        name = row["name"]
        targets = set()
        edges = row["next"]
        require(isinstance(edges, list), f"{name} 的 next 应为数组")
        for edge in edges:
            target = edge["target"]
            require(target in documents and target not in targets, f"{name} 的目标不存在或重复：{target}")
            targets.add(target)
            evidence = edge["evidence"]
            require(isinstance(evidence, list) and evidence, f"{name} → {target} 缺少依据")
            for item in evidence:
                source, quote = item["source"], item["quote"]
                require(isinstance(source, str) and Path(source).as_posix() == source
                        and not Path(source).is_absolute() and ".." not in Path(source).parts,
                        f"无效来源路径：{source}")
                require(not source.endswith("/SKILL.md") or source == documents[name]["document"],
                        f"{name} 的调用须有自身流程中的依据：{source}")
                target_name = rf"(?<![a-z0-9-]){re.escape(target)}(?![a-z0-9-])"
                require(isinstance(quote, str) and re.search(target_name, quote) and quote in markdown(root, source),
                        f"{name} → {target} 引文与 {source} 不符")
                require(isinstance(item["condition"], str) and item["condition"].strip(),
                        f"{name} → {target} 缺少调用条件")
        skills.append({**documents[name], "category": row["category"], "next": edges})
    return {"categories": categories, "skills": skills}


def publish(repo, review):
    index = build((repo / "skills").resolve(), review)
    output = repo / "dev-visual" / "skill-relation.json"
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=output.parent, delete=False) as stream:
            tmp = Path(stream.name)
            json.dump(index, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        tmp.replace(output)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    return index


if __name__ == "__main__":
    try:
        index = publish(Path(__file__).resolve().parents[4], json.load(sys.stdin))
        print(f"{len(index['skills'])} 个技能，{len(index['categories'])} 个类别，"
              f"{sum(len(s['next']) for s in index['skills'])} 条后续调用。")
    except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError) as error:
        sys.exit(f"未写入索引：{error}")
