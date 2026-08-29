param(
  [string]$HostName = "127.0.0.1",
  [int]$Port = 8090
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
  $Python = "python"
}
& $Python -m alembic upgrade head
& $Python -m uvicorn app.main:app --host $HostName --port $Port
