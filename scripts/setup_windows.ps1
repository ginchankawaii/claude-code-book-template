# keiba_ateru セットアップ（Windows / PowerShell）
# 取得(jrvltsql)と解析(本リポジトリ)のフォルダ・clone・venv を一括で用意する。
# 使い方:  PowerShell を開いて
#   irm https://raw.githubusercontent.com/ginchankawaii/claude-code-book-template/claude/horse-racing-prediction-pl12di/scripts/setup_windows.ps1 | iex
# もしくはこのファイルを保存して  powershell -ExecutionPolicy Bypass -File setup_windows.ps1

$ErrorActionPreference = "Stop"
$Root = "C:\keiba_ateru"
$RepoUrl = "https://github.com/ginchankawaii/claude-code-book-template.git"
$Branch  = "claude/horse-racing-prediction-pl12di"

Write-Host "=== keiba_ateru セットアップ ===" -ForegroundColor Cyan

# --- 前提チェック ---
function Need($cmd, $hint) {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
    Write-Host "[未インストール] $cmd  → $hint" -ForegroundColor Yellow
    return $false
  }
  return $true
}
$okGit    = Need "git"    "https://git-scm.com/download/win を入れてください"
$okDocker = Need "docker" "Docker Desktop を入れてください(解析側で使用): https://www.docker.com/products/docker-desktop/"

# 32bit Python の確認
$has32 = $false
try { & py -3-32 --version 2>$null; if ($LASTEXITCODE -eq 0) { $has32 = $true } } catch {}
if (-not $has32) {
  Write-Host "[注意] 32bit Python 3.10+ が見つかりません。jrvltsql の JV-Link 取得に必要です。" -ForegroundColor Yellow
  Write-Host "       python.org の Windows installer (32-bit) を入れてから再実行してください。" -ForegroundColor Yellow
}

if (-not $okGit) { Write-Host "git が無いので中断します。" -ForegroundColor Red; exit 1 }

# --- フォルダ ---
New-Item -ItemType Directory -Force -Path $Root | Out-Null
Set-Location $Root
Write-Host "作業ルート: $Root" -ForegroundColor Green

# --- 取得ツール jrvltsql ---
if (-not (Test-Path "$Root\jrvltsql")) {
  Write-Host "jrvltsql を clone..." -ForegroundColor Cyan
  git clone https://github.com/miyamamoto/jrvltsql.git
} else { Write-Host "jrvltsql は既にあります(skip)" }

# --- 解析リポジトリ(これまでの成果) ---
if (-not (Test-Path "$Root\keiba-ateru")) {
  Write-Host "解析リポジトリを clone..." -ForegroundColor Cyan
  git clone -b $Branch $RepoUrl keiba-ateru
} else { Write-Host "keiba-ateru は既にあります(skip)" }
New-Item -ItemType Directory -Force -Path "$Root\keiba-ateru\data" | Out-Null

# --- jrvltsql の 32bit venv 準備 ---
if ($has32) {
  Set-Location "$Root\jrvltsql"
  if (-not (Test-Path "$Root\jrvltsql\jvenv")) {
    Write-Host "32bit venv を作成して jrvltsql を導入..." -ForegroundColor Cyan
    & py -3-32 -m venv jvenv
    & "$Root\jrvltsql\jvenv\Scripts\python.exe" -m pip install --upgrade pip
    & "$Root\jrvltsql\jvenv\Scripts\pip.exe" install -e .
  } else { Write-Host "jvenv は既にあります(skip)" }
  Set-Location $Root
}

# --- 次の手順を表示 ---
Write-Host ""
Write-Host "=== 準備完了。次の2ステップ ===" -ForegroundColor Green
Write-Host ""
Write-Host "① 取得(DBを作る):" -ForegroundColor Cyan
Write-Host "   cd $Root\jrvltsql"
Write-Host "   .\jvenv\Scripts\activate"
Write-Host "   quickstart.bat                 # data\keiba.db が出来る(時間かかる)"
Write-Host "   deactivate"
Write-Host ""
Write-Host "② 解析(Docker):" -ForegroundColor Cyan
Write-Host "   copy $Root\jrvltsql\data\keiba.db $Root\keiba-ateru\data\"
Write-Host "   cd $Root\keiba-ateru"
Write-Host "   docker compose build"
Write-Host "   docker compose run --rm keiba --db /data/keiba.db"
Write-Host ""
Write-Host "②の出力が「バリデーション: クリーン」なら成功。警告が出たらその行を共有してください。" -ForegroundColor Green
