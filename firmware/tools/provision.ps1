# MindClip プロビジョニング（Windows / PowerShell 5.1）
#
# USB でつないだ MindClip に、Wi-Fi・サーバの URL・証明書・共有鍵（HMAC）を入れて、
# test wifi / test server まで行う。手で貼り付ける代わりに使う。
#
#   powershell -ExecutionPolicy Bypass -File firmware\tools\provision.ps1 -ServerUrl https://192.168.11.74:8443
#
# - Wi-Fi のパスワードはこの画面で入力する（画面に出ない・ファイルに残らない）。
# - 鍵・パスワードは画面に表示しない。デバイスの応答は OK: / NG: / ERR: と、
#   show の結果（wifi.pass の行を除く）だけを表示する。
# - 本体のボタンは使わない。esptool でリセットし、起動直後 3秒の受付窓で CLI に入る。

param(
  [Parameter(Mandatory = $true)][string]$ServerUrl,
  [string]$PkiDir   = (Join-Path $env:USERPROFILE '.mindclip-pki'),
  [string]$HmacFile = '',
  [string]$DeviceId = 'mindclip-01',
  [string]$Ssid     = '',
  [string]$Port     = '',
  [switch]$TestOnly          # 設定は入れず test wifi / test server だけ行う
)

$ErrorActionPreference = 'Stop'
if (-not $HmacFile) { $HmacFile = Join-Path $PkiDir 'hmac.key' }

function Find-XiaoPort {
  $dev = Get-CimInstance Win32_PnPEntity | Where-Object { $_.DeviceID -match 'VID_303A' -and $_.Name -match '\((COM\d+)\)' }
  foreach ($d in $dev) { if ($d.Name -match '\((COM\d+)\)') { return $Matches[1] } }
  return $null
}

function Find-Esptool {
  $e = Get-ChildItem "$env:LOCALAPPDATA\Arduino15\packages\esp32\tools\esptool_py" -Recurse -Filter esptool.exe -ErrorAction SilentlyContinue |
       Sort-Object FullName -Descending | Select-Object -First 1
  if (-not $e) { throw 'esptool.exe が見つかりません（Arduino の esp32 ボードパッケージを入れてください）' }
  return $e.FullName
}

# --- 入力の確認（秘密は読むだけで表示しない） ---
if (-not $TestOnly) {
  foreach ($f in 'ca.crt', 'device.crt', 'device.key') {
    if (-not (Test-Path (Join-Path $PkiDir $f))) { throw "見つかりません: $(Join-Path $PkiDir $f)" }
  }
  if (-not (Test-Path $HmacFile)) { throw "見つかりません: $HmacFile" }
  $hmac = (Get-Content $HmacFile -Raw).Trim()
  if ($hmac -notmatch '^[0-9a-fA-F]{64}$') { throw 'hmac.key が 64桁の16進ではありません' }
  if (-not $Ssid) { $Ssid = Read-Host 'Wi-Fi の SSID（2.4GHz で届く名前）' }
  $sec = Read-Host 'Wi-Fi のパスワード（画面には出ません）' -AsSecureString
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
  $wifiPass = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
  if ($wifiPass -match '\s') { Write-Warning 'パスワードの前後や途中の空白は、デバイス側で削られることがあります' }
}

if (-not $Port) { $Port = Find-XiaoPort }
if (-not $Port) { throw 'MindClip（XIAO ESP32S3）のポートが見つかりません。スイッチを ON にして、データ通信できる USB ケーブルでつないでください' }
Write-Host "ポート: $Port"

# --- シリアル ---
$sp = $null
$buf = New-Object System.Text.StringBuilder

function Open-Port {
  param([int]$TimeoutMs = 8000)
  $t0 = Get-Date
  while (((Get-Date) - $t0).TotalMilliseconds -lt $TimeoutMs) {
    try {
      $p = New-Object System.IO.Ports.SerialPort $Port, 115200, 'None', 8, 'One'
      $p.Encoding = [Text.Encoding]::UTF8
      $p.NewLine = "`n"
      $p.DtrEnable = $false; $p.RtsEnable = $false   # 立てるとリセット・書き込みモードに入ることがある
      $p.ReadTimeout = 50
      $p.Open()
      return $p
    } catch { Start-Sleep -Milliseconds 50 }
  }
  return $null
}

function Read-Available {
  if ($sp.BytesToRead -gt 0) { [void]$buf.Append($sp.ReadExisting()) }
}

# プロンプト "mindclip> " が出るまで待ち、それまでの出力を返す
function Wait-Prompt {
  param([int]$TimeoutSec = 15)
  $t0 = Get-Date
  while (((Get-Date) - $t0).TotalSeconds -lt $TimeoutSec) {
    Read-Available
    $s = $buf.ToString()
    $i = $s.LastIndexOf('mindclip> ')
    if ($i -ge 0) {
      [void]$buf.Clear()
      return $s.Substring(0, $i)
    }
    Start-Sleep -Milliseconds 50
  }
  $s = $buf.ToString(); [void]$buf.Clear()
  $tail = ($s -split "`n" | Where-Object { $_ -notmatch 'wifi\.pass|hmac\.key' } | Select-Object -Last 3) -join ' / '
  throw "デバイスの応答がありません（$TimeoutSec 秒）。途中まで: $tail"
}

