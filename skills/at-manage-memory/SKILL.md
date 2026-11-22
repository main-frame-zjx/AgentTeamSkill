---
name: at-manage-memory
description: 根据角色的最新项目进展提炼 Memory.md，供下一次开工快速恢复中长期上下文。
---

# AT_manage_memory

先通过 `memory` 传入 `{"role":"高级工程师"}`，获取原文、字节数和 SHA-256。结合本轮真实工作、需求历史及上次记忆，保留项目阶段、仍生效的决定、跨任务依赖、阻塞与下一步。已交付的事项只保留对后续迭代有影响的结果；详细测试和逐步操作可用需求编号索引。内容无变化时直接结束。

需要改写时，再调用 `memory` 传入 `role,content,expected_sha256`，其中哈希必须取自刚才读取的版本。脚本检查并提交 UTF-8 正文，返回字节数与 `over_memory_target`。以 10 KiB（10,240 字节）为软目标，超出时优先合并重复项、将可复用细节提炼到知识库，再精简概述。发生并发变化时重新读取后整合。

共用入口位于本技能目录的 `../at-init-team/scripts/at.py`。 将它解析为绝对路径后，从用户的项目上下文运行 `python -X utf8 "<入口>" <命令> --root "<项目目录>" --input "<UTF-8 JSON文件>"`。只读空输入可省略 `--input`。[命令接口](../at-init-team/references/commands.md) 给出了字段和重试约定。
