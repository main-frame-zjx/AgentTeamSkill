"""Manage only the stdio registration recorded by this installer."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

NAME = "agent-team-chat"


def interpreter():
    if sys.prefix != sys.base_prefix:
        candidate = Path(getattr(sys, "_base_executable", "") or sys.executable)
        if candidate.is_file() and not candidate.resolve().is_relative_to(Path(sys.prefix).resolve()):
            try:
                check = subprocess.run([str(candidate), "-I", "-c",
                                        "import sys; sys.exit(sys.version_info < (3, 11))"],
                                       capture_output=True, timeout=10)
                if check.returncode == 0:
                    return str(candidate.resolve())
            except (OSError, subprocess.TimeoutExpired):
                pass
        print("基础 Python 不可用。此配置依赖当前虚拟环境，请保留它或用长期安装的 Python 重新登记。", file=sys.stderr)
    return sys.executable


def config(dest):
    script = dest / "at-receive-message/scripts/at_chat_mcp.py"
    return {"command": interpreter(), "args": ["-B", "-X", "utf8", str(script.resolve())]}


def marker():
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    return home / "agent-team-chat-install.json"


def cli(*args):
    executable = shutil.which("codex")
    if not executable:
        raise ValueError("未找到 codex，使用 --no-mcp 安装或 --print-mcp-config 输出宿主配置")
    try:
        proc = subprocess.run([executable, "mcp", *args], capture_output=True, encoding="utf-8", errors="replace", timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Codex MCP 查询或操作超时，请重试") from exc
    if proc.returncode:
        raise ValueError(proc.stderr.strip() or "Codex MCP 配置操作失败")
    return proc.stdout


def actual():
    for entry in json.loads(cli("list", "--json")):
        if entry["name"] == NAME:
            spec = entry.get("transport", {})
            return {k: spec.get(k) for k in ("command", "args")}
    return None


def status():
    path = marker()
    if not path.is_file():
        return "unmanaged"
    current = actual()
    if current is None:
        return "absent"
    owned = json.loads(path.read_text(encoding="utf-8"))
    return "owned" if current in owned else "foreign"


def record(specs):
    path = marker()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as f:
        json.dump(specs, f)
    os.replace(f.name, path)


def register(dest):
    desired = config(dest)
    current = actual()
    owners = json.loads(marker().read_text(encoding="utf-8")) if marker().is_file() else []
    if current and current not in owners:
        raise ValueError("同名 MCP 由其他配置管理，已保留；可用 --print-mcp-config 查看本次配置")
    if current != desired:
        record([v for v in (current, desired) if v])
        cli("add", NAME, "--", desired["command"], *desired["args"])
        if actual() != desired:
            raise ValueError("宿主登记结果与请求不符")
    record([desired])


def remove():
    state = status()
    if state == "owned":
        cli("remove", NAME)
        if actual() is not None:
            raise ValueError("MCP 注销后仍可见")
    if state in ("absent", "owned"):
        marker().unlink(missing_ok=True)
