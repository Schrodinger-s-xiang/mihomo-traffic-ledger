@echo off
cd /d "%~dp0"
powershell -NoProfile -Command "$target = Join-Path (Get-Location) 'app.py'; Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(w)?([0-9.]*)?\.exe$' -and $_.CommandLine -and ($_.CommandLine.Contains($target)) } | ForEach-Object { Stop-Process -Id $_.ProcessId }"
echo If started with a relative path, use Task Manager or Ctrl+C in the start window.
pause
