# 宿主清单与验收

## Codex

默认通过当前设备的 Codex App Server 查询同一工作区，精确匹配所有返回项，包括 `enabled: false`。先对照当前 Agent 的技能来源；客户端有额外根时传入其实际值。对直接扫描源码的额外根，使用原客户端的配置入口移除该根；进程级额外根可通过 `skills/extraRoots/set` 提交保留其他项的新列表，持久化配置也应同步更新。仅在实际更改生效后，使用 `verify --removed-extra "<该根>"` 同步本次复查参数。

原活动服务提供控制套接字时，可以在 prepare 时用 `--codex-socket "<该套接字路径>"`，通过 `codex app-server proxy` 对同一服务盘点和验收。移除客户端附加根后，用此连接或原客户端的新快照完成验收。

若活动客户端的插件、远端或自定义来源与独立 App Server 不同，直接在活动客户端调用 `skills/list`（原 cwd、`forceReload: true`）。将该 cwd 返回的 `skills`、`errors` 及 `complete`（本次成功且 errors 为空）写入下述快照信封。后续始终取同一来源。简短的聊天技能提示可能截断。

通过注册名启动卸载时，第一次盘点应能找到实际调用的 `at-uninstall`。若启动入口或会话已知的来源与清单不符，切换到原活动服务核查后再操作。旧版用户直接从下载仓库读取本说明时，清单中可以没有 `at-uninstall`。

## DeepSeek Harness

优先在原 Harness 的宿主上下文调用 runner 旁 `dsh-snapshot.mjs` 导出的 `observe(ctx, agent, session, challenge, signal)`。传入**正在处理本次请求的 agent** 和真实会话 ID，以便查询该作用域上的所有提供方。把返回值原样写为 UTF-8 JSON。文件监听刷新需要时间；仍显示上次的入口时，在下一步重新查询。

普通聊天只有模型工具时，也可以用当前会话的完整目录更新和 `skill` 工具逐名检查。确认宿主完成发现（无 incomplete 提示），逐一查询本轮的 16 个名称，仅记录查询结果。已加载正文记 `FOUND`，明确“不允许模型调用”记 `SKILL_NOT_MODEL_INVOCABLE`，明确“unknown or no longer available”记 `SKILL_NOT_FOUND`；工具不可用、超时、目录发现失败或其他歧义均记 `UNKNOWN`。发现的技能正文仅用于识别来源，不执行业务。将实际入口绝对路径写入 `path`；工具只返回目录时，读取其 SKILL.md 核对名称。对于扁平文件和路径不明的条目，核对当前会话技能选择器的来源。只看到名称建议框为空不能证明清单完整。

两种取证方式都使用原会话、原 cwd 和 runner **最近一次输出的 challenge**。每次 `inventory` 或 `verify` 重新查询宿主，不能将历史聊天记录或磁盘扫描结果当成宿主清单。若当前版本不能提供完整证据，报告“未能验证”。使用 `--snapshot` 传入的文件放在 runner 目录内。

逐名工具模式要求该版本的 `skill` 工具能明确区分“未注册”和“禁止模型调用”。无法区分时使用宿主快照，或保留“未能验证”。

| 快照字段 | 含义 |
|---|---|
| host、session、cwd、challenge | 发起此次查询的宿主标识（codex 或 dsh）、真实会话 ID、原工作目录和本次查询标记。Codex 使用 prepare 时的 session，默认空字符串。 |
| complete | 宿主明确完成了本次发现时为 true。 |
| skills | 宿主返回的完整注册项数组；每项含 name，以及宿主提供的 path、source、provider。 |
| probes | DSH 工具逐名模式下替代 skills。键为全部 16 个正式名称，值为含 code 和可用 path 的对象。 |

DSH 可在文件系统提供方的 `customSkillDirs` 中解除单个源码扫描根；从当前配置层读出并保留其他项，等待配置重载。使用工作区或用户技能根中的链接时，只解除入口链接。用户范围的共享 `.agents/skills` 可能同时供两个宿主使用。

宿主接口见 [Codex App Server](https://developers.openai.com/codex/app-server/) 和 [DeepSeek Harness 技能注册表](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/skills.zh.md)。
