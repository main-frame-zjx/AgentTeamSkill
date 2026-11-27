---
name: at-receive-message
description: 收齐当前角色在项目中的未处理提醒，按优先级与需求列出待办，保留各接收者的处理状态。
---

# AT_receive_message

1. 在角色目录使用当前角色，在项目根显式指定角色。通过 agent-team-chat 的 `chat_receive` 传入当前会话绝对目录 `working_dir`。默认每页 30 条，只要有 `next_cursor` 就用相同身份继续读取，直至本轮快照结束。initialized 为 false 表示项目尚无通讯记录。展示损坏群组等 warnings，区分“没有待办”和“部分数据无法读取”。
2. 按 P0 验收打回、P1 送验、P2 审阅反馈与协作、P3 关键同步排序。按需求合并工作项，保留每一个消息 ID、接收者、目标动作和证据路径。对带 blocked 记录的待办列出阻塞原因、所等输入和关联回复。需要上下文时用 `chat_history` 阅读群历史并核对需求最新阶段与验收人。
3. 收件全程只读。独立查询时向用户汇总待办；开工时把完整清单交给当前工作流。宿主未挂载 MCP 时用本技能的 CLI，调用及分页示例见[通讯协议](references/protocol.md)。
