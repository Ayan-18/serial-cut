param(
  [string]$ShortcutName = "SerialCuts"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Launcher = Join-Path $ProjectRoot "Start SerialCuts.cmd"
if (-not (Test-Path -LiteralPath $Launcher)) {
  throw "Launcher not found: $Launcher"
}

$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop ($ShortcutName + ".lnk")
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Launcher
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.Description = "Локальный запуск SerialCuts"
$Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,238"
$Shortcut.Save()

Write-Host "Shortcut created: $ShortcutPath"
