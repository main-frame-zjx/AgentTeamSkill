---
name: at-start-board
description: 在当前 Windows 设备后台启动 Agent Team 本地看板，打开浏览器并在当前用户桌面创建可再次启动服务的 AgentTeamBoard 快捷方式。
---

# AT_start_board

从任意工作目录运行此技能自带的 Windows 启动器。将脚本路径解析为绝对路径后执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "<本技能目录>\scripts\start-board.ps1"
```

等待脚本完成。首次启动需要 Node.js 22.12+、npm 和下载锁定依赖所需的网络访问；之后按依赖和源码变化决定是否重新构建。脚本检查本机服务标识，启动或复用看板，打开默认浏览器，并使用系统识别的桌面目录写入 `AgentTeamBoard.lnk`。桌面入口即使在电脑重启之后也可以直接打开看板。

成功时给出脚本返回的访问地址与快捷方式路径。用户可在看板中选择含 AT.json 的项目目录。失败时报告实际出错阶段或日志位置；端口被其他程序占用时说明占用情况，交由用户处理。
