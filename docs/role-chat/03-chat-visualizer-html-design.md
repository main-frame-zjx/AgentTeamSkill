# 产品三：AgentTeam 通讯内容可视化 HTML 项目设计文档

> **文档状态**：定稿设计（v1.1，已确认一期接入 `$at-start-board` 与桌面快捷方式、随 `$at-init-team` 初始化数据目录）\
> **实施修订（2026-11-27）**：默认首页为待办总览。直接打开 HTML 时使用普通脚本和浏览器目录选择，两种入口共用界面。HTTP 服务读取通讯内核的已提交快照，目录模式按同一事务记录和索引修订号取数。看板项目列表以只读方式导入，通讯查看器自己的选择保存在 AgentTeamChat 配置中。
>
> **配套文档**：\
> - [产品一：AgentTeam 轻量级角色沟通软件设计文档](01-lightweight-messenger-design.md)\
> - [产品二：新 Skill 设计与老 Skill 配套改动方案](02-skills-and-workflow-design.md)

---

## 1. 产品定位与技术架构选型

### 1.1 目标与使用场景
为用户提供一款**离线、轻量、高信息密度**的本地网页可视化工具，用来直观查看项目内各 AI 角色之间的沟通记录与待办积压情况：
- 一眼看清**当前哪些角色还有未处理消息**、分别关联哪个需求、卡了多久。
- 按需求群组浏览完整沟通脉络（送验提醒 → 验收打回 → 再次送验），清晰区分发送角色与背后的 **AI 模型（GPT / Gemini 等）**。
- 看聊天时直接对照**关联需求的实时阶段与验收条件**，点击消息里的文件路径即可在侧栏**只读预览项目文件片段**，无需来回切窗口。

### 1.2 技术架构选型与权衡

| 维度 | 选型方案 | 选型理由 |
| --- | --- | --- |
| **目录位置** | 仓库根目录 `chat-visual/`（与 `dev-visual/`、`board/` 平级） | 保持三类可视化工具结构对称；开发与测试边界清晰，不侵入现有 `board/` 的 Node 构建流。 |
| **本地服务** | **Python 3.11+ 标准库 `ThreadingHTTPServer`**（仅监听 `127.0.0.1`） | 零 `npm install`、零构建等待、零外网依赖；复用 AgentTeam 必备的 Python 环境，参考 `dev-visual/serve.py` 的极简稳定架构。 |
| **前端栈** | **原生 HTML5 + CSS3 + ES Module JS** + 内置离线 `markdown-it.min.js`（复用 `dev-visual/vendor/`） | 符合“无需高深复杂技术栈”的原则；页面秒开、体积 < 100 KB、无框架升级负担。 |
| **默认端口** | `47362`（紧邻项目看板 `47361`，支持 `--port` 指定或冲突回退） | 易记、无权限需求，不与技能手册 `8764` 和项目看板 `47361` 冲突。 |
| **项目列表复用** | **自动只读共享 `%LOCALAPPDATA%\AgentTeamBoard\projects.json`** + 支持 `--project "<路径>"` 直达 + 页面内本机文件夹选择器 | 用户在项目看板里添加过的项目，打开通讯可视化页面自动出现，无需重复添加！ |
| **无后端纯静态兜底** | 页面检测为 `file://` 协议时，自动切换为「本地目录直读模式」（利用现代浏览器 `showDirectoryPicker` 读取含 `AT.json` 的目录） | 即使不启动 Python 服务、直接双击 `index.html`，也能离线只读查看聊天记录（主推通过 `.bat` 启本地服务，以获得自动刷新与多项目记忆能力）。 |

> **生态定位说明**：\
> 一期即作为独立零 Node 依赖的轻量 HTML 项目 `chat-visual/`（端口 `47362`）落地，并**直接在一期接入 `$at-start-board` 与 `tools/windows/` 桌面快捷方式体系**（与项目看板、技能手册并列，由 `AgentTeamStopService` 一并安全停止），同时复用 `AgentTeamBoard` 的项目注册表与视觉语言。

