import { execFile } from 'node:child_process'
import { promisify } from 'node:util'

const run = promisify(execFile)
const dialog = [
  '[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)',
  'Add-Type -AssemblyName System.Windows.Forms',
  '$owner = New-Object System.Windows.Forms.Form',
  '$owner.TopMost = $true',
  '$picker = New-Object System.Windows.Forms.FolderBrowserDialog',
  "$picker.Description = '选择 Agent Team 项目根目录'",
  '$picker.ShowNewFolderButton = $false',
  'try { if ($picker.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Write($picker.SelectedPath) } } finally { $picker.Dispose(); $owner.Dispose() }'
].join('\n')

export async function pickFolder() {
  const encoded = Buffer.from(dialog, 'utf16le').toString('base64')
  const { stdout } = await run('powershell.exe', ['-NoProfile', '-STA', '-EncodedCommand', encoded],
    { windowsHide: true, encoding: 'utf8' })
  return stdout || null
}

