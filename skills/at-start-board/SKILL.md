---
name: at-start-board
description: 在 Windows 优先复用桌面快捷方式打开 AgentTeam 项目看板和技能手册。首次使用、入口缺失或打开失败时，检查并补齐依赖，生成或修复两个看板和停止服务的三个桌面快捷方式。
---

# AT_start_board

## 第一步：检查桌面入口，优先复用

用 `[Environment]::GetFolderPath('DesktopDirectory')` 定位当前用户的实际桌面。全局安装时从本技能目录的 `.agentteam-install.json` 读取 `source_root`；直接使用仓库中的技能时，从 `skills/at-start-board/` 向上两级定位来源仓库。

按第三步的映射表逐个检查三个 `.lnk` 是否存在，用 `WScript.Shell.CreateShortcut(完整路径)` 读取已有入口的目标、工作目录、图标和端口参数。核对对应 EXE 和图标文件确实存在。正常桌面参数为空或仅指定有效的自定义端口；两个看板入口若保存了 `-NoBrowser` 也需要修复。停止服务入口只核对属性，检查期间不要运行它。**只要缺少或损坏任一入口，就进入第二步，再完成第三步。即使两个网页都可用，缺少停止服务快捷方式也须补齐。**

三个入口正确时，通过两个看板入口分别验证能否打开项目：使用各自已核对的目标 EXE、工作目录和端口参数，追加 `-NoBrowser`，用 `Start-Process -Wait -PassThru` 等待退出并读取 `ExitCode`。这条路径与双击使用同一启动器，可复用已运行的服务，也可启动已关闭的服务。只传启动器支持的 `-BoardPort`、`-HandbookPort` 和 `-NoBrowser` 参数。

使用 `127.0.0.1` 和入口配置的端口，分别请求两个服务的 `/api/health` 和首页 `/`。健康响应的 `version` 应为 1，`app` 分别为项目看板的 `agent-team-board` 和技能手册的 `agent-team-handbook`。首页应返回 HTTP 200，HTML 标题分别为 `Agent Team Board` 和 `技能手册 · AgentTeam`。**三个入口均正确、两个启动器均成功且两个网页验证通过时，在默认浏览器中各打开一次。页面正常即报告两个链接并结束技能。** 这条路径无需运行第三步的生成器。若启动失败、首页不可用或已打开的页面空白，记录具体错误，进入第二步。

## 第二步：补齐依赖，修复失败项

首次设置、桌面入口缺失或损坏、启动器返回失败、网页无法正常显示时进入此步。记下受影响的入口、退出码或 HTTP 错误，按涉及的组件检查：

| 组件 | 启动条件 |
| --- | --- |
| 项目看板 | `node.exe --version` 达到来源仓库 `board/package.json` 的要求（当前为 22.12.0 及以上）；`npm.cmd --version` 可用；`python.exe` 可运行后台启动助手。 |
| 技能手册 | 仓库要求 Python 3.11 及以上。用 `python.exe --version` 核实版本，检查同一安装提供的 `pythonw.exe` 可被启动器找到，以及来源仓库的 `dev-visual/serve.py` 和 `skills/` 可读。 |

- **缺少运行环境**：先告诉用户缺哪项、检测到的版本和所需版本，再实际帮助安装。Windows 可用 WinGet 时，查询并核实满足要求的官方 Node.js LTS（含 npm）或 Python 3 安装包，按准确包 ID 安装。已装 Node.js 但缺 npm 时，优先修复现有发行版。WinGet 不可用时使用相应官方 Windows 安装程序。更新当前进程的 PATH 后重新检查版本和可执行文件；遇到 UAC 等需要用户操作的界面，再请用户完成该步并继续。
- **缺少项目依赖或前端产物**：项目看板启动器会按 `board/package-lock.json` 安装依赖并构建前端。若已有服务健康但首页或静态资源损坏，进入来源仓库的 `board/`，依赖缺失或损坏时执行 `npm.cmd ci --include=dev --no-audit --no-fund`，需要重建页面时执行 `npm.cmd run build`。检查失败命令的输出和 `%LOCALAPPDATA%\AgentTeamBoard\server-<端口>.err.log`。
- **路径或页面故障**：来源仓库已搬迁时，从新位置运行 `python install.py` 更新登记。页面空白时检查对应的脚本、样式和数据请求。端口被其他程序占用时，识别占用者，保留该进程，确认可用端口后传给第三步。

启动条件满足后进入第三步；依赖原本齐全时直接继续。仍有阻塞时说明受影响的页面、错误和日志位置。

## 第三步：生成或修复三个桌面快捷方式，打开两个看板

将以下三个入口交付到 Windows 当前用户的实际桌面。每个快捷方式直接指向安装来源仓库 `tools/windows/` 中对应的无控制台 EXE，工作目录设为该目录，图标使用表中相对于该目录的 ICO 文件。

| 桌面快捷方式 | 目标 EXE | 图标素材 | 双击操作 |
| --- | --- | --- | --- |
| `AgentTeam 技能看板.lnk` | `AgentTeamHandbook.exe` | `icons/agentteam-handbook.ico` | 后台启动或复用技能手册并打开页面，默认端口 8764 |
| `AgentTeamStopService.lnk` | `AgentTeamStopService.exe` | `icons/agentteam-stop.ico` | 核验服务身份后关闭两个后台服务 |
| `Agent Team Board.lnk` | `AgentTeamBoard.exe` | `icons/agentteam-board.ico` | 后台启动或复用项目看板并打开页面，默认端口 47361 |

先核对三个图标和 EXE。缺少图标时从来源仓库恢复对应素材；缺少 EXE 时运行同目录的 `build-launchers.ps1`。随后从任意工作目录执行以下总入口，将 `<本技能目录>` 替换为实际绝对路径。若第一步已确认自定义端口，追加 `-Port <项目看板端口>` 和 `-HandbookPort <技能手册端口>`。

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "<本技能目录>\scripts\start-board.ps1" -NoBrowser
```

总入口会先调用 `tools/windows/set-desktop-shortcuts.ps1` 按原名补齐或修正三个桌面入口，属性正确的入口会被保留，再启动或复用两个服务。`-NoBrowser` 只用于本次调用，便于在页面验证通过后统一打开浏览器。遇到同名快捷方式属于其他程序时，保留原文件并报告其路径和目标。

等待总入口完成，回读桌面上的三个 `.lnk`，按表逐项核对目标、工作目录及图标，再按第一步复核两个网页。验证通过后，在默认浏览器中各打开一次；本轮已打开的故障页面刷新原标签页即可。向用户返回三个快捷方式的完整路径和两个实际访问地址。若仍有失败，报告已可用的项目、具体阻塞和日志位置。
