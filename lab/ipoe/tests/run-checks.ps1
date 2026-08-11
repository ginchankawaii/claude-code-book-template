# run-checks.ps1 - Windows version of run-checks.sh
#
# For the verification client PC connected to the CPE LAN port.
# Use this when you cannot put a Linux machine under the CPE.
#
#   Usage (PowerShell):
#     .\run-checks.ps1
#     .\run-checks.ps1 -ExpectSrc4 198.51.100.10     # MAP-E  (PD mode)
#     .\run-checks.ps1 -ExpectSrc4 198.51.100.20     # MAP-E  (RA mode)
#     .\run-checks.ps1 -ExpectSrc4 203.0.113.1       # DS-Lite (after AFTR NAT)
#     .\run-checks.ps1 -ExpectSrc4 203.0.113.2       # PPPoE   (after BRAS NAT)
#
#   Save evidence:
#     .\run-checks.ps1 -ExpectSrc4 203.0.113.1 | Tee-Object -FilePath checks.log
#
# NOTE: This file is deliberately ASCII-only. Japanese text in a .ps1 gets
#       mangled by Windows PowerShell 5.1 depending on the file encoding,
#       which would make the evidence log unreadable. See runbook section 8.
#
# Requires: Windows 10 1803+ (for curl.exe). No extra install needed.

param(
    [string]$ExpectSrc4 = "",
    [string]$ExpectSrc6 = "",
    [switch]$SkipV6
)

$V4_TARGET = "203.0.113.80"
$V6_TARGET = "2001:db8:cafe::80"
$DNS_NAME  = "www.lab.example"
$BIG_MIN   = 5000000

$script:Pass = 0
$script:Fail = 0

function Check {
    param([string]$Name, [scriptblock]$Test)
    $ok = $false
    try { $ok = [bool](& $Test) } catch { $ok = $false }
    if ($ok) { Write-Output "PASS: $Name"; $script:Pass++ }
    else     { Write-Output "FAIL: $Name"; $script:Fail++ }
}

# LAN is IPv4-only in most real projects: the reason for moving off PPPoE is
# speed (PPPoE congestion), not IPv6 adoption. Re-addressing the LAN would mean
# firewall and application rework, so customers keep IPv4 inside.
# In that setup IPv6 from the client is SUPPOSED to fail - do not count it.
function CheckV6 {
    param([string]$Name, [scriptblock]$Test)
    if ($SkipV6) { Write-Output "SKIP: $Name (-SkipV6 / LAN is IPv4 only)"; return }
    Check $Name $Test
}

Write-Output "=== IPoE switch check $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="

Write-Output "--- Addresses / routes ---"
Get-NetIPAddress -AddressFamily IPv6 -ErrorAction SilentlyContinue |
    Where-Object { $_.PrefixOrigin -ne 'WellKnown' -and $_.IPAddress -notlike 'fe80*' } |
    Format-Table -AutoSize InterfaceAlias, IPAddress, PrefixLength, AddressState, PreferredLifetime |
    Out-String | Write-Output
Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Format-Table -AutoSize InterfaceAlias, NextHop, RouteMetric | Out-String | Write-Output
Get-NetRoute -DestinationPrefix '::/0' -ErrorAction SilentlyContinue |
    Format-Table -AutoSize InterfaceAlias, NextHop, RouteMetric | Out-String | Write-Output

# Warm up the path (not counted). First packet can time out while neighbours resolve.
ping.exe -4 -n 1 -w 3000 $V4_TARGET | Out-Null
ping.exe -6 -n 1 -w 3000 $V6_TARGET | Out-Null

# Source address sanity check. If a ULA (fd00::/8) is picked, every IPv6 test
# below will time out and the reason is very hard to see from the symptoms.
$src6 = ""
try {
    $r = Find-NetRoute -RemoteIPAddress $V6_TARGET -ErrorAction Stop
    $src6 = ($r | Where-Object { $_.IPAddress } | Select-Object -First 1).IPAddress
} catch { }
if ($src6 -match '^(fd|fc)') {
    Write-Output "WARNING: IPv6 source is a ULA ($src6)."
    Write-Output "         The lab has no return path for ULA, so all IPv6 checks will FAIL."
    Write-Output "         Fix: disable ULA on the CPE (uci set network.globals.ula_prefix='')"
} elseif ($src6) {
    Write-Output "INFO: IPv6 source address = $src6"
} else {
    Write-Output "WARNING: could not determine an IPv6 source address (no global IPv6?)"
}

