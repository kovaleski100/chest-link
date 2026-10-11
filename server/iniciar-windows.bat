@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python "%~dp0servidor.py" %*
) else (
  py -3 "%~dp0servidor.py" %*
)
pause
