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
$LlmAdapter = (& $Python -c "from app.infrastructure.config import Settings; print(Settings().llm_adapter)").Trim()
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($LlmAdapter -eq "llama-cpp-http") {
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_local.ps1 -HostName $HostName -Port $Port
  exit $LASTEXITCODE
}
& $Python -m alembic upgrade head
& $Python -m uvicorn app.main:app --host $HostName --port $Port
