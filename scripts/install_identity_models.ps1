param(
  [switch]$ConfirmDownload
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"

Write-Host "Local identity models from the official OpenCV Zoo:"
Write-Host "  YuNet face detector: about 0.3 MB"
Write-Host "  SFace face recognizer: about 39 MB"
Write-Host "  Files stay under data\models\face; video and photos stay on this computer"

if (-not $ConfirmDownload) {
  $answer = Read-Host "Download and verify these models? [y/N]"
  if ($answer -notin @("y", "Y", "yes", "YES")) {
    Write-Host "Cancelled."
    exit 1
  }
}

$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
  throw "Project virtual environment is missing. Run scripts\setup.ps1 first."
}

& $Python .\scripts\download_identity_models.py
exit $LASTEXITCODE
