@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run.ps1"
if errorlevel 1 (
  echo.
  echo SerialCuts stopped with an error. See the message above.
  pause
)