# 表示してよい行だけ出す（コマンドのエコーと wifi.pass の行は出さない）
function Show-Reply {
  param([string]$text)
  foreach ($l in ($text -split "`r?`n")) {
    $l = $l.TrimEnd()
    if (-not $l) { continue }
    if ($l -match '^(set|paste|show|save|test|reboot|help)\b') { continue }   # エコー
    if ($l -match '^wifi\.pass\s') { continue }
    if ($l -match '^(OK:|NG:|ERR:|result=|connecting|GET /|\[)' -or $l -match '^\S+\s+= ') { Write-Host "  $l" }
  }
}

function Send-Cmd {
  param([string]$line, [int]$TimeoutSec = 15, [string]$Label = $line)
  Write-Host "> $Label"
  $sp.Write($line + "`n")
  Show-Reply (Wait-Prompt -TimeoutSec $TimeoutSec)
}

function Send-Pem {
  param([string]$key, [string]$file)
  Write-Host "> paste $key  ($([IO.Path]::GetFileName($file)))"
  $sp.Write("paste $key`n")
  $t0 = Get-Date
  while (-not $buf.ToString().Contains('PEM を貼り付けてください')) {
    Read-Available
    if (((Get-Date) - $t0).TotalSeconds -gt 5) { throw "paste $key の受付が始まりません" }
    Start-Sleep -Milliseconds 20
  }
  [void]$buf.Clear()
  foreach ($l in (Get-Content $file)) {
    if ($l.Trim()) { $sp.Write($l.Trim() + "`n"); Start-Sleep -Milliseconds 15 }
  }
  $sp.Write(".`n")
  $r = Wait-Prompt -TimeoutSec 10
  Show-Reply $r
  $expected = ((Get-Content $file | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim().Length + 1 }) | Measure-Object -Sum).Sum
  if ($r -match 'に (\d+) バイト保存') {
    if ([int]$Matches[1] -ne $expected) { throw "$key のバイト数が合いません（送信 $expected / 保存 $($Matches[1])）" }
  } else { throw "$key を保存できませんでした" }
}

try {
  # --- リセット → 3秒以内に CLI へ ---
  $esptool = Find-Esptool
  $entered = $false
  for ($try = 1; $try -le 3 -and -not $entered; $try++) {
    Write-Host "本体を再起動して設定モードに入ります（$try 回目）..."
    $ErrorActionPreference = 'Continue'
    & $esptool --chip esp32s3 -p $Port --after hard-reset read-mac *> $null
    $ErrorActionPreference = 'Stop'
    $sp = Open-Port -TimeoutMs 8000
    if (-not $sp) { continue }
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt 6) {
      try { $sp.Write("`n") } catch { }
      Start-Sleep -Milliseconds 150
      try { Read-Available } catch { }
      if ($buf.ToString().Contains('mindclip> ')) { $entered = $true; break }
    }
    if (-not $entered) { try { $sp.Close() } catch { }; $sp = $null; [void]$buf.Clear() }
  }
  if (-not $entered) { throw '設定モードに入れませんでした（LED が速く点滅しない）。USB を挿し直してもう一度実行してください' }
  # 余分に送った改行への応答（プロンプトの連続）が止まるまで捨てる
  do { Start-Sleep -Milliseconds 400; $n = $sp.BytesToRead; Read-Available; [void]$buf.Clear() } while ($n -gt 0)
  Write-Host '設定モードに入りました（LED が速く点滅します）'

  if (-not $TestOnly) {
    Send-Cmd "set wifi.ssid $Ssid"
    Send-Cmd "set wifi.pass $wifiPass" -Label 'set wifi.pass ********'
    $wifiPass = $null
    Send-Cmd "set srv.url $ServerUrl"
    Send-Cmd "set dev.id $DeviceId"
    Send-Pem 'srv.ca'  (Join-Path $PkiDir 'ca.crt')
    Send-Pem 'dev.crt' (Join-Path $PkiDir 'device.crt')
    Send-Pem 'dev.key' (Join-Path $PkiDir 'device.key')
    Send-Cmd "set hmac.key $hmac" -Label 'set hmac.key ****（64桁）'
    $hmac = $null
    Send-Cmd 'save'
  }
  Send-Cmd 'show'
  Send-Cmd 'test wifi'   -TimeoutSec 60
  Send-Cmd 'test server' -TimeoutSec 90
  Write-Host ''
  Write-Host '終わったら、本体は 5分で自動的に通常動作に戻ります（すぐ戻すなら USB を抜く）。'
}
finally {
  if ($sp -and $sp.IsOpen) { $sp.Close() }
}
