#!/usr/bin/env python3
"""IPv6 / IPoE ハンズオン の PowerPoint 生成スクリプト

  usage: pip install python-pptx && python3 build-handson.py [出力パス]

内容の正本は同じディレクトリの handson.md。**内容を直すときは .md を先に直すこと。**

説明会資料 (build-setsumeikai.py) との違い:
  - こちらは **手を動かす人向け**。投影しながら全員が同時にコマンドを打つ前提
  - **コマンドは省略せずそのまま載せる。**写経できないと止まるため
  - **「どこで打つか」を毎ページ明示する。**ハンズオンで一番多い事故がこれ

スライドの描画関数は build-toranomaki.py から読み込んでいます。
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "toranomaki", os.path.join(_HERE, "build-toranomaki.py"))
_t = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_t)

Presentation = _t.Presentation
Inches = _t.Inches
title_slide = _t.title_slide
section_slide = _t.section_slide
bullet_slide = _t.bullet_slide
table_slide = _t.table_slide
diagram_slide = _t.diagram_slide

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_HERE, "handson.pptx")


def build():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)

    title_slide(
        prs,
        "IPv6 / IPoE ハンズオン",
        "触って、壊して、直す",
        [
            "対象: 説明会を受けた人 / 時間: 150 分 (休憩 10 分を含む)",
            "前提: 検証ラボが構築済みで run-checks.sh が PASS していること",
            "",
            "今日やること: 正常な状態を 見て / 方式を 切り替えて / わざと 壊して / 直す",
            "",
            "知識ではなく、手を動かした記憶を持ち帰ってもらいます。",
        ],
    )

    bullet_slide(
        prs,
        "このハンズオンの狙い",
        [
            (0, "説明会で「MAP-E はポートが 240 個しかない」と聞いても、実感はありません", "b"),
            (1, "自分でセッションを張って詰まらせると、二度と忘れません", ""),
            (0, "4 部構成です", "b"),
            (1, "第1部 見る … 正常な状態を観察する。これが無いと異常が分かりません", ""),
            (1, "第2部 切り替える … 方式が変わると何が変わるかを体で覚える", ""),
            (1, "第3部 壊す … 症状から原因に辿り着く型を覚える", ""),
            (1, "第4部 直す … 戻し忘れが次の検証を壊すことを知る", ""),
            (0, "一番大事なのは第3部です", "w"),
            (1, "現場で呼ばれるのは、壊れたときだけだからです", ""),
        ],
    )

    table_slide(
        prs,
        "コマンドを打つ場所の早見表 (事故はだいたいここ)",
        ["呼び名", "何をしている VM か", "今日の役割"],
        [
            ["NGN-SIM", "NTT の網の代わり", "アドレスを配る。方式 (RA / PD) を切り替える"],
            ["VNE", "MAP-E の BR と DS-Lite の AFTR", "IPv4 の運び方を切り替える。障害を注入する"],
            ["INET-SIM", "模擬インターネット (Web + DNS)", "到達先。アクセス元アドレスを表示してくれる"],
            ["CPE", "OpenWrt または実機 892FJ", "お客様のルータ役"],
            ["CLIENT", "CPE 配下の検証クライアント", "ほとんどの確認はここで打ちます"],
        ],
        [2.0, 4.2, 5.6],
        footer="この資料では各コマンドの前に必ず 【CLIENT】 のように場所を書きます。毎回 声に出して確認してください",
        fsize=13,
    )

    bullet_slide(
        prs,
        "開始前チェック — これが通らないと先に進めません",
        [
            (0, "全員で一斉にやってください。1 人でも通らなければ、そこで止めて直します", "b"),
            (1, "【CLIENT】 SKIP_V6=1 EXPECT_SRC4=198.51.100.10 ./ipoe/tests/run-checks.sh", "c"),
            (0, "期待する結果: 最終行が === 結果: PASS=n FAIL=0 ===", "b"),
            (0, "FAIL が出たら、先に進まないでください。ハンズオンの全部が狂います", "w"),
            (1, "出口 IPv4 が期待値と違う → 方式が想定と違う。または VNE と INET-SIM が同居している", ""),
            (1, "DNS だけ FAIL → runbook §9-B / C / D。原因が 3 つ重なりえます", ""),
            (1, "IPv6 だけ全滅 → §9-I (ULA へのフォールバック) / §9-K (復路の上書き)", ""),
        ],
    )

    # ================= 第1部 =================
    section_slide(prs, "第1部", "見る — 正常な状態を観察する",
                  "30 分。「正常」がどう見えるかを知らないと、異常が分かりません")

    bullet_slide(
        prs,
        "演習 1: アドレスがどう降りてくるかを見る (10 分)",
        [
            (0, "① キャプチャを先に流し始める", "b"),
            (1, "【CPE】 tcpdump -nvi eth0 'icmp6 and ip6[40] == 134'", "c"),
            (1, "134 は RA (Router Advertisement) の番号。これだけを拾います", ""),
            (0, "② 別の窓で、CPE の WAN を再接続する", "b"),
            (1, "【CPE】 ifdown wan6 && ifup wan6", "c"),
            (0, "期待する結果 — RA の中にプレフィックスが入っています", "b"),
            (1, "fe80::ac:ff:fe00:1 > ff02::1: [ICMPv6] router advertisement", "c"),
            (1, "  prefix info option (3), length 32: 2001:db8:1014:300::/64", "c"),
            (1, "  rdnss option (25), length 24: 2001:db8:cafe::53", "c"),
            (0, "ここを見てください", "w"),
            (1, "送信元が fe80::。グローバルアドレスではありません (説明会の「鶏と卵」)", ""),
            (1, "プレフィックスは /64。後半 64 ビットは CPE が自分で作ります", ""),
            (1, "RA にプレフィックスが無い → NGN-SIM が PD 方式です。演習 4 で切り替えます", ""),
        ],
    )

    bullet_slide(
        prs,
        "演習 2: 「疎通した」を疑う (10 分) — 今日いちばん大事です",
        [
            (0, "① まず ping する", "b"),
            (1, "【CLIENT】 ping -c3 203.0.113.80", "c"),
            (1, "通ります。ここで「つながった」と言いたくなりますが、待ってください", ""),
            (0, "② どのアドレスで外に出たかを見る", "b"),
            (1, "【CLIENT】 curl http://203.0.113.80/", "c"),
            (1, "src: 198.51.100.10   ← これが答え", "c"),
            (0, "実話: 全項目 PASS したのに経路が間違っていたことがあります", "w"),
            (1, "DS-Lite の構成を誤った状態で PASS=10。出口はクライアントの私設アドレスのまま", ""),
            (1, "ping も curl も成功するので、見た目では絶対に分かりません", ""),
            (0, "切替当日、疎通確認だけで「OK です」と言わないでください", "w"),
        ],
    )

    table_slide(
        prs,
        "出口アドレスの読み方 (この表を手元に置いてください)",
        ["出口アドレス", "意味"],
        [
            ["198.51.100.10", "MAP-E (PD 方式) が成立している"],
            ["198.51.100.20", "MAP-E (RA 方式) が成立している"],
            ["203.0.113.1", "DS-Lite の AFTR で網側 NAT された"],
            ["203.0.113.2", "PPPoE の BRAS で NAT された"],
            ["!私設アドレスのまま", "!経路が間違っています"],
        ],
        [3.4, 8.4],
        footer="run-checks.sh は EXPECT_SRC4 を渡すと、この確認を自動でやります。渡さないと確認しません",
        fsize=14,
    )

    bullet_slide(
        prs,
        "演習 3: MAP-E の計算が合っているか確かめる (10 分)",
        [
            (0, "手順", "b"),
            (1, "【CPE】 ip -4 addr show map0", "c"),
            (1, "【CPE】 nft list table inet fw4 | grep -A2 'snat'", "c"),
            (0, "降ってきた IPv6 が 2001:db8:100a:500::/56 のときの期待値", "b"),
            (1, "共有 IPv4        198.51.100.10", "c"),
            (1, "PSID             5", "c"),
            (1, "先頭ブロック      4176 〜 4191", "c"),
            (1, "ポート総数        16 個 × 15 ブロック = 240", "c"),
            (0, "ポート集合の全体 (間隔 4096)", "b"),
            (1, "4176-4191 / 8272-8287 / 12368-12383 / … / 61520-61535", "c"),
            (0, "0〜4095 のブロックが存在しません", "w"),
            (1, "だから 80 番も 443 番も原理的に使えません。説明会の「若い番号」はこれです", ""),
        ],
    )

    # ================= 第2部 =================
    section_slide(prs, "第2部", "切り替える — 方式が変わると何が変わるか",
                  "30 分。ラボの一番おいしいところです。実網では数日かかります")

    bullet_slide(
        prs,
        "演習 4: RA 方式 ⇄ PD 方式 を切り替える (15 分)",
        [
            (0, "① PD 方式 (ひかり電話あり相当) に切り替える", "b"),
            (1, "【NGN-SIM】 sudo ./ipoe/ngn/setup-ngn.sh pd", "c"),
            (1, "【CPE】     ifdown wan6 && ifup wan6", "c"),
            (1, "【CPE】     ip -6 addr show", "c"),
            (0, "② RA 方式 (ひかり電話なし相当) に戻す", "b"),
            (1, "【NGN-SIM】 sudo ./ipoe/ngn/setup-ngn.sh ra", "c"),
            (1, "【CPE】     ifdown wan6 && ifup wan6", "c"),
            (0, "期待する結果", "b"),
            (1, "RA 方式 … /64 が 1 本。委譲が無いので LAN 側に配れない", ""),
            (1, "PD 方式 … /64 が 1 本 + /56 の委譲。LAN 側に /60 が降りる (OpenWrt 既定)", ""),
            (0, "切り替えたら必ず run-checks.sh を流し直してください", "w"),
            (1, "方式が変わると出口アドレスも変わります (198.51.100.10 ⇄ .20)", ""),
            (1, "Kea のリースが残っていると Renew で旧プレフィックスが返ります。先に消すこと", "w"),
        ],
    )

    bullet_slide(
        prs,
        "演習 5: MAP-E ⇄ DS-Lite を切り替える (15 分)",
        [
            (0, "① DS-Lite に切り替える", "b"),
            (1, "【VNE】 sudo ./ipoe/vne/setup-map-br.sh stop", "c"),
            (1, "【VNE】 sudo CE_WAN6=<CPE の WAN アドレス> ./ipoe/vne/setup-aftr.sh", "c"),
            (1, "CPE 側も DS-Lite に切り替えます (OpenWrt なら proto dslite)", ""),
            (0, "② 出口アドレスを確認する", "b"),
            (1, "【CLIENT】 curl http://203.0.113.80/", "c"),
            (0, "期待する結果 — ここが変わります", "b"),
            (1, "MAP-E   … 198.51.100.10   NAT したのは CPE 自身", ""),
            (1, "DS-Lite … 203.0.113.1     NAT したのは網側の AFTR", ""),
            (0, "この 1 行が変わるだけで、ポート開放の可否が変わります", "w"),
            (1, "それを次の第3部で、実際に失敗させて確かめます", ""),
        ],
    )

    # ================= 第3部 =================
    section_slide(prs, "第3部", "壊す — 障害を注入して症状を見る",
                  "50 分。手順書どおりでは再現しないものが 4 つあります。そこが山場です")

    bullet_slide(
        prs,
        "演習 6 (R3): MAP-E のポートを枯渇させる (15 分)",
        [
            (0, "滞留するセッションを 20 本張ります", "b"),
            (1, "【CLIENT】 for i in $(seq 20); do curl -s --limit-rate 1k -m 60 \\", "c"),
            (1, "             http://203.0.113.80/big.bin -o /dev/null & done", "c"),
            (1, "【CLIENT】 sleep 5; jobs -r | wc -l", "c"),
            (1, "--limit-rate 1k が肝です。すぐ閉じる curl 連打では NAT テーブルが埋まりません", "w"),
            (0, "期待する結果 — ここが実測と違います", "w"),
            (1, "設計上は 240 本。しかし OpenWrt が CPE のときは 成功するのは きっかり 16 本", ""),
            (1, "15 本の snat がすべて同じマッチ条件のため、先頭ブロックしか使われないためです", ""),
            (1, "【CPE】 nft list table inet fw4 | grep -B2 'counter packets'", "c"),
            (1, "カウンタで確定できます (nat 1: packets 3462 / nat 4 以降: packets 0)", ""),
            (0, "この演習で一番大事な体験: 設計値どおりに動くとは限らない", "w"),
            (1, "実機 CPE では未検証です。「設計上 240」とだけ言い、「実測で 240」とは言わないこと", ""),
        ],
    )

    bullet_slide(
        prs,
        "演習 7 (R4): DS-Lite でポート開放を失敗させる (15 分)",
        [
            (0, "⚠ 先に対照実験をやってください", "w"),
            (1, "「着信しない」理由が仕様なのか、受け側がいないだけなのかは外から区別できません", ""),
            (1, "自宅の検証で、待受が無いまま「再現した」と読みかけました", ""),
            (0, "① クライアントで待受を起動する", "b"),
            (1, "【CLIENT】 sudo systemd-run --unit=r4test --collect \\", "c"),
            (1, "             python3 -m http.server 8000 --bind 0.0.0.0", "c"),
            (1, "多段 ssh 越しの nohup ... & では起動しません。必ず systemd-run で", "w"),
            (0, "② LAN 内から到達できることを先に示す ← ここを飛ばさないこと", "b"),
            (1, "【CPE】 wget -O - http://<クライアントの IP>:8000/", "c"),
            (0, "③ その状態で、外から試す", "b"),
            (1, "【INET-SIM】 curl -m5 http://203.0.113.1:8080/    → 接続拒否", "c"),
            (1, "【INET-SIM】 curl -m5 http://192.0.0.2:8080/      → タイムアウト", "c"),
            (0, "後始末: 【CLIENT】 sudo systemctl stop r4test", "b"),
        ],
    )

    bullet_slide(
        prs,
        "演習 7 の切り分けの見せ方 — 「そもそも公開先が無い」",
        [
            (0, "CPE の DNAT ルールを見せてください", "b"),
            (1, "【CPE】 nft list ruleset | grep dnat", "c"),
            (0, "宛先が 192.0.0.2 になっています", "b"),
            (1, "これは RFC 6333 が定める B4 (トンネルの入口) のアドレスです", ""),
            (1, "つまり そもそも公開できる先が存在しない ことが一目で分かります", ""),
            (0, "お客様への説明はこう組み立てます", "b"),
            (1, "「お客様のルータには外から見えるアドレスが無く、事業者の設備で変換されています」", ""),
            (1, "「設定でどうにかできる話ではありません。固定 IP のオプション契約が必要です」", ""),
            (0, "「できません」を、根拠を持って言えるようになるのがこの演習の目的です", "w"),
        ],
    )

    bullet_slide(
        prs,
        "演習 8 (R5): MTU ブラックホール — 3 段階そろって初めて再現します",
        [
            (0, "① まず障害だけ入れる", "b"),
            (1, "【VNE】    sudo ./ipoe/vne/setup-aftr.sh break-pmtu", "c"),
            (1, "【CLIENT】 SKIP_V6=1 ./ipoe/tests/run-checks.sh    → まだ PASS します", "c"),
            (0, "② CPE の MSS clamp を切る", "b"),
            (1, "【CPE】 uci set firewall.@zone[1].mtu_fix='0'; uci commit firewall; \\", "c"),
            (1, "         /etc/init.d/firewall reload                → それでもまだ PASS", "c"),
            (0, "③ 両端で PMTU キャッシュを消す", "b"),
            (1, "【CLIENT】   sudo ip route flush cache", "c"),
            (1, "【INET-SIM】 sudo ip route flush cache", "c"),
            (1, "【CLIENT】   SKIP_V6=1 ./ipoe/tests/run-checks.sh", "c"),
            (1, "→ ここで初めて FAIL: TCP 5MB over IPv4 が出ます", "w"),
            (0, "小さいページと ping は PASS したままです", "w"),
            (1, "「表示は出るのにファイルが落ちない」の正体。既定の mtu_fix が対処そのものです", ""),
        ],
    )

    bullet_slide(
        prs,
        "演習 9 (R6): DNS フォールバック遅延 — 同じ障害でも症状が違う (5 分)",
        [
            (0, "手順", "b"),
            (1, "【INET-SIM】 sudo ./ipoe/inet/setup-inet.sh break-v6", "c"),
            (1, "【CLIENT】   time curl -s -o /dev/null http://www.lab.example/", "c"),
            (1, "【CLIENT】   time wget -q -O /dev/null http://www.lab.example/", "c"),
            (0, "期待する結果 — これが実測です", "b"),
            (1, "curl … 8ms → 207ms。体感できません", ""),
            (1, "wget … 15 秒でタイムアウト。完全にハングします", "w"),
            (0, "「A さんの PC は遅いが B さんは普通」というお客様申告の正体がこれです", "w"),
            (0, "戻す: 【INET-SIM】 sudo ./ipoe/inet/setup-inet.sh restore", "b"),
        ],
    )

    # ================= 第4部 =================
    section_slide(prs, "第4部", "直す — 全部戻す",
                  "20 分。戻し忘れは「原因の分からない断続失敗」として次を壊します")

    bullet_slide(
        prs,
        "演習 10: 戻し忘れを潰す",
        [
            (0, "壊したものを戻さないと、次の検証が全部おかしくなります", "w"),
            (1, "しかも「原因の分からない断続失敗」として現れるので、たちが悪いです", ""),
            (0, "戻すものチェックリスト", "b"),
            (1, "□ R3  nft delete table ip map-enforce   (使った場合のみ)", "c"),
            (1, "□ R4  sudo systemctl stop r4test", "c"),
            (1, "□ R5  mtu_fix='1' に戻す / setup-aftr.sh restore-pmtu", "c"),
            (1, "□ R6  setup-inet.sh restore", "c"),
            (1, "□ 方式  演習前の方式 (RA / PD、MAP-E / DS-Lite) に戻す", "c"),
            (0, "戻ったことの確認", "b"),
            (1, "【CLIENT】 SKIP_V6=1 EXPECT_SRC4=<戻した方式の期待値> ./ipoe/tests/run-checks.sh", "c"),
            (1, "FAIL=0 に戻ることを確認してから解散してください", "w"),
        ],
    )

    bullet_slide(
        prs,
        "切り分けの型 (持ち帰り)",
        [
            (0, "症状から原因に辿り着く順番です", "b"),
            (1, "① どのアドレスで外に出たか   curl http://203.0.113.80/", "c"),
            (1, "   → 違えば経路の問題。方式か構成を疑う", ""),
            (1, "② 大きいパケットだけ落ちるか   ping -M do -s 1432 と -s 1472", "c"),
            (1, "   → 大きいものだけ落ちるなら MTU の問題", ""),
            (1, "③ 名前解決だけ落ちるか", ""),
            (1, "   → DNS の問題。原因が 3 つ重なりえます (§9-B / C / D)", ""),
            (1, "④ 片方向だけ落ちるか   → 復路を疑う (§9-K)", ""),
            (0, "やってはいけないこと", "w"),
            (1, "1 つ直して、確かめずに次を直す。どれが効いたか分からなくなります", ""),
            (1, "疎通確認だけで「直りました」と言う。出口アドレスを見てください", ""),
        ],
    )

    bullet_slide(
        prs,
        "今日 手を動かして分かったこと",
        [
            (0, "① 「疎通した」は「正しい経路を通った」ではない", "b"),
            (1, "演習 2。全項目 PASS でも経路が違うことがあります", ""),
            (0, "② 設計値どおりに動くとは限らない", "b"),
            (1, "演習 6。240 のはずが 16 本で詰まりました", ""),
            (0, "③ 手順書どおりでは再現しない障害がある", "b"),
            (1, "演習 8。3 段階そろって初めて再現しました", ""),
            (0, "④ 同じ障害でも、クライアントによって症状が違う", "b"),
            (1, "演習 9。curl は 207ms、wget は 15 秒", ""),
            (0, "⑤ 戻し忘れが次を壊す", "b"),
            (1, "演習 10", ""),
            (0, "この 5 つは教科書に書いてありません。手を動かした人だけが持ち帰れます", "w"),
        ],
    )

    bullet_slide(
        prs,
        "次にやること / 参考",
        [
            (0, "次にやること", "b"),
            (1, "自分の担当案件で方式が何か調べる (契約書の「IPv6 接続サービス」の名称)", ""),
            (1, "切替前のヒアリング 5 項目を実際に使ってみる (説明会資料 5-1)", ""),
            (1, "もっと壊したい人へ: test-matrix.md §4 に R1〜R13。今日やったのは 4 つだけです", ""),
            (0, "参考", "b"),
            (1, "構築手順          runbook-vmware.md", ""),
            (1, "障害再現レシピ     test-matrix.md §4 (全 13 種)", ""),
            (1, "詰まったとき       runbook-vmware.md §9 (A〜N)", ""),
            (1, "実走の一次記録     build-log.md", ""),
            (1, "説明会資料 (座学)  slides/setsumeikai.md", ""),
        ],
    )

    prs.save(OUT)
    print("saved: %s (%d slides)" % (OUT, len(prs.slides._sldIdLst)))


if __name__ == "__main__":
    build()
