<#
.SYNOPSIS
    Outlookの予定にINS番号を自動付与し、INS番号ごとの工数集計を表示する。

.DESCRIPTION
    キーワード辞書(ins_dictionary.csv)と予定の件名・場所を突き合わせて
    INS番号を付与します。既定ではドライラン(表示のみ)で、-Apply を付けた
    ときだけOutlookに書き込みます。

    あわせてINS番号ごとの合計時間を表示するので、クラウドログ入力の
    チートシートとしても使えます(書き込みせず集計だけ見る使い方もOK)。

    ※クラウドログのOutlook連携がINS番号を「どの欄」から読むかは要確認。
      既定は分類(Category)に "INS:12345" 形式で付与します。仕様が判明したら
      -Target と -InsFormat を合わせてください。

.PARAMETER Date
    対象開始日。既定は昨日(前日の実績を翌朝に登録する運用を想定)。

.PARAMETER Days
    対象日数。既定は1日。-Days 5 で1週間分をまとめて処理。

.PARAMETER DictionaryPath
    キーワード辞書CSV(ヘッダー: Keyword,Ins,Note)。UTF-8(BOM付き)で保存。
    上の行ほど優先。ins_dictionary.sample.csv をコピーして作成する。

.PARAMETER Target
    Category      = 予定の分類に付与(既定・件名を汚さない)
    SubjectPrefix = 件名の先頭に [INS:12345] を付与

.PARAMETER InsFormat
    付与する文字列の書式。{0} がINS番号に置き換わる。既定 "INS:{0}"。

.PARAMETER Apply
    実際にOutlookへ書き込む。付けなければドライラン(表示のみ)。

.EXAMPLE
    .\Set-InsNumber.ps1
    昨日の予定をドライランし、付与予定の内容と工数集計を表示する。

.EXAMPLE
    .\Set-InsNumber.ps1 -Apply
    昨日の予定に実際にINS番号を書き込む。

.EXAMPLE
    .\Set-InsNumber.ps1 -Date 2026-07-21 -Days 5
    7/21からの5日分をドライランする。