---

## 2. 目录结构与模块职责

```text
chat-visual/
├─ 打开角色通讯.bat              # Windows 一键启动脚本（启动本地服务并打开浏览器）
├─ serve.py                      # 纯 Python 只读本地 HTTP 服务（127.0.0.1，含安全路径检查）
├─ index.html                    # 主页面骨架
├─ style.css                     # 视觉样式（延续 AgentTeam Board 的深青石板绿与温润纸感）
├─ app.js                        # 主状态管理、轮询刷新、路由与交互协调
├─ api.js                        # HTTP 模式与 file:// 目录直读模式的统一数据适配器
├─ render.js                     # 群组列表、结构化消息卡片、收件箱矩阵、需求/文件抽屉渲染
├─ mark.svg                      # 应用图标（SVG，离线零依赖）
├─ vendor/
│  └─ markdown-it.min.js         # 本地离线 Markdown 渲染器（禁用原始 HTML，防 XSS）
└─ tests/
   ├─ test_server.py             # 后端 API、路径越界拦截、坏文件降级单测
   └─ test_ui_logic.mjs          # 前端筛选、排序、状态聚合与安全转义单测
```

---

## 3. 后端只读 API 与安全边界设计

### 3.1 安全红线（完全对齐 `board/server/http.mjs` 与 `dev-visual/serve.py`）
1. **严格只读**：除“在用户配置中登记/切换项目目录”外，**绝不写入、修改或删除目标项目中的任何文件**。
2. **仅限本机回环**：强制绑定 `127.0.0.1`，校验 `Host` 请求头与 `Origin` 头（防止 DNS 重绑定或跨站请求）。
3. **严格路径越界防护与目录规则对齐**：复用 `resolveInside(root, ...)` 校验真实路径（`Path.resolve()` 后必须 `is_relative_to(project_root)`），拒绝符号链接逃逸与 `..` 穿越。读取通讯数据时与产品一采用同一目录解析规则：默认 `public/chat/`，当 `AT.json` 中 `team_repo` 目录名恰为 `chat` 时自动读取 `public/at-chat/`。
4. **安全响应头**：
   - `X-Content-Type-Options: nosniff`
   - `Referrer-Policy: no-referrer`
   - `Cache-Control: no-store`
   - `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'`
5. **文件只读预览限流与白名单**：仅允许预览项目内的 UTF-8 文本类文件（`.md`, `.py`, `.ts`, `.js`, `.mjs`, `.vue`, `.json`, `.yaml`, `.yml`, `.txt`, `.css`, `.html`, `.cs`, `.cpp`, `.h`, `.ps1`, `.sh`, `.toml`, `.ini` 等），单次返回上限 **256 KB**，超限截断并标注，禁止读取 `.git/` 与二进制文件。

### 3.2 REST API 契约

| 方法与路径 | 用途 | 核心返回结构 |
| --- | --- | --- |
| `GET /api/health` | 健康检查与进程身份校验 | `{"app": "agent-team-chat", "version": 1, "pid": 12345}` |
| `GET /api/projects` | 获取可选项目列表（合并 `--project` 与 `%LOCALAPPDATA%\AgentTeamBoard\projects.json`） | `{"active": "<id>", "projects": [{"id", "name", "root", "has_chat"}]}` |
| `POST /api/projects/pick` | 弹出系统文件夹选择框添加一个含 `AT.json` 的项目（仅存本地配置） | 同上 |
| `POST /api/projects/<id>/select` | 切换当前查看项目 | 同上 |
| `GET /api/projects/<id>/overview` | 获取项目通讯全局快照（支持 `If-None-Match` / 变更版本号 `etag` 轻量轮询） | 见下方示例 |
| `GET /api/projects/<id>/groups/<group_id>` | 获取单群组全部消息 + 绑定需求的实时详情（目标、验收条件、追加记录） | 见下方示例 |
| `GET /api/projects/<id>/file?path=<rel>&lines=<a-b>` | 只读预览消息中 `refs[]` 引用的项目文件（可选高亮行区间） | `{"path", "total_lines", "content", "truncated", "highlight": [a, b]}` |

