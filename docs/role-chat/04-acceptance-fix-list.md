# AgentTeam 角色通讯三产品 · 验收修复建议清单

> **验收范围**：对当前实现的产品一（`skills/at-receive-message/scripts/` 通讯内核与 MCP/CLI）、产品二（新旧技能、`install.py`、`at-uninstall`、`dev-visual/skill-relation.json`、`README.md`）、产品三（`chat-visual/`、`tools/windows/`、`at-start-board`）及配套 `tests/` 进行代码审查与实机边界复现验收。\
> **配套设计文档**：\
> - [01-lightweight-messenger-design.md](01-lightweight-messenger-design.md)\
> - [02-skills-and-workflow-design.md](02-skills-and-workflow-design.md)\
> - [03-chat-visualizer-html-design.md](03-chat-visualizer-html-design.md)
>
> **总体评价**：整体骨架与既有规范对齐度较好，WAL 崩溃恢复事务日志（`.at-state/chat-transaction.json`）、游标分页快照、4 个 Windows 桌面快捷方式与 3 服务托管、以及现有自动化测试（`tests/` 43 项、`dev-visual/tests/` 4 项、`board/` 5 项）均运行通过。以下列出实测复现出的 **P0 必修复项**、**P1 重要修复项**、**P2 文档同步项**，以及**经共识暂不调整项**。

---

## 经共识暂不调整项（本次修复请勿改动）

1. **单会话单角色 / 单项目进程 `cwd` 绑定机制**：AgentTeam 明确设计为一个 AI 会话只扮演一个角色、只处理一个项目（`at-team-discuss` 开会除外，其通过独立 subagent 分演角色），因此维持既有基于会话工作目录的角色隔离，不做“单 MCP 进程跨项目/跨角色切换”的改造。
2. **项目根目录 `$at-help` 未处理消息推荐提示**：暂不扩展，维持现有仅在角色目录按未处理消息优先推荐 `$at-work` 的行为。
3. **`chat-visual/index.html` 引用仓库相对静态资源**：维持对 `../dev-visual/vendor/markdown-it.min.js` 与 `../tools/windows/icons/agentteam-chat.ico` 的相对引用，暂不单独复制独立副本。

---

## 一、P0 必修复项（实战阻塞与明显逻辑错误）

### P0-1：解除 `review_request` / `review_rejected` 对事件公式的过度死锁，恢复多接收者与改派能力

- **涉及文件**：
  - `skills/at-receive-message/scripts/chat_core/engine.py`（L95-L101）
  - `skills/at-receive-message/scripts/chat_core/tasks_bridge.py`（L23-L41）
  - `skills/at-reply-message/SKILL.md`（L10）
  - `skills/at-work/SKILL.md`（L11、L17）
  - `tests/test_chat.py`
- **现状问题**（均已实测复现）：
  1. `engine.py:98` 硬性校验 `recipients == actual["to"]`（永远只有 1 人 `[target]`），**直接封死了多接收者场景**（例如送验时同时提醒 `[项目负责人, 策划]`，或打回时同时通知 `[高级工程师, 项目负责人]`，直接报错拒绝）。
  2. `engine.py:99` 将 `idempotency_key` 死绑为 `f"{kind}/{task['id']}/{event['key']}"` 隐藏公式。若 AI 在独立会话或未保留 `move` 回执时自行传入常规幂等键（如 `"review-r1"`），会被直接拦截，极易造成模型调用反复失败。
  3. **改派验收人后死锁**：需求处于 `3待验收` 时，若由项目负责人 B 通过 `amend` 将验收人改派给 C，`tasks_bridge.py:39` 返回的 `actor` 仍取旧 `move["actor"]`（原工程师 A），导致执行改派的 B 无法向 C 发送 `review_request`（实测报错拒绝）。
  4. 为配合该强耦合机制，在 `$at-work` 中引入了“开工先调一次 `$at-reply-message` 补发 `missing_notifications` + 收尾再调一次 `$at-reply-message`”的冗余往返。
