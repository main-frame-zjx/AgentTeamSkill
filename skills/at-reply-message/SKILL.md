---
name: at-reply-message
description: 结算角色已完成的收件，记录仍待跟进的阻塞，并向指定接收者发送送验、打回、协作或审阅提醒。
---

# AT_reply_message

消息用一两句写清下一步行动与依据。跳过闲聊、“收到”“谢谢”等空回复。文件只给项目根相对路径，可附行号和一句说明；不要发送附件或粘贴整段文件。

1. 用实际结果决定每位接收者的结论。已通过并归档用 `accepted`，已解决用 `resolved`，已知悉或确认已改派用 `noted`。验收人为用户时先取得本人结论。仍须等待输入用 `deferred` 写明阻塞，需要澄清时另发带 `reply_to` 的消息；原收件保留 pending。未着手的事项继续留在收件箱。
2. 退回给需求所属人发 `review_rejected`，首次或再次送验给当前有效验收人发 `review_request`，可抄送需要行动的其他角色。自己验收直接列入验收清单。验收通过只核销。协作、审阅、关键同步按需使用 `collab_request`、`review_feedback`、`info_sync`。需要通过回复履责时，在同群用 `reply_to` 关联原件，再以 `replied` 核销；同批外发及此前本人发出的关联回复都可追溯。
3. 核对需求当前事件。可直接采用流转回执或漏发清单中的建议字段，也可自行指定稳定的 `idempotency_key`。重试沿用原键与内容。需求已再次流转时采用对应的新事件。填写实际操作角色和模型，未知子版本时用已知系列。
4. 调用 `agent-team-chat` 的 `chat_settle`，传当前会话绝对目录 `working_dir`、`model`、`handle` 与 `send`，项目根另传 `role`。核对 `handled`、`deferred`、`sent`、`remaining_pending` 和 `warnings`。专题群可先用 `chat_create_group`。宿主未挂载 MCP 时使用同内核的[通讯 CLI](../at-receive-message/references/protocol.md)。
