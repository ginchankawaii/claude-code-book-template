Attribute VB_Name = "modDigest"
Option Explicit

'====================================================================
' タスク管理台帳 ダイジェストメール送信マクロ (v2: 顧客/案件対応)
'   手動実行: Alt+F8 → SendDigest (またはボタンに登録)
'   自動実行: ThisWorkbook の Workbook_Open から SendDigestAuto が呼ばれる
'             (設定シートの「自動配信」が ON かつ本日未送信のときだけ送信)
' Outlook がインストールされたローカルの Excel で動作します。
'====================================================================

Private Const SHEET_TASK As String = "タスク"
Private Const SHEET_CONFIG As String = "設定"
Private Const DATA_TOP As Long = 4
Private Const DATA_BOTTOM As Long = 503

' タスクシートの列位置 (列構成を変えたらここを直す)
Private Const COL_CUST As Long = 2    ' B: 顧客
Private Const COL_PROJ As Long = 3    ' C: 案件
Private Const COL_NAME As Long = 4    ' D: タスク名
Private Const COL_OWNER As Long = 5   ' E: 担当
Private Const COL_DUE As Long = 7     ' G: 期限
Private Const COL_STAT As Long = 8    ' H: 状態
Private Const COL_DEF As Long = 13    ' M: 完了の定義

'--- 手動送信用エントリポイント -------------------------------------
Public Sub SendDigest()
    SendDigestCore True
End Sub

'--- 自動送信用エントリポイント (Workbook_Open から) ----------------
Public Sub SendDigestAuto()
    On Error GoTo Quiet
    Dim cfg As Worksheet
    Set cfg = ThisWorkbook.Worksheets(SHEET_CONFIG)
    If UCase$(Trim$(CStr(cfg.Range("F4").Value))) <> "ON" Then Exit Sub
    If IsDate(cfg.Range("F7").Value) Then
        If CDate(cfg.Range("F7").Value) = Date Then Exit Sub  ' 本日送信済み
    End If
    SendDigestCore False
    Exit Sub
Quiet:
    ' 自動実行時はブックを開く操作を邪魔しない
End Sub

'--- 本体 -----------------------------------------------------------
Private Sub SendDigestCore(ByVal manual As Boolean)
    On Error GoTo Fail

    Dim wsT As Worksheet, cfg As Worksheet
    Set wsT = ThisWorkbook.Worksheets(SHEET_TASK)
    Set cfg = ThisWorkbook.Worksheets(SHEET_CONFIG)

    '--- タスク収集 ---
    Dim htmlOver As String, htmlToday As String, htmlReview As String, htmlNoDue As String
    Dim cntOver As Long, cntToday As Long, cntReview As Long, cntNoDue As Long
    Dim r As Long, taskName As String, owner As String, stat As String, pj As String
    Dim dueVal As Variant, doneDef As String

    For r = DATA_TOP To DATA_BOTTOM
        taskName = Trim$(CStr(wsT.Cells(r, COL_NAME).Value))
        If taskName <> "" Then
            owner = Trim$(CStr(wsT.Cells(r, COL_OWNER).Value))
            dueVal = wsT.Cells(r, COL_DUE).Value
            stat = Trim$(CStr(wsT.Cells(r, COL_STAT).Value))
            doneDef = Trim$(CStr(wsT.Cells(r, COL_DEF).Value))
            pj = Trim$(CStr(wsT.Cells(r, COL_CUST).Value)) & " / " & _
                 Trim$(CStr(wsT.Cells(r, COL_PROJ).Value))
            If stat <> "完了" Then
                If stat = "レビュー待ち" Then
                    cntReview = cntReview + 1
                    htmlReview = htmlReview & TaskRow(pj, owner, taskName, dueVal, doneDef, "")
                End If
                If IsDate(dueVal) Then
                    If CDate(dueVal) < Date Then
                        cntOver = cntOver + 1
                        htmlOver = htmlOver & TaskRow(pj, owner, taskName, dueVal, doneDef, _
                            CStr(CLng(Date - CDate(dueVal))) & "日超過")
                    ElseIf CDate(dueVal) = Date Then
                        cntToday = cntToday + 1
                        htmlToday = htmlToday & TaskRow(pj, owner, taskName, dueVal, doneDef, "")
                    End If
                Else
                    cntNoDue = cntNoDue + 1
                    htmlNoDue = htmlNoDue & TaskRow(pj, owner, taskName, dueVal, doneDef, "期限を設定してください")
                End If
            End If
        End If
    Next r

    '--- 送るものがない場合 ---
    If cntOver + cntToday + cntReview + cntNoDue = 0 Then
        If manual Then
            MsgBox "超過・今日期限・レビュー待ち・期限未設定のタスクはありません。" & vbCrLf & _
                   "本日のダイジェスト送信は不要です。", vbInformation, "TASK CONTROL"
        Else
            cfg.Range("F7").Value = Date  ' 空振りでも当日分のチェック済みとする
        End If
        Exit Sub
    End If

    '--- 宛先 ---
    Dim toAddr As String, i As Long, addr As String
    For i = 4 To 13
        addr = Trim$(CStr(cfg.Cells(i, 2).Value))       ' B: メールアドレス
        If addr <> "" Then toAddr = toAddr & addr & ";"
    Next i
    addr = Trim$(CStr(cfg.Range("F6").Value))           ' 追加宛先
    If addr <> "" Then toAddr = toAddr & addr & ";"
    If toAddr = "" Then
        If manual Then MsgBox "設定シートにメールアドレスが1件もありません。", vbExclamation, "TASK CONTROL"
        Exit Sub
    End If

    '--- 本文組み立て ---
    Dim body As String
    body = "<div style=""font-family:Meiryo,'Yu Gothic',sans-serif;font-size:10.5pt;"">"
    body = body & "<div style=""background:#0D1117;color:#00E676;font-family:Consolas,monospace;" & _
                  "padding:8px 12px;margin-bottom:10px;"">root@team:~# ./daily_briefing " & _
                  Format$(Date, "yyyy-mm-dd") & "</div>"
    If cntOver > 0 Then body = body & Section("■ OVERDUE / 期限超過 " & cntOver & "件 ― 最優先で対応。難しければ今日中にメンターへ相談", "#C00000", htmlOver)
    If cntToday > 0 Then body = body & Section("■ DUE TODAY / 今日期限 " & cntToday & "件", "#BF8F00", htmlToday)
    If cntReview > 0 Then body = body & Section("■ REVIEW / レビュー待ち " & cntReview & "件 ― メンターは確認して「完了」へ", "#2E75B6", htmlReview)
    If cntNoDue > 0 Then body = body & Section("■ NO DUE / 期限未設定 " & cntNoDue & "件", "#808080", htmlNoDue)
    body = body & "<p style=""color:#808080;font-size:9pt;"">このメールはタスク管理台帳(Box)のマクロから送信されています。" & _
                  "最新状況・ガント・案件サマリは台帳を確認。工数ログの記入も忘れずに。</p></div>"

    '--- Outlook 送信 ---
    Dim olApp As Object, olMail As Object
    Set olApp = CreateObject("Outlook.Application")
    Set olMail = olApp.CreateItem(0)  ' olMailItem
    With olMail
        .To = toAddr
        .Subject = "【TASK CONTROL】" & Format$(Date, "m/d") & " DAILY BRIEFING (OVERDUE " & _
                   cntOver & " / TODAY " & cntToday & " / REVIEW " & cntReview & ")"
        .HTMLBody = body
        If Trim$(CStr(cfg.Range("F5").Value)) = "即送信" Then
            .Send
        Else
            .Display   ' 下書き表示: 内容を確認してから手動で送信
        End If
    End With

    cfg.Range("F7").Value = Date   ' 最終送信日を記録
    Exit Sub

