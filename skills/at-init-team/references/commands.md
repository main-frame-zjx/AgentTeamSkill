# Agent Team Python 接口

Python 3.11+，使用标准库和本机 Git。每个命令返回 UTF-8 JSON；成功时退出码为 0 并带有 `result`，失败时退出码为 1 并带有 `error`。参数通过 UTF-8 JSON 文件或 `--input -` 传入。临时输入放项目目录外，包含用户文本时使用文件 API 写入，避免 shell 转义改变内容。写命令失败后先检查返回信息。

```text
python -X utf8 "<已解析的 at.py 绝对路径>" <命令> --root "<工作目录>" --input "<请求文件>"
```

| 命令 | 输入 | 结果 |
|---|---|---|
| init | name, vault, remote，可选 version | 在指定空目录生成项目配置，current_version 默认为 v1.0。 |
| project | 空对象 | AT.json，包括角色、分支和知识库位置。 |
| help | 空对象，可指定任意工作目录 | 已安装技能目录表、项目状态、当前角色、需求明细和下一步建议。空目录和无效项目也会返回诊断；查询不写项目文件。 |
| add-member | name, persona, focus[], workflow[] | 角色与已登记路径。 |
| update-member | role；写入另传 content、expected_sha256 | 读取返回完整 Agent.md 与内容哈希，写入返回路径、新哈希及角色仓库提交号。已符合请求的未提交草稿保留现状，commit 返回 null。内容已写入但 Git 提交中断时可用原请求恢复。 |
| add-tasks | items[]，每项有 key, role, title, goal, criteria[]；首次给角色分配前缀时传 prefix；可选 summary, reviewer, source。批次和单项均可传 version | 每项的 id、role、实际绑定的 version 和文件路径 path。 |
| list | role，可选 stages[] | 该角色的需求清单。 |
| show | role，以及 id 或 path | original、current、events、stage、path。 |
| note / amend | role, id, key, actor, reason；amend 另需 changes | 追加说明或修订当前 goal、criteria、reviewer。 |
| move | role, id, key, actor, reason, from, to；送验和验收另需 evidence[] | 最新状态及文件位置。 |
| sync | role | 更新已提交且干净的角色分支，返回 test_this_commit。 |
| deliver | role, tested_commit, checks[] | 已推送 main 的 commit 与验证记录。 |
| publish | name, source，项目根调用另传 role | 将离线 HTML 入口与同名资源目录写入登记角色的 report/，返回 entry、bundle 和文件数。在角色目录可自动识别 role。 |
| report-dir | 项目根传 role，角色目录可省略 | 准备角色本机报告目录与 Git 忽略规则，返回 path，可直接归档非 HTML 成果。 |
| release-check / release | kind（bin、user 或 dev）、目标版本及相应材料 | 查看发布资格、既有修订，或交付该类别的独立修订目录。见[发布接口](../../at-publish/references/release.md)。 |
| verify-bin | 目标版本、发行目录、EXE 入口、构建依据和功能验证参数 | 在项目外迁移启动，返回与已测试文件内容绑定的验证编号。 |
| memory | role；写入另传 content, expected_sha256 | 正文或写入结果、sha256、UTF-8 字节数。 |
| library | role, path；写入同 memory | 角色目录下相对路径对应的笔记。新建时哈希传 null。 |
| meeting-context | 可选 host | 主持人及全部角色的档案和记忆路径。 |
| meeting | 见下例 | 会议纪要和分派需求列表。 |

一般命令支持从项目子目录向上查找 AT.json。会议命令严格检查指定目录本身，技能调用时传入当前目录。创建和修订需求的 key 由调用方在首次尝试前确定，重试保持相同。任务 key 在项目范围内唯一，事件 key 在单个需求内唯一。actor 为已注册的执行人或亲自作决定的“用户”。from、to 使用完整目录名。

## 示例会议输入

