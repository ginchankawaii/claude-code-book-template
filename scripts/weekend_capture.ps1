# =====================================================================
# 土日だけ動く「賢い金(中間オッズ)」軽量キャプチャ
# ---------------------------------------------------------------------
# 流れ: realtime起動(0B30=全賭式オッズ等) → 夕方まで待機 → プロセスをkill
#       → 単勝の時系列だけ odds_history.db へ退避 → 本体のTS_SOKUHOを一掃
#       → fetchキャッシュ掃除。これで本体DB(約21GB)を肥大させない。
#
# jltsql の "stop" は未実装(no-op)なので、停止はプロセスのkillで行う。
# タスクスケジューラから土・日の朝に起動される(register_weekend_tasks.ps1)。
# 手動テストもできる:  powershell -ExecutionPolicy Bypass -File scripts\weekend_capture.ps1
# =====================================================================
$ErrorActionPreference = "Stop"

# --- 環境(必要ならここだけ書き換える) ---
$Root   = "C:\keiba_ateru\jrvltsql"
$Repo   = "C:\keiba_ateru\keiba-ateru"
$Jlt    = Join-Path $Root "jvenv\Scripts\jltsql.exe"
$Py     = Join-Path $Root "jvenv\Scripts\python.exe"
$DB     = Join-Path $Root "data\keiba.db"
$Arch   = Join-Path $Root "data\odds_history.db"
$Prune  = Join-Path $Repo "tools\prune_realtime_odds.py"
$Specs  = "0B11,0B12,0B14,0B15,0B30"   # 馬体重/結果/馬場/出馬表/全賭式オッズ
$StopAt = "17:50"                       # この時刻に自動停止(最終レース後)

$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Stamp  = Get-Date -Format "yyyyMMdd"
$Log    = Join-Path $LogDir "capture_$Stamp.log"
function Log($m) { "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  $m" | Tee-Object -FilePath $Log -Append }

function Get-RealtimeProcs {
    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -and $_.CommandLine -match 'jltsql.*realtime' }
}

Log "=== weekend_capture 開始 ==="

# --- 二重起動防止: 既に realtime が居たら何もしない ---
$already = Get-RealtimeProcs
if ($already) {
    Log "既に realtime 稼働中 (PID $($already.ProcessId -join ',')) → 起動せず終了"
    exit 0
}

if (-not (Test-Path $Jlt)) { Log "jltsql が見つからない: $Jlt"; exit 1 }

# --- realtime 起動 ---
$end = [datetime]::Today.Add([timespan]::Parse($StopAt))
if ((Get-Date) -ge $end) { Log "既に停止時刻を過ぎている($StopAt) → 起動せず終了"; exit 0 }
Log "realtime 起動: specs=$Specs  自動停止予定=$end"
$rtOut = Join-Path $LogDir "rt_$Stamp.out"
$rtErr = Join-Path $LogDir "rt_$Stamp.err"
$p = Start-Process -FilePath $Jlt `
        -ArgumentList @('realtime','start','--specs',$Specs,'--db','sqlite') `
        -WorkingDirectory $Root -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $rtOut -RedirectStandardError $rtErr
Log "起動 PID=$($p.Id)"

# --- 夕方まで監視(60秒ごと) ---
while ((Get-Date) -lt $end) {
    if ($p.HasExited) { Log "realtime が予期せず終了 (ExitCode $($p.ExitCode))。errログ: $rtErr"; break }
    Start-Sleep -Seconds 60
}

# --- 停止(stopはno-opなのでプロセス木をkill) ---
Log "停止: taskkill /T /F PID=$($p.Id)"
& taskkill /PID $p.Id /T /F 2>&1 | Out-Null
Start-Sleep -Seconds 3
# 取りこぼした realtime プロセスも掃除(子python等)
foreach ($q in (Get-RealtimeProcs)) {
    Log "残存 realtime kill PID=$($q.ProcessId)"
    Stop-Process -Id $q.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 3

# --- 剪定: 単勝軌跡を退避し本体TS_SOKUHOを一掃 ---
if (Test-Path $Prune) {
    Log "剪定実行: $Prune"
    & $Py $Prune --db $DB --archive $Arch 2>&1 | Tee-Object -FilePath $Log -Append
} else {
    Log "剪定スクリプトが無い: $Prune (本体DBが肥大するので要修正)"
}

# --- fetchキャッシュ掃除(残骸が出ることがある) ---
$cache = Join-Path $Root "data\cache"
if (Test-Path $cache) { Log "cache 掃除: $cache"; Remove-Item $cache -Recurse -Force -ErrorAction SilentlyContinue }

# --- 空き容量を記録 ---
$free = [math]::Round((Get-PSDrive C).Free / 1GB, 2)
Log "完了。C: 空き $free GB"
Log "=== weekend_capture 終了 ==="