- **修复要求**：
  1. 取消 `engine.py` 对 `review_request` / `review_rejected` 必须精确匹配隐藏公式 `idempotency_key` 和单人 `recipients == actual["to"]` 的硬锁死。
  2. 保留轻量的领域合理性校验即可：
     - `review_request` / `review_rejected` 必须发在存在的 `task:` 需求群；
     - `review_request` 要求目标需求当前处于 `3待验收`，且 `to[]` 至少包含需求当前有效 `reviewer`（允许额外抄送其他注册角色）；
     - `review_rejected` 要求目标需求当前处于 `2处理中`（且存在退回记录），且 `to[]` 至少包含需求所属 `owner`（允许额外抄送其他注册角色）。
  3. 改派验收人后，允许执行改派的角色或需求所属角色向新验收人发送 `review_request`；`move.notification` 保留作为**建议模板元数据**（供 AI 省事复用），但不再作为强制暗号门槛。
  4. 简化 `$at-work` 流程，不再强制一轮内调用两次 `$at-reply-message`（统一在收尾集中结算）。

---

### P0-2：消除单份坏需求雪崩瘫痪 + 兼容尚无 `public/chat/` 的既有 v3 项目 + 修正 `guidance.py` 报错路径

- **涉及文件**：
  - `skills/at-receive-message/scripts/chat_core/tasks_bridge.py`（L14-L20）
  - `skills/at-receive-message/scripts/chat_core/engine.py`（L254）
  - `skills/at-receive-message/scripts/chat_core/store.py`（L68-L70、L116-L135）
  - `skills/at-init-team/scripts/guidance.py`（L99-L115）
  - `chat-visual/serve.py`（L30-L44）
- **现状问题**（均已实测复现）：
  1. **单文件故障雪崩**：`engine.py:254` 对除 `summary` 外的全部命令都无条件调用 `tasks_bridge.snapshots(root, data)`，后者遍历所有角色的 `role_tasks(..., repair=False)` 且无 `try/except`。只要项目中任意一个角色存在 1 份格式损坏或中断流转的需求文件，**全项目所有群组（包含完全无关的专题群 `topic:`）、所有角色的 `receive`/`settle`/`groups`/`history` 以及 `chat-visual` 网页全部崩溃**。
  2. **既有 v3 项目（未初始化 `public/chat/`）直接崩溃**：`store.py:69` 直接读取 `public/chat/meta.json`，在旧版 `agent-team/v3` 项目上调用 `at-help`、`work-context`、`summary`、`chat-visual` 均直接抛出 `FileNotFoundError`。
  3. **`guidance.py` 嫁祸错误路径**：`guidance.py:105` 调用 `chat_run("summary", start, {})` 前未更新 `check_path`（仍停留在 L99 的 `.at-state/releases.json`），一旦通讯目录缺失或损坏，`at-help` 返回的故障文件错误指向 `.at-state/releases.json`。
- **修复要求**：
  1. `tasks_bridge.snapshots()` 改为按文件/按角色容错读取（参考 `board/server/project.mjs`），将损坏或异常的需求文件记录到 `warnings` 中，不阻断其他正常需求和群组的收发与查看（仅当用户显式操作该损坏需求对应的 `task:` 群时才返回清晰错误）。
  2. `store.py` 在 `public/chat/meta.json` 不存在时：
     - **只读命令**（`summary` / `receive` / `groups` / `workflow` 及 `chat-visual/serve.py`）优雅返回 `initialized: false`、`groups: []`、`pending_total: 0` 与提示信息，不抛 `FileNotFoundError`；
     - **写入命令**（`send` / `settle` / `create-group`）在确认为合法 `agent-team/v3` 项目时可自动补建 `public/chat/`（或返回明确引导信息）。
  3. `guidance.py` 在调用 `chat_run("summary", ...)` 前先将 `check_path` 更新为当前项目的通讯目录 `meta.json` 路径，确保异常定位准确。

---

### P0-3：修复 `chat-visual/serve.py` 子线程 Tkinter 弹窗风险与 `app.js` 角色视角“自己发的消息全标未读”逻辑 Bug

- **涉及文件**：
  - `chat-visual/serve.py`（L151-L159）
  - `chat-visual/app.js`（L65-L67、L167、L217-L218）
