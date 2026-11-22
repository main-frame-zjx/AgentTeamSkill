[CmdletBinding()]
param(
    [ValidateRange(1, 65535)][int]$Port = 47361,
    [string]$DesktopDirectory = [Environment]::GetFolderPath('DesktopDirectory'),
    [switch]$FromShortcut,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$url = "http://127.0.0.1:$Port"

function Get-BoardStatus {
    $socket = New-Object Net.Sockets.TcpClient
    try { $socket.Connect('127.0.0.1', $Port) }
    catch [Net.Sockets.SocketException] { return 'offline' }
    finally { $socket.Dispose() }
    try {
        $reply = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 2 -UseBasicParsing
        if ($reply.app -eq 'agent-team-board' -and $reply.version -eq 1) { return 'ready' }
    } catch {}
    return 'occupied'
}

function Set-BoardShortcut {
    if (!(Test-Path -LiteralPath $DesktopDirectory -PathType Container)) {
        throw "Windows desktop directory unavailable: $DesktopDirectory"
    }
    $path = Join-Path $DesktopDirectory 'AgentTeamBoard.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($path)
    $description = 'Open Agent Team Board'
    if ((Test-Path -LiteralPath $path) -and $link.Description -ne $description) {
        throw "A different shortcut already exists: $path"
    }
    $link.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $link.Arguments = "-NoProfile -ExecutionPolicy RemoteSigned -WindowStyle Hidden -File `"$PSCommandPath`" -FromShortcut -Port $Port"
    $link.WorkingDirectory = $PSScriptRoot
    $link.Description = $description
    $link.Save()
    Write-Output "Shortcut: $path"
}

$gate = New-Object Threading.Mutex($false, "Local\AgentTeamBoard-Start-$Port")
$locked = $false
try {
    try { $locked = $gate.WaitOne([TimeSpan]::FromMinutes(5)) }
    catch [Threading.AbandonedMutexException] { $locked = $true }
    if (!$locked) { throw 'Another board launch is still preparing dependencies. Try again shortly.' }
    $status = Get-BoardStatus
    if ($status -eq 'occupied') { throw "Port $Port is in use by another application." }
    if ($status -eq 'offline') {
        $board = Join-Path $PSScriptRoot '../assets/board'
        if (!(Test-Path -LiteralPath (Join-Path $board 'package-lock.json'))) {
            $board = Join-Path $PSScriptRoot '../../../board'
        }
        $board = (Resolve-Path -LiteralPath $board).Path
        $node = (Get-Command node.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
        Push-Location -LiteralPath $board
        try {
            & $node 'server/launch.mjs' '--prepare-only'
            if ($LASTEXITCODE -ne 0) { throw "Board preparation failed (exit $LASTEXITCODE)." }
        } finally { Pop-Location }
        $logs = Join-Path $env:LOCALAPPDATA 'AgentTeamBoard'
        [void][IO.Directory]::CreateDirectory($logs)
        $stderr = Join-Path $logs "server-$Port.err.log"
        $serverPid = & python.exe -B (Join-Path $PSScriptRoot 'start_server.py') $node $board $Port $logs
        if ($LASTEXITCODE -ne 0) { throw 'Failed to start the background process.' }
        $child = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
        if (!$child) { throw "Board exited. See $stderr" }
        Write-Output "Server PID: $serverPid"
        $deadline = [DateTime]::UtcNow.AddSeconds(20)
        do {
            $status = Get-BoardStatus
            if ($status -eq 'ready') { break }
            if ($child.HasExited) { throw "Board failed to start. See $stderr" }
            Start-Sleep -Milliseconds 200
        } while ([DateTime]::UtcNow -lt $deadline)
        if ($status -ne 'ready') {
            if (!$child.HasExited) { $child.Kill() }
            throw "Board health check failed. See $stderr"
        }
    }
    if (!$FromShortcut) { Set-BoardShortcut }
    if (!$NoBrowser) { Start-Process $url }
    Write-Output "Ready: $url"
} catch {
    if ($FromShortcut -and !$NoBrowser) {
        $shell = New-Object -ComObject WScript.Shell
        [void]$shell.Popup($_.Exception.Message, 0, 'Agent Team Board', 16)
    }
    throw
} finally {
    if ($locked) { $gate.ReleaseMutex() }
    $gate.Dispose()
}
