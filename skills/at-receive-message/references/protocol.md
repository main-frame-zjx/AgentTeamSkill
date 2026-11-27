# 本地通讯接口

服务名为 `agent-team-chat`。每个 MCP 工具均需当前会话的绝对 `working_dir`。在项目根指定 `role`，在角色目录按该角色运行。模型优先使用明确的传入值，`auto` 依次读取 AT_AGENT_MODEL、CODEX_MODEL、OPENAI_MODEL、GEMINI_MODEL、ANTHROPIC_MODEL、DSH_MODEL。“用户”表示本人决定，记作 human。

| MCP 工具 | 输入与结果 |
|---|---|
| chat_receive | 可传 role、limit、cursor、include_recent_context。按 P0–P3 和项目内消息序号读取，返回 messages、pending_total、next_cursor 与 warnings。传回 next_cursor 继续。 |
| chat_settle | model、handle、send。handle 每项含 message_id、resolution、note。send 每项须含 task_id 或 group_id、kind、to、body、idempotency_key，可加 refs、reply_to 和 event_key。 |
| chat_create_group | slug、title，显式建立专题群。需求群在首次发信时建立。 |
| chat_groups | only_pending、include_archived、version 可选，返回群组与按接收者计数的项目待办。 |
| chat_history | task_id 或 group_id，可传 status、offset、limit，返回 messages、当前需求及 next_offset。 |

单条正文最多 1500 字，至多 10 个引用。引用格式为 `{"path":"public/代码库/说明.md","lines":"4-12","note":"接口约定"}`。收件、工作清单、查看历史均保留 pending。仅可处理发给自己的消息，replied 可核对同群本人已发出的一个或多个 reply_to，返回 reply_message_ids。deferred 将 note、模型、时间和关联澄清保存在本接收者的 blocked 字段，返回 deferred 数组并继续计入 pending。

```json
{"working_dir":"D:/项目/AT_验收人","model":"gemini-series","handle":[{"message_id":"MSG-000001","resolution":"accepted","note":"逐项通过，需求已归档"}],"send":[]}
```

CLI 通过 `python -B -X utf8 "<本技能>/scripts/at_chat.py" <命令> --root "<项目或角色目录>" --input "<UTF-8 JSON 或 ->"` 调用，返回 `{ok,result}` 或 `{ok:false,error}`。MCP 工具依次对应 receive、settle、create-group、groups、history。另提供 summary、workflow、send（sender_model 和单条发送字段）、handle（model、items）及 reopen（model、items 每项含 message_id 和纠错 note，保留原处理记录）。初次使用通讯的 v3 项目只读返回 initialized: false，首次有效写入会创建通讯区。只读空输入可省略。项目外路径、身份不符、非法路径、键冲突及锁超时均返回错误。遇坏群文件时核对 warnings 再报告未处理总数。
