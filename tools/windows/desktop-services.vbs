Option Explicit
Dim action, files, shell, script, host, cmd
If WScript.Arguments.Count <> 1 Then WScript.Quit 2
action = WScript.Arguments(0)
Select Case action
    Case "handbook", "board", "stop"
    Case Else
        WScript.Quit 2
End Select
Set files = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
script = files.BuildPath(files.GetParentFolderName(WScript.ScriptFullName), "desktop-services.ps1")
host = shell.ExpandEnvironmentStrings("%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe")
cmd = Chr(34) & host & Chr(34) & " -NoLogo -NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -File " & Chr(34) & script & Chr(34) & " " & action
WScript.Quit shell.Run(cmd, 0, True)
