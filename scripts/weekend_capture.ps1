# =====================================================================
# Weekend "smart money" interim-odds capture (disk-safe).
# (Comments kept ASCII on purpose: Windows PowerShell 5.1 misreads UTF-8
#  Japanese as Shift-JIS and breaks parsing. See docs/SMARTMONEY_CAPTURE.md.)
#
# Flow: start realtime (0B30 = all-bet odds, + race card / results / weight)
#       -> wait until evening -> kill the process (jltsql "stop" is a no-op)
#       -> archive win-odds timeseries (TS_SOKUHO_O1) into odds_history.db
#       -> wipe TS_SOKUHO_O1..O6 in the main DB -> clean fetch cache.
# This keeps the ~21GB main DB from bloating.
#
# Launched by Task Scheduler (register_weekend_tasks.ps1) Sat/Sun morning.
# Manual test: powershell -ExecutionPolicy Bypass -File scripts\weekend_capture.ps1
# =====================================================================
$ErrorActionPreference = "Stop"

# --- Environment (edit here only if paths differ) ---
$Root   = "C:\keiba_ateru\jrvltsql"
$Repo   = "C:\keiba_ateru\keiba-ateru"
$Jlt    = Join-Path $Root "jvenv\Scripts\jltsql.exe"
$Py     = Join-Path $Root "jvenv\Scripts\python.exe"
$DB     = Join-Path $Root "data\keiba.db"
$Arch   = Join-Path $Root "data\odds_history.db"
$Prune  = Join-Path $Repo "tools\prune_realtime_odds.py"
$Specs  = "0B11,0B12,0B14,0B15,0B30"   # weight / results / track / race-card / all-odds
$StopAt = "17:50"                       # auto-stop time (after last race)

$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Stamp  = Get-Date -Format "yyyyMMdd"
$Log    = Join-Path $LogDir "capture_$Stamp.log"
function Log($m) { "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  $m" | Tee-Object -FilePath $Log -Append }

function Get-RealtimeProcs {
    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -and $_.CommandLine -match 'jltsql.*realtime' }
}

Log "=== weekend_capture start ==="

# --- Prevent double start: if realtime already running, do nothing ---
$already = Get-RealtimeProcs
if ($already) {
    Log "realtime already running (PID $($already.ProcessId -join ',')) -> skip"
    exit 0
}
if (-not (Test-Path $Jlt)) { Log "jltsql not found: $Jlt"; exit 1 }

# --- Start realtime ---
$end = [datetime]::Today.Add([timespan]::Parse($StopAt))
if ((Get-Date) -ge $end) { Log "past stop time ($StopAt) -> skip"; exit 0 }
Log "start realtime: specs=$Specs  auto-stop=$end"
$rtOut = Join-Path $LogDir "rt_$Stamp.out"
$rtErr = Join-Path $LogDir "rt_$Stamp.err"
$spArgs = @{
    FilePath               = $Jlt
    ArgumentList           = @('realtime', 'start', '--specs', $Specs, '--db', 'sqlite')
    WorkingDirectory       = $Root
    PassThru               = $true
    WindowStyle            = 'Hidden'
    RedirectStandardOutput = $rtOut
    RedirectStandardError  = $rtErr
}
$p = Start-Process @spArgs
Log "started PID=$($p.Id)"

# --- Monitor until evening (every 60s) ---
while ((Get-Date) -lt $end) {
    if ($p.HasExited) { Log "realtime exited early (code $($p.ExitCode)). see $rtErr"; break }
    Start-Sleep -Seconds 60
}

# --- Stop (kill tree; jltsql stop is a no-op) ---
Log "stop: taskkill /T /F PID=$($p.Id)"
& taskkill /PID $p.Id /T /F 2>&1 | Out-Null
Start-Sleep -Seconds 3
foreach ($q in (Get-RealtimeProcs)) {
    Log "kill leftover realtime PID=$($q.ProcessId)"
    Stop-Process -Id $q.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 3

# --- Prune: archive win-odds timeseries, wipe TS_SOKUHO in main DB ---
if (Test-Path $Prune) {
    Log "prune: archive win-odds to odds_history.db, wipe TS_SOKUHO_O1..O6"
    & $Py $Prune --db $DB --archive $Arch 2>&1 | Tee-Object -FilePath $Log -Append
} else {
    Log "prune script missing: $Prune (main DB will bloat - fix this)"
}

# --- Clean fetch cache (realtime can leave residue) ---
$cache = Join-Path $Root "data\cache"
if (Test-Path $cache) { Log "clean cache: $cache"; Remove-Item $cache -Recurse -Force -ErrorAction SilentlyContinue }

# --- Record free space ---
$free = [math]::Round((Get-PSDrive C).Free / 1GB, 2)
Log "done. C: free $free GB"
Log "=== weekend_capture end ==="
