#!/usr/bin/env python3
"""IPv6 / IPoE ハンズオン の PowerPoint 生成スクリプト

  usage: pip install python-pptx && python3 build-handson.py [出力パス]

内容の正本は同じディレクトリの handson.md。**内容を直すときは .md を先に直すこと。**

**設計の考え方(前の版から変えたところ)**
  受講者にサーバの管理作業をやらせても学びになりません。前の版はそれをやっていて、
  「コマンドを打っているだけで何をしているか分からない」というフィードバックを受けました。

  この版では:
    - **受講者は実機のルータ (Cisco 892FJ) だけを触る**
    - **司会が lab/ipoe/lab-mode.sh で網の方式を裏で切り替える**
    - **同じコマンドを打っても、方式が変わると出力が変わる**のを見る
    - 各演習は必ず「打つコマンド → 出てくる出力 → **いま何が起きたか**」の 3 点セット

スライドの描画関数は build-toranomaki.py から読み込んでいます。

**話す人向けの指示はスライド本体に書かないこと。**「〜と宣言してください」「ここは 5 分かけて」
のような司会への指示は **notes= に渡してノートへ**。投影すると聴衆に見えてしまいます。
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "toranomaki", os.path.join(_HERE, "build-toranomaki.py"))
_t = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_t)

Presentation, Inches = _t.Presentation, _t.Inches
title_slide, section_slide = _t.title_slide, _t.section_slide
bullet_slide, table_slide, diagram_slide = _t.bullet_slide, _t.table_slide, _t.diagram_slide

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_HERE, "handson.pptx")


def build():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)

    title_slide(
        prs,
        "IPv6 / IPoE ハンズオン",
        "実機を触って、環境が変わるのを見る",
        [
            "対象: 説明会を受けた人 / 時間: 150 分 (休憩 10 分を含む)",
            "",
            "やること: 実機のルータ (Cisco 892FJ) にコマンドを打つ。",
            "その間、司会が裏で網の方式を切り替えます。",
            "",
            "同じコマンドを打っても、方式が変わると出力が変わります。そこを見ます。",
        ],
    )

    table_slide(
        prs,
        "今日の役割分担 — あなたはサーバを触りません",
        ["誰が", "何をするか"],
        [
            ["司会 (講師)", "lab-mode.sh で網の方式を切り替える。「いま RA 方式です」と宣言する"],
            ["あなた", "実機の 892FJ にログインして IOS のコマンドを打つ。出力を読む"],
        ],
        [2.6, 9.2],
        footer="各演習は「打つコマンド → 出てくる出力 → いま何が起きたか」の 3 点セットです",
        fsize=14,
        notes=[
            "【司会へ】",
            "・開始前に lab-mode.sh status を叩いて、いまの方式を把握しておくこと。",
            "・受講者がサーバに触ろうとしたら止める。ここを混ぜると学びが薄まる。",
            "・「3 つめ(いま何が起きたか)が本体です」と最初に言い切っておくと、",
            "  受講者がコマンドの写経で満足しなくなる。",
        ],
    )

    diagram_slide(
        prs,
        "つながり方",
        [
            ("司会の端末", "lab-mode.sh で\n方式を切り替える"),
            ("NGN-SIM / VNE", "NTT の網と\nVNE の代わり"),
            ("Cisco 892FJ", "あなたが触るのはここ\nコンソール接続"),
            ("検証用 PC", "892FJ の LAN ポートに直結\n疎通と出口を確認"),
        ],
        note=[
            "司会が使うのはこれだけです (受講者は打ちません):",
            "  ./lab-mode.sh ra / pd        … 網の IPv6 の配り方を切り替える",
            "  ./lab-mode.sh dslite <CEのIPv6> … IPv4 の運び方を DS-Lite にする",
            "  ./lab-mode.sh break mtu|dns / restore … 障害を注入する / 戻す",
        ],
        notes=[
            "【司会へ】",
            "・切り替えるたびに「いま何方式か」と「期待する出口アドレス」を必ず読み上げること。",
            "  lab-mode.sh がその 2 つを画面に出すので、それをそのまま読めばよい。",
            "・ホワイトボードに 5 つの登場人物 (司会端末 / NGN-SIM / VNE / 892FJ / 検証用 PC) を",
            "  書いておくと、受講者が「いまどこの話か」で迷わなくなる。",
        ],
    )

    bullet_slide(
        prs,
        "0-2. まず実機をまっさらにする (10 分)",
        [
            (0, "前の案件の設定が残っていると、原因不明のトラブルになります", "w"),
            (1, "Router# write erase", "c"),
            (1, "  Erasing the nvram filesystem ... Continue? [confirm]   ← Enter", "c"),
            (1, "Router# reload", "c"),
            (1, "  System configuration has been modified. Save? [yes/no]:  no   ← ★ no", "c"),
            (1, "  Proceed with reload? [confirm]   ← Enter", "c"),
            (1, "再起動後、初期設定ダイアログが出たら no と答えてください", ""),
            (0, "いま何が起きたか", "b"),
            (1, "設定を全部消して、工場出荷に近い状態に戻しました", ""),
            (1, "Save? に yes と答えると 消したはずの設定が書き戻ります。ここは必ず no です", "w"),
        ],
    )

    bullet_slide(
        prs,
        "0-3. 最低限の設定を入れる (10 分)",
        [
            (0, "interface GigabitEthernet0   ← WAN", "c"),
            (1, " no ip address", "c"),
            (1, " ipv6 address autoconfig default", "c"),
            (1, " ipv6 enable", "c"),
            (1, " ipv6 nd ra suppress all", "c"),
            (0, "interface Vlan1   ← LAN", "c"),
            (1, " ip address 192.168.100.1 255.255.255.0", "c"),
            (1, " ip tcp adjust-mss 1420", "c"),
            (0, "1 行ずつ意味があります", "b"),
            (1, "ipv6 unicast-routing … IPv6 のルータとして動かす。無いと転送しません", ""),
            (1, "ipv6 address autoconfig … 網から降る RA を使って 自分でアドレスを作る", ""),
            (1, "ipv6 nd ra suppress all … 自分は RA を撒かない。実網で撒くと事故になります", ""),
            (1, "ip tcp adjust-mss 1420 … 後半の MTU の演習で効きます。いまは入れておくだけ", ""),
        ],
        footer="890 系は機種で構成が違います。show ip interface brief で実物を確認してから使ってください",
    )

    # ================= 第1部 =================
    section_slide(prs, "第1部", "アドレスが降りてくるのを見る",
                  "35 分。設定を変えずに、網の方式だけを変えます")

    bullet_slide(
        prs,
        "演習 1: RA 方式で IPv6 が付く (10 分)",
        [
            (0, "【司会】 ./lab-mode.sh ra", "c"),
            (0, "【あなた】892FJ で", "b"),
            (1, "CPE(config-if)# shutdown", "c"),
            (1, "CPE(config-if)# no shutdown", "c"),
            (1, "CPE# show ipv6 interface GigabitEthernet0", "c"),
            (0, "出てくる出力", "b"),
            (1, "  IPv6 is enabled, link-local address is FE80::E6AA:5DFF:FE82:364A", "c"),
            (1, "  Global unicast address(es):", "c"),
            (1, "    2001:DB8:1014:300:E6AA:5DFF:FE82:364A, subnet is 2001:DB8:1014:300::/64", "c"),
        ],
        notes=[
            "【司会へ】",
            "・lab-mode.sh ra を叩いたら「いまラボは RA 方式です。ひかり電話なしのお客様と",
            "  同じ状態です」と宣言してから、受講者に打たせること。",
            "・全員のアドレスが付くまで待つ。1 人でも付かなければ次に進まない。",
            "・付かない人がいたら: インタフェース名が違う (show ip interface brief で確認)、",
            "  または ipv6 unicast-routing が入っていない。",
            "・次の演習 2 との対比が本体なので、ここでは深追いせず 10 分で切ること。",
        ],
    )

    bullet_slide(
        prs,
        "演習 1 で何が起きたか — 3 段階です",
        [
            (0, "① no shutdown した瞬間、892FJ は FE80:: を自分で作った", "b"),
            (1, "誰にも聞かずに作れるアドレス。説明会の「鶏と卵」がこれです", ""),
            (0, "② その FE80:: を送信元にして「ルータいますか」と網に聞いた", "b"),
            (0, "③ 網が RA で「前半は 2001:DB8:1014:300::/64 です」と答えた", "b"),
            (1, "892FJ が 後半 E6AA:5DFF:FE82:364A を自分で作って 完成させた", ""),
            (0, "後半は MAC アドレスから作られています", "w"),
            (1, "この機体の MAC は E4:AA:5D:82:36:4A。変形して入っているのが見えます", ""),
            (1, "だから「事前にアドレスが分からない」。これが後の演習 4 で効いてきます", ""),
        ],
    )

    bullet_slide(
        prs,
        "演習 2: PD 方式にすると、アドレスが付かなくなる (15 分) ← 今日いちばん大事",
        [
            (0, "【司会】 ./lab-mode.sh pd", "c"),
            (0, "【あなた】さっきと まったく同じ操作を もう一度", "b"),
            (1, "CPE(config-if)# shutdown", "c"),
            (1, "CPE(config-if)# no shutdown", "c"),
            (1, "CPE# show ipv6 interface GigabitEthernet0", "c"),
            (0, "出てくる出力", "b"),
            (1, "  IPv6 is enabled, link-local address is FE80::E6AA:5DFF:FE82:364A", "c"),
            (1, "  No global unicast address is configured        ← ★ 付かない", "c"),
            (0, "設定は 1 文字も変えていません。網の方式が変わっただけです", "w"),
        ],
        notes=[
            "【司会へ】",
            "・lab-mode.sh pd を叩いたら「いま PD 方式にしました。ひかり電話ありのお客様と",
            "  同じ状態です」と宣言してから、受講者に打たせること。",
            "・**受講者に設定を触らせないこと。**「同じ操作をもう一度」が効きどころ。",
            "・付かないことを全員が確認するまで待つ。ここで驚いてもらうのが目的。",
            "・「なんで付かないと思いますか?」と 30 秒だけ考えさせてから次のページへ。",
        ],
    )

    table_slide(
        prs,
        "演習 2 で何が起きたか",
        ["", "RA 方式", "PD 方式"],
        [
            ["網が RA で配るもの", "プレフィックス (前半)", "「DHCPv6 で取りに来い」という指示だけ"],
            ["autoconfig の結果", "アドレスが作れる", "材料が無いので作れない"],
        ],
        [3.0, 4.2, 4.6],
        footer="ipv6 address autoconfig は RA の中のプレフィックスからしかアドレスを作れません",
        fsize=14,
        notes=[
            "【司会へ】",
            "・**ここは 5 分かけて説明すること。**今日の中心です。急がない。",
            "・PD 方式では網が「プレフィックスは DHCPv6 で取りに来い」としか言わないので、",
            "  autoconfig は材料が無くて何も作れない、という筋道を口で説明する。",
            "・次ページで「RA 自体は届いている」を見せると効く。そこまでを 1 セットで。",
        ],
    )

    bullet_slide(
        prs,
        "演習 2 が実案件だとどう出るか — 一番たちが悪いパターン",
        [
            (0, "RA 自体は届いています", "w"),
            (1, "CPE# show ipv6 interface GigabitEthernet0 | include Router advertisement", "c"),
            (1, "  ND router advertisements are sent every 200 seconds", "c"),
            (0, "つまり現場ではこう見えます", "b"),
            (1, "「RA は来ている。ケーブルも問題ない。なのにアドレスが付かない」", ""),
            (1, "→ 原因が見えません。方式の食い違いを疑えるかどうかが分かれ目です", "w"),
            (0, "対処", "b"),
            (1, "PD 方式のお客様には DHCPv6-PD に対応した CPE が要ります", ""),
            (1, "autoconfig だけの設定では成立しません", ""),
            (0, "※ この症状は自宅の検証で実際に踏みました。原因に辿り着くまで時間を使いました", ""),
        ],
    )

    table_slide(
        prs,
        "これは実際に自社で起きた事故です — 2 回続けて開通できませんでした",
        ["", "担当者が想定したもの", "実際", "結果"],
        [
            ["1 回目", "動的 IP コースだと思って設定", "固定 IP コースだった", "失敗"],
            ["2 回目", "固定 IP と気づき PD 方式だと思って設定", "RA 方式だった", "失敗"],
        ],
        [1.6, 4.6, 3.4, 2.2],
        footer="その回線の公式ページには IPv4 の運び方は書いてあるのに、IPv6 の払い出し方式 (RA か PD か) が書かれていません",
        fsize=14,
    )

    bullet_slide(
        prs,
        "なぜ起きたのか — 担当者のミスとして片付けてはいけません",
        [
            (0, "公開情報だけでは、机上で決められないからです", "w"),
            (1, "その回線の公式ページに書いてあったこと", ""),
            (1, "  動的 IP コース … transix IPv4接続 (DS-Lite) 対応機種が必要", "c"),
            (1, "  固定 IP コース … transix IPv4接続 (固定IP) 対応機種が必要", "c"),
            (1, "  IPv6 の払い出し方式 (RA か PD か) … 記載なし", "c"),
            (0, "この事故が示している 3 つのこと", "b"),
            (1, "① 「方式」は 1 つではなく 2 段ある。IPv6 の払い出し と IPv4 の運び方 は独立です", ""),
            (1, "  「transix だから DS-Lite」まで分かっても、RA か PD かは別に確かめる必要があります", ""),
            (1, "② コース名 (動的 IP / 固定 IP) で IPv4 の方式が変わる。契約したコースの確認が要ります", ""),
            (1, "③ 「ひかり電話ありなら PD」は事業者向けサービスでは通用しない", ""),
            (1, "  家庭向けの経験則をそのまま当てはめると外します。この案件は固定 IP なのに RA 方式でした", ""),
            (0, "だから開通後に実測するしかありません", "w"),
            (1, "いま見た「設定は同じなのにアドレスが付かない」が、そのとき現場で起きていた光景です", ""),
        ],
    )

    bullet_slide(
        prs,
        "演習 3: RA を実際に目で見る (10 分)",
        [
            (0, "【司会】 ./lab-mode.sh ra        ← RA 方式に戻す", "c"),
            (0, "【あなた】892FJ で", "b"),
            (1, "CPE# debug ipv6 nd", "c"),
            (1, "  (そのあと shutdown / no shutdown)", "c"),
            (0, "出てくる出力 — 演習 1 の 3 段階がそのまま流れます", "b"),
            (1, "ICMPv6-ND: Sending RS on GigabitEthernet0", "c"),
            (1, "ICMPv6-ND: Received RA from FE80::AC:FF:FE00:1", "c"),
            (1, "ICMPv6-ND:   Prefix 2001:DB8:1014:300::/64 onlink autoconfig", "c"),
            (1, "ICMPv6-ND: Autoconfiguring address 2001:DB8:1014:300:E6AA:...", "c"),
            (0, "読み方", "b"),
            (1, "Received RA from FE80::... ← 送信元がリンクローカル。説明会のとおりです", ""),
            (1, "Prefix ... autoconfig ← この印が付いているから自分で作ってよい", ""),
            (1, "PD 方式のときは この Prefix の行が出ません。それが演習 2 の正体です", "w"),
            (0, "終わったら必ず止めてください: CPE# undebug all", "w"),
        ],
    )

    # ================= 第2部 =================
    section_slide(prs, "第2部", "IPv4 を通す",
                  "40 分。IPv6 は通っていますが IPv4 はまだ通りません")

    bullet_slide(
        prs,
        "演習 4: DS-Lite のトンネルを張る (20 分)",
        [
            (0, "【あなた】検証用 PC で確かめる", "b"),
            (1, "ping 203.0.113.80    → 通りません。IPv6 しか降りていないので当然です", "c"),
            (0, "【あなた】892FJ で 自分の WAN アドレスを確認して、司会に伝える", "b"),
            (1, "CPE# show ipv6 interface GigabitEthernet0 | include 2001", "c"),
            (1, "なぜ伝えるのか: RA 方式のアドレスは MAC から作られるので 司会側では事前に分かりません", "w"),
            (1, "網側のトンネルを、この値に向ける必要があります", ""),
            (0, "【司会】 ./lab-mode.sh dslite 2001:db8:1014:300:e6aa:5dff:fe82:364a", "c"),
            (0, "【あなた】892FJ でトンネルを張る", "b"),
            (1, "interface Tunnel0", "c"),
            (1, " ip address 192.0.0.2 255.255.255.248", "c"),
            (1, " ip mtu 1460", "c"),
            (1, " ip tcp adjust-mss 1420", "c"),
            (1, " tunnel source GigabitEthernet0", "c"),
            (1, " tunnel mode ipv6", "c"),
            (1, " tunnel destination 2001:DB8:8888::1", "c"),
            (1, "ip route 0.0.0.0 0.0.0.0 Tunnel0", "c"),
        ],
    )

    table_slide(
        prs,
        "演習 4 で何が起きたか — 1 行ずつ意味があります",
        ["設定", "意味"],
        [
            ["ip address 192.0.0.2", "RFC 6333 が「トンネルの入口はこれを使え」と決めている。自由に決めてはいけません"],
            ["tunnel mode ipv6", "IPv4 のパケットを IPv6 で包む。説明会の「箱に詰める」がこれです"],
            ["tunnel destination 2001:DB8:8888::1", "箱を開ける相手 (AFTR)。網側の装置です"],
            ["ip mtu 1460", "箱の厚み 40 バイトを引いた大きさ"],
            ["ip tcp adjust-mss 1420", "さらに TCP と IP のヘッダ 40 を引いた値。無いと大きいファイルが落ちません"],
            ["ip route 0.0.0.0 0.0.0.0 Tunnel0", "IPv4 の行き先を全部このトンネルに投げる"],
        ],
        [4.0, 7.8],
        footer="Line protocol on Interface Tunnel0, changed state to up が出れば成功。検証用 PC から ping が通ります",
        fsize=12,
    )

    bullet_slide(
        prs,
        "演習 5: 「通った」で終わらせない — 出口アドレスを見る (10 分)",
        [
            (0, "【あなた】検証用 PC で", "b"),
            (1, "curl http://203.0.113.80/", "c"),
            (1, "  lab-inet OK", "c"),
            (1, "  src: 203.0.113.1        ← これが答え", "c"),
            (0, "src: は「サーバから見て、どのアドレスから来たか」です", "b"),
            (1, "203.0.113.1        → 網側の AFTR で NAT された = DS-Lite が成立している", ""),
            (1, "192.168.100.x のまま → 経路が間違っています (NAT が効いていない)", "w"),
            (0, "実話", "w"),
            (1, "検証スクリプトが 全項目 PASS したのに経路が間違っていたことがあります", ""),
            (1, "ping も curl も成功するので、見た目では絶対に分かりません", ""),
            (1, "気づいたのは src: を見たときだけでした", ""),
            (0, "切替当日、疎通確認だけで「OK です」と言わないでください", "w"),
            (0, "ついでに TTL を見る: ping すると TTL=62。相手は 64 で返すので ルータを 2 つ越えた", ""),
        ],
    )

    bullet_slide(
        prs,
        "演習 6: 892FJ では MAP-E ができない (10 分)",
        [
            (0, "【あなた】892FJ で試してみる", "b"),
            (1, "CPE(config)# nat64 ?", "c"),
            (1, "→ nat64 というコマンド自体がありません", ""),
            (0, "いま何が起きたか", "b"),
            (1, "892FJ の IOS (classic IOS 15.x) には MAP-E の機能がありません", ""),
            (1, "DS-Lite は組めます (tunnel mode ipv6 だけで済むため)", ""),
            (1, "MAP-E は組めません (アドレスとポートの計算をする機能が要るため)", ""),
            (0, "これが実案件だとどう効くか", "w"),
            (1, "お客様の VNE が MAP-E 系 (v6プラス / OCN バーチャルコネクト等) だと 892FJ は使えません", ""),
            (1, "機器リプレース前提の見積になります", ""),
            (1, "納入実績に 892FJ が多いなら、契約書で VNE を確認する時点でこれが分かります", ""),
        ],
    )

    # ================= 第3部 =================
    section_slide(prs, "第3部", "壊す",
                  "40 分。現場で呼ばれるのは壊れたときだけです")

    bullet_slide(
        prs,
        "演習 7: MTU ブラックホール (20 分) — 3 つそろわないと壊れません",
        [
            (0, "【あなた】まず正常な状態を確認", "b"),
            (1, 'curl -o NUL -w "size=%{size_download}\\n" http://203.0.113.80/big.bin', "c"),
            (1, "size=5242880 (5MB) が落ちてきます", ""),
            (0, "① 【司会】 ./lab-mode.sh break mtu     → もう一度 curl。まだ落ちてきます", "c"),
            (0, "② 【あなた】892FJ で MSS の調整を切る", "b"),
            (1, "interface Tunnel0 →  no ip tcp adjust-mss     → まだ落ちてきます", "c"),
            (0, "③ 【あなた】経路の記憶を消す", "b"),
            (1, "CPE# clear ipv6 traffic", "c"),
            (1, "検証用 PC (Windows): netsh interface ipv4 delete destinationcache", "c"),
            (1, "→ ここで初めて 5MB が止まります", "w"),
        ],
    )

    table_slide(
        prs,
        "演習 7 で何が起きたか — なぜ ①② では壊れなかったのか",
        ["段階", "なぜまだ動いたのか"],
        [
            ["① 障害だけ入れた", "892FJ が MSS を 1420 に調整していたので、そもそも大きいパケットが出ていなかった"],
            ["② MSS 調整を切った", "経路の MTU が学習済みだったので、まだ小さいまま送っていた"],
            ["③ 記憶を消した", "ここで初めて 1500 で送り始めて、途中で詰まった"],
        ],
        [3.2, 8.6],
        footer="「さっきまで再現していたのに再現しない」が起きる理由。直したつもりで直っていないことに気づけません",
        fsize=13,
    )

    bullet_slide(
        prs,
        "演習 8: ポート開放を試して、失敗させる (15 分)",
        [
            (0, "【あなた】検証用 PC で待受を立てる", "b"),
            (1, "python3 -m http.server 8000", "c"),
            (0, "【あなた】892FJ でポート開放を設定してみる", "b"),
            (1, "ip nat inside source static tcp 192.168.100.50 8000 interface Tunnel0 8080", "c"),
            (1, "設定は通ります", ""),
            (0, "【司会】INET-SIM から外から叩く", "b"),
            (1, "curl -m5 http://203.0.113.1:8080/    → 接続拒否", "c"),
            (1, "curl -m5 http://192.0.0.2:8080/      → タイムアウト", "c"),
            (0, "どちらも届きません", "w"),
        ],
    )

    bullet_slide(
        prs,
        "演習 8 で何が起きたか — 外から見えるアドレスが 1 つも無い",
        [
            (0, "CPE# show ip interface brief で確かめてください", "c"),
            (1, "GigabitEthernet0 (WAN) … IPv4 アドレスが無い (no ip address)", ""),
            (1, "Tunnel0 … 192.0.0.2。これは RFC 6333 が決めた「トンネルの入口」です", ""),
            (1, "外から見えるアドレスではありません", "w"),
            (0, "外から来た通信を受け取る場所が、そもそも存在しません", "w"),
            (1, "設定 UI 上は入るのに一切着信しないのは、これが理由です", ""),
            (0, "お客様への説明の組み立て方", "b"),
            (1, "「お客様のルータには外から見えるアドレスが無く、事業者の設備でまとめて変換されています」", ""),
            (1, "「設定でどうにかできる話ではありません」", ""),
            (1, "「外から入る通信が必要でしたら、固定 IP のオプション契約が要ります」", ""),
            (0, "後始末: no ip nat inside source static tcp ... を忘れずに", "w"),
        ],
    )

    bullet_slide(
        prs,
        "演習 9: 同じ障害でも、端末によって症状が違う (5 分)",
        [
            (0, "【司会】 ./lab-mode.sh break dns", "c"),
            (0, "【あなた】検証用 PC で 2 つ叩き比べる", "b"),
            (1, 'curl -s -o NUL -w "%{time_total}\\n" http://www.lab.example/', "c"),
            (1, "wget -q -O NUL http://www.lab.example/", "c"),
            (0, "結果", "b"),
            (1, "curl … 0.2 秒程度。速いので気づけません", ""),
            (1, "wget … 15 秒でタイムアウト。完全に固まります", "w"),
            (0, "いま何が起きたか", "b"),
            (1, "AAAA (IPv6 のアドレス) は返るのに、IPv6 では到達できない状態を作りました", ""),
            (1, "curl は IPv6 を少し試して すぐ IPv4 に切り替えます (Happy Eyeballs)", ""),
            (1, "wget は IPv6 で待ち続けます", ""),
            (0, "「A さんの PC は遅いが B さんは普通」というお客様申告の正体がこれです", "w"),
        ],
    )

    # ================= 第4部 =================
    section_slide(prs, "第4部", "戻して終わる",
                  "15 分。戻し忘れは次の演習で「原因の分からない失敗」として出ます")

    bullet_slide(
        prs,
        "演習 10: 元に戻す",
        [
            (0, "【あなた】892FJ で確認", "b"),
            (1, "CPE# show running-config | include adjust-mss", "c"),
            (1, "ip tcp adjust-mss 1420 が Tunnel0 と Vlan1 の両方にあること。無ければ入れ直す", ""),
            (1, "CPE# show running-config | include ip nat inside source", "c"),
            (1, "何も出ないこと (演習 8 の設定が残っていないこと)", ""),
            (0, "【司会】 ./lab-mode.sh restore  →  ./lab-mode.sh status", "c"),
            (1, "「障害の注入: なし」になっていることを全員で確認します", ""),
            (0, "【あなた】最後に", "b"),
            (1, "curl http://203.0.113.80/     →  src: 203.0.113.1 に戻っていれば完了", "c"),
        ],
        notes=[
            "【司会へ】",
            "・**全員が FAIL=0 に戻るまで解散しないこと。**戻し忘れが次回の演習を壊す。",
            "・とくに 892FJ 側の adjust-mss と ip nat inside source の消し忘れが多い。",
            "・lab-mode.sh status で「障害の注入: なし」を全員に見せてから締める。",
        ],
    )

    bullet_slide(
        prs,
        "今日 手を動かして分かったこと",
        [
            (0, "① 設定を変えなくても、網の方式が変わればアドレスが付かなくなる", "b"),
            (1, "演習 2。しかも RA 自体は届いているので、原因が見えません", ""),
            (0, "② ping が通っても、正しい経路を通ったことにはならない", "b"),
            (1, "演習 5。見るべきは 出口アドレス だけです", ""),
            (0, "③ 892FJ では MAP-E ができない", "b"),
            (1, "演習 6。機器と方式の組み合わせは、契約書を見た時点で分かります", ""),
            (0, "④ 障害は 3 つそろわないと再現しない", "b"),
            (1, "演習 7。「さっきまで再現していたのに」が起きます", ""),
            (0, "⑤ 同じ障害でも端末によって症状が違う", "b"),
            (1, "演習 9", ""),
            (0, "この 5 つは、教科書にもマニュアルにも書いてありません", "w"),
        ],
    )

    bullet_slide(
        prs,
        "次にやること / 参考",
        [
            (0, "次にやること", "b"),
            (1, "自分の担当案件の VNE を調べる (契約書の「IPv6 接続サービス」の名称)", ""),
            (1, "892FJ を納入している拠点をリストアップする。MAP-E 系ならリプレースが要ります", ""),
            (1, "もっと壊したい人へ: test-matrix.md §4 に R1〜R13。今日やったのは 3 つだけです", ""),
            (0, "参考", "b"),
            (1, "実機の設定手順 (詳細)   runbook-vmware.md §8", ""),
            (1, "詰まったとき           runbook-vmware.md §9 (A〜N)", ""),
            (1, "障害再現レシピ (全13種) test-matrix.md §4", ""),
            (1, "説明会資料 (座学)       slides/setsumeikai.md", ""),
            (1, "司会用のモード切替      lab/ipoe/lab-mode.sh --help", ""),
        ],
    )

    prs.save(OUT)
    print("saved: %s (%d slides)" % (OUT, len(prs.slides._sldIdLst)))


if __name__ == "__main__":
    build()
