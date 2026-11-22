"""Project setup, member provisioning and verified Git delivery."""

import os
import tempfile
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

from core import (PROJECT_FORMAT, STAGES, atomic, digest, dump, field, git, git_result, inside, lock, member,
                  project, read_json, require, require_repo_root, role_dir, save, segment, texts, write)
from versions import version


def repository_name(remote):
    if "://" in remote:
        path = urlsplit(remote).path
    else:
        # Local paths and Git's SCP-style host:owner/repository syntax.
        path = remote.replace("\\", "/").split(":", 1)[-1]
    path = path.rstrip("/").removesuffix("/.git")
    leaf = path.rsplit("/", 1)[-1]
    if "://" in remote:
        leaf = unquote(leaf)
    name = leaf.removesuffix(".git")
    require(name.casefold() != ".git", "仓库名称不能用作工作目录")
    return segment(name, allow_leading_dot=True)


def init(root, request):
    require(root.is_dir(), "请选择已有的空目录")
    name = segment(field(request, "name"))
    current_version = version(request.get("version", "1.0"))
    vault = Path(field(request, "vault")).expanduser().resolve()
    require(vault.is_dir() and not vault.is_relative_to(root), "请选择项目目录外已有的 Obsidian 库")
    remote = field(request, "remote")
    require(not remote.startswith("-"), "无效 Git 地址")
    if Path(remote).is_dir():
        remote = str(Path(remote).resolve())
    repo_name = repository_name(remote)
    team_repo = f"public/{repo_name}"
    gate = Path(tempfile.gettempdir()) / ("agent-team-init-" + digest(os.fsencode(os.path.normcase(str(root)))) + ".lock")
    with lock(gate):
        require(not any(root.iterdir()), "初始化要求空目录，包括隐藏文件")
        with tempfile.TemporaryDirectory(dir=root.parent, prefix=".at-init-") as tmp:
            stage = Path(tmp)
            (stage / "public").mkdir()
            for channel in ("bin", "user", "dev"):
                (stage / "publish" / channel).mkdir(parents=True)
            repo = stage / team_repo
            git(stage, "clone", "--no-local", "--", remote, str(repo))
            if git_result(repo, "show-ref", "--verify", "--quiet", "refs/remotes/origin/main").returncode == 0:
                git(repo, "switch", "main")
                empty_remote = False
            else:
                require(not git(repo, "ls-remote", "--heads", "origin"),
                        "远程已有其他分支。请先在团队仓库创建 main，再初始化。")
                git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
                git(repo, "commit", "--allow-empty", "-m", "Initialize team repository")
                empty_remote = True
            data = {"format": PROJECT_FORMAT, "id": str(uuid.uuid4()), "name": name, "current_version": current_version,
                    "vault": str(vault), "team_repo": team_repo, "remote": remote, "members": []}
            write(stage / "AT.json", dump(data))
            if empty_remote:
                git(repo, "push", "-u", "origin", "main")
            require(not any(root.iterdir()), "初始化期间目录内容发生变化")
            moved = []
            try:
                for entry in sorted(stage.iterdir(), key=lambda p: p.name == "AT.json"):
                    dest = root / entry.name
                    require(not dest.exists(), f"目标已存在 {dest}")
                    entry.rename(dest)
                    moved.append(dest)
            except BaseException:
                for dest in reversed(moved):
                    dest.rename(stage / dest.name)
                raise
    return data


def prepare_report_dir(base, *, register=False):
    folder = inside(base, "report")
    require(folder.resolve() == folder, f"角色报告目录已重定向 {folder}")
    ignore = inside(base, ".gitignore")
    keep = inside(folder, ".gitkeep")
    original = ignore.read_bytes() if ignore.exists() else b""
    rules = b"/report/*\n!/report/.gitkeep\n"
    paths = []
    if rules not in original.replace(b"\r\n", b"\n"):
        clean = not register or not git(base, "status", "--porcelain", "--", ".gitignore")
        with ignore.open("ab") as stream:
            if original and not original.endswith(b"\n"):
                stream.write(b"\n")
            stream.write(rules)
        if clean:
            paths.append(ignore)
    folder.mkdir(exist_ok=True)
    if not keep.exists():
        write(keep, "")
    if register and not git(base, "ls-files", "--", "report/.gitkeep"):
        paths.append(keep)
    if register and paths:
        save(base, paths, "Prepare local role report directory")
    return folder


