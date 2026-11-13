@echo off
setlocal
set "ROOT=%~dp0"
set "URL=http://127.0.0.1:8765/"
powershell -NoProfile -Command "try { $s=Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/state' -TimeoutSec 2; if ($null -ne $s.jobs) { exit 0 } } catch {}; exit 1"
if not errorlevel 1 (
  start "" "%URL%"
  exit /b 0
)
if exist "%ROOT%.venv\Scripts\python.exe" (
  "%ROOT%.venv\Scripts\python.exe" "%ROOT%scripts\job_board.py"
) else (
  py -3 "%ROOT%scripts\job_board.py"
)
if errorlevel 1 pause
