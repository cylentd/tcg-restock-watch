# Register a Windows scheduled task that starts the watcher at every logon and
# restarts it if it dies. Run once from an elevated or normal PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\install-task.ps1
# Remove with:  Unregister-ScheduledTask -TaskName "TCG Restock Watch" -Confirm:$false
#
# With -MarketOnly it registers a separate task, "TCG Market Prices", that runs
# `watch.py --market-only` (TCGplayer prices and daily history, no retailer polls).
# That mode leaves the "TCG Restock Watch" task alone, enabled or disabled.
#   powershell -ExecutionPolicy Bypass -File scripts\install-task.ps1 -MarketOnly
# Remove with:  Unregister-ScheduledTask -TaskName "TCG Market Prices" -Confirm:$false
param([switch]$MarketOnly)

$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command python.exe).Source }

$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

if ($MarketOnly) {
    $action = New-ScheduledTaskAction -Execute $python -Argument "`"$root\watch.py`" --market-only" -WorkingDirectory $root
    Register-ScheduledTask -TaskName "TCG Market Prices" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName "TCG Market Prices"
    Write-Host "Installed and started TCG Market Prices. Log: $env:USERPROFILE\.tcg-watch\watch.log"
    exit 0
}

$action = New-ScheduledTaskAction -Execute $python -Argument "`"$root\watch.py`"" -WorkingDirectory $root
Register-ScheduledTask -TaskName "TCG Restock Watch" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "TCG Restock Watch"
Write-Host "Installed and started. Log: $env:USERPROFILE\.tcg-watch\watch.log"