#>
param(
    [DateTime]$Date = (Get-Date).Date.AddDays(-1),
    [int]$Days = 1,
    [string]$DictionaryPath = (Join-Path $PSScriptRoot 'ins_dictionary.csv'),
    [ValidateSet('Category', 'SubjectPrefix')]
    [string]$Target = 'Category',
    [string]$InsFormat = 'INS:{0}',
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'

# --- 辞書の読み込み -------------------------------------------------------
if (-not (Test-Path -LiteralPath $DictionaryPath)) {
    Write-Error ("辞書ファイルが見つかりません: {0}`nins_dictionary.sample.csv をコピーして ins_dictionary.csv を作成してください。" -f $DictionaryPath)
}
$dictionary = @(Import-Csv -LiteralPath $DictionaryPath -Encoding UTF8 |
    Where-Object { $_.Keyword -and $_.Ins })
if ($dictionary.Count -eq 0) {
    Write-Error "辞書が空です。ヘッダー Keyword,Ins,Note の行と、キーワードを1行以上書いてください。"
}

# --- Outlookから対象期間の予定を取得 --------------------------------------
try {
    $outlook = New-Object -ComObject Outlook.Application
} catch {
    Write-Error "Outlookを起動できません。Outlookがインストールされた端末で実行してください。($_)"
}
$namespace = $outlook.GetNamespace('MAPI')
$calendar = $namespace.GetDefaultFolder(9)   # 9 = olFolderCalendar
$items = $calendar.Items
$items.Sort('[Start]')
$items.IncludeRecurrences = $true

$rangeStart = $Date.Date
$rangeEnd = $rangeStart.AddDays($Days)
# Restrictの日付書式はOSロケール依存のため、カルチャ準拠の 'g' 書式を使う
# 開始・終了の両方で絞り、範囲に重なる予定(前日夜から跨ぐ会議など)も拾う
$filter = "[Start] < '{1}' AND [End] > '{0}'" -f `
    $rangeStart.ToString('g'), $rangeEnd.ToString('g')
$appointments = @($items.Restrict($filter))

if ($appointments.Count -eq 0) {
    Write-Host ("{0:yyyy/MM/dd} から {1} 日分の予定はありませんでした。" -f $rangeStart, $Days)
    return
}

# --- 付与済み判定用の正規表現 (InsFormatの{0}を数字にしたもの) -------------
$formatParts = $InsFormat -split '\{0\}', 2
$existingPattern = [regex]::Escape($formatParts[0]) + '(\d+)'
if ($formatParts.Count -gt 1 -and $formatParts[1]) {
    $existingPattern += [regex]::Escape($formatParts[1])
}

# --- 各予定を辞書と突き合わせ ---------------------------------------------
$plan = @()
foreach ($appt in $appointments) {
    if ($appt.AllDayEvent) { continue }

    $subject = [string]$appt.Subject
    $haystack = $subject + ' ' + [string]$appt.Location
    $hours = [Math]::Round(([DateTime]$appt.End - [DateTime]$appt.Start).TotalHours, 2)

    $checkText = if ($Target -eq 'Category') { [string]$appt.Categories } else { $subject }
    $existingMatch = [regex]::Match($checkText, $existingPattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)

    $entry = [PSCustomObject]@{
        Start   = [DateTime]$appt.Start
        Hours   = $hours
        Subject = $subject
        Ins     = $null
        Action  = ''
        Item    = $appt
    }

    if ($existingMatch.Success) {
        $entry.Ins = $existingMatch.Groups[1].Value
        $entry.Action = '付与済み'
    } else {
        foreach ($row in $dictionary) {
            if ($haystack.IndexOf([string]$row.Keyword, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                $entry.Ins = [string]$row.Ins
                $entry.Action = if ($Apply) { '付与' } else { '付与(予定)' }
                break
            }
        }
        if (-not $entry.Ins) { $entry.Action = '未マッチ' }
    }
    $plan += $entry
}

# --- 書き込み (-Apply のときだけ) -----------------------------------------
foreach ($entry in $plan) {
    if ($entry.Action -ne '付与') { continue }
    $tag = $InsFormat -f $entry.Ins
    $appt = $entry.Item
    if ($Target -eq 'Category') {
        # 分類はロケールにより「,」「;」区切りが混在するため両対応で分割する
        $categories = @()
        if ($appt.Categories) {
            $categories = @($appt.Categories -split '\s*[;,]\s*' | Where-Object { $_ })
        }
        if ($categories -notcontains $tag) {
            $appt.Categories = ($categories + $tag) -join '; '
        }
    } else {
        $appt.Subject = ('[{0}] {1}' -f $tag, $entry.Subject)
    }
    $appt.Save()
}

# --- 結果表示 -------------------------------------------------------------
$modeLabel = if ($Apply) { '書き込みモード' } else { 'ドライラン(表示のみ)' }
Write-Host ''
Write-Host ("=== {0:yyyy/MM/dd} から {1} 日分 [{2}] ===" -f $rangeStart, $Days, $modeLabel)
$plan |
    Select-Object @{n = '開始'; e = { $_.Start.ToString('MM/dd HH:mm') } },
                  @{n = '時間'; e = { $_.Hours } },
                  @{n = 'INS'; e = { if ($_.Ins) { $_.Ins } else { '-' } } },
                  @{n = '状態'; e = { $_.Action } },
                  @{n = '件名'; e = { $_.Subject } } |
    Format-Table -AutoSize

# --- 工数集計 (クラウドログ入力のチートシート) ----------------------------
$tagged = @($plan | Where-Object { $_.Ins })
if ($tagged.Count -gt 0) {
    Write-Host '--- INS番号ごとの工数集計 (クラウドログ入力用) ---'
    $tagged | Group-Object Ins | ForEach-Object {
        [PSCustomObject]@{
            INS      = $_.Name
            '合計時間' = [Math]::Round(($_.Group | Measure-Object Hours -Sum).Sum, 2)
            '件数'   = $_.Count
        }
    } | Format-Table -AutoSize
}

$unmatched = @($plan | Where-Object { $_.Action -eq '未マッチ' })
if ($unmatched.Count -gt 0) {
    Write-Host ('--- 未マッチの予定 {0} 件: 辞書(ins_dictionary.csv)にキーワードを追加してください ---' -f $unmatched.Count)
    $unmatched | ForEach-Object { Write-Host ('  ・{0}' -f $_.Subject) }
}
if (-not $Apply) {
    Write-Host ''
    Write-Host '※これはドライランです。実際に書き込むには -Apply を付けて実行してください。'
}