def add_member(root, request):
    data = project(root)
    name = segment(field(request, "name").removeprefix("AT_"))
    require(name != "用户", "“用户”用于记录用户本人作出的决定，请选择角色名称")
    persona = field(request, "persona")
    focus, workflow = texts(request, "focus"), texts(request, "workflow")
    directory = "AT_" + name
    branch = "at/" + uuid.uuid5(uuid.UUID(data["id"]), name).hex[:16]
    role = {"name": name, "dir": directory, "branch": branch,
            "library": f"{data['name']}/{directory}"}
    base = role_dir(root, role)
    library = inside(Path(data["vault"]), segment(data["name"]), segment(directory))
    pending = root / ".at-state" / (branch.split("/")[1] + ".json")
    profile = (f"# {name}\n\n## 人设\n\n{persona}\n\n## 工作重点\n\n"
               + "\n".join("- " + s for s in focus) + "\n\n## 常规工作流\n\n"
               + "\n".join(f"{i}. {s}" for i, s in enumerate(workflow, 1)) + "\n")
    existing = next((r for r in data["members"] if r["name"].casefold() == name.casefold()), None)
    if existing and not pending.exists():
        require(all(existing.get(k) == v for k, v in role.items()) and (base / "Agent.md").read_text(encoding="utf-8") == profile,
                "同名角色已存在，档案不同")
        require_repo_root(base)
        prepare_report_dir(base, register=True)
        return existing
    if pending.exists():
        require(read_json(pending) == request, "同名成员有未完成的创建操作，请使用原输入重试")
    else:
        require(not base.exists() and not library.exists(), "角色目录或知识库目录重名")
        write(pending, dump(request))
    base.mkdir(exist_ok=True)
    if not (base / ".git").exists():
        git(base, "init", "-b", "main")
    require_repo_root(base)
    if not (base / ".gitignore").exists():
        write(base / ".gitignore", "/repository/\n")
    report = prepare_report_dir(base)
    write(base / ".gitattributes", "workspace/*/*.md text eol=lf\n")
    write(base / "Agent.md", profile)
    memory = base / "Memory.md"
    if not memory.exists():
        write(memory, f"# {name}的工作记忆\n\n角色已加入{data['name']}，等候首项需求。\n")
    keep = [base / ".agent/.gitkeep", *(base / "workspace" / s / ".gitkeep" for s in STAGES)]
    for path in keep:
        write(path, "")
    library.mkdir(parents=True, exist_ok=True)
    repo = inside(root, data["team_repo"])
    require_repo_root(repo)
    worktree = inside(base, "repository", repo.name)
    worktree.parent.mkdir(exist_ok=True)
    if not worktree.exists():
        git(repo, "fetch", "origin", "main")
        if git_result(repo, "show-ref", "--verify", "--quiet", "refs/heads/" + branch).returncode:
            git(repo, "worktree", "add", "-b", branch, worktree, "refs/remotes/origin/main")
        else:
            git(repo, "worktree", "add", worktree, branch)
    require_repo_root(worktree)
    require(git(worktree, "branch", "--show-current") == branch, "角色工作树分支不符")
    save(base, [base / ".gitignore", base / ".gitattributes", base / "Agent.md", memory, report / ".gitkeep", *keep],
         f"Register {directory}")
    if not existing:
        data["members"].append(role)
        write(root / "AT.json", dump(data))
    pending.unlink()
    return role


def update_member(root, request):
    role = member(project(root), field(request, "role"))
    base = role_dir(root, role)
    require_repo_root(base)
    path = inside(base, "Agent.md")
    require(path.is_file() and path.resolve() == path, f"找不到原始角色档案 {path}")
    prior = path.read_bytes()
    original = prior.decode("utf-8-sig")
    result = {"role": role["name"], "path": str(path), "sha256": digest(prior)}
    if "content" not in request:
        return {**result, "content": original}

    content = request["content"]
    require(isinstance(content, str) and content.strip(), "需要非空的角色档案正文")
    require(original.splitlines() and content.splitlines()[0] == original.splitlines()[0], "请保留角色名称标题")
    if "\r\n" in original and "\n" not in original.replace("\r\n", ""):
        content = content.replace("\r\n", "\n").replace("\n", "\r\n")
    # Preserve the existing BOM and retain untouched sections verbatim.
    new = content.encode("utf-8-sig" if prior.startswith(b"\xef\xbb\xbf") else "utf-8")
    expected = field(request, "expected_sha256")
    require(expected == result["sha256"] or new == prior, "档案已被修改，请重新读取并合并")
    if new != prior:
        atomic(path, new)
    # A retry after a failed Git commit also reaches save when the requested bytes already exist.
    if new != prior or expected != result["sha256"]:
        save(base, [path], f"Update profile for {role['name']}")
    elif git(base, "status", "--porcelain", "--", "Agent.md"):
        return {**result, "commit": None}
    return {**result, "sha256": digest(new), "commit": git(base, "log", "-1", "--format=%H", "--", "Agent.md")}


def repositories(root, request):
    data = project(root)
    role = member(data, field(request, "role"))
    repo = inside(root, data["team_repo"])
    tree = inside(role_dir(root, role), "repository", repo.name)
    require_repo_root(repo)
    require_repo_root(tree)
    require(git(tree, "branch", "--show-current") == role["branch"], "角色工作树分支不符")
    require(not git(tree, "status", "--porcelain"), "请先在角色分支提交本次工作并检查工作树")
    require(git(repo, "branch", "--show-current") == "main" and not git(repo, "status", "--porcelain"),
            "public 团队仓库必须位于干净的 main 分支")
    git(repo, "fetch", "origin", "main")
    return role, repo, tree


def sync(root, request):
    role, repo, tree = repositories(root, request)
    git(tree, "merge", "--no-edit", "refs/remotes/origin/main")
    return {"branch": role["branch"], "test_this_commit": git(tree, "rev-parse", "HEAD")}


def deliver(root, request):
    tested = field(request, "tested_commit")
    checks = texts(request, "checks")
    role, repo, tree = repositories(root, request)
    require(git(tree, "rev-parse", "HEAD") == tested, "自测版本与当前角色提交不一致")
    receipt = {"commit": tested, "branch": role["branch"], "remote_branch": "origin/main", "checks": checks}
    if git_result(repo, "merge-base", "--is-ancestor", tested, "refs/remotes/origin/main").returncode == 0:
        if git_result(repo, "merge-base", "--is-ancestor", "main", "refs/remotes/origin/main").returncode == 0:
            git(repo, "merge", "--ff-only", "refs/remotes/origin/main")
        return receipt
    for ref in ("refs/remotes/origin/main", "main"):
        require(git_result(repo, "merge-base", "--is-ancestor", ref, tested).returncode == 0,
                "main 已变化，请同步角色分支并重新自测")
    git(repo, "merge", "--ff-only", tested)
    git(repo, "push", "origin", "main:main")
    return receipt
