# AgentTeamSkill

AgentTeamSkill 是一组给 Codex 使用的中文技能，适合需要多个角色共同交付的项目。以坦克游戏为例，策划、工程师和美术可以在项目负责人主持的会议中议定“坦克撞墙后仍可沿墙转向”，把决议分派成带验收条件的需求。工程师在自己的 Git 工作树中实现并测试，验收人按条件检查，负责人从已验收的成果制作版本交付。每份需求都能追溯到执行角色、状态变化和交付证据。

本次更新的功能与项目格式要求见[2026-11-27 迭代说明](docs/iterations/2026-11-27.md)。

## 在 Windows 上获取 16 个技能、角色通讯 MCP 和三个看板

准备好 Git 和 Python 3.11 或更新版本，在 PowerShell 中克隆仓库并为 Codex 安装技能。项目看板另需 Node.js 22.12 或更新版本和 npm，首次启动会联网下载依赖并构建页面。单独浏览技能手册只需 Python。

```powershell
git clone https://github.com/main-frame-zjx/AgentTeamSkill.git
cd AgentTeamSkill
python install.py
```

安装后，在新的 Codex 会话输入 `$at-help` 查看技能，或输入 `$at-start-board` 打开三个看板。首次设置会创建四个桌面快捷方式。请保留克隆目录，快捷方式和技能手册都从这里读取文件。

| 要做什么 | 桌面快捷方式 | 直接从仓库启动 |
| --- | --- | --- |
| 按分类查阅技能原文和后续调用 | `AgentTeam 技能看板` | 双击 [dev-visual/打开技能手册.bat](dev-visual/打开技能手册.bat)，默认端口为 8764 |
| 查看需求、角色和报告 | `Agent Team Board` | 双击 [board/启动看板.bat](board/启动看板.bat)，默认端口为 47361。打开后选择含 `AT.json` 的项目目录 |
| 查看角色待办和需求群记录 | `AgentTeam 角色通讯` | 双击 [打开角色通讯](chat-visual/打开角色通讯.bat)，默认端口 47362 |
| 关闭三个后台服务 | `AgentTeamStopService` | 双击 [tools/windows/AgentTeamStopService.exe](tools/windows/AgentTeamStopService.exe) 停止默认端口上的服务 |

只想浏览看板时，可在克隆后直接使用表中的仓库入口。要更新技能，在克隆目录运行 `git pull --ff-only`，再运行 `python install.py`。安装器默认使用 `$CODEX_HOME/skills`，未设置该变量时使用 `~/.codex/skills`。自定义安装位置使用 `python install.py --dest "D:\指定目录\skills"`，更新时沿用同一命令。

## 角色通讯

默认安装向 Codex 登记本地 stdio MCP `agent-team-chat`。缺少 Codex CLI 时，安装器会保留已安装技能并打印可复制的 MCP 配置。仅安装技能用 `python install.py --no-mcp`，其他宿主可用 `python install.py --dest "<技能目录>" --print-mcp-config` 输出配置。自定义 Codex 安装目录可传 `--host codex` 注册。卸载时核验本安装器登记的 MCP。

工程师送验后，验收人开工即可看到需求群中的定向提醒。验收通过后核销；退回时将原因和证据路径发给工程师。每名接收者有自己的待办状态。直接双击 [HTML 入口](chat-visual/index.html) 可选择项目目录。通过 [本机服务](chat-visual/serve.py) 启动还可切换项目并自动刷新。

## 角色工作记忆与 Obsidian 个人库

每个角色的 `Memory.md` 最多 6,656 个 UTF-8 字节。开工时可看到角色概况、活跃需求、当前焦点、生效决定、风险与依赖、个人知识索引与候选。用 `$at-manage-memory` 告诉角色要记住什么，脚本从需求和仓库刷新客观信息，并将记忆和结构化状态一起提交到角色 Git 仓库。