- **现状问题**：
  1. **Windows 多线程 Tkinter 崩溃/遮挡风险**：`serve.py` 使用 `ThreadingHTTPServer`，`/api/projects/pick` 在 HTTP 工作线程直接调用 `tkinter.Tk()` 且无防重入锁、未设置顶属性。Windows 下多线程/并发点击“打开项目”存在 `RuntimeError: Calling Tcl from different apartment` 崩溃风险，且文件夹对话框常被浏览器遮挡在后台。
  2. **角色视角未读与筛选逻辑 Bug（已确认）**：
     ```js
     function statusOf(m, role) {
       return role ? m.recipients[role]?.status : m.overall_status;
     }
     // card():
     const box = el("article", null, statusOf(m, role) !== "handled" ? "unread" : "");
     ```
     当切换角色视角（如选择“高级工程师”）时，`chat()` 展示了该角色发出的消息（`m.sender === role`），此时 `m.recipients[role]` 为 `undefined`：
     - `undefined !== "handled"` 为 `true`，导致**该角色自己发出的所有消息（即使对方早已处理归档）全部被错误标上橙色 `.unread` 未读边框**；
     - 若再叠加筛选状态 `"handled"`，`status === statusOf(m, role)` 比较 `"handled" === undefined` 为 `false`，导致该角色发出的已处理消息全部消失。
- **修复要求**：
  1. 参考 `board/server/picker.mjs` 与 `board/server/http.mjs` 的实现：`/api/projects/pick` 增加互斥锁（`picking`，并发请求返回 `409`），在 Windows 上通过独立子进程（如 PowerShell `FolderBrowserDialog` 或独立 Python 进程，设置窗口置顶）弹出文件夹选择器，彻底避免在 HTTP 工作线程中实例化 `Tk()`。
  2. 修正 `app.js` 的 `statusOf(m, role)` 逻辑：
     - 当 `role` 位于 `m.recipients` 中时，返回 `m.recipients[role].status`；
     - 当 `role` 是发送者而非接收者时，回退返回 `m.overall_status`；
     - 未读高光 `.unread` 仅用于“当前筛选视角下确为未处理/待办”的消息，并对“发给我的待办”和“我发出等别人处理”在样式上做出清晰区分。

---

## 二、P1 重要修复项（协议细节、Skill 流程、安装卸载与可视化体验）

### P1-1：补齐通讯内核与 MCP 协议校验漏洞

- **涉及文件**：
  - `skills/at-receive-message/scripts/chat_core/engine.py`（L87、L147-L150）
  - `skills/at-receive-message/scripts/at_chat_mcp.py`（L47、L51-L64、L87-L94、L107-L110、L124、L134-L135）
  - `skills/at-receive-message/scripts/chat_core/store.py`（L42-L56、L87）
