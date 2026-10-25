$ErrorActionPreference = 'Stop'
$target = Join-Path $PSScriptRoot 'app.py'
Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python(w)?([0-9.]*)?\.exe$' -and $_.CommandLine -and
    $_.CommandLine.IndexOf($target, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
} | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction Stop }
Start-Sleep -Milliseconds 500
& (Join-Path $PSScriptRoot 'start.bat')
