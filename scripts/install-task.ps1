# Register a Windows scheduled task that starts the watcher at every logon and
# restarts it if it dies. Run once from an elevated or normal PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\install-task.ps1
# Remove with:  Unregister-ScheduledTask -TaskName "TCG Restock Watch" -Confirm:$false

$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command python.exe).Source }

$action = New-ScheduledTaskAction -Execute $python -Argument "`"$root\watch.py`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "TCG Restock Watch" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "TCG Restock Watch"
Write-Host "Installed and started. Log: $env:USERPROFILE\.tcg-watch\watch.log"
