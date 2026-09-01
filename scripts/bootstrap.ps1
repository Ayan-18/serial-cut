<#
  SerialCuts bootstrap: verifies prerequisites with clear messages, then sets up
  the local environment. Safe to re-run. Does a one-time Execution Policy bypass
  for this process only.
#>
param(
  [string]$PythonLauncher = "py",
  [string]$PythonVersion = "-3.11",
  [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
Set-Location (Split-Path -Parent $PSScriptRoot)

$problems = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]

function Test-Command($name) {
  return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

Write-Host "== SerialCuts bootstrap ==" -ForegroundColor Cyan

# --- Python 3.11.x -----------------------------------------------------------
$pythonOk = $false
if (Test-Command $PythonLauncher) {
  $version = (& $PythonLauncher $PythonVersion -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null)
  if ($LASTEXITCODE -eq 0 -and $version -match '^3\.(11|12)\.') {
    Write-Host "[ok]   Python $version" -ForegroundColor Green
    $pythonOk = $true
  }
}
if (-not $pythonOk) {
  $problems.Add("Python 3.11.x не найден. Установите: winget install --exact --id Python.Python.3.11")
}

# --- FFmpeg / ffprobe ------------------------------------------------------------
if ((Test-Command ffmpeg) -and (Test-Command ffprobe)) {
  Write-Host "[ok]   FFmpeg и ffprobe в PATH" -ForegroundColor Green
} else {
  $problems.Add("FFmpeg/ffprobe не в PATH. Установите: winget install --exact --id Gyan.FFmpeg  (перезапустите оболочку после установки)")
}

# --- Node.js (frontend build only) --------------------------------------------
if (Test-Command node) {
  Write-Host "[ok]   Node $((& node --version))" -ForegroundColor Green
} elseif (-not $SkipFrontend) {
  $warnings.Add("Node.js не найден — сборка frontend будет пропущена. Установите Node 22+ и повторите, либо запустите с -SkipFrontend.")
  $SkipFrontend = $true
}

# --- llama-server (optional) --------------------------------------------------
if (Test-Command llama-server) {
  Write-Host "[ok]   llama-server в PATH" -ForegroundColor Green
} else {
  $warnings.Add("llama-server не в PATH — нужен только для локальной Qwen: winget install --exact --id ggml.llamacpp")
}

if ($problems.Count -gt 0) {
  Write-Host ""
  Write-Host "Не хватает обязательных компонентов:" -ForegroundColor Red
  $problems | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
  exit 1
}

# --- .env ------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath ".env")) {
  Copy-Item ".env.example" ".env"
  Write-Host "[new]  .env создан из .env.example" -ForegroundColor Green
}

# --- virtual environment -------------------------------------------------------
if (-not (Test-Path -LiteralPath ".\.venv\Scripts\python.exe")) {
  Write-Host "Создаю .venv ($PythonLauncher $PythonVersion)..."
  & $PythonLauncher $PythonVersion -m venv .venv
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& .\.venv\Scripts\python.exe -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $SkipFrontend) {
  Push-Location frontend
  try {
    npm install
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    npm run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  } finally {
    Pop-Location
  }
}

if ($warnings.Count -gt 0) {
  Write-Host ""
  Write-Host "Предупреждения:" -ForegroundColor Yellow
  $warnings | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
}

Write-Host ""
Write-Host "Готово. Дальше:" -ForegroundColor Cyan
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_system.ps1"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1"
