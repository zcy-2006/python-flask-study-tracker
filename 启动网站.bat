@echo off
cd /d "%~dp0"
title Study Tracker

powershell.exe -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if not errorlevel 1 (
    start "" "http://127.0.0.1:5000"
    exit /b 0
)

if not exist ".venv\Scripts\python.exe" (
    echo Python virtual environment was not found.
    echo Run: python -m venv .venv
    pause
    exit /b 1
)

echo Starting Study Tracker...
start "" powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:5000'"

".venv\Scripts\python.exe" -m flask --app app run --host 127.0.0.1 --port 5000

echo Server stopped.
pause