Fail:
    MsgBox "ダイジェスト送信でエラーが発生しました。" & vbCrLf & _
           "Outlook が起動できるか確認してください。" & vbCrLf & vbCrLf & _
           "詳細: " & Err.Description, vbExclamation, "TASK CONTROL"
End Sub

'--- 1タスク分のテーブル行 ------------------------------------------
Private Function TaskRow(ByVal pj As String, ByVal owner As String, ByVal taskName As String, _
                         ByVal dueVal As Variant, ByVal doneDef As String, _
                         ByVal note As String) As String
    Dim dueTxt As String
    If IsDate(dueVal) Then dueTxt = Format$(CDate(dueVal), "m/d") Else dueTxt = "-"
    If owner = "" Then owner = "(担当未設定)"
    TaskRow = "<tr>" & _
        "<td style=""border:1px solid #bbb;padding:3px 8px;white-space:nowrap;"">" & pj & "</td>" & _
        "<td style=""border:1px solid #bbb;padding:3px 8px;white-space:nowrap;"">" & owner & "</td>" & _
        "<td style=""border:1px solid #bbb;padding:3px 8px;"">" & taskName & _
        IIf(doneDef <> "", "<br><span style=""color:#808080;font-size:9pt;"">完了の定義: " & doneDef & "</span>", "") & "</td>" & _
        "<td style=""border:1px solid #bbb;padding:3px 8px;white-space:nowrap;"">" & dueTxt & "</td>" & _
        "<td style=""border:1px solid #bbb;padding:3px 8px;white-space:nowrap;color:#C00000;"">" & note & "</td>" & _
        "</tr>"
End Function

'--- セクション見出し+テーブル --------------------------------------
Private Function Section(ByVal title As String, ByVal color As String, ByVal rows As String) As String
    Section = "<p style=""color:" & color & ";font-weight:bold;margin-bottom:4px;"">" & title & "</p>" & _
        "<table style=""border-collapse:collapse;font-size:10pt;margin-bottom:12px;"">" & _
        "<tr style=""background:#F2F2F2;"">" & _
        "<th style=""border:1px solid #bbb;padding:3px 8px;"">顧客 / 案件</th>" & _
        "<th style=""border:1px solid #bbb;padding:3px 8px;"">担当</th>" & _
        "<th style=""border:1px solid #bbb;padding:3px 8px;"">タスク</th>" & _
        "<th style=""border:1px solid #bbb;padding:3px 8px;"">期限</th>" & _
        "<th style=""border:1px solid #bbb;padding:3px 8px;"">備考</th></tr>" & _
        rows & "</table>"
End Function
