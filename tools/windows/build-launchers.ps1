[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$framework = if ([Environment]::Is64BitOperatingSystem) { 'Framework64' } else { 'Framework' }
$compiler = Join-Path $env:SystemRoot "Microsoft.NET\$framework\v4.0.30319\csc.exe"
$source = Join-Path $PSScriptRoot 'DesktopLauncher.cs'
$launchers = @{ handbook = 'AgentTeamHandbook'; board = 'AgentTeamBoard'; stop = 'AgentTeamStopService' }
foreach ($action in $launchers.Keys) {
    $output = Join-Path $PSScriptRoot ($launchers[$action] + '.exe')
    $icon = Join-Path $PSScriptRoot "icons\agentteam-$action.ico"
    & $compiler /nologo /target:winexe /platform:anycpu /optimize+ /reference:System.Windows.Forms.dll "/define:$($action.ToUpperInvariant())" "/win32icon:$icon" "/out:$output" $source
    if ($LASTEXITCODE -ne 0) { throw "Could not build $output." }
    Write-Output $output
}
