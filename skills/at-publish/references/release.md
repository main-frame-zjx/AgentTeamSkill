# 发布接口

所有发布操作沿用管理角色权限。在已登记管理角色的实际工作目录自动识别身份。项目根会话先取得用户对本次发布角色的确认，请求添加 `actor` 和 `actor_confirmed:true`。下文各发布请求示例默认从相应管理角色目录执行。普通角色应切换到项目负责人的 AI 会话。版本用 `version`，缺省取 `AT.json.current_version`。输入 `1.10` 对应目录 `v1.10`。每次写入通过项目锁和暂存目录落盘，历史在 `.at-state/releases.json`。

## 发现与修订

- `release-check` 接受 `actor, kind, version`。返回 `latest`（该类同版最近修订、发布时间、相对入口）、`revision`（下一修订号）、`pending`、`ready`、`issues`、`scope`、`changes`、`stages` 和 `artifacts`。这是发布资格检查，具体内容及程序验证记录在生成时校验。
- `kind` 为 `bin`、`user` 或 `dev`。首次正式交付版本的 `bin/user` 须提供 `artifacts`，例如 `[{"task":"<目标版本需求编号>","path":"public/game/maps/tutorial.json"}]`，或 `[{"task":"<需求编号>","commit":"<真实 SHA>"}]`。可用 `repo` 指定项目内独立仓库。团队提交须已进入 main。后续同版交付沿用原验收记录。`dev` 可以在零条归档时发布。
- 首次 `release` 传唯一的 `request_id`（例如新 UUID）。有已有成果时，先显示 `latest` 并等用户选择。选沿用传 `{"kind":"dev","version":"1.0","actor":"项目负责人","action":"reuse"}`。选新修订时传完整新内容，并加上 `"action":"new","previous_revision":1` 和新的请求编号。修订号已变化时重新展示最新成果。只指定版本与类别遇到已有成果时，命令返回 `needs_choice`。
- 中断后使用原 `kind, version, request_id` 重试；如果尚未落盘暂存记录，重发完整原请求。成功返回 `entry, bundle, revision, time, existing`。

## Windows 程序包

项目已有的打包命令负责构建。读项目说明确认运行平台和架构，按已验收的版本准备一个仅含发行文件的目录。若原始成品是单文件 EXE，单独放入目录即可。若含运行库或资源，保留其目录结构。程序的来源和对应版本写入 `build_evidence`。

用 `verify-bin` 复制完整发行目录，实际启动复制后的 EXE。工作目录是迁移副本，PATH 只含 Windows 系统目录，用户配置和临时文件使用独立目录。下面的参数仅演示项目已有的自测接口，应换成目标程序支持的真实操作。

```json
{
  "actor":"项目负责人", "version":"1.0", "source":"public/game/dist/windows",
  "entry":"TankWar.exe", "build_evidence":"由本版本验收提交按项目 build.ps1 构建",
  "feature":"载入教程并完成第一关", "args":["--self-test","tutorial"], "expect":"tutorial passed"
}
```

- `source` 可为项目相对路径或独立发行目录的绝对路径。`entry` 为其中的相对 EXE 路径。自动验证要求正常退出且输出包含 `expect`。如程序将结果写入文件，传相对路径 `result_file`，脚本读取本次运行新生成的 UTF-8 文件。
- 图形程序缺少自动自测接口时，使用 `"interactive":true`，通过 `--input "<文件>"` 在交互终端启动。通过界面实际完成 `feature` 中的操作，正常退出后，在终端输入具体操作和观察结果。验证失败则留空。可用 `timeout_seconds` 指定测试时间。仅启动到主界面不足以证明核心功能可用。
- 通过后，使用返回的 `id` 调用 `release`，例如 `{"actor":"项目负责人","kind":"bin","version":"1.0","request_id":"<UUID>","bin_check":"<验证编号>","artifacts":[{"task":"<需求编号>","commit":"<验收 SHA>"}]}`。脚本核对版本及所有包内文件的 SHA-256，原始文件发生变化需重新验证。记录本机 Windows 和架构，只报告实际测试的环境。最终交付整个 `rN/` 目录。

## 两种离线 HTML

用户指南示例：

```json
{
  "actor":"项目负责人", "kind":"user", "version":"1.0", "request_id":"<UUID>",
  "artifacts":[{"task":"<本版需求编号>","path":"public/game/maps/tutorial.json"}],
  "overview":"这是一款支持本地对战的坦克游戏。",
  "capabilities":["支持键盘操作，可以在教程地图完成一场对战。"],
  "how_to":["完整复制 Windows 程序包并打开 TankWar.exe。","从主菜单进入教程，按方向键将坦克移到提示区域。"],
  "limitations":["当前教程使用键盘。"],
  "images":[{"path":"public/截图/教程.png","caption":"教程入口和起点提示。"}]
}
```

甲方总览示例：

```json
{
  "actor":"项目负责人", "kind":"dev", "version":"1.0", "request_id":"<另一个 UUID>",
  "overview":"教程地图已完成设计，客户端正在接入。",
  "highlights":["本轮确定了教程起点和移动路径。"],
  "blockers":["手柄交互方案仍待确认。"], "decisions":["首版是否提供手柄引导？"],
  "next_steps":["完成键盘教程后，提交首轮可玩性验收。"]
}
```

所有示例均应替换成已核实的项目事实。两种 HTML 均可传本地 PNG、JPEG、GIF、WebP 和图注 `images`，路径相对项目根。`blockers, decisions, next_steps` 可传空数组表示暂无已记录事项。甲方总览按汇报时刻保存实际需求分布。指南用有序步骤表达操作流程。

## 项目版本与历史

| 命令 | 用途 |
|---|---|
| `set-iteration` | `{"version":"1.10","goal":"完成手柄联机验收"}` 设置默认迭代。可选的单行 `goal` 会显示在角色工作记忆中。 |
| `authorize-publisher` | 用户明确指定另一个注册岗位承担发布管理后，传 `role, user_confirmed=true`。 |
