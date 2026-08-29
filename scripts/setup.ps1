param(
  [string]$PythonLauncher = "py",
  [string]$PythonVersion = "-3.11"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
Write-Host "SerialCuts setup: creating local virtual environment"
& $PythonLauncher $PythonVersion -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& .\.venv\Scripts\python.exe -m alembic upgrade head
Push-Location frontend
npm install
npm run build
Pop-Location
Write-Host "Done. Run scripts\check_system.ps1, then scripts\run.ps1."