#### `GET /api/projects/<id>/overview` 响应示例
```json
{
  "etag": "sha256-9a81f2...",
  "project": {
    "name": "坦克大战",
    "root": "D:/Projects/TankWar",
    "current_version": "v1.0",
    "roles": ["项目负责人", "高级工程师", "关卡策划", "美术设计"],
    "chat_dir": "public/chat",
    "has_chat": true
  },
  "stats": {
    "groups_total": 5,
    "messages_total": 18,
    "pending_total": 3,
    "by_role": {
      "高级工程师": {"pending": 2, "oldest_pending_at": "2026-11-27T10:42:18+00:00"},
      "项目负责人": {"pending": 1, "oldest_pending_at": "2026-11-27T11:10:05+00:00"},
      "关卡策划": {"pending": 0, "oldest_pending_at": null},
      "美术设计": {"pending": 0, "oldest_pending_at": null}
    },
    "models_seen": ["gpt-5.3-codex", "gemini-2.5-pro"]
  },
  "groups": [
    {
      "group_id": "task:AT-9f2a1c0b8e7d6c5b4a3f2e1d0c9b8a7f",
      "kind": "task",
      "title": "坦克撞墙停止",
      "task": {
        "code": "Dev00001",
        "owner": "高级工程师",
        "reviewer": "项目负责人",
        "stage": "2处理中",
        "version": "v1.0"
      },
      "message_count": 2,
      "pending_count": 1,
      "pending_recipients": ["高级工程师"],
      "last_message": {
        "id": "MSG-000002",
        "kind": "review_rejected",
        "sender": "项目负责人",
        "sender_model": "gemini-2.5-pro",
        "model_family": "gemini",
        "preview": "验收未通过，已退回 2处理中：最高速度下沿水平墙向右贴墙转向拐角时...",
        "created_at": "2026-11-27T10:42:18+00:00"
      }
    }
  ],
  "pending_items": [
    {
      "message_id": "MSG-000002",
      "group_id": "task:AT-9f2a1c0b8e7d6c5b4a3f2e1d0c9b8a7f",
      "group_title": "坦克撞墙停止",
      "task_code": "Dev00001",
      "recipient": "高级工程师",
      "sender": "项目负责人",
      "sender_model": "gemini-2.5-pro",
      "model_family": "gemini",
      "kind": "review_rejected",
      "preview": "验收未通过，已退回 2处理中...",
      "created_at": "2026-11-27T10:42:18+00:00"
    }
  ],
  "warnings": []
}
```

---

## 4. 前端信息架构与交互设计

### 4.1 整体界面布局（线框图）

