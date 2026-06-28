# =====================================================================
# weekend_capture.ps1 を「毎週土・日の朝9時」に自動起動するタスクを登録する。
# 管理者PowerShellで一度だけ実行する(最上位権限の登録には管理者が要る場合がある):
#
#   powershell -ExecutionPolicy Bypass -File scripts\register_weekend_tasks.ps1
#
# 解除したいとき:
#   Unregister-ScheduledTask -TaskName "KeibaWeekendOddsCapture" -Confirm:$false
#
# 重要(JV-Link は COM): タスクは「ログオン中のユーザ」で対話デスクトップ上で動かす。
#   → PCはログインしたまま(ロック画面はOK)にしておくこと。ログオフ/別ユーザだと動かない。
# 重要(スリープ): 日中にPCがスリープすると取得が止まる。電源プランで「スリープしない」に
#   するか、少なくとも開催時間帯(9〜18時)は起きているようにすること。-WakeToRun で
#   開始時刻には起こすが、途中のスリープは防げない。
# =====================================================================
$ErrorActionPreference = "Stop"

$Repo     = "C:\keiba_ateru\keiba-ateru"
$Script   = Join-Path $Repo "scripts\weekend_capture.ps1"
$TaskName = "KeibaWeekendOddsCapture"

if (-not (Test-Path $Script)) { throw "キャプチャ本体が見つからない: $Script" }

# バックティック行継続は壊れやすいので、1行 + splatting(ハッシュテーブル渡し)で組む
$actionArg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArg

# 土・日の 09:00 起動(1Rの前。朝のオッズ形成から拾う)
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday, Sunday -At 9:00am

$settingsParams = @{
    StartWhenAvailable         = $true
    AllowStartIfOnBatteries    = $true
    DontStopIfGoingOnBatteries = $true
    WakeToRun                  = $true
    ExecutionTimeLimit         = (New-TimeSpan -Hours 11)
    MultipleInstances          = 'IgnoreNew'
}
$settings = New-ScheduledTaskSettingsSet @settingsParams

# 対話デスクトップが要る(JV-Link COM)ため、ログオン中ユーザで最上位権限実行
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

Write-Host "登録完了: タスク '$TaskName' (毎週 土・日 09:00 起動 / 17:50 自動停止)"
Write-Host "確認:   Get-ScheduledTask -TaskName $TaskName"
Write-Host "今すぐ手動テスト: Start-ScheduledTask -TaskName $TaskName"
Write-Host "ログ:   ..\jrvltsql\logs\capture_<日付>.log"
