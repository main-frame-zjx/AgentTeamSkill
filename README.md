# AgentTeamSkill

AgentTeamSkill 是一组给 Codex 使用的中文技能，适合需要多个角色共同交付的项目。以坦克游戏为例，策划、工程师和美术可以在项目负责人主持的会议中议定“坦克撞墙后仍可沿墙转向”，把决议分派成带验收条件的需求。工程师在自己的 Git 工作树中实现并测试，验收人按条件检查，负责人从已验收的成果制作版本交付。每份需求都能追溯到执行角色、状态变化和交付证据。

## 在 Windows 上安装

准备好 Codex、Python 3.11 或更新版本，以及已配置提交身份的 Git。创建团队项目时还需要一个项目目录外的 Obsidian 库，以及可访问并推送的团队 Git 仓库。使用看板的设备还需要 Node.js 22.12 或更新版本和 npm，首次启动需能下载锁定的依赖。

在 PowerShell 中克隆本仓库并运行安装器。

```powershell
git clone https://github.com/main-frame-zjx/AgentTeamSkill.git
cd AgentTeamSkill
python install.py
```

安装器将 13 个技能复制到 `$CODEX_HOME/skills`，未设置该变量时使用 `~/.codex/skills`，同时为看板技能复制运行所需的源码。需要安装到指定位置时，运行 `python install.py --dest "D:\指定目录\skills"`。更新时在克隆目录运行 `git pull --ff-only`，再运行同一安装命令。安装器会指出安装副本中与源码冲突的改动，便于先合并再更新。

## 从空目录开始

1. 在 Codex 中打开**另一个空目录**作为项目目录，输入 `$at-help 我应该从哪里开始？`。它会列出技能，并根据当前位置推荐下一步。
2. 调用 `$at-init-team`，给出项目名、Obsidian 库和团队代码仓库地址。为团队选择它自己的 Git 仓库。初始化完成后，项目根目录下会出现 `AT.json`。
3. 用 `$at-add-team-member` 建立项目负责人和执行角色。例如输入“添加一位负责碰撞和移动的客户端工程师”，逐轮确定角色的做事方式、工作重点和日常流程。
4. 分工明确时用 `$at-add-worklist` 直接分派。有设计取舍时，在项目根目录切到 Ultra，用 `$at-team-discuss` 让至少两位角色召开会议。
5. 用 `$at-work` 让需求所属角色开工，用 `$at-review-work` 验收。需要发布时，由负责人或已获授权的管理角色调用 `$at-publish`。

## 技能目录

| 调用名 | 具体用途 | 何时使用 |
|---|---|---|
| [`$at-help`](skills/at-help/SKILL.md) | 列出可用技能，只读检查目录、成员、需求和版本，给出下一步及调用示例 | 初次上手，或接手一个已有项目 |
| [`$at-init-team`](skills/at-init-team/SKILL.md) | 在空目录建立项目配置、公共工作区、团队 Git 仓库和发布目录 | 开始新项目 |
| [`$at-add-team-member`](skills/at-add-team-member/SKILL.md) | 通过访谈确定角色设定，建立角色仓库、团队代码工作树和知识库目录 | 新增岗位或扩大团队 |
| [`$at-update-team-member`](skills/at-update-team-member/SKILL.md) | 按指令局部修改角色的 Agent.md，并提交到角色本地仓库 | 调整角色长期职责、工作重点或流程 |
| [`$at-team-discuss`](skills/at-team-discuss/SKILL.md) | 主持真实多角色会议，留下纪要并分派议定的需求 | 多个角色需要共同决定目标或方案 |
| [`$at-add-worklist`](skills/at-add-worklist/SKILL.md) | 为一个或多个角色建立有目标、版本和验收条件的需求 | 工作项已明确，可以直接分派 |
| [`$at-work`](skills/at-work/SKILL.md) | 让角色领取或续做需求，验证交付、送验并整理记忆 | 需要开始实现，或继续处理中任务 |
| [`$at-manage-workspace`](skills/at-manage-workspace/SKILL.md) | 查询需求，追加阻塞说明，修订验收条件或记录状态流转 | 已有任务需要维护 |
| [`$at-review-work`](skills/at-review-work/SKILL.md) | 按有效验收条件检查实际交付，归档或记录退回原因 | 需求进入待验收 |
| [`$at-manage-memory`](skills/at-manage-memory/SKILL.md) | 更新角色的 Memory.md，保留恢复工作所需的上下文 | 交接阶段进展或整理下一轮工作起点 |
| [`$at-manage-library`](skills/at-manage-library/SKILL.md) | 在角色的 Obsidian 目录中沉淀可复用的解法和设计依据 | 经验值得在后续任务中检索 |
| [`$at-publish`](skills/at-publish/SKILL.md) | 核查发布资格，生成 Windows 程序包、离线用户指南或甲方总览 | 阶段汇报、正式交付或同版本修订 |
| [`$at-start-board`](skills/at-start-board/SKILL.md) | 启动本地看板、打开浏览器并创建 AgentTeamBoard 桌面快捷方式 | 查看团队全局进度、角色档案或报告 |

## 项目文件放在哪里

```text
我的项目/
├─ AT.json                        项目名、版本、成员、团队仓库与知识库位置
├─ public/
│  ├─ <团队仓库名>/               团队代码的 main 工作树
│  └─ meetings/                   会议纪要
├─ AT_<角色名>/                   该角色的本地 Git 仓库
│  ├─ Agent.md                    角色人设、重点和工作流
│  ├─ Memory.md                   角色工作记忆
│  ├─ .agent/                     角色个人技能
│  ├─ workspace/                  1新需求、2处理中、3待验收、4已归档
│  ├─ repository/<团队仓库名>/    团队代码的角色分支工作树
│  └─ report/                     该角色的本机阶段成果
└─ publish/                       bin 程序包、user 用户指南、dev 甲方总览
```

Obsidian 笔记位于所选库的 `<项目名>/AT_<角色名>/`。团队代码、角色档案和阶段成果各有自己的存放位置。排查具体命令的输入或重试行为时，可查阅[共用 CLI 接口](skills/at-init-team/references/commands.md)。

## 在另一台 Windows 设备验证

1. 完成安装，在 Codex 的新会话调用 `$at-help`。在空目录应看到 13 项技能，首选为初始化。在已有项目的角色目录中，应看到与该角色有关的下一步。
2. 选择一个测试项目，输入 `$at-update-team-member 给项目负责人增加每周五汇总风险的职责`。检查返回的差异、该角色的 `Agent.md` 和本地 Git 提交。
3. 调用 `$at-start-board`。首次启动会安装依赖并构建前端。浏览器打开 [本机看板](http://127.0.0.1:47361) 后，点击“添加项目”或“选择项目文件夹”，选择含 `AT.json` 的目录，检查四列需求、角色档案和报告。
4. 确认桌面上出现 **AgentTeamBoard**。再次调用技能或双击快捷方式应打开同一个服务。重启 Windows 后再次双击，应能重新启动服务并看到之前登记的项目。项目列表与启动日志保存在 `%LOCALAPPDATA%\AgentTeamBoard`。

## 在源码仓库运行测试

```powershell
python -B -m unittest discover -s tests -v
cd board
npm ci
npm test
npm run build
```

在 Windows 上，可从源码仓库根目录运行下列冷启动测试。它把技能装到临时中文路径，使用临时桌面、独立端口和临时看板配置，覆盖首次安装依赖、快捷方式重启、重复调用和端口冲突。

```powershell
$env:AT_TEST_BOARD_START = "1"
python -B -m unittest discover -s tests -p test_board_install.py -v
```