```text
+---------------------------------------------------------------------------------------------------+
| [Mark] AgentTeam 角色通讯  | 项目: [坦克大战 v1.0 v] [+打开项目]  | [群聊视图] [待办总览(3)] | ⟳ 19:58 |
+------------------------+------------------------------------------------+-------------------------+
| [搜索群组/消息/编号...]  |  # Dev00001 · 坦克撞墙停止   [2处理中] [v1.0]    | [需求详情] [本群待办] [文件] |
|                        |  所属: 高级工程师  |  验收人: 项目负责人          |-------------------------|
| 筛选: [全部][未处理 3]   |------------------------------------------------| 目标：                  |
| 视角: [全部角色      v] | 过滤: [全部][未处理][已处理] [模型: 全部 v]     | 玩家坦克移动时保持在围墙 |
|                        |                                                | 以外。                  |
| -- 活跃需求群 (3) --   | +--------------------------------------------+ |                         |
| ▎Dev00001 坦克撞墙停止  | | [高] 高级工程师  [GPT · gpt-5.3-codex]     | | 验收条件：              |
|  [2处理中]    (● 1未办) | | [送验提醒]              2026-11-27 10:15   | | 1. 四向正面撞墙都停止   |
|  项目负责人: 验收未通过...| | To: @项目负责人 [✓ 已处理 · gemini-2.5-pro]| | 2. 贴墙转向可沿墙移动   |
|                        | | 已完成四向撞墙停止与贴墙转向，提交 8a3f2c1...| |                         |
|  Dev00003 炮弹反弹逻辑  | | 📎 AT_高级工程师/.../AT-Dev00001.md [预览] | | 最近流转：              |
|  [3待验收]    (● 1未办) | | 📎 AT_高级工程师/report/碰撞测试.html [复制]| | • 10:42 退回 2处理中    |
|  高级工程师: 已推送至...| +--------------------------------------------+ |   项目负责人：拐角越界  |
|                        |                                                | • 10:15 送入 3待验收    |
|  Art00002 坦克受击火花  | +--------------------------------------------+ |   高级工程师：自测通过  |
|  [4已归档]      已清零  | | ↩ 回复 MSG-000001（高级工程师 · 送验提醒）  | |                         |
|                        | | [项] 项目负责人  [Gemini · gemini-2.5-pro]  | |-------------------------|
| -- 专题协作群 (1) --   | | [验收打回]              2026-11-27 10:42   | | (点击消息中的文件时，    |
|  # v1.0 封版协调       | | To: @高级工程师 [● 未处理]                  | |  自动切到 [文件] Tab     |
|  [专题]        (● 1未办) | | 验收未通过，已退回 2处理中：最高速度下...   | |  展示带行号只读源码)    |
|                        | | 📎 public/tank_war/src/collision.py:84-112 | |                         |
| ▸ 已归档需求群 (1)     | +--------------------------------------------+ |                         |
+------------------------+------------------------------------------------+-------------------------+
```

### 4.2 核心视图与交互设计

#### 视图一：群聊视图（主视图，三栏结构）
1. **左栏：群组导航与视角过滤**
   - **默认排序**：优先将“存在未处理消息的群组”置顶，其内按最新消息时间倒序；已关联 `4已归档` 且无未处理消息的需求群自动归拢到底部可折叠分组「已归档需求群」，保持日常视野极度清爽。
   - **角色视角切换**：下拉选择某个角色（如“高级工程师”）后，群组卡片角标自动变为**仅针对该角色的未处理数**，中栏消息卡片对发给该角色的条目做左侧高光强调，方便用户代入某一角色审查待办。
   - **快捷筛选胶囊**：「全部」 / 「仅有未处理」 / 「仅需求群」 / 「仅专题群」 / 按迭代版本筛选。
   - **全局关键词搜索**：实时检索群组标题、需求编号、消息正文、发送者、模型名与引用路径。

