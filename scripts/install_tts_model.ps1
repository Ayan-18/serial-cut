param()

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
Set-Location (Split-Path -Parent $PSScriptRoot)

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { $python = "python" }

Write-Host "Скачиваю локальную модель озвучки Silero v4_ru (~60 МБ)..."
& $python -c "from app.application.model_install import install_model; e = install_model('tts', confirm=True); print('Готово:', e.target_dir)"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Проверьте torch: .\.venv\Scripts\python.exe -m pip install -e `".[tts]`" (если ещё не установлен)."
