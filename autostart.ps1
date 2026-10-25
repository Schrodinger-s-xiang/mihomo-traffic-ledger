[CmdletBinding()]
param([switch]$Remove)
$ErrorActionPreference = 'Stop'
try {
    $startup = [Environment]::GetFolderPath('Startup')
    if (-not $startup) { throw 'Cannot locate the current-user Startup folder.' }
    $shortcutPath = Join-Path $startup 'Mihomo Traffic Ledger.lnk'
    if ($Remove) {
        if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath }
        Write-Host 'Automatic startup disabled. A running recorder is not stopped.'
        exit 0
    }
    $appPath = Join-Path $PSScriptRoot 'app.py'
    if (-not (Test-Path -LiteralPath $appPath)) { throw 'app.py is missing. Extract the complete package first.' }
    $pythonw = $null
    foreach ($name in @('py.exe', 'python.exe')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        $probeArgs = @('-c', "import sys; print(sys.executable if sys.version_info >= (3, 10) else '')")
        if ($name -eq 'py.exe') { $probeArgs = @('-3') + $probeArgs }
        try {
            $output = @(& $cmd.Source @probeArgs 2>$null)
            if ($LASTEXITCODE -ne 0 -or $output.Count -ne 1) { continue }
            $pythonPath = ([string]$output[0]).Trim()
            if (-not $pythonPath -or -not (Test-Path -LiteralPath $pythonPath)) { continue }
            $candidate = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
            if (Test-Path -LiteralPath $candidate) { $pythonw = $candidate; break }
        } catch { continue }
    }
    if (-not $pythonw) { throw 'Python 3.10+ with pythonw.exe was not found. Install Python from python.org, then retry.' }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $pythonw
    $shortcut.Arguments = '"' + $appPath + '" --no-browser'
    $shortcut.WorkingDirectory = $PSScriptRoot
    $shortcut.WindowStyle = 7
    $shortcut.Description = 'Record Mihomo traffic silently after Windows sign-in.'
    $shortcut.Save()
    if (-not (Test-Path -LiteralPath $shortcutPath)) { throw 'Failed to save the startup shortcut.' }
    # pythonw starts without a console; --no-browser suppresses the dashboard tab.
    Start-Process -FilePath $pythonw -ArgumentList $shortcut.Arguments -WorkingDirectory $PSScriptRoot
    Write-Host 'Automatic startup enabled for the current Windows user.'
    Write-Host 'The recorder starts silently after sign-in; no browser tab is opened.'
    Write-Host 'Open http://127.0.0.1:8765 to view your ledger.'
    Write-Host 'Keep this program folder in its current location.'
} catch {
    Write-Host ('Failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