- **现状问题**：
  1. **允许自发自收**：`engine.py:87` 仅校验 `recipients != [role]`，传入 `to: ["甲", "乙"]` 时允许发送者把自己加入接收者列表，立刻给自己制造未处理待办（已实测复现）。
  2. **`replied` 限制过死且缺少 `deferred`**：`engine.py:147-150` 强制 `replied` 必须同次提交**恰好 1 条** `reply_to` 回复，导致分两步 `send` + `handle` 无法核销为 `replied`（已实测复现），也无法对单条复杂消息拆发两条定向回复；同时砍掉了设计文档中的 `deferred`（阻塞结转）结论。
  3. **MCP `validate()` 漏校验 + 兼容边界缺陷**：
     - 声明了 `minLength: 1`、`minimum: 0` 却未在 `validate()` 中校验（已实测 `version: ""`、`limit: -5` 均穿透）；
     - `chat_history.status` 缺少 `enum(("pending", "handled", "partial"))`；
     - 未知工具名抛出原始 `KeyError` 字符串；
     - `at_chat_mcp.py:124` 若宿主传入 `capabilities: {"roots": null}` 或 `capabilities: null` 会异常，且若宿主响应 `roots/list` 返回空列表 `{"roots": []}`（部分宿主未显式配置 roots 时的默认返回）或错误，会误拦正常的单角色会话调用。
  4. **存储校验与警告路径泄漏**：`store.py:42-56` 未校验 `seq` 为正整数、群内递增、`< meta["next_seq"]` 及全局唯一；L87 拼出的 `warnings` 暴露宿主机绝对路径且混用 `\` 与 `/`。
- **修复要求**：
  1. `engine.py:87` 改为禁止 `role in recipients`（同时保持禁止 `"*"` / `"all"`）。
  2. `engine.py:147-150`：`replied` 允许同次提交 `>= 1` 条 `reply_to` 回复，**或**同群组历史上已存在由当前角色发出且 `reply_to == mid` 的消息（支持断点补核销与两步 CLI）；恢复 `deferred` 结论（用于明确记录阻塞并转交澄清的场景，或仅当已发反问/记录阻塞时允许）。
  3. `at_chat_mcp.py`：
     - `validate()` 实际校验 `minLength`、`minimum`；
     - `chat_history.status` 改为 `enum(("pending", "handled", "partial"))`；
     - `name not in TOOLS` 返回清晰的中文工具不存在报错；
     - 安全读取 `(params.get("capabilities") or {})`；仅当宿主返回**非空** `roots` 列表时执行工作区边界拦截（若宿主未返回有效 root 列表则不误杀正常单角色调用，同时把通讯报错文案从 `versions.py` 的“发布请由项目负责人执行”解耦为通讯专用中文提示）。
  4. `store.py` 补齐 `seq` 唯一性与单调性校验；`self.errors` 统一使用相对项目根目录的 POSIX 路径（如 `public/chat/groups/xxx.json: ...`）。

---

### P1-2：重构 `at-work/SKILL.md` 与 `at-reply-message/SKILL.md`，落实现场清单闭环与反闲聊红线

- **涉及文件**：
  - `skills/at-work/SKILL.md`
  - `skills/at-work/references/checklist-and-comms.md`
  - `skills/at-reply-message/SKILL.md`
  - `dev-visual/skill-relation.json`
- **现状问题**：
  1. `skills/at-work/SKILL.md` 的 frontmatter `description` 仍是旧版，未体现收发消息、工作清单与终检。
  2. 正文仍采用旧的 1~8 扁平流水账，**核心 P0~P3 优先级规则与未做完保留 `pending` 的红线被藏在二级文件 `checklist-and-comms.md` 中**；且第 2 步末尾写了“逐项执行其余工作……调用 `$at-review-work`”，与后面第 3~7 步开发送验流程逻辑顺序倒置；末尾未提 `agent-team-chat` MCP 入口。
  3. `skills/at-reply-message/SKILL.md` 未明文写入“禁止闲聊与礼貌性空回复（如收到/谢谢/辛苦了）”“禁止粘贴大段文件或发附件，仅引相对路径”，也未标明 MCP 必填参数名 `working_dir`（绝对路径）。
- **修复要求**：
  1. 按设计文档 [02-skills-and-workflow-design.md](02-skills-and-workflow-design.md#L186-L246) 重排 `skills/at-work/SKILL.md`：
     - 更新 frontmatter `description`；
     - 清晰划分为四个阶段：**阶段一：启动感知与收取新消息** → **阶段二：制定本轮工作清单（动手前强制列出 P0~P3 编号清单与固定收尾项）** → **阶段三：按清单逐项执行（先验收/协作、再推进自有需求开发交付）** → **阶段四：收尾结算（`$at-reply-message` → `$at-manage-memory`）与对照清单终检**；
     - 消除第 2 步与第 3~7 步的顺序冲突，在文末明确写出 `agent-team-chat` MCP 主入口与 CLI 兜底入口。
  2. 在 `skills/at-reply-message/SKILL.md` 顶部和步骤中明确写入反闲聊红线、路径引用红线与 MCP 必填 `working_dir` 字段，去除对内部 `move.notification` / `missing_notifications` 的强绑定表述。
  3. 文档修改后，使用 `.agents/skills/update-skills-relation` 重建 `dev-visual/skill-relation.json`（同步刷新 `at-work` 简介与触发引文）。

---

### P1-3：加固 `install.py` 与 `at-uninstall` 在无 `codex` CLI 或虚拟环境下的健壮性

- **涉及文件**：
  - `skills/at-uninstall/scripts/chat_registration.py`（L13-L30、L41-L50）
  - `skills/at-uninstall/scripts/uninstall.py`（L114、L133-L134）
  - `install.py`（L100-L102）
- **现状问题**（已实测复现）：
  1. `uninstall.py:114` 在 `host == "codex"` 且存在 marker 文件时，未捕获 `chat_registration.status()` 抛出的异常。若机器 PATH 中无 `codex`（例如采用 `--snapshot` 离线快照验收），整个 `inventory` / `verify` 直接崩溃退出。
  2. `install.py` 默认调用 `chat.register(dest)`，若本机 PATH 未安装 `codex` CLI，会在 16 个技能全部装完后直接报错以退出码 1 中断；且 `chat_registration.config()` 直接固化当前 `sys.executable`，若在临时 venv 中执行安装，删除 venv 后已注册的 MCP 即失效。
- **修复要求**：
  1. `uninstall.py:114` 增加异常捕获：查询 MCP 状态失败时将 `mcp` 记为 `"error"` 并把具体原因写入 `errors`（标记 `complete: false` 或 `done: false`），确保能正常输出 16 行技能盘点表与诊断结果，而非直接崩溃。
  2. `chat_registration.py`：若未检测到 `codex` CLI，支持安全回退或明确区分退出行为（如支持直接幂等读写 `$CODEX_HOME/config.toml` 的 `[mcp_servers.agent-team-chat]`，或提供清晰可复制配置而不让已完成的技能安装前功尽弃）；检测到 `sys.prefix != sys.base_prefix`（处于虚拟环境）时优先解析基础 Python 解释器或给出醒目提示。

---

### P1-4：完善 `chat-visual/` 可视化交互、安全防线与视觉辨识度

- **涉及文件**：
  - `chat-visual/serve.py`（L68-L117、L137、L168-L175）
  - `chat-visual/app.js`
  - `chat-visual/local.js`（L81-L111、L148）
  - `chat-visual/style.css`
  - `chat-visual/index.html`
- **现状问题**：
  1. **5 秒轮询暴力重绘打断阅读**：只要项目内任何群组有更新，`refresh()` 就执行 `$("content").replaceChildren(...)`，导致滚动条回弹顶部、用户展开的「流转与追加记录」或「已归档需求群」瞬间折叠、文本选区被清空。
  2. **POST 防 CSRF 不严 + 缺少项目移除入口**：`serve.py:137` 在请求未携带 `Origin` 头时默认放行；且 `Registry` 只能添加不能移除，已删除的项目会永久残留在 `%LOCALAPPDATA%\AgentTeamChat\projects.json` 并持续弹警告。
  3. **存在未接通的死代码**：前端轮询始终全量拉 `/snapshot`，后端 `/overview` 和 `/groups/<id>` 未被调用；`app.js:133` 请求 `/file` 未传 `lines` 参数，导致后端 `highlight` 解析成为死代码。
  4. **视觉语义与交互体验缩水**：
     - 5 种消息类型全用同一灰绿 `.chip`，**验收打回无红色警示、送验提醒无紫色区分**；
     - 模型徽章漏掉 `claude` / `deepseek` / `human` / `other` 样式，`.gpt` 漏写文字色；
     - 导航按钮「待办总览」缺少未处理计数角标；左栏群卡片缺少最新消息预览与时间；中栏顶部缺少需求阶段/所属/验收人上下文横幅；
     - 复制路径按钮无任何“已复制”反馈；文件预览用居中模态 `<dialog>` 遮挡聊天正文，无法边看消息边对照代码；
     - `local.js:148` 的 `preview` 未截断长正文，且 `file://` 模式下任一角色 workspace 目录缺失时 `src.list()` 直接抛异常中断全页加载。
