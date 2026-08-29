param(
  [switch]$ConfirmDownload
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"

Write-Host "Local model download:"
Write-Host "  faster-whisper-small: about 486 MB"
Write-Host "  Qwen3-4B Q4_K_M: about 2.5 GB"
Write-Host "  Total: about 3 GB; files stay under data\models"

if (-not $ConfirmDownload) {
  $answer = Read-Host "Download these models from official Hugging Face repositories? [y/N]"
  if ($answer -notin @("y", "Y", "yes", "YES")) {
    Write-Host "Cancelled."
    exit 1
  }
}

$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
  throw "Project virtual environment is missing. Run scripts\setup.ps1 first."
}

& $Python .\scripts\download_models.py
exit $LASTEXITCODE
