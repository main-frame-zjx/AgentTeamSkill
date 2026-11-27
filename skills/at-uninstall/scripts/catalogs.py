"""Read a fresh Codex catalog or consume a scoped observation from the calling DSH agent."""

import json
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time


NAMES = (
    "at-init-team", "at-add-team-member", "at-update-team-member", "at-help",
    "at-team-discuss", "at-add-worklist", "at-work", "at-manage-workspace",
    "at-review-work", "at-manage-memory", "at-manage-library", "at-publish",
    "at-receive-message", "at-reply-message", "at-start-board", "at-uninstall",
)


def codex_view(cwd, extra, socket=None):
    executable = shutil.which("codex")
    if not executable:
        raise ValueError("找不到 codex，请使用当前宿主返回的完整清单")
    transport = ["proxy", "--sock", socket] if socket else ["--stdio"]
    process = subprocess.Popen([executable, "app-server", *transport], cwd=cwd, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, encoding="utf-8")
    lines = queue.Queue()

    def reader():
        try:
            for line in process.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    def send(message):
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    def response(number):
        end = time.monotonic() + 20
        while True:
            try:
                line = lines.get(timeout=max(0, end - time.monotonic()))
            except queue.Empty as exc:
                raise ValueError("Codex 查询超时") from exc
            if line is None:
                raise ValueError("Codex 查询提前结束")
            message = json.loads(line)
            if message.get("id") == number:
                if "error" in message:
                    raise ValueError(str(message["error"]))
                return message["result"]

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    try:
        send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "at_uninstall", "version": "1"},
              "capabilities": {"experimentalApi": True}}})
        response(1)
        send({"method": "initialized", "params": {}})
        params = {"cwds": [cwd], "forceReload": True}
        if extra and not socket:
            # Configure only our short-lived verifier. A running client's root set belongs to that client.
            send({"id": 3, "method": "skills/extraRoots/set", "params": {"extraRoots": extra}})
            response(3)
        send({"id": 2, "method": "skills/list", "params": params})
        rows = response(2)["data"]
        if len(rows) != 1 or Path(rows[0]["cwd"]).resolve() != Path(cwd):
            raise ValueError("Codex 返回的工作区不符")
        return validate_view({"complete": rows[0].get("errors") == [], "skills": rows[0]["skills"],
                              "errors": rows[0].get("errors")})
    finally:
        process.kill()
        process.wait()
        thread.join()
        process.stdin.close()
        process.stdout.close()


def validate_view(observation):
    rows = observation["skills"]
    if not isinstance(rows, list) or not all(isinstance(s, dict) and isinstance(s.get("name"), str) for s in rows):
        raise ValueError("宿主技能清单格式不正确")
    errors = observation.get("errors", [])
    return {"complete": observation.get("complete") is True and errors == [],
            "skills": [s for s in rows if s["name"] in NAMES], "errors": errors}


def read_view(state, evidence):
    if evidence is None:
        if state.get("live_evidence"):
            raise ValueError("继续使用原活动客户端的新快照")
        if state["host"] == "codex":
            return codex_view(state["cwd"], state["extra"], state["socket"])
        raise ValueError("请提供当前 DeepSeek Harness 会话的新快照或逐名查询记录")
    data = json.loads(evidence.read_text(encoding="utf-8-sig"))
    if (not isinstance(data, dict) or any(data.get(k) != state[k] for k in ("challenge", "host", "session"))
            or not Path(data["cwd"]).is_absolute()
            or Path(data["cwd"]).resolve() != Path(state["cwd"])):
        raise ValueError("快照与本次查询、原宿主会话或工作目录不符")
    if "probes" in data:
        if state["host"] != "dsh" or set(data["probes"]) != set(NAMES):
            raise ValueError("需要当前 DSH 会话的全部逐名查询结果")
        rows = []
        for name, probe in data["probes"].items():
            code = probe["code"]
            if code in ("FOUND", "SKILL_NOT_MODEL_INVOCABLE"):
                rows.append({"name": name, "path": probe.get("path")})
            elif code != "SKILL_NOT_FOUND":
                data["complete"] = False
        data["skills"] = rows
    view = validate_view(data)
    state["live_evidence"] = True
    return view