- **修复要求**：
  1. **无打断刷新**：刷新前记录当前滚动位置、焦点和已展开的 `<details>` 标识并在更新后恢复（或仅在数据变化时增量更新节点；用户在群聊向上翻看历史时于底部浮出「有新消息」提示而非强行跳顶）。
  2. **安全与项目管理**：所有 `POST` 接口强制校验同源 `Origin` 且携带自定义头（如 `X-Chat-Request: 1`，对齐 `board/server/http.mjs`）；增加 `POST /api/projects/<id>/remove` 与前端「从列表移除」操作。
  3. **清理死代码**：`filePreview` 传递 `lines` 参数（或统一由一端高亮）；前端按 `/overview` + 按需 `/groups/<id>` 拆分加载，或明确精简服务端接口。
  4. **补齐视觉与交互**：
     - 按 [03-chat-visualizer-html-design.md](03-chat-visualizer-html-design.md#L228-L256) 为 5 种 `kind` 与 6 种 `model_family` 配置明确语义色；
     - 顶栏「待办总览」显示待办总数角标，左栏群卡补充最新摘要与时间，中栏头部补充需求状态横幅；
     - 「复制路径」点击后按钮短暂变为「已复制 ✓」（兼容剪贴板失败提示）；文件预览改为可与聊天正文对照的侧边抽屉（或支持在右栏「文件预览」Tab 打开）；
     - `local.js` 对 `preview` 截断（如前 160 字），并在 `tasks()` 遍历角色目录时逐目录/逐文件 `try/catch` 降级记录到 `warnings`。

---

## 三、P2 文档同步项

### P2-1：同步更新 `README.md` 滞后信息

- **涉及文件**：`README.md`（L74-L76、L112）
- **现状问题**：
  1. L74–76 技能总表中 `$at-receive-message`、`$at-reply-message` 描述过于简略，`$at-work` 仍是旧版描述（未体现收发消息与清单终检）。
  2. L112 仅写配置与日志保存在 `%LOCALAPPDATA%\AgentTeamBoard`，未同步说明角色通讯的本机项目配置保存在 `%LOCALAPPDATA%\AgentTeamChat`。
- **修复要求**：
  1. 对齐更新 `README.md` L74–76 的三行技能描述与适用时机，与新版 `SKILL.md` 保持一致。
  2. 在 L112 补充 `%LOCALAPPDATA%\AgentTeamChat` 的说明。

---

## 四、回归测试补充清单

完成上述修复后，需补充并运行以下回归测试（全部通过后视为验收达标）：

1. **`tests/test_chat.py`**：
   - 送验 `review_request` / 打回 `review_rejected` 支持多位接收者与常规自定义 `idempotency_key`；改派验收人后由改派人发送 `review_request` 成功。
   - 发送者把自己包含在 `to: ["甲", "乙"]` 中被明确拒绝。
   - 分两步 `send(reply_to=m1)` 后再 `handle(m1, resolution="replied")` 成功；支持 `deferred` 结论。
   - 单角色存在一份坏需求 Markdown 时，其他角色和专题群的 `receive`/`settle`/`groups` 仍正常工作并返回 `warnings`。
   - 尚无 `public/chat/` 的既有 `agent-team/v3` 项目调用 `summary`/`groups`/`help`/`work-context` 不崩溃且不报错指向 `.at-state/releases.json`。
   - MCP `validate()` 拦截空字符串 `minLength: 1`、负整数 `minimum: 0`、非法 `chat_history.status`；宿主返回空 `roots: []` 时单角色正常调用不被误杀。
2. **`tests/test_uninstall.py` / `tests/test_chat_install.py`**：
   - 存在 MCP marker 但 PATH 无 `codex` 时，`uninstall.py inventory/verify` 不崩溃并输出完整诊断结构。
   - 无 `codex` CLI 时 `install.py` 的降级/友好提示行为验证。
3. **`tests/test_chat_viewer.py` & 新增 `chat-visual/tests/test_ui_logic.mjs`**：
   - `serve.py` 拦截无 `Origin` 或缺 `X-Chat-Request` 头的 `POST` 请求；支持 `POST /api/projects/<id>/remove` 移除失效项目；对尚无 `public/chat/` 的旧 v3 项目返回空态快照而非 HTTP 400。
   - 新增免浏览器可运行的 Node 单测 `chat-visual/tests/test_ui_logic.mjs`：覆盖 `statusOf(m, role)`（确保发送者自己发出的已处理消息不标 `.unread`、按 `"handled"` 筛选不丢失）、5 种消息类型与模型徽章映射、以及 Markdown 渲染防 XSS。
4. **`dev-visual/tests/`**：重跑索引校验与文档加载测试，确认刷新 `dev-visual/skill-relation.json` 后全绿。
