# =====================================================================
# Register a scheduled task to run weekend_capture.ps1 every Sat & Sun 09:00.
# (Comments kept ASCII on purpose: Windows PowerShell 5.1 misreads UTF-8
#  Japanese as Shift-JIS and breaks parsing. Explanation lives in
#  docs/SMARTMONEY_CAPTURE.md instead.)
#
# Run once in an ADMIN PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\register_weekend_tasks.ps1
# Remove:
#   Unregister-ScheduledTask -TaskName "KeibaWeekendOddsCapture" -Confirm:$false
#
# JV-Link is a COM component: the task runs as the logged-on user on an
#   interactive desktop -> keep the PC logged in (lock screen is fine).
#   Logoff / different user => it will not run.
# Sleep: if the PC sleeps during the day, capture stops. Disable sleep on AC.
# =====================================================================
$ErrorActionPreference = "Stop"

$Repo     = "C:\keiba_ateru\keiba-ateru"
$Script   = Join-Path $Repo "scripts\weekend_capture.ps1"
$TaskName = "KeibaWeekendOddsCapture"

if (-not (Test-Path $Script)) { throw "capture script not found: $Script" }

# Single line + splatting (no backtick line-continuation, which is fragile).
$actionArg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArg

# Sat & Sun 09:00 (before race 1; capture morning odds formation too).
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday, Sunday -At "09:00"

$settingsParams = @{
    StartWhenAvailable         = $true
    AllowStartIfOnBatteries    = $true
    DontStopIfGoingOnBatteries = $true
    WakeToRun                  = $true
    ExecutionTimeLimit         = (New-TimeSpan -Hours 11)
    MultipleInstances          = 'IgnoreNew'
}
$settings = New-ScheduledTaskSettingsSet @settingsParams

# Needs interactive desktop (JV-Link COM): run as logged-on user, highest priv.
$principalParams = @{
    UserId    = "$env:USERDOMAIN\$env:USERNAME"
    LogonType = 'Interactive'
    RunLevel  = 'Highest'
}
$principal = New-ScheduledTaskPrincipal @principalParams

$registerParams = @{
    TaskName  = $TaskName
    Action    = $action
    Trigger   = $trigger
    Settings  = $settings
    Principal = $principal
    Force     = $true
}
Register-ScheduledTask @registerParams | Out-Null

Write-Host "Registered task '$TaskName' (Sat & Sun 09:00 start / 17:50 auto-stop)."
Write-Host "Check:    Get-ScheduledTask -TaskName $TaskName"
Write-Host "Test now: Start-ScheduledTask -TaskName $TaskName"
Write-Host "Logs:     ..\jrvltsql\logs\capture_<date>.log"