2. **中栏：高信息密度结构化消息流**
   - **群组头横幅**：展示需求短编号（`Dev00001`）、标题、实时阶段胶囊（颜色与 `board/` 四泳道一致：新需求蓝 / 处理中琥珀 / 待验收紫 / 已归档绿）、所属角色、验收人、版本号。
   - **结构化消息卡片（非气泡，信息零遮挡）**：
     - **顶部元信息行**：
       - 发送角色色标头像 + 角色名（复用 `board/` 的 5 色角色胶囊体系）。
       - **AI 模型徽章**：按 `model_family` 显示明确可辨识的品牌色标 + 完整模型名（如 `GPT · gpt-5.3-codex`、`Gemini · gemini-2.5-pro`、`用户 · Human`）。
       - **消息类型标签**：`送验提醒`、`验收打回`、`审阅反馈`、`协作提醒`、`节点同步`。
       - **消息编号与时间**：`MSG-000002` + 本地格式化时间（hover 显示精确秒数）。
     - **回复引用条（可选）**：当 `reply_to` 非空时显示在卡片顶部，点击平滑滚动到被回复的原消息并触发 1.5 秒脉冲高亮。
     - **接收者与状态条**：
       - 清晰列出 `To: @角色名` + 独立状态徽章：
         - `● 未处理`（醒目橙红胶囊，未处理消息卡片带柔和暖色左边框与微底色，一眼锁定！）
         - `✓ 已处理`（沉稳青绿胶囊，hover 或展开显示：`处理时间`、`处理所用 AI 模型`、`处理结论 resolution`、`处理备注 note` 及关联回复链接 `→ MSG-000002`）
     - **正文区域**：由离线 `markdown-it` 安全渲染（`html: false`，支持加粗、列表、行内代码、代码块）。
     - **引用文件条（`refs[]`）**：每个引用渲染为紧凑文件胶囊，含相对路径、行号区间（如有）、简短 `note`，提供两个快捷按钮：
       - **预览**：在右侧面板打开只读代码/文本预览并自动滚动到指定行区间高亮；
       - **复制路径**：一键复制相对路径（或项目内完整路径）到剪贴板。

3. **右栏：可折叠上下文面板（三标签）**
   - **需求详情**：实时展示关联需求的目标、验收条件编号列表、全部追加记录（与 `TaskDetail.vue` 信息一致，用户审阅聊天时无需切换页面）。专题群则展示群组元信息与参与成员统计。
   - **本群待办**：集中列出本群所有 `pending` 消息，点击直达对应消息卡片。
   - **文件预览**：展示点击的 `refs` 文件只读源码/Markdown，带左侧行号与目标行浅黄背景高亮，底部注明“只读预览，最多显示 256 KB”。

#### 视图二：待办收件箱总览（Inbox Matrix）
专门响应“核心重点是提醒待办事项”的产品定位：
- **顶部汇总条**：全项目未处理消息总数、按类型分布（打回 N / 待验 N / 协作 N / 同步 N）、最长等待时长。
- **按接收角色分栏/分组展示**：每个角色一张聚合面板，显示该角色当前所有未处理消息卡片（按 P0→P3 优先级排列，标注等待时长如“已等待 26 分钟”），点击任意一条直接切回群聊视图并定位高亮该条消息。
- **空态激励**：全项目未处理消息清零时显示清晰的「全队待办提醒已清零」状态页。

---

## 5. 视觉设计规范（Design System）

为让用户从 `Agent Team Board`（项目看板）切换到通讯可视化页面时感受到统一的品牌质感，直接继承并微调 `board/src/style.css` 的设计语言：

### 5.1 色彩 Token
| 用途 | 色值 | 说明 |
| --- | --- | --- |
| 页面画布底色 | `#f8f9f6` | 温润暖白纸感，久看不刺眼 |
| 顶栏 / 品牌深色 | `#203739` | 与 `board/` 侧栏一致的深青石板绿 |
| 主强调色（品牌绿） | `#166351` | 选中 Tab、主按钮、激活态 |
| 正文墨色 / 次要灰 | `#233335` / `#62716e` | 高对比度清晰排版 |
| 分割线 | `#dce2db` | 低干扰极细边框 |
| **未处理状态（Pending）** | 文字 `#9a3412` / 底 `#ffedd5` / 边 `#f97316` | 强视觉注意力聚焦，绝不漏看待办 |
| **已处理状态（Handled）** | 文字 `#166534` / 底 `#dcfce7` / 边 `#86efac` | 沉稳收敛，退居背景 |
| **消息类型：验收打回** | 文字 `#991b1b` / 底 `#fee2e2` | 红色警示 |
| **消息类型：送验提醒** | 文字 `#5b21b6` / 底 `#ede9fe` | 紫色，与看板“3待验收”泳道呼应 |
| **消息类型：审阅反馈 / 协作** | 文字 `#854d0e` / 底 `#fef3c7` | 琥珀色 |
| **消息类型：节点同步** | 文字 `#1e40af` / 底 `#dbeafe` | 信息蓝 |

