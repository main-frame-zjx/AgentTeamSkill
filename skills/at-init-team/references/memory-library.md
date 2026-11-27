# 有界工作记忆与个人学习库

共用入口和 JSON 输入方式见[命令接口](commands.md)。在角色目录运行可省略 `role`，在项目根传角色名。全项目笔记检索和巡检可直接从项目根运行。

| 命令 | 输入与结果 |
| --- | --- |
| `work-context` | 角色目录可省略 `role`；可选 `agent_sha256`、`memory_sha256`。一次只读返回 `Agent.md`、`handoff` 记忆、`.agent/` 个人技能、`1新需求`/`2处理中` 任务快照及代码工作树脏状态与落后 `origin/main` 提交数。角色目录内禁止代办其他角色。|
| `memory-read` | 返回实时渲染的六个槽位 `content`、语义条目、当前 `sha256`、候选总数和前三条。开工传 `view: handoff` 可省去与正文重复的语义字段；同会话传 `if_none_match`（上次 `sha256`）且记忆、实态均未变化且无手改/恢复提示时，仅返回 `unchanged: true` 省去正文。`stale_hints` 提示所引需求已归档。|
| `memory-sync` | 刷新本角色的磁盘文件，或传 `{"all":true}` 刷新全员。语义条目保留。|
| `memory-patch` | 传回 `expected_sha256` 和最小更新。新增条目由脚本分配 ID；修改传原 ID。完整操作见下文。|
| `memory-history` | `{"version":"v1.0"}` 返回正式发布时的记忆；`{"query":"D01","limit":5}` 查变更差异。历史文本最多 8 KiB，`truncated: true` 时缩小 `limit`、用更精确的词或按版本读取。|
| `library-index` | `query` 检索个人库标题、摘要、标签。默认 `scope: role`。传 `{"scope":"project","query":"输入"}` 检索全员笔记，按结果的 `role,path` 阅读。候选只返回指定或当前角色的条目，项目根未选角色时为空。可用 `task_id` 或 `version` 筛选候选，用 `include_resolved:true` 查看已处理项。|
| `library-read` | `path` 是相对个人库的文件名，如 `系统设计/输入路由.md`。返回元数据、正文和 `sha256`。|
| `library-upsert` | 传结构化内容与 `expected_sha256`（新建为 null），跨角色同名时 `duplicate_title_warnings` 列出原作者与路径。成功项在 `completed`，修复操作在 `pending`。|
| `library-lint` | 检查全项目笔记属性、证据与双链，报告同名项。缺失的角色或分类目录列入 `issues`。加 `rebuild_moc:true` 可用可读笔记重建项目导航。|

## 更新交接现场

```json
{
  "role": "工程师",
  "expected_sha256": "<memory-read 返回的 sha256>",
  "focus": {
    "current_goal": "验证第二个手柄重连。",
    "progress": "已通过键盘和手柄的正常输入用例。",
    "next_step": "运行断开并重连第二个手柄的测试。"
  },
  "ops": [
    {"op":"upsert_decision","summary":"玩法层只接收语义动作。","ref":"meeting:public/meetings/input.md"},
    {"op":"upsert_risk","summary":"手柄重连仍待设备测试，工程师将在周五复核。","ref":"task:<稳定需求ID>"}
  ]
}
```

焦点可用空对象清除。决定与风险的修改沿用 `id`，移除分别用 `retire_decision`、`resolve_risk`。全文最多 6,656 个 UTF-8 字节，焦点最多 800 字节，决定最多 12 条且合计 2,200 字节，风险最多 6 条且合计 1,200 字节，语义栏预算包含渲染标签与来源。超量清单的完整内容可用 `list`、`library-index` 查询。

手改冲突时先读 `manual_diff`，将需要保存的改动整理进补丁，另附本次返回的 `manual_sha256` 作为 `merge_sha256`。原稿保存在项目的 `.at-state/memory-originals/<哈希>.md`。提交失败时先用 `memory-sync` 重试。只有角色记忆及其结构化状态进入本次 Git 提交。

## 候选与验收

在 `note` 或送验的 `move` 输入中加入：

```json
{"candidates":[{"key":"input-routing","kind":"system-design","topic":"双人输入的设备路由"}]}
```

需求和候选 key 共同确定候选 ID，贯穿返工、归档和重试。独立候选用 `memory-patch` 的 `queue_library`，传同样字段及 `source`（如 `meeting:public/meetings/input.md` 或 `version:v1.0`）。验收时按真实需求 ID 检索全队列。用 `assess_candidate` 记录 `id,status,reason`，状态为 `needs_evidence`、`dismissed`、`published` 或 `merged`。后两项还须传个人库中已存在的 `path`。写笔记时传 `resolve_candidate_id` 可一步完成入库登记。

## 编写学习笔记

```json
{
  "role": "美术",
  "trigger": "review",
  "resolve_candidate_id": "<library-index 返回的 ID>",
  "expected_sha256": null,
  "kind": "reusable-pattern",
  "title": "在目标尺寸验收道具图标",
  "admission": {
    "reusable_or_complete": "可在下一批同尺寸道具复用。",
    "beginner_value": "理解为什么画布放大后看不见轮廓混淆。",
    "evidence_refs": ["task:<已归档需求ID>", "file:public/道具对照.png"]
  },
  "meta": {"difficulty":"入门","summary":"将轮廓缩放到游戏实际显示尺寸后对照。","tags":["图标","验收"]},
  "sections": {
    "problem":"在画布上能清楚分辨的两件道具，缩到游戏内的尺寸后，外轮廓会合并成相似的色块。",
    "conclusion":"先在目标尺寸检查轮廓，再检查颜色。",
    "steps":"将各图标放入同一张对照图，统一缩放到游戏实际尺寸。",
    "verification":"隐藏颜色后，请未看过原图的人逐个辨认道具。若两件仍容易混淆，先调整外轮廓的缺口，再比较改动前后的样张。",
    "boundaries":"适用于固定尺寸的 HUD 图标。可缩放的界面还要检查各档尺寸。"
  }
}
```

`system-design` 使用 `design,tradeoffs` 替代 `steps,verification`。两类均要求 `problem,conclusion,boundaries` 和证据。可用的证据前缀是 `task:`（全项目的稳定需求 ID，跨角色可引用）、`meeting:`（实际返回的项目相对纪要路径）、`file:`（项目相对交付文件）、`code:`（团队主工作树内文件）、`commit:`（团队仓库 SHA）。阶段收口传 `trigger: milestone`，用户直接要求整理传 `trigger: explicit`，均需可复核的证据。必填章节的正文合计至少 300 个 UTF-8 字节，空白、章节标题、摘要和证据清单不计入。正文允许三级及以下小标题。整篇上限 12 KiB。

`meta` 可传 `version`、`tags` 和 `prerequisites`（双链数组）。前置阅读和替代笔记使用完整双链，如 `[[输入路由]]`。写入前核对目标已存在且唯一，同名时使用带项目和角色目录的链接。难度为入门、进阶或专题。替代旧方案时将旧文 `status` 设为 `superseded`，用 `replacement` 指向新文。项目导航列出生效笔记，用带目录的链接区分同名文章。脚本用标准库读取生成的 YAML 属性，也支持 Obsidian 常用的无引号文本和分行列表。

遇到 `pending` 时，笔记路径与哈希仍代表已写成的内容。导航失败可在处理原因后重跑 `library-lint` 并指定 `rebuild_moc`；角色记忆失败时按原输入重跑 `library-upsert`。若原文已被别人更新，先读取新哈希、合并后再提交。
