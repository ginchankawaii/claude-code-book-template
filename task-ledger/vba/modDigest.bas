Attribute VB_Name = "modDigest"
Option Explicit

'====================================================================
' タスク管理台帳 ダイジェストメール送信マクロ
'   手動実行: Alt+F8 → SendDigest (またはボタンに登録)
'   自動実行: ThisWorkbook の Workbook_Open から SendDigestAuto が呼ばれる
'             (設定シートの「自動配信」が ON かつ本日未送信のときだけ送信)
' Outlook がインストールされたローカルの Excel で動作します。
'====================================================================

Private Const SHEET_TASK As String = "タスク"
Private Const SHEET_CONFIG As String = "設定"
Private Const DATA_TOP As Long = 4
Private Const DATA_BOTTOM As Long = 503

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
    Dim r As Long, taskName As String, owner As String, stat As String
    Dim dueVal As Variant, doneDef As String

    For r = DATA_TOP To DATA_BOTTOM
        taskName = Trim$(CStr(wsT.Cells(r, 2).Value))   ' B: タスク名
        If taskName <> "" Then
            owner = Trim$(CStr(wsT.Cells(r, 3).Value))  ' C: 担当
            dueVal = wsT.Cells(r, 5).Value              ' E: 期限
            stat = Trim$(CStr(wsT.Cells(r, 6).Value))   ' F: 状態
            doneDef = Trim$(CStr(wsT.Cells(r, 8).Value)) ' H: 完了の定義
            If stat <> "完了" Then
                If stat = "レビュー待ち" Then
                    cntReview = cntReview + 1
                    htmlReview = htmlReview & TaskRow(owner, taskName, dueVal, doneDef, "")
                End If
                If IsDate(dueVal) Then
                    If CDate(dueVal) < Date Then
                        cntOver = cntOver + 1
                        htmlOver = htmlOver & TaskRow(owner, taskName, dueVal, doneDef, _
                            CStr(CLng(Date - CDate(dueVal))) & "日超過")
                    ElseIf CDate(dueVal) = Date Then
                        cntToday = cntToday + 1
                        htmlToday = htmlToday & TaskRow(owner, taskName, dueVal, doneDef, "")
                    End If
                Else
                    cntNoDue = cntNoDue + 1
                    htmlNoDue = htmlNoDue & TaskRow(owner, taskName, dueVal, doneDef, "期限を設定してください")
                End If
            End If
        End If
    Next r

    '--- 送るものがない場合 ---
    If cntOver + cntToday + cntReview + cntNoDue = 0 Then
        If manual Then
            MsgBox "超過・今日期限・レビュー待ち・期限未設定のタスクはありません。" & vbCrLf & _
                   "本日のダイジェスト送信は不要です。", vbInformation, "タスク台帳"
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
        If manual Then MsgBox "設定シートにメールアドレスが1件もありません。", vbExclamation, "タスク台帳"
        Exit Sub
    End If

    '--- 本文組み立て ---
    Dim body As String
    body = "<div style=""font-family:Meiryo,'Yu Gothic',sans-serif;font-size:10.5pt;"">"
    body = body & "<p>タスク台帳ダイジェスト(" & Format$(Date, "m月d日(aaa)") & ")</p>"
    If cntOver > 0 Then body = body & Section("■ 期限超過 " & cntOver & "件 ― 最優先で対応。難しければ今日中にメンターへ相談", "#C00000", htmlOver)
    If cntToday > 0 Then body = body & Section("■ 今日期限 " & cntToday & "件", "#BF8F00", htmlToday)
    If cntReview > 0 Then body = body & Section("■ レビュー待ち " & cntReview & "件 ― メンターは確認して「完了」へ", "#2E75B6", htmlReview)
    If cntNoDue > 0 Then body = body & Section("■ 期限未設定 " & cntNoDue & "件", "#808080", htmlNoDue)
    body = body & "<p style=""color:#808080;font-size:9pt;"">このメールはタスク管理台帳(Box)のマクロから送信されています。最新の状況は台帳を確認してください。</p></div>"

    '--- Outlook 送信 ---
    Dim olApp As Object, olMail As Object
    Set olApp = CreateObject("Outlook.Application")
    Set olMail = olApp.CreateItem(0)  ' olMailItem
    With olMail
        .To = toAddr
        .Subject = "【タスク台帳】" & Format$(Date, "m/d") & " ダイジェスト(超過" & cntOver & "件/今日" & cntToday & "件/レビュー待ち" & cntReview & "件)"
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
           "詳細: " & Err.Description, vbExclamation, "タスク台帳"
End Sub

'--- 1タスク分のテーブル行 ------------------------------------------
Private Function TaskRow(ByVal owner As String, ByVal taskName As String, _
                         ByVal dueVal As Variant, ByVal doneDef As String, _
                         ByVal note As String) As String
    Dim dueTxt As String
    If IsDate(dueVal) Then dueTxt = Format$(CDate(dueVal), "m/d") Else dueTxt = "-"
    If owner = "" Then owner = "(担当未設定)"
    TaskRow = "<tr>" & _
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
        "<th style=""border:1px solid #bbb;padding:3px 8px;"">担当</th>" & _
        "<th style=""border:1px solid #bbb;padding:3px 8px;"">タスク</th>" & _
        "<th style=""border:1px solid #bbb;padding:3px 8px;"">期限</th>" & _
        "<th style=""border:1px solid #bbb;padding:3px 8px;"">備考</th></tr>" & _
        rows & "</table>"
End Function