Write-Output "--- Reachability ---"
Check "IPv4 ping ($V4_TARGET)" { ping.exe -4 -n 2 -w 2000 $V4_TARGET | Out-Null; $LASTEXITCODE -eq 0 }
CheckV6 "IPv6 ping ($V6_TARGET)" { ping.exe -6 -n 2 -w 2000 $V6_TARGET | Out-Null; $LASTEXITCODE -eq 0 }

Write-Output "--- DNS ---"
Clear-DnsClientCache -ErrorAction SilentlyContinue
Check "A record ($DNS_NAME)"    { (Resolve-DnsName -Name $DNS_NAME -Type A    -ErrorAction Stop).Count -gt 0 }
Check "AAAA record ($DNS_NAME)" { (Resolve-DnsName -Name $DNS_NAME -Type AAAA -ErrorAction Stop).Count -gt 0 }

Write-Output "--- HTTP (the response shows the exit address) ---"
$body4 = ""
$body6 = ""
try { $body4 = (curl.exe -4 -fs --connect-timeout 5 "http://$V4_TARGET/") -join "`n" } catch { }
try { $body6 = (curl.exe -6 -fs --connect-timeout 5 "http://[$V6_TARGET]/") -join "`n" } catch { }
if ($body4) { Write-Output $body4 }
if ($body6) { Write-Output $body6 }
Check "HTTP over IPv4" { $body4 -ne "" }
CheckV6 "HTTP over IPv6" { $body6 -ne "" }

Write-Output "--- Exit address (are we really going through the CPE?) ---"
$s4 = ""
$s6 = ""
if ($body4 -match '(?m)^src:\s*(\S+)') { $s4 = $Matches[1] }
if ($body6 -match '(?m)^src:\s*(\S+)') { $s6 = $Matches[1] }
Write-Output "INFO: exit IPv4 = $(if ($s4) { $s4 } else { '(unknown)' })  /  exit IPv6 = $(if ($s6) { $s6 } else { '(unknown)' })"
if ($ExpectSrc4) { Check "exit IPv4 is $ExpectSrc4" { $s4 -eq $ExpectSrc4 } }
else { Write-Output "INFO: -ExpectSrc4 not given, so the path itself is NOT verified." }
if ($ExpectSrc6) { Check "exit IPv6 is $ExpectSrc6" { $s6 -eq $ExpectSrc6 } }

Write-Output "--- Large TCP transfer (MSS/PMTUD black hole only breaks big transfers) ---"
function BigOk {
    param([string]$Family, [string]$Url)
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        curl.exe $Family -fs -m 30 -o $tmp $Url 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { return $false }
        return ((Get-Item $tmp).Length -ge $BIG_MIN)
    } finally { Remove-Item $tmp -ErrorAction SilentlyContinue }
}
Check "TCP 5MB over IPv4" { BigOk "-4" "http://$V4_TARGET/big.bin" }
CheckV6 "TCP 5MB over IPv6" { BigOk "-6" "http://[$V6_TARGET]/big.bin" }

Write-Output "--- Fragmentation (large ICMP without DF) ---"
Check "IPv4 fragment (2000B)" { ping.exe -4 -n 2 -w 2000 -l 2000 $V4_TARGET | Out-Null; $LASTEXITCODE -eq 0 }
CheckV6 "IPv6 fragment (2000B)" { ping.exe -6 -n 2 -w 2000 -l 2000 $V6_TARGET | Out-Null; $LASTEXITCODE -eq 0 }

Write-Output "--- Path MTU (ping with DF) ---"
foreach ($size in 1472, 1432, 1426) {
    ping.exe -4 -n 1 -w 2000 -f -l $size $V4_TARGET | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Output "INFO: IPv4 path MTU >= $($size + 28) (payload $size passed)"
        break
    } else {
        Write-Output "INFO: payload $size failed"
    }
}

Write-Output "--- DNS fallback feel (delay appears when v6 is broken) ---"
$sw = [System.Diagnostics.Stopwatch]::StartNew()
curl.exe -s --connect-timeout 15 -o NUL "http://$DNS_NAME/" 2>$null | Out-Null
$rc = $LASTEXITCODE
$sw.Stop()
Write-Output "INFO: http://$DNS_NAME/ took $($sw.ElapsedMilliseconds) ms (rc=$rc)"

Write-Output "=== Result: PASS=$($script:Pass) FAIL=$($script:Fail) ==="
if ($script:Fail -gt 0) { exit 1 } else { exit 0 }
