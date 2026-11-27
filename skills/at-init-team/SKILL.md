---
name: at-init-team
description: 在空目录建立 Agent Team 项目和 GitHub 团队仓库，生成 AT.json、公共资源区和发布目录。
---

# AT_init_team

项目格式为 `agent-team/v3`。若已知本轮目标，随 `init` 或 `set-iteration` 传单行 `goal`，供各角色的工作记忆直接引用。

新项目默认从 `v1.0` 开始。用户指定起始版本时，在 `init` 请求中传入 `version`，如 `"version":"2.1"`。脚本将其规范为 `v2.1` 并写入 `AT.json` 的 `current_version`。未指定时直接采用默认值。

1. 以用户指定的已有目录为目标，默认当前目录。先列出含隐藏项的全部内容；发现任何内容就说明占用项，请用户指定空目录。确认项目名（默认目录名）和目标 Obsidian 库；本机可从 `%APPDATA%/obsidian/obsidian.json` 读取已登记库。只有一个时可直接采用并告知。无需启动 Obsidian。
2. 已给 GitHub 仓库 URL 时直接使用。需要新建时引导用户确定 GitHub 所有者、仓库名和可见性。在获得建库授权后可用已登录的 `gh repo create`；若无 CLI 或登录信息，给出 [GitHub 新建仓库](https://github.com/new) 的具体填写值，收取仓库 URL 后继续。无需把仓库设为公开。输入远程地址时使用无令牌的 HTTPS 或 SSH 地址，通过本机凭据认证。
3. 调用 `init`，输入形如 `{"name":"坦克大战","vault":"D:/Notes","remote":"https://github.com/OWNER/tanks.git"}`。使用现有 main 或为空仓库建立并推送首个 main 提交。脚本在临时目录准备好仓库和管理资料后再放入目标目录。返回非零时读取错误并处理；远程如已有其他分支，请让用户确定 main 的起点。
4. 核对返回的项目名、当前版本、库和仓库位置。`AT.json` 的 `team_repo` 指向 `public/<远程仓库名>/`，例如 `tank_war.git` 对应 `public/tank_war/`。项目根按普通目录保存 `AT.json`、公共资料和项目级交付目录 `publish/bin/`、`publish/user/`、`publish/dev/`。每个角色的本地 Git 仓库在添加该成员时建立。核对公共通讯目录 `public/chat/` 中的 meta.json 和 groups/；团队仓名为 chat 时使用 `public/at-chat/`。下一步可调用 `$at-add-team-member`。

共用入口为本技能目录下的 `scripts/at.py`。 将它解析为绝对路径后，从用户的项目上下文运行 `python -X utf8 "<入口>" <命令> --root "<项目目录>" --input "<UTF-8 JSON文件>"`。只读空输入可省略 `--input`。[命令接口](references/commands.md) 给出了字段和重试约定。
