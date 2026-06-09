# install.ps1 — register Pulse to launch at logon (Windows).
# Runs the overlay with pythonw.exe (no console window).
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) { $pythonw = (Get-Command python.exe).Source }
$script = Join-Path $repo "pulse_win.py"

$action  = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$script`"" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "Pulse" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

# start it now too
Start-Process -FilePath $pythonw -ArgumentList "`"$script`"" -WorkingDirectory $repo
Write-Host "Pulse installed (Task Scheduler, at logon) and started from $repo"
