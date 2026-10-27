@echo off
rem Double-click to start the Surebet Scanner and open the dashboard.
rem Stop it from the dashboard: Settings > Server > Stop server.
setlocal
cd /d "%~dp0"
title Surebet launcher

rem Prefer the project venv, fall back to python on PATH.
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

rem Same PORT as config/settings.py: .env override, else 8000.
set "PORT=8000"
if exist ".env" for /f "usebackq tokens=1,* delims==" %%A in (".env") do if /i "%%A"=="PORT" set "PORT=%%B"
set "URL=http://localhost:%PORT%"

rem Already running? Just open the page.
curl -s -o nul -m 2 "%URL%/api/health" && goto open

echo Starting Surebet server on port %PORT% ...
rem Server gets its own minimized window. It closes when the server stops;
rem on a crash it stays open so the error can be read.
start "Surebet Server" /min cmd /c ""%PY%" main.py || pause"

rem Wait up to 60 s for the server to answer.
for /l %%i in (1,1,60) do (
    curl -s -o nul -m 1 "%URL%/api/health" && goto open
    ping -n 2 127.0.0.1 >nul
)
echo Server did not start. Check the "Surebet Server" window for errors.
pause
exit /b 1

:open
start "" "%URL%"
exit /b 0
