@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Первый запуск: проверяю окружение...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\bootstrap.ps1"
  if errorlevel 1 (
    echo.
    echo Не удалось подготовить окружение. См. сообщения выше.
    pause
    exit /b 1
  )
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run.ps1"
if errorlevel 1 (
  echo.
  echo SerialCuts stopped with an error. See the message above.
  pause
)
