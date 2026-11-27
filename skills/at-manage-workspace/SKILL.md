---
name: at-manage-workspace
description: 查看和维护 Agent Team 需求文件，追加说明、修订验收条件，并在四个任务状态间流转。
---

# AT_manage_workspace

`note` 和送验 `move` 可附 `candidates` 数组，每项含稳定 `key`、`kind` 和 `topic`。同一需求及 key 标识同一候选。需求变更成功后若有 `pending_memory`，按返回角色恢复记忆刷新。

所有已有需求的修改均用本技能的 Python 入口。一次修改一个需求，写入稳定的事件 key，失败重试沿用同一输入。
- `list` 接受 `role` 和可选 `stages` 数组；`show` 接受 `role,id`，同时返回原始需求、当前有效条件及全部记录。
- `note` 接受 `role,id,key,actor,reason`，可记录阻塞、进度和证据。`amend` 另接受 `changes` 对象，允许修订 `goal`、`criteria`、`reviewer`。先了解用户或会议已决定的修改，保留原始规格；编号和负责人固定。
- `move` 接受 `role,id,key,actor,reason,from,to`。只允许 `1新需求 → 2处理中 → 3待验收 → 4已归档` 和 `3待验收 → 2处理中`。开始和送验由需求所属角色执行，验收或退回由验收人执行。actor 为“用户”仅用于记录用户本人明确作出的决定。
- 送验、退回、通过都须有 `evidence` 文本数组。送验记录实际验证和交付物，团队代码附已推送的提交 SHA；退回给出失败条件与复现依据；通过逐项列明检查结果。归档后可读取完整历史。

示例：`{"role":"高级工程师","id":"<需求编号>","key":"first-start","actor":"高级工程师","reason":"开始实现碰撞","from":"1新需求","to":"2处理中"}`。脚本负责移动、追加记录，并提交到需求所属角色的本地仓库；禁止手改需求文件或在资源管理器移动它们。

共用入口位于本技能目录的 `../at-init-team/scripts/at.py`。 将它解析为绝对路径后，从用户的项目上下文运行 `python -X utf8 "<入口>" <命令> --root "<项目目录>" --input "<UTF-8 JSON文件>"`。只读空输入可省略 `--input`。[命令接口](../at-init-team/references/commands.md) 给出了字段和重试约定。
