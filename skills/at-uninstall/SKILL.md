---
name: at-uninstall
description: 从当前 Codex 或 DeepSeek Harness 注销 AgentTeam 全系列技能，刷新宿主清单逐名验收，包括卸载自身。用户明确要卸载本套技能时使用。
---

# AT_uninstall

**完成条件**是原宿主、原工作区的完整技能清单中，每个正式名称均为零命中。先确定发起调用的宿主。用户明确指定两者时，为两个宿主分别保留盘点和验收结果。保留下载仓库、团队项目、角色数据和看板快捷方式。

1. 运行 `python -B -X utf8 "<本技能>/scripts/uninstall.py" prepare --host codex --cwd "<原工作目录>"`。DeepSeek Harness 使用 `--host dsh --session "<当前会话ID>"`。把已知的本宿主自定义扫描目录通过 `--root` 传入，另一宿主的自定义扫描目录通过 `--other-root` 传入。Codex 当前客户端实际附加的发现根使用 `--codex-extra`。这些参数可重复。先把返回的 **16 个 names 全部列给用户**，记住独立的 `runner` 路径和 `challenge`。从此使用该 runner，重试时仍用同一个。
2. 执行 `python -B -X utf8 "<runner>" inventory`。Codex 自动查询原工作区的 `skills/list` 并强制刷新；若当前客户端有专有来源，使用[宿主验收说明](references/hosts.md)提供原客户端快照。DeepSeek Harness 每次查询均按该说明取得当前会话的实际证据并传 `--snapshot "<文件>"`。逐项查看 `entries` 的来源。已禁用的同名条目仍占一个名额。
3. 对标有 `shared` 的入口，先列出路径、共享宿主和影响。只有用户同意解除该共享入口，才向 `apply` 加上对应的 `--allow-shared "<完整入口路径>"`。对于专有入口，直接执行 `python -B -X utf8 "<runner>" apply`。程序移出可发现的入口或解除链接，就地保留普通文件的改名备份和运行资源，并将变更记入 runner 旁的 `run.json`。
4. `action: host` 需要继续定位。若宿主正在直接扫描下载仓库，在宿主中解除**指向该仓库技能目录的那一条扫描配置**，保留其他配置；若为插件提供的技能，从提供方取消对应项。修改共享扫描配置会影响其他技能时先向用户说明影响。安装位置遗漏可在下一次查询补上 `--root`。遇到来源冲突、缺少授权或访问失败，保留具体来源和状态。
5. 执行 `python -B -X utf8 "<runner>" verify`，DSH 附本轮新快照。发现低优先级副本时，按新 `entries` 再执行 `apply → verify`。程序在其他名称均已消失后才解除自身。没有变化的残留先解决所列原因。查询失败或不完整时重新取得宿主证据。
6. Codex 同时检查 `mcp`，核验本安装器登记的 agent-team-chat 已注销。foreign 表示同名配置已由用户改管并保留。按 `rows` 输出 **16 行**，包含技能名、原来源、刷新后的命中及结果；其中包括原本未安装的技能。仅当 `verify` 返回 `done: true` 和退出码 0 时宣布完成。退出码 1 表示仍有残留或操作出错，2 表示证据不完整。中断后从独立 runner 再次 `verify` 可恢复。
