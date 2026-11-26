[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('handbook', 'board', 'both', 'stop')][string]$Action,
    [ValidateRange(1, 65535)][int]$BoardPort = 47361,
    [ValidateRange(1, 65535)][int]$HandbookPort = 8764,
    [switch]$FromDesktop,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$handbook = Join-Path $root 'dev-visual\serve.py'
$boardLauncher = Join-Path $root 'skills\at-start-board\scripts\start-project-board.ps1'

function Get-Health($Port) {
    try {
        Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2 -UseBasicParsing
    } catch { return $null }
}

function Open-Handbook {
    $url = "http://127.0.0.1:$HandbookPort/"
    $health = Get-Health $HandbookPort
    if ($health.app -eq 'agent-team-handbook' -and $health.version -eq 1) {
        $listener = Get-NetTCPConnection -State Listen -LocalAddress 127.0.0.1 -LocalPort $HandbookPort
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
        if ($health.pid -ne $owner.ProcessId -or $owner.CommandLine -notmatch ([regex]::Escape($handbook) + '(?=["\s]|$)')) {
            throw "A handbook from a different checkout is using port $HandbookPort."
        }
    } else {
        $pythonw = (Get-Command pythonw.exe -CommandType Application | Select-Object -First 1).Source
        $service = Start-Process -FilePath $pythonw -ArgumentList "-B -X utf8 `"$handbook`" --port $HandbookPort --strict-port --no-browser" -WorkingDirectory (Split-Path $handbook) -WindowStyle Hidden -PassThru
        try {
            $deadline = [DateTime]::UtcNow.AddSeconds(15)
            do {
                $health = Get-Health $HandbookPort
                if ($health.app -eq 'agent-team-handbook' -and $health.version -eq 1 -and $health.pid -eq $service.Id) { break }
                if ($service.HasExited -or [DateTime]::UtcNow -ge $deadline) {
                    throw "Could not start AgentTeam Handbook on port $HandbookPort. Check whether the port is in use."
                }
                Start-Sleep -Milliseconds 120
            } while ($true)
            Write-Output "Server PID: $($service.Id)"
        } catch {
            if (!$service.HasExited) { $service.Kill() }
            throw
        } finally { $service.Dispose() }
    }
    if (!$NoBrowser) { Start-Process $url }
    Write-Output "Ready: $url"
}

function Open-ProjectBoard {
    $env:npm_config_cache = Join-Path $env:LOCALAPPDATA 'npm-cache'
    & $boardLauncher -Port $BoardPort
    if (!$NoBrowser) { Start-Process "http://127.0.0.1:$BoardPort/" }
}

function Stop-AgentTeamListener($Port, $App, $Names, $CommandPattern) {
    $listener = Get-NetTCPConnection -State Listen -LocalAddress 127.0.0.1 -LocalPort $Port -ErrorAction SilentlyContinue
    if (!$listener) { return }
    $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    if (!$process) { return }
    try {
        # Keep a process handle across verification so a recycled PID cannot be killed.
        $null = $process.Handle
        $info = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
        $health = Get-Health $Port
        if ($process.HasExited) { return }
        if ($health.app -ne $App -or $health.version -ne 1 -or
            $info.Name -notin $Names -or $info.CommandLine -notmatch $CommandPattern -or
            ($App -eq 'agent-team-handbook' -and $health.pid -ne $process.Id)) {
            throw "Port $Port belongs to an unverified process. It was left running."
        }
        $process.Kill()
        if (!$process.WaitForExit(5000)) { throw "Timed out stopping $App." }
    } finally { $process.Dispose() }
}

# Serialize desktop actions, including a Stop click during a cold board build.
$gate = New-Object Threading.Mutex($false, 'Local\AgentTeam-DesktopServices')
$locked = $false
try {
    try { $locked = $gate.WaitOne([TimeSpan]::FromMinutes(6)) }
    catch [Threading.AbandonedMutexException] { $locked = $true }
    if (!$locked) { throw 'Another AgentTeam desktop action is still running.' }
    switch ($Action) {
        'board' { Open-ProjectBoard }
        'handbook' { Open-Handbook }
        'both' {
            $errors = @()
            try { Open-ProjectBoard } catch { $errors += $_.Exception.Message }
            try { Open-Handbook } catch { $errors += $_.Exception.Message }
            if ($errors.Count) { throw ($errors -join [Environment]::NewLine) }
        }
        'stop' {
            $errors = @()
            try { Stop-AgentTeamListener $HandbookPort 'agent-team-handbook' @('python.exe', 'pythonw.exe') ([regex]::Escape($handbook) + '(?=["\s]|$)') }
            catch { $errors += $_.Exception.Message }
            try { Stop-AgentTeamListener $BoardPort 'agent-team-board' @('node.exe') '(?:^|[\s"/\\])server[/\\]start\.mjs(?=["\s]|$)' }
            catch { $errors += $_.Exception.Message }
            if ($errors.Count) { throw ($errors -join [Environment]::NewLine) }
        }
    }
} catch {
    if ($FromDesktop -and !$NoBrowser) {
        $shell = New-Object -ComObject WScript.Shell
        [void]$shell.Popup($_.Exception.Message, 0, 'AgentTeam', 16)
    }
    throw
} finally {
    if ($locked) { $gate.ReleaseMutex() }
    $gate.Dispose()
}
