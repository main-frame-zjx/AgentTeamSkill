[CmdletBinding()]
param(
    [string]$DesktopDirectory = [Environment]::GetFolderPath('DesktopDirectory'),
    [ValidateRange(1, 65535)][int]$BoardPort = 47361,
    [ValidateRange(1, 65535)][int]$HandbookPort = 8764,
    [ValidateRange(1, 65535)][int]$ChatPort = 47362
)
$ErrorActionPreference = 'Stop'
if (!(Test-Path -LiteralPath $DesktopDirectory -PathType Container)) {
    throw "Windows desktop directory unavailable: $DesktopDirectory"
}
$definitions = @(
    @{ Name='AgentTeam 技能看板'; Exe='AgentTeamHandbook.exe'; Action='handbook'; Title='打开 AgentTeam 技能手册' },
    @{ Name='Agent Team Board'; Exe='AgentTeamBoard.exe'; Action='board'; Title='打开 Agent Team 项目看板' },
    @{ Name='AgentTeam 角色通讯'; Exe='AgentTeamChat.exe'; Action='chat'; Title='打开 AgentTeam 角色通讯' },
    @{ Name='AgentTeamStopService'; Exe='AgentTeamStopService.exe'; Action='stop'; Title='停止项目看板、技能手册和角色通讯的后台服务' }
)
$options = @()
if ($BoardPort -ne 47361) { $options += "-BoardPort $BoardPort" }
if ($HandbookPort -ne 8764) { $options += "-HandbookPort $HandbookPort" }
if ($ChatPort -ne 47362) { $options += "-ChatPort $ChatPort" }
$arguments = $options -join ' '
$shell = New-Object -ComObject WScript.Shell
$hostExe = Join-Path $env:SystemRoot 'System32\wscript.exe'
$legacyVbs = Join-Path $PSScriptRoot 'desktop-services.vbs'
# Preflight all destinations before applying any changes.
$plans = foreach ($def in $definitions) {
    $target = Join-Path $PSScriptRoot $def.Exe
    $icon = Join-Path $PSScriptRoot "icons\agentteam-$($def.Action).ico"
    if (!(Test-Path -LiteralPath $target -PathType Leaf) -or !(Test-Path -LiteralPath $icon -PathType Leaf)) {
        throw "缺少 $target 或 $icon。请核对仓库文件，缺少 EXE 时运行 tools/windows/build-launchers.ps1。"
    }
    $path = Join-Path $DesktopDirectory ($def.Name + '.lnk')
    $link = $shell.CreateShortcut($path)
    $exists = Test-Path -LiteralPath $path
    if ($exists -and $link.TargetPath -ne $target) {
        $olderVbs = $link.TargetPath -eq $hostExe -and $link.Arguments -eq ('//Nologo "' + $legacyVbs + '" ' + $def.Action)
        $knownDescription = $link.Description -eq $def.Title -or ($def.Action -eq 'stop' -and $link.Description -eq '停止技能手册和项目看板的后台服务')
        $movedCheckout = $knownDescription -and [IO.Path]::GetFileName($link.TargetPath) -eq $def.Exe
        if (!$olderVbs -and !$movedCheckout) { throw "同名快捷方式指向其他程序：$path" }
    }
    [pscustomobject]@{ Link=$link; Path=$path; Target=$target; Icon="$icon,0"; Title=$def.Title; Exists=$exists }
}
foreach ($plan in $plans) {
    $link = $plan.Link
    if (!$plan.Exists -or $link.TargetPath -ne $plan.Target -or $link.WorkingDirectory -ne $PSScriptRoot -or
        $link.Arguments -ne $arguments -or $link.IconLocation -ne $plan.Icon -or $link.Description -ne $plan.Title) {
        $link.TargetPath = $plan.Target
        $link.WorkingDirectory = $PSScriptRoot
        $link.Arguments = $arguments
        $link.IconLocation = $plan.Icon
        $link.Description = $plan.Title
        $link.Save()
    }
    Write-Output "Shortcut: $($plan.Path)"
}

$oldPath = Join-Path $DesktopDirectory 'AgentTeamBoard.lnk'
if (Test-Path -LiteralPath $oldPath -PathType Leaf) {
    $old = $shell.CreateShortcut($oldPath)
    $oldHost = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if ($old.Description -eq 'Open Agent Team Board' -and $old.TargetPath -eq $oldHost -and
        $old.Arguments -match '^-NoProfile -ExecutionPolicy RemoteSigned -WindowStyle Hidden -File "([^"]+\\at-start-board\\scripts\\start-board\.ps1)" -FromShortcut -Port \d+$' -and
        $old.WorkingDirectory -eq [IO.Path]::GetDirectoryName($Matches[1])) {
        Remove-Item -LiteralPath $oldPath
    }
}
