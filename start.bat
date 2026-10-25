@echo off
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0app.py"
) else (
  python "%~dp0app.py"
)
if errorlevel 1 (
  echo.
  echo Install Python 3.10 or newer from https://www.python.org/downloads/windows/
  echo Enable "Add Python to PATH" during installation.
  pause
)
