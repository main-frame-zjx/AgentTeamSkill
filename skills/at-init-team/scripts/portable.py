"""Verify the exact Windows distribution in a relocated copy before publishing it."""

import hashlib
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from core import dump, field, inside, now, project, read_json, require, write
from versions import version


def distribution_files(folder):
    require(folder.is_dir(), f"发行目录不存在 {folder}")
    result = {}
    for path in folder.rglob("*"):
        info = path.lstat()
        require(not path.is_symlink() and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT,
                f"请将运行所需链接替换为实际文件 {path}")
        require(path.name.casefold() not in (".git", ".at-state"), f"请提供独立的发行目录 {path}")
        if path.is_file():
            with path.open("rb") as stream:
                result[path.relative_to(folder).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


def verify(root, request, actor):
    require(os.name == "nt", "Windows 程序包需要在 Windows 上运行验证")
    target = version(request.get("version", project(root)["current_version"]))
    source = (root / field(request, "source")).resolve()
    entry = field(request, "entry")
    exe = inside(source, entry)
    require(not Path(entry).anchor and exe.is_file() and exe.suffix.lower() == ".exe", "请给出发行目录内的 EXE 相对路径")
    entry = exe.resolve().relative_to(source).as_posix()
    build = field(request, "build_evidence")
    feature = field(request, "feature")
    args = request.get("args", [])
    require(isinstance(args, list) and all(isinstance(a, str) for a in args), "args 应为启动参数字符串数组")
    manual = request.get("interactive") is True
    expected = None if manual else field(request, "expect")
    files = distribution_files(source)
    temp_root = Path(tempfile.gettempdir()).resolve()
    if temp_root.is_relative_to(root) or temp_root.is_relative_to(source):
        temp_root = root.parent
    require(not temp_root.is_relative_to(source), "请选择仅含可分发程序的源目录")
    with tempfile.TemporaryDirectory(prefix="AT 迁移验证 ", dir=temp_root) as temp:
        base = Path(temp)
        copied = base / "独立运行"
        shutil.copytree(source, copied)
        require(distribution_files(copied) == files, "复制期间发行文件已变化")
        system = Path(os.environ["SystemRoot"])
        env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "COMSPEC", "SystemDrive") if key in os.environ}
        env.update(PATH=os.pathsep.join(map(str, (system / "System32", system))),
                   TEMP=temp, TMP=temp, USERPROFILE=str(base / "profile"), HOME=str(base / "profile"),
                   APPDATA=str(base / "profile/roaming"), LOCALAPPDATA=str(base / "profile/local"))
        for key in ("USERPROFILE", "APPDATA", "LOCALAPPDATA"):
            Path(env[key]).mkdir(parents=True, exist_ok=True)
        timeout = request.get("timeout_seconds", 600 if manual else 90)
        require(type(timeout) is int and timeout > 0, "timeout_seconds 应为正整数")
        if manual:
            print(f"请在迁移副本中验证「{feature}」后正常退出程序。", file=sys.stderr, flush=True)
        output_path = None
        if "result_file" in request:
            output_path = inside(copied, field(request, "result_file"))
            require(not output_path.exists(), "用于验证的结果文件应由本次运行生成")
        with (base / "run.log").open("wb") as log:
            proc = subprocess.run([str(copied / entry), *args], cwd=copied, env=env, stdin=subprocess.DEVNULL,
                                  stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        log_text = (base / "run.log").read_text(encoding="utf-8", errors="replace")
        require(proc.returncode == 0, f"迁移启动或功能验证失败，退出码 {proc.returncode}。{log_text[-600:]}")
        if manual:
            print("请输入实测操作及观察结果；未通过请留空。", file=sys.stderr, flush=True)
            observed = sys.stdin.readline().strip()
            require(observed, "缺少交互功能验证结果")
        else:
            if output_path:
                require(output_path.is_file(), f"未生成验证结果 {output_path.name}")
                log_text = output_path.read_text(encoding="utf-8-sig", errors="replace")
            require(expected in log_text, f"未观察到期望结果 {expected}。{log_text[-600:]}")
            observed = expected
    proof_id = uuid.uuid4().hex
    proof = {"id": proof_id, "version": target, "actor": actor, "time": now(), "source": str(source),
             "entry": entry, "files": files, "build_evidence": build, "feature": feature, "observed": observed,
             "windows": platform.platform(), "architecture": os.environ.get("PROCESSOR_ARCHITEW6432") or platform.machine(),
             "mode": "interactive" if manual else "automated", "args": args}
    write(inside(root, ".at-state", "bin-checks", proof_id + ".json"), dump(proof))
    return {k: v for k, v in proof.items() if k not in ("files", "source")}


def package(root, stage, request, target):
    proof_id = field(request, "bin_check")
    require(re.fullmatch(r"[0-9a-f]{32}", proof_id), "bin_check 需要 verify-bin 返回的编号")
    proof = read_json(inside(root, ".at-state", "bin-checks", proof_id + ".json"))
    require(proof["version"] == target and proof["id"] == proof_id, "验证记录与目标版本不符")
    source = Path(proof["source"])
    require(not stage.is_relative_to(source) and distribution_files(source) == proof["files"],
            "发行文件已变化，请重新运行迁移验证")
    shutil.copytree(source, stage)
    require(distribution_files(stage) == proof["files"], "打包期间发行文件已变化")
    return proof["entry"], {k: v for k, v in proof.items() if k not in ("files", "source")}
