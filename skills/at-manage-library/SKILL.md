---
name: at-manage-library
description: 在 Obsidian 中维护 Agent Team 角色个人知识库，沉淀可复用的方法、设计依据和问题解法。
---

# AT_manage_library

用 `project` 获取选定角色的 `library` 相对路径及项目 `vault`。根据本轮工作检索该子目录的现有 Markdown，可用 Obsidian 插件、CLI 或直接搜索文件。优先更新同主题笔记；主题独立时新建笔记。写出适用条件、结论及依据，适合时引用需求编号、提交或相关笔记。只有流水进度或没有新增知识时报告“无需更新”。

用 `library` 读取，如 `{"role":"高级工程师","path":"技术/墙体碰撞.md"}`。写入时增加完整 `content` 和读取返回的 `expected_sha256`（新笔记传 null）。笔记路径相对角色个人知识库；不能越界。并发冲突先重读合并。Python 可直接维护普通笔记。确需更名且存在反向链接时使用可更新链接的 Obsidian 操作。最后报告实际新增或更新的笔记。

共用入口位于本技能目录的 `../at-init-team/scripts/at.py`。 将它解析为绝对路径后，从用户的项目上下文运行 `python -X utf8 "<入口>" <命令> --root "<项目目录>" --input "<UTF-8 JSON文件>"`。只读空输入可省略 `--input`。[命令接口](../at-init-team/references/commands.md) 给出了字段和重试约定。