有行动项时，`add-tasks`、`meeting` 优先采用单项 `version`，其次采用批次 `version`，最后采用 `AT.json` 的 `current_version`。首次缺少版本时先按用户给出的数字版本调用 `set-iteration`。历史需求的版本补登记、正式发布及查询接口见[正式发布接口](../../at-publish/references/release.md)。

开场单列在 `opening`。`rounds` 至少包含 10 轮，每轮须包含主持人和其他全体角色的实际发言摘要。重大决策记录用户实际回复。项目角色多于两位时按名单扩展每轮对象。

```json
{
  "key": "2026-11-21-collision",
  "topic": "坦克与墙体碰撞",
  "host": "项目负责人",
  "opening": "确定本轮碰撞范围及验收方式。",
  "rounds": [
    {"项目负责人": "先覆盖四向移动。", "高级工程师": "需要明确沿墙移动行为。"},
    {"项目负责人": "同意沿墙移动作为独立验收项。", "高级工程师": "两项可以在同一场景验证。"},
    {"项目负责人": "场景里用哪段墙？", "高级工程师": "用一段水平墙和一段竖直墙，四个方向都能撞到。"},
    {"项目负责人": "怎样判定撞墙后停住？", "高级工程师": "持续按键，逐帧检查坦克边缘是否越过墙面。"},
    {"项目负责人": "坦克速度会影响这项检查吗？", "高级工程师": "会，最高速度时也要覆盖，避免一步越过薄墙。"},
    {"项目负责人": "坦克停住后，玩家应该能立即转向。", "高级工程师": "我会检查切换到平行方向后的第一帧。"},
    {"项目负责人": "沿墙走到拐角时呢？", "高级工程师": "如果前方出现垂直墙，也应再次停止。"},
    {"项目负责人": "这些情况能稳定复现吗？", "高级工程师": "固定起点和输入序列，每次从同一个位置出发。"},
    {"项目负责人": "验收时我需要哪些材料？", "高级工程师": "我会提供场景、输入步骤，以及实际测试的提交编号。"},
    {"项目负责人": "我按四向撞墙和贴墙转向两项验收。", "高级工程师": "我负责实现并提交刚才约定的复现场景。"}
  ],
  "decisions": ["采用四向移动并支持沿墙转向。"],
  "user_decisions": [],
  "open_questions": [],
  "items": [
    {"key": "walls", "role": "高级工程师", "prefix": "Dev", "title": "墙体碰撞", "goal": "阻止穿墙。",
     "criteria": ["四向正面撞墙均停止", "贴墙转向后可沿墙移动"]}
  ]
}
```

## 存储约定

`AT.json` 使用 `agent-team/v2`，存放在普通项目根目录。项目锁与待重试记录在 `.at-state/`。`team_repo` 指向 `public/<远程仓库名>/`，目录名去除末尾的 `.git`。每个 `AT_<角色名>/` 都是独立的本地 Git 仓库，跟踪档案、记忆、个人技能和需求，并忽略整个 `repository/`。该目录内的 `repository/<远程仓库名>/` 是共享仓库的角色工作树，可在其旁存放其他独立仓库。跨角色分派会分别提交到各需求所属角色的仓库。各角色的 `report/` 保存本机阶段成果，Git 只跟踪目录占位。项目级程序包、用户指南、甲方总览分别保存在 `publish/bin/`、`publish/user/`、`publish/dev/`。Obsidian 笔记保存在选定库的角色子目录。

每份需求是规范 UTF-8 Markdown，包含原始 JSON 数据块与追加事件。正文中的稳定编号用于会议引用和重试。文件名如 `AT-Design00001-首领规则.md`，以成员登记的 `task_prefix`（1–24 个英文字母，项目内唯一）和角色自己的五位流水号开头。中文概括取 `summary` 或短标题，最多 40 字；脚本替换 Windows 文件名禁用字符。流转沿用原文件名。查询、说明、修订和流转可用原始 `id` 或当前文件的精确 `path`（绝对或相对项目根目录），旧式编号文件也可读取。
