"""Install the Agent Team skills into the global Codex skill directory."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


SOURCE = Path(__file__).resolve().parent / "skills"
OWNER = ".agentteam-install.json"


def replace(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        f.write(data)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def install(dest):
    dest.mkdir(parents=True, exist_ok=True)
    plans = []
    for src in sorted(SOURCE.glob("at-*")):
        target = dest / src.name
        if target.resolve() != target:
            raise ValueError(f"目标技能目录已重定向 {target}")
        files = {p.relative_to(src).as_posix(): p.read_bytes() for p in src.rglob("*")
                 if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
        if src.name == "at-start-board":
            board = SOURCE.parent / "board"
            runtime = [board / name for name in ("package.json", "package-lock.json", "index.html",
                                                  "vite.config.ts", "tsconfig.json")]
            for folder in ("src", "server"):
                runtime.extend(p for p in (board / folder).rglob("*") if p.is_file())
            for path in runtime:
                files["assets/board/" + path.relative_to(board).as_posix()] = path.read_bytes()
        manifest = target / OWNER
        previous = {}
        if manifest.exists():
            previous = json.loads(manifest.read_text(encoding="utf-8"))["files"]
        elif target.exists():
            raise ValueError(f"已有非本安装器管理的技能 {target}")
        hashes = {n: hashlib.sha256(blob).hexdigest() for n, blob in files.items()}
        for name in set(previous) | set(files):
            path = target / name
            if not path.resolve().is_relative_to(target) or path.resolve() == target:
                raise ValueError(f"技能清单中的路径越界 {name}")
            if path.exists():
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                if actual not in (previous.get(name), hashes.get(name)):
                    raise ValueError(f"全局副本已被独立修改，先合并到源文件 {path}")
        plans.append((target, files, hashes, previous))
    for target, files, hashes, previous in plans:
        metadata = {"files": hashes}
        if target.name == "at-start-board":
            metadata["source_root"] = str(SOURCE.parent)
        manifest_bytes = json.dumps(metadata, indent=2).encode("utf-8")
        if not target.exists():
            with tempfile.TemporaryDirectory(dir=dest, prefix=".at-install-") as tmp:
                ready = Path(tmp) / target.name
                for name, blob in files.items():
                    replace(ready / name, blob)
                replace(ready / OWNER, manifest_bytes)
                ready.rename(target)
            print(target)
            continue
        for name, blob in files.items():
            path = target / name
            if not path.exists() or path.read_bytes() != blob:
                replace(path, blob)
        for name in previous.keys() - files.keys():
            (target / name).unlink(missing_ok=True)
        if (target / OWNER).read_bytes() != manifest_bytes:
            replace(target / OWNER, manifest_bytes)
        print(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    parser.add_argument("--dest", type=Path, default=home / "skills")
    try:
        install(parser.parse_args().dest.resolve())
    except (ValueError, OSError) as ex:
        parser.exit(1, f"{ex}\n")
