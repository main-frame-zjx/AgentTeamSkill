[CmdletBinding()]
param(
    [ValidateRange(1, 65535)][int]$Port = 47361,
    [ValidateRange(1, 65535)][int]$HandbookPort = 8764,
    [ValidateRange(1, 65535)][int]$ChatPort = 47362,
    [string]$DesktopDirectory = [Environment]::GetFolderPath('DesktopDirectory'),
    [switch]$FromShortcut,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$manifest = Join-Path $PSScriptRoot '..\.agentteam-install.json'
if (Test-Path -LiteralPath $manifest -PathType Leaf) {
    $root = (Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json).source_root
} else {
    $root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
}
if (!$root -or !(Test-Path -LiteralPath (Join-Path $root 'tools/windows/set-desktop-shortcuts.ps1') -PathType Leaf)) {
    throw 'AgentTeam source checkout not found. Run install.py from its current location.'
}

$tools = Join-Path $root 'tools/windows'
if ($FromShortcut) {
    # Keep older project-board shortcuts working until the next normal invocation.
    & (Join-Path $tools 'desktop-services.ps1') board -BoardPort $Port -NoBrowser:$NoBrowser
} else {
    & (Join-Path $tools 'set-desktop-shortcuts.ps1') -DesktopDirectory $DesktopDirectory -BoardPort $Port -HandbookPort $HandbookPort -ChatPort $ChatPort
    & (Join-Path $tools 'desktop-services.ps1') all -BoardPort $Port -HandbookPort $HandbookPort -ChatPort $ChatPort -NoBrowser:$NoBrowser
}
