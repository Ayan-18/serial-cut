param(
  [string]$Python = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
if (-not (Test-Path -LiteralPath $Python)) {
  $Python = "python"
}
& $Python -c "from app.bot.telegram import run_telegram_bot; run_telegram_bot()"