角色可在送验时登记有学习价值的候选，工作记忆展示最多三条。验收或阶段收口时，`$at-manage-library` 按来源找回完整候选，把有证据的内容整理到个人库的“系统设计”或“可复用方案”。工程师可引用代码，策划和美术可引用配置、素材及验收记录。下次开工时默认搜索自己的笔记，人可从 `00-项目学习导航.md` 浏览整个项目。[记忆与个人库接口](skills/at-init-team/references/memory-library.md)

推荐安装 Obsidian 桌面应用，在项目目录之外创建或选择一个笔记库（vault）。运行 `$at-init-team` 时指定这个库，之后就可以在 Obsidian 中查看和检索各角色积累的知识。[Obsidian 官网](https://obsidian.md/)

如果使用 Codex（ChatGPT），还推荐在 Codex 或 ChatGPT 桌面应用的插件目录中安装 **Obsidian** 插件，方便让 Agent 搜索、阅读和整理本地角色笔记。[Obsidian 插件页面](https://chatgpt.com/plugins/plugins_6aee4fde227881919d61b034b1c31096)

## 从 Agent 卸载

在 Codex 输入 `$at-uninstall`，在 DeepSeek Harness 输入 `/at-uninstall`。若要将这套技能安装到 Harness 私有用户目录，可用 `python install.py --dest "$env:USERPROFILE\.dsh\skills"`；自定义 DSH_HOME 时改用其 skills 子目录。

卸载默认只处理当前宿主。Agent 会先列出全部 16 项，解除实际注册入口，最后注销卸载技能自身，再逐名报告原宿主清单的查询结果。下载的 Git 仓库、项目和看板运行资源可继续保留。重新安装时运行原安装命令。

旧版安装中没有卸载技能时，可以更新下载仓库，让当前 Agent 直接读取并遵循[卸载技能说明](skills/at-uninstall/SKILL.md)，用同一份清单核验旧版实际安装的项目。

## 从空目录开始

创建团队项目前，请先配置 Git 提交身份，并准备好可访问和推送的团队 Git 仓库。

1. 在 Codex 中打开**另一个空目录**作为项目目录，输入 `$at-help 我应该从哪里开始？`。它会列出技能，并根据当前位置推荐下一步。
2. 调用 `$at-init-team`，给出项目名、Obsidian 库和团队代码仓库地址。为团队选择它自己的 Git 仓库。初始化后，根目录的 `AT.json` 记录项目格式 `agent-team/v3` 和当前迭代（默认 `v1.0`）。
3. 用 `$at-add-team-member` 建立项目负责人和执行角色。例如输入“添加一位负责碰撞和移动的客户端工程师”，逐轮确定角色的做事方式、工作重点和日常流程。
4. 分工明确时用 `$at-add-worklist` 直接分派。有设计取舍时，在项目根目录切到 Ultra，用 `$at-team-discuss` 让至少两位角色召开会议。
5. 用 `$at-work` 让需求所属角色开工，用 `$at-review-work` 验收。需要发布时，由负责人或已获授权的管理角色调用 `$at-publish`。

## 技能目录

开发者可在 Windows 双击[打开技能手册](dev-visual/打开技能手册.bat)，用 Python 离线浏览。每次打开或刷新页面，手册都会扫描 `skills/*/SKILL.md`，读取最新的名称、简介和正文，可按正文关键词搜索。新技能出现在侧栏末尾的“未分类”，可以直接打开或分享本机链接。删除技能后刷新，目录和页底跳转会同步移除该项。

需要整理分类、阅读顺序或更新后续调用及原文依据时，在开发仓库中运行 [`$update-skills-relation`](.agents/skills/update-skills-relation/SKILL.md) 重建[关系索引](dev-visual/skill-relation.json)，再刷新页面。

| 调用名 | 具体用途 | 何时使用 |
|---|---|---|
| [`$at-help`](skills/at-help/SKILL.md) | 列出可用技能，只读检查目录、成员、需求和版本，给出下一步及调用示例 | 初次上手，或接手一个已有项目 |
| [`$at-init-team`](skills/at-init-team/SKILL.md) | 在空目录建立项目配置、公共工作区、团队 Git 仓库和发布目录 | 开始新项目 |
| [`$at-add-team-member`](skills/at-add-team-member/SKILL.md) | 通过访谈确定角色设定，建立角色仓库、团队代码工作树和知识库目录 | 新增岗位或扩大团队 |
| [`$at-update-team-member`](skills/at-update-team-member/SKILL.md) | 按指令局部修改角色的 Agent.md，并提交到角色本地仓库 | 调整角色长期职责、工作重点或流程 |
| [`$at-team-discuss`](skills/at-team-discuss/SKILL.md) | 主持真实多角色会议，留下纪要并分派议定的需求 | 多个角色需要共同决定目标或方案 |
| [`$at-add-worklist`](skills/at-add-worklist/SKILL.md) | 为一个或多个角色建立有目标、版本和验收条件的需求 | 工作项已明确，可以直接分派 |
| [`$at-receive-message`](skills/at-receive-message/SKILL.md) | 按页收齐角色的未处理消息，列出需求、行动及阻塞 | 开工、查询待我验收或待返工事项 |
| [`$at-reply-message`](skills/at-reply-message/SKILL.md) | 逐人核销、保留受阻待办，按需求定向外发 | 送验、退回、改派、协作反馈 |
| [`$at-work`](skills/at-work/SKILL.md) | 收齐提醒、列编号清单，逐项验收或交付，结算消息并终检 | 角色开始或继续本轮工作 |
| [`$at-manage-workspace`](skills/at-manage-workspace/SKILL.md) | 查询需求，追加阻塞说明，修订验收条件或记录状态流转 | 已有任务需要维护 |
| [`$at-review-work`](skills/at-review-work/SKILL.md) | 按有效验收条件检查实际交付，归档或记录退回原因 | 需求进入待验收 |
| [`$at-manage-memory`](skills/at-manage-memory/SKILL.md) | 维护六槽位工作交接记忆，保留当前焦点、生效决定和风险 | 收尾交接、会议决议生效或跨角色依赖变化 |
| [`$at-manage-library`](skills/at-manage-library/SKILL.md) | 在项目内查重，为人类初学者编写已落地的系统设计或可复用方案笔记 | 验收归档、阶段收口或用户指定整理主题 |
| [`$at-publish`](skills/at-publish/SKILL.md) | 核查发布资格，生成 Windows 程序包、离线用户指南或甲方总览 | 阶段汇报、正式交付或同版本修订 |
| [`$at-start-board`](skills/at-start-board/SKILL.md) | 创建四个桌面入口，在浏览器打开项目看板、角色通讯和技能手册 | 查看团队进度、角色报告或技能文档 |
| [`$at-uninstall`](skills/at-uninstall/SKILL.md) | 从当前 Codex 或 DeepSeek Harness 解除全系列注册，并逐项验证技能名已消失 | 卸载本套技能并保留源码和项目 |

## 项目文件放在哪里

```text
我的项目/
├─ AT.json                        agent-team/v3 格式、当前迭代、成员、团队仓库与知识库位置
├─ public/
│  ├─ <团队仓库名>/               团队代码的 main 工作树
│  ├─ chat/                       项目通讯索引与群文件；团队仓同名时使用 at-chat/
│  └─ meetings/                   会议纪要
├─ AT_<角色名>/                   该角色的本地 Git 仓库
│  ├─ Agent.md                    角色人设、重点和工作流
│  ├─ Memory.md                   角色工作记忆
│  ├─ .memory-state.json          角色的结构化记忆，与 Memory.md 同次提交
│  ├─ .agent/                     角色个人技能
│  ├─ workspace/                  1新需求、2处理中、3待验收、4已归档
│  ├─ repository/<团队仓库名>/    团队代码的角色分支工作树
│  └─ report/                     该角色的本机阶段成果
└─ publish/<bin|user|dev>/vX.Y/rN/ 程序包、用户指南、甲方总览的版本修订
```

Obsidian 笔记位于所选库的 `<项目名>/AT_<角色名>/`。团队代码、角色档案和阶段成果各有自己的存放位置。排查具体命令的输入或重试行为时，可查阅[共用 CLI 接口](skills/at-init-team/references/commands.md)。

## 在另一台 Windows 设备验证

1. 完成安装，在 Codex 的新会话调用 `$at-help`。在空目录应看到 16 项技能，首选为初始化。在已有项目的角色目录中，应看到与该角色有关的下一步。
2. 选择一个测试项目，输入 `$at-update-team-member 给项目负责人增加每周五汇总风险的职责`。检查返回的差异、该角色的 `Agent.md` 和本地 Git 提交。
3. 调用 `$at-start-board`，浏览器会分别打开[项目看板](http://127.0.0.1:47361)、[角色通讯](http://127.0.0.1:47362)和[技能手册](http://127.0.0.1:8764)。项目看板首次启动会安装依赖并构建前端。在项目看板选择含 `AT.json` 的项目目录，即可查看需求、角色和报告。手册读取安装来源仓库的最新技能文档。
4. 桌面的 **Agent Team Board** 、**AgentTeam 角色通讯** 和 **AgentTeam 技能看板** 分别打开对应页面，**AgentTeamStopService** 关闭这三个后台服务。四个快捷方式直接指向来源仓库 `tools/windows/` 中的无控制台 EXE，图标来自同目录的 `icons/`。仓库搬迁后，从新位置再次运行 `python install.py`，再调用技能即可重建入口。角色通讯的本机项目列表保存在 `%LOCALAPPDATA%\AgentTeamChat`，项目看板的列表与启动日志保存在 `%LOCALAPPDATA%\AgentTeamBoard`。

只需创建或修复桌面入口时，可独立运行 [set-desktop-shortcuts.ps1](tools/windows/set-desktop-shortcuts.ps1)。修改启动器源码或图标后，用 [build-launchers.ps1](tools/windows/build-launchers.ps1) 重新编译四个 EXE。

## 在源码仓库运行测试

在仓库根目录运行。技能手册的索引测试还需 PyYAML，可用 `python -m pip install PyYAML` 安装。

```powershell
python -B -m unittest discover -s tests -v
python -B -m unittest discover -s dev-visual/tests -v
node --test dev-visual/tests/catalog.test.mjs chat-visual/tests/test_ui_logic.mjs
cd board
npm.cmd ci --cache "$env:LOCALAPPDATA\npm-cache"
npm.cmd test
npm.cmd run build
```

在 Windows 上，可从源码仓库根目录运行下列冷启动测试。它把技能装到临时中文路径，使用临时桌面、独立端口和临时看板配置，覆盖首次安装依赖、快捷方式重启、重复调用和端口冲突。

```powershell
$env:AT_TEST_BOARD_START = "1"
python -B -m unittest discover -s tests -p test_board_install.py -v
```

通讯测试使用临时中文项目、真实 stdio 子进程和中途退出的写入进程。浏览器验收同时打开本机服务和本地 HTML；设置 `AT_CHAT_PLAYWRIGHT` 为已安装的 Playwright 包目录后运行 `python -B -m unittest discover -s tests -p test_chat_viewer.py -v`，默认使用 Edge。

卸载集成测试使用临时宿主配置目录。Codex 测试需要 PATH 中的 `codex`。要同时运行 DeepSeek Harness 的实时注册表测试，可将官方包安装到临时目录后执行：

```powershell
$dshTest = Join-Path $env:TEMP ("at-dsh-test-" + [guid]::NewGuid())
npm install --prefix $dshTest --cache "$dshTest/npm-cache" --ignore-scripts @deepseek-ai/dsh-skill@0.2.2-rc.5 @deepseek-ai/dsh-skill-filesystem@0.2.2-rc.5
$env:AT_TEST_DSH_MODULES = Join-Path $dshTest "node_modules"
python -B -m unittest discover -s tests -p test_uninstall.py -v
```