### 5.2 AI 模型品牌徽章色彩
| 模型家族（`model_family`） | 徽章样式 | 展示示例 |
| --- | --- | --- |
| `gpt` | 底 `#e7f5ef` / 文字 `#0f5132` / 边 `#a3cfbb` | `GPT · gpt-5.3-codex` |
| `gemini` | 底 `#e8f0fe` / 文字 `#1a56db` / 边 `#a4cafe` | `Gemini · gemini-2.5-pro` |
| `claude` | 底 `#fdf2e9` / 文字 `#9c4221` / 边 `#f6ad55` | `Claude · claude-sonnet-4` |
| `deepseek` | 底 `#eef2ff` / 文字 `#3730a3` / 边 `#c7d2fe` | `DeepSeek · deepseek-r1` |
| `human` | 底 `#f1f5f9` / 文字 `#334155` / 边 `#cbd5e1` | `用户 · Human` |
| `other` | 底 `#f3f4f6` / 文字 `#4b5563` / 边 `#d1d5db` | `Model · <原始名>` |

### 5.3 排版与响应式断点
- **字体**：沿用 `Inter, "Segoe UI", "Microsoft YaHei UI", sans-serif`；编号、时间、SHA、代码与路径使用等宽字体 `"IBM Plex Mono", "Cascadia Code", Consolas, monospace` + `font-variant-numeric: tabular-nums`。
- **响应式适配**：
  - `≥ 1200px`：经典三栏（左群组 `280px` + 中消息流自适应 + 右上下文面板 `340px`，右栏支持一键折叠）。
  - `820px ~ 1199px`：两栏（左群组 + 中消息流），右栏点击后以滑出抽屉呈现。
  - `< 820px`：单栏移动端布局，顶部切换群组抽屉与详情抽屉。

---

## 6. 数据刷新、启动集成与演进规划

### 6.1 无闪烁实时轮询机制
- 参考 `board/src/App.vue` 的轮询设计：仅当 `document.visibilityState === 'visible'` 时，每 **5 秒** 发起一次轻量 `GET /api/projects/<id>/overview`（携带当前 `etag`）。
- 服务端基于 `public/chat/` 及相关需求文件的 `mtime + size` 计算摘要：
  - 若无变化返回 `304 Not Modified`，前端零重绘、零滚动条抖动。
  - 若有新消息或状态变化，增量更新列表并在新消息到达时，如果用户正停留在底部则平滑滚动至最新消息，若用户正在向上翻看历史则在底部浮出「有 N 条新消息 ↓」温和提示，绝不强行打断阅读。

### 6.2 一期启动方式与桌面快捷方式集成（同步接入 `$at-start-board` / `AgentTeamStopService`）

一期即同时支持“直接从仓库启动”和“通过 `$at-start-board` 创建的 Windows 桌面快捷方式启动”，与现有 `dev-visual/`（纯 Python + `pythonw.exe` 隐藏进程）采用完全一致的托管机制：

1. **四个桌面快捷方式映射（由 3 个扩展为 4 个）**：

| 桌面快捷方式 | 目标 EXE | 图标素材 | 双击操作 |
| --- | --- | --- | --- |
| `AgentTeam 技能看板.lnk` | `AgentTeamHandbook.exe` | `icons/agentteam-handbook.ico` | 启动或复用技能手册（默认端口 `8764`） |
| `Agent Team Board.lnk` | `AgentTeamBoard.exe` | `icons/agentteam-board.ico` | 启动或复用项目看板（默认端口 `47361`） |
| `AgentTeam 角色通讯.lnk` *(新增)* | `AgentTeamChat.exe` | `icons/agentteam-chat.ico` | 启动或复用角色通讯可视化（默认端口 `47362`） |
| `AgentTeamStopService.lnk` | `AgentTeamStopService.exe` | `icons/agentteam-stop.ico` | 逐一核验身份后关闭以上**三个**后台服务 |

