# keiba_ateru setup (Windows / PowerShell)
# Creates folders, clones acquisition(jrvltsql) and analysis(this repo), sets up a 32-bit venv.
# NOTE: ASCII-only on purpose so Windows PowerShell (Shift-JIS codepage) won't mojibake/parse-fail.
# Usage:  powershell -ExecutionPolicy Bypass -File .\keiba-ateru\scripts\setup_windows.ps1

$ErrorActionPreference = "Stop"
$Root    = "C:\keiba_ateru"
$RepoUrl = "https://github.com/ginchankawaii/claude-code-book-template.git"
$Branch  = "claude/horse-racing-prediction-pl12di"

Write-Host "=== keiba_ateru setup ===" -ForegroundColor Cyan

function Need($cmd, $hint) {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
    Write-Host "[MISSING] $cmd  -> $hint" -ForegroundColor Yellow
    return $false
  }
  Write-Host "[ok] $cmd found" -ForegroundColor DarkGray
  return $true
}
$okGit    = Need "git"    "install Git for Windows: https://git-scm.com/download/win"
$okDocker = Need "docker" "install Docker Desktop (used by analysis): https://www.docker.com/products/docker-desktop/"

# 32-bit Python check (needed for jrvltsql / JV-Link COM)
$has32 = $false
try { & py -3-32 --version 2>$null; if ($LASTEXITCODE -eq 0) { $has32 = $true } } catch {}
if ($has32) {
  Write-Host "[ok] 32-bit Python found" -ForegroundColor DarkGray
} else {
  Write-Host "[MISSING] 32-bit Python 3.10+  -> install the python.org Windows installer (32-bit)" -ForegroundColor Yellow
}

if (-not $okGit) { Write-Host "git is required. Aborting." -ForegroundColor Red; exit 1 }

# Folders
New-Item -ItemType Directory -Force -Path $Root | Out-Null
Set-Location $Root
Write-Host "work root: $Root" -ForegroundColor Green

# Acquisition tool jrvltsql (public repo)
if (-not (Test-Path "$Root\jrvltsql")) {
  Write-Host "cloning jrvltsql..." -ForegroundColor Cyan
  git clone https://github.com/miyamamoto/jrvltsql.git
} else { Write-Host "jrvltsql already present (skip)" }

# Analysis repo (this project = all prior work)
if (-not (Test-Path "$Root\keiba-ateru")) {
  Write-Host "cloning analysis repo..." -ForegroundColor Cyan
  git clone -b $Branch $RepoUrl keiba-ateru
} else { Write-Host "keiba-ateru already present (skip)" }
New-Item -ItemType Directory -Force -Path "$Root\keiba-ateru\data" | Out-Null

# jrvltsql 32-bit venv
if ($has32) {
  Set-Location "$Root\jrvltsql"
  if (-not (Test-Path "$Root\jrvltsql\jvenv")) {
    Write-Host "creating 32-bit venv and installing jrvltsql..." -ForegroundColor Cyan
    & py -3-32 -m venv jvenv
    & "$Root\jrvltsql\jvenv\Scripts\python.exe" -m pip install --upgrade pip
    & "$Root\jrvltsql\jvenv\Scripts\pip.exe" install -e .
  } else { Write-Host "jvenv already present (skip)" }
  Set-Location $Root
}

Write-Host ""
Write-Host "=== ready. next 2 steps ===" -ForegroundColor Green
Write-Host ""
Write-Host "STEP 1 - acquire (build the DB):" -ForegroundColor Cyan
Write-Host "   cd $Root\jrvltsql"
Write-Host "   .\jvenv\Scripts\activate"
Write-Host "   quickstart.bat                 # creates data\keiba.db (takes a while)"
Write-Host "   deactivate"
Write-Host ""
Write-Host "STEP 2 - analyze (Docker):" -ForegroundColor Cyan
Write-Host "   copy $Root\jrvltsql\data\keiba.db $Root\keiba-ateru\data\"
Write-Host "   cd $Root\keiba-ateru"
Write-Host "   docker compose build"
Write-Host "   docker compose run --rm keiba --db /data/keiba.db"
Write-Host ""
Write-Host "If STEP 2 prints 'validation: clean' you are good. Otherwise share the warning line." -ForegroundColor Green
