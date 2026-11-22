"""Shared filesystem, locking, input and Git primitives for the Agent Team skills."""

import hashlib
import json
import ntpath
import os
import re
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath


class Problem(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Problem(message)


def field(data, key):
    value = data.get(key)
    require(isinstance(value, str) and value.strip(), f"缺少非空文本字段 {key}")
    return value.strip()


def texts(data, key, allow_empty=False):
    values = data.get(key)
    require(isinstance(values, list) and (values or allow_empty), f"{key} 必须是文本数组")
    require(all(isinstance(v, str) and v.strip() for v in values), f"{key} 有空项")
    return [v.strip() for v in values]


def segment(value, *, allow_leading_dot=False):
    require(isinstance(value, str) and 0 < len(value) <= 100, "名称长度必须为 1–100 字符")
    reserved = ntpath.isreserved(value) if hasattr(ntpath, "isreserved") else PureWindowsPath(value).is_reserved()
    require(value == value.strip() and not value.endswith(".") and (allow_leading_dot or not value.startswith("."))
            and not re.search(r'[<>:"/\\|?*\x00-\x1f]', value)
            and not reserved, f"无效文件名 {value!r}")
    return value


def inside(base, *parts):
    base = base.resolve()
    path = base.joinpath(*parts)
    require(path.resolve().is_relative_to(base), f"路径越界 {path}")
    return path


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def write(path, value):
    atomic(path, value.encode("utf-8"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


@contextmanager
def lock(path, wait=60):
    """Kernel lock is released even if the process is terminated."""
    with path.open("a+b") as stream:
        # Windows permits locking a byte beyond EOF. Never write to that byte before acquiring it.
        deadline = time.monotonic() + wait
        while True:
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                require(time.monotonic() < deadline, "另一项 Agent Team 操作正在进行，请重试")
                time.sleep(0.1)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def git_result(repo, *args):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_LITERAL_PATHSPECS="1")
    return subprocess.run(["git", "-C", str(repo), *map(str, args)], capture_output=True,
                          encoding="utf-8", errors="replace", env=env, timeout=120)


def git(repo, *args):
    result = git_result(repo, *args)
    require(result.returncode == 0, (result.stderr or result.stdout).strip() or "Git 操作失败")
    return result.stdout.strip()


def require_repo_root(repo):
    require((repo / ".git").exists() and Path(git(repo, "rev-parse", "--show-toplevel")).resolve() == repo.resolve(),
            f"目录缺少自己的 Git 仓库或工作树 {repo}")


def save(root, paths, message):
    require_repo_root(root)
    names = sorted({p.relative_to(root).as_posix() for p in paths})
    stageable = [n for n in names if (root / n).exists() or git(root, "ls-files", "--", n)]
    # A failed commit can leave a deletion staged: it then exists only in HEAD.
    selected = [n for n in names if n in stageable or
                git_result(root, "cat-file", "-e", "HEAD:" + n).returncode == 0]
    if selected and git(root, "status", "--porcelain", "--", *selected):
        if stageable:
            git(root, "add", "-A", "--", *stageable)
        git(root, "commit", "--only", "-m", message, "--", *selected)


def project_root(start, exact=False):
    start = start.resolve()
    for path in ([start] if exact else [start, *start.parents]):
        if (path / "AT.json").is_file():
            return path
    raise Problem("此目录未找到 Agent Team 的 AT.json")


PROJECT_FORMAT = "agent-team/v2"


def project(root):
    data = read_json(root / "AT.json")
    require(isinstance(data, dict) and data.get("format") == PROJECT_FORMAT,
            f"AT.json 格式不受支持，当前需要 {PROJECT_FORMAT}")
    return data


def member(data, name):
    for role in data["members"]:
        if name in (role["name"], role["dir"]):
            return role
    raise Problem(f"项目未注册角色 {name}")


STAGES = ("1新需求", "2处理中", "3待验收", "4已归档")


def role_dir(root, role):
    return inside(root, segment(role["dir"]))