2. **需同步修改的启动器与技能文件**：
   - `tools/windows/DesktopLauncher.cs`：新增 `#elif CHAT` 条件编译分支（`Action = "chat"`），参数白名单新增 `-ChatPort`。
   - `tools/windows/build-launchers.ps1`：`launchers` 哈希表新增 `chat = 'AgentTeamChat'`，重编译生成无控制台 `AgentTeamChat.exe`（需提供配套 `icons/agentteam-chat.ico`）。
   - `tools/windows/desktop-services.ps1`：
     - 参数新增 `[int]$ChatPort = 47362`，`Action` 扩展为 `handbook | board | chat | both | all | stop`（保留 `both` 兼容，`$at-start-board` 默认调用 `all` 启动全部三服务）。
     - 新增 `Open-ChatVisual`（逻辑复用 `Open-Handbook`：通过 `pythonw.exe` 后台启动 `chat-visual/serve.py --port $ChatPort --strict-port --no-browser`，轮询 `/api/health` 校验 `app == 'agent-team-chat'`、`version == 1` 与 `pid` 匹配）。
     - `stop` 分支新增 `Stop-AgentTeamListener $ChatPort 'agent-team-chat' @('python.exe', 'pythonw.exe') ...`，安全停止角色通讯后台服务。
   - `tools/windows/set-desktop-shortcuts.ps1`：新增 `-ChatPort` 参数与 `AgentTeam 角色通讯` 定义项，并更新 `AgentTeamStopService` 描述文案。
   - `skills/at-start-board/scripts/start-board.ps1` 与 `SKILL.md`：同步增加 `-ChatPort`、四个 `.lnk` 核验、三个服务的 `/api/health` 与首页校验（标题 `角色通讯 · AgentTeam`）及浏览器打开。
3. **独立调试入口**：仍保留 `chat-visual/打开角色通讯.bat` 以及命令行 `python -B -X utf8 chat-visual/serve.py --project "<项目目录>"`，方便脱离快捷方式单独启动。

### 6.3 异常与降级体验
- **项目已初始化但尚无消息**（`$at-init-team` 已建立 `public/chat/meta.json` 且 `groups: []`，或旧项目无 `public/chat/`）：展示清晰引导页——“该项目暂无角色沟通记录，角色调用 `$at-work` 或 `$at-reply-message` 后消息将自动出现在此”，并支持自动轮询一旦出现首条消息立即切入主界面。
- **局部数据文件损坏**：在顶部展示与 `board/` 同款的柔和黄色折叠告警条 `warnings`，明确指出损坏文件路径与原因，其余正常群组照常展示。
- **引用文件已移动或删除**：例如需求已从 `2处理中` 移到 `3待验收`，消息卡片上的旧路径预览时，后端可自动按 `task_id` 提示“该需求文件已流转至 `3待验收/...`，是否预览最新位置？”，极大提升排查体验！

### 6.4 自动化测试清单
1. **`chat-visual/tests/test_server.py`**：
   - `/api/health` 响应与版本号校验。
   - 非 `127.0.0.1` Host 头拒绝（403）。
   - `/api/projects/<id>/file` 路径穿越（`../AT.json`、绝对路径、`.git/config`、符号链接逃逸）全部拦截返回 400/403；超 256 KB 文本正确截断。
   - 正常多群组、多接收者、混合 `gpt`/`gemini` 模型数据解析与 `overview` / `groups` / `etag` 304 缓存命中验证。
   - `public/chat/` 不存在与局部坏 JSON 降级告警验证。
2. **`chat-visual/tests/test_ui_logic.mjs`**：
   - 角色视角过滤、仅未处理过滤、优先级排序（含未处理群置顶、归档群折叠）。
   - Markdown 渲染 XSS 防护（验证 `<script>` / `onerror` 均被安全转义）。
   - 模型家族徽章映射与相对时间格式化。
