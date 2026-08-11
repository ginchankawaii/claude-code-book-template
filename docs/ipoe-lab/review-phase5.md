# フェーズ5 全体レビュー — 修正指示書(Opus 向け)

- 実施日: 2026-08-11
- レビュー体制: fable(主査)+ 独立監査 6 本(A: RFC 照合 / B: スクリプト実装 / C: 検証結果の証拠性 / D: 前提・盲点 / E: 対象者 3 ペルソナ通読 / F: 一貫性・運用性・機密)
- 判定: **CONFIRMED** = 主査が原文・コードと突き合わせて確定 / **PLAUSIBLE** = 監査指摘のとおりだが最終確認は修正時に行うこと
- 行番号はレビュー時点のもの。修正の過程でずれるので、**引用文で検索してから直すこと**
- **この指示書に載っていない箇所を「ついでに」直さないこと。**直したくなったら本書末尾の「見送り」に追記して止める

## 修正時の全体ルール

1. スライド (pptx) に触る修正は build-*.py を直して**再生成**し、枠越えチェック 0 件と PNG 目視を再実施する
2. 「経路/NAT」「設計値/実測値」の書き分けは**正本ルール**(build-log 0-A)に従い、正本→コピーの順で直す
3. 修正が終わったら本書の各項目に `[x]` を付け、最後にまとめて commit / push。バンドル再生成も忘れずに
4. **P0-1〜P0-3 (lab-mode.sh) の修正後は、実機ラボで PD/RA 両方式の status・mape・restore を実走して確認すること**(前回は RA 側しか実走していなかったため P0-1 を見逃した)

---

## P0 — 勉強会当日を壊すもの(最優先)

### P0-1. lab-mode.sh: `status` が PD 方式を必ず RA と誤報告する 【CONFIRMED / B】
- [lab/ipoe/lab-mode.sh:93] `grep -c '^…prefix 2001:' … || echo 0`
- PD モードでは grep -c が「0」を**出力した上で**終了コード 1 を返すため `echo 0` も走り、取得値が `0\n0` の 2 行になる。`case "$p" in 0)` に一致せず `*)` → v6mode=ra に汚染。バナーの出口アドレスも 198.51.100.20 (誤) になる
- 修正: `grep -q` + 終了コード判定にするか、`p="${p%%$'\n'*}"` で先頭行のみ採用。**修正後に PD 実機で status を実走確認**

### P0-2. lab-mode.sh: `mape` が RA 方式のとき動かない構成を案内する 【CONFIRMED / B】
- [lab/ipoe/lab-mode.sh:154-163] setup-map-br.sh を常に PD 用既定値で起動。expected_src4 は mape:ra→198.51.100.20 を返す(=サポート宣言)のに、RA 方式で必須の `CE_MAP_ADDR=2001:db8:1014:300:0:c633:6414:3 CE_SHARED_V4=198.51.100.20`(build.md の表)を渡していない
- さらに `ra|pd` 切替時に ipv4mode=mape なら BR のトンネル終点が旧 CE のまま残るが、警告なし
- 修正: `mape` 内で `state_get v6mode` を見て RA なら上記 2 変数を付与。`ra|pd` 側で ipv4mode=mape のときは「MAP-E BR の再実行が必要」と表示(自動再実行でも可)

### P0-3. lab-mode.sh: `restore` が失敗しても障害クリア扱い 【CONFIRMED / B】
- [lab/ipoe/lab-mode.sh:217-219] rsh の終了コードを無視して `state_set fault ""`。SSH 不達でも「障害の注入: なし」表示になり、実機に drop ルールが残る
- 修正: 各 rsh の成否を確認し、失敗時は fault を残して警告

### P0-4. handson 演習 2: 「RA は届いている」の証拠コマンドが誤り 【CONFIRMED / A+C】
- [docs/ipoe-lab/slides/handson.md:244-247][build-handson.py の対応スライド] `show ipv6 interface Gi0 | include Router advertisement` の出力「sent every 200 seconds」は**自分が送る RA のタイマ設定値**で受信の証拠にならない。しかも 0-3 で `ipv6 nd ra suppress all` 済みなので「suppressed」表示になりこの出力自体出ない可能性が高い
- 修正: 受信確認は `show ipv6 routers`(受信 RA で学習したルータ一覧)に差し替え。build-log:1662-1663 では同じ行を正しく「自分が撒いている証拠」として使っており、混同しないこと

### P0-5. handson 演習 7 (MTU): 手順どおりでは再現しない可能性が高い 【CONFIRMED / A+C】
- [handson.md:506-541] (a) 892FJ では未実走(R5 実測は OpenWrt + mtu_fix + 両端 flush)。(b) 5MB は**ダウンロード**方向なのに送信側 INET-SIM の PMTU キャッシュフラッシュが手順にない(lab-mode.sh break mtu の案内自身が「クライアントと INET-SIM で」と要求)。(c) `clear ipv6 traffic` は統計カウンタのクリアで、消したい対象(IPv4 の PMTU キャッシュ)に効く根拠がない
- 修正: 手順に INET-SIM 側 `ip route flush cache` を追加(司会側手順へ)。`clear ipv6 traffic` は削除。**892FJ で一度通しで実走してから出力を確定**。実走できない場合は「OpenWrt での実測から構成した手順(892FJ では未実走)」と明記

### P0-6. handson: 検証用 PC の設定が資料のどこにもない 【CONFIRMED / E】
- 0-3 は CPE 側 (Vlan1 192.168.100.1/24) のみ。DHCP プールも PC 静的設定の指示もなく、演習 8 で突然 `192.168.100.50` が既知の値として登場
- 修正: 0-3 に「検証用 PC: 192.168.100.50/24 / GW 192.168.100.1 / DNS は INET-SIM (203.0.113.53)」を追記(md と スライド両方)

### P0-7. handson: 検証 PC の OS が演習ごとに揺れ、演習 9 は Windows で不成立 【CONFIRMED / E+C+F】
- 演習 7 `curl -o NUL`(Windows)/ 演習 8 `python3 -m http.server`(非 Windows)/ 演習 9 `wget`(Windows に無い。PowerShell の wget エイリアスは別物で 15 秒タイムアウトが再現しない)。curl 207ms / wget 15 秒の実測値は Linux lab-client のもの
- 修正: 検証 PC の OS を 1 つに確定し(Windows 推奨なら演習 9 は Linux の lab-client で司会がデモ、等の役割分担でも可)、全コマンドをその前提で通す。演習 8 の「司会が用意した待受」の作り方も追記 (F の運用引き継ぎ 2 も同時に解消)

### P0-8. handson スライド版 0-3: コマンドブロックに必須 3 点が欠落 【CONFIRMED / E】
- [build-handson.py:147-166] `ipv6 unicast-routing`(解説行にはあるがコマンド列にない)・FastEthernet0 の VLAN 割当・`end`/`write memory` が欠落。スライドだけ見て打つと演習 1 でアドレスが付かない
- 修正: スライドのコマンド列に追記。入り切らなければ「このスライドは抜粋。打つのは配布資料の全量」と明示

### P0-9. handson 演習 8: `ip nat inside/outside` がどのインタフェースにもない 【CONFIRMED / A+E+C】
- [handson.md:571-615] 静的 NAT が DS-Lite 以前に不活性で、「DS-Lite だから不達」の対照実験として成立していない。IPv4 に強い受講者ほど教訓自体を疑う。892FJ でも未実走のまま出力を断定
- 修正: inside/outside を付けた手順に直した上で **892FJ で実走して出力を確定**。演習 6 の `nat64 ?` も同様に実走确認(こちらは classic IOS 非対応の設計知識としては正しい見込み)

---

## P1 — 事実誤り・矛盾(配布前に必須)

### P1-1. 「経路が間違っていた」誤再話 — 5 文書 7 か所 + build-log 自身 【CONFIRMED / C】
- 実際(build-log 3.3-A)は「経路は設計どおり。同居構成で**網側 NAT が当たらなかった**」。パケットは CPE→トンネル→AFTR を通っていた。「CPE を通っていなかった」(build-log:1937)は一度も起きていない仮想シナリオ
- 対象: ai-context.md:123,147,163 / setsumeikai.md:772 / handson.md:427,429 / build-setsumeikai.py:707 / build-handson.py:381,383 / build-log.md:1937
- 修正: 「全項目 PASS したのに**網側 NAT が効いていなかった**」に統一。切り分け表(ai-context:163)は「私設アドレスのまま → NAT がどこでも当たっていない(経路誤り**または** NAT 設定漏れ)」に。build-log:1937 は「サイクル 3 の『PASS するのに NAT が効いていなかった』と同じ構図」に

### P1-2. Cat8000v「CE に使える」がサイクル 7 と正面矛盾 【CONFIRMED / C】
- [runbook-vmware.md:19]「Cat8000v を CE に使える。MAP-E CLI 実装ありを確認済み」/ [proxmox-prototype.md:289,320] 同旨 / [build-log.md:2016,2020-2022] §3.5 H3 の結果欄
- サイクル 7 で MAP-E 有効化→QFP クラッシュ→転送不能と確定済み
- 修正: 「MAP-E CLI 構文は確認できたが、転送は QFP クラッシュで不可(CE には使えない。バックログ 10)」に 4 か所とも統一

### P1-3. 「若い番号 0〜4095 は誰にも配られない」は offset=4 前提 【CONFIRMED / A】
- [build-setsumeikai.py:467][setsumeikai.md:495 相当][setsumeikai.md:611-613 の VPN 根拠] OCN VC (offset=6) では除外は 0〜1023 のみで、**UDP 4500 は配られ得る**。「IPsec 待受不可」の結論は 500(<1024) だけで成立する
- 修正: 「ウェルノウンポート (0〜1023) はどのサービスでも誰にも配られません。v6プラスではさらに 0〜4095 が除外されます」の形に。VPN スライドの根拠は 500 に一本化

### P1-4. setsumeikai デッキ: 「計算で決まる」スライドが MAP-E 本体より前 【CONFIRMED / E】
- [build-setsumeikai.py:457-471 が 473-489 より前] md の 具体→抽象 の順が逆転。共有 IPv4 もポート範囲も聞いていない段階で計算の話をされる
- 修正: 2 スライドの順序を入れ替え(md の順に戻すだけ。枚数不変)

### P1-5. runbook のステータス矛盾・虎の巻表紙 【CONFIRMED / F】
- [build-toranomaki.py:1455]「runbook … (執筆前)」→ 正: 執筆済み(同デッキ 488 行・README:10 と矛盾)
- [build-toranomaki.py:453] 表紙「検証環境: …(構築中)」→ 正: 「自宅構築済み・社内展開前」

### P1-6. handson 所要時間: 各節合計 150 分 + 休憩 10 分 = 160 分 【CONFIRMED / F+E】
- [handson.md:4]「150 分(休憩 10 分 × 1 を含む)」と合計が合わない
- 修正: E の提案を採用する場合 — 演習 3 (RA を目で見る) を演習 1 に統合(最初から `debug ipv6 nd` を仕掛けて演習 1 の出力として見せる)して約 10 分捻出し、150 分に収める。採用しないなら表記を 160 分に。**どちらにするかはユーザーに確認せず、演習 3 統合案を採用してよい**(E の判定では G2/G3 補強も同時に達成できるため)。統合で浮いた枠に「司会が OpenWrt CE を MAP-E に切替→受講者は出口アドレスだけ比較」を正式演習化すると、現状どの演習でも使われていない `lab-mode.sh mape` が活きる

### P1-7. 「§9 (A〜N)」だが 9-H は欠番 【CONFIRMED / F】
- [ai-context.md:276 / handson.md:720 / build-handson.py:551] runbook は 9-G→9-I
- 修正: runbook に 9-H を新設して詰めるか、3 か所を「A〜N (H 欠番)」または「§9 のトラブル一覧」に

### P1-8. 数値の再話ゆれ 3 件 【CONFIRMED / C】
- 「レシピが想定と違った」件数: build-log:115「4 件」vs study-guide:23「5 件」vs トラッカーの R4a「OK 再現」。実態は「R1/R3/R5/R6/D1 の 5 件 + R4 は手順注意」— 3 か所をこの整理で統一
- setup 所要: build-log「4 台で 2.6 分」vs runbook:34「5 台で約 2.5 分」。5 台目は未計測なので「4 台実測 2.6 分 + 分離 INET-SIM(未計測)」に
- VM 作成: runbook:33「6 台で約 3 分」→ 実測は 5 台 3 分 + 9005 が 1 分 52 秒。「6 台で約 5 分」に

### P1-9. 枚数表記のずれ(setsumeikai.md の節ヘッダ vs デッキ実枚数) 【CONFIRMED / F】
- 第2部「5 枚」→ 実 7 枚 / 第3部「9 枚」→ 実 11 枚 / 第4部は md 見出し 7 個に対しスライド 5 枚(4-1・4-6 は意図的にスライド化していないなら md 側にその旨を注記)
- 修正: md の枚数表記をデッキ実数に合わせる

---

## P2 — 低優先の誤り・体裁(直せるものは直す)

- P2-1. [setsumeikai.md:758]「3-5 で入れた『あの 1 行』」→ 正: 3-6。**併せて節番号参照は全スライドで見出し語参照に置換**(デッキに節番号が表示されないため。E 提案) 【CONFIRMED】
- P2-2. [setsumeikai.md:131]「10 分」vs [build-setsumeikai.py:182]「7 分で」→ どちらかに統一 【CONFIRMED】
- P2-3. [study-guide.md:240][build-toranomaki.py:973]「4 往復」→ 正: 4 メッセージ = 2 往復 【PLAUSIBLE / A】
- P2-4. [ai-context.md:14-22 ほか]「すべて文書・例示用に予約」→ 100.64.0.0/10 (RFC 6598) は CGN 共有アドレス。「文書用+共有アドレス空間で、いずれも実害なし」に 【PLAUSIBLE / A】
- P2-5. [README.md:167]「NGN は DUID-LL しか受け付けない」の断定 → 他文書同様「複数の独立報告あり・公開仕様では未確認」の但し書きを付ける 【PLAUSIBLE / A】
- P2-6. [study-guide.md:480]「PPPoE の MRU 上限で実質 1454」→ 1454 はフレッツ網固有の設計値。「フレッツ網では 1454(一般には 1492)」に 【PLAUSIBLE / A】
- P2-7. [handson.md:383]「192.0.0.2 …自由に決めてはいけません」→ RFC 6333 は 192.0.0.0/29 を予約し .2 は既定 (SHOULD)。「通常これを使う約束」程度に弱める 【PLAUSIBLE / A】
- P2-8. [setsumeikai.md:596-599] VPN 表「待ち受け不可。ポートを選べません」→ 割当ポート内での待受は可能。「IKE の慣習ポート (500) では待てない」に表現を揃える 【PLAUSIBLE / A】
- P2-9. [setsumeikai.md:327-330]「網側にセッションが 1 分ほど残り」→ 1 分はラボ BRAS の設定値。「ラボでは 1 分。実網はもっと長いことがある」に 【PLAUSIBLE / A】
- P2-10. [runbook-vmware.md:908]「TTL=62 = トンネル経由」→「トンネル経由と整合(証明は src:)」に弱める 【PLAUSIBLE / C】
- P2-11. [ai-context.md:207-208 ほか]「OpenWrt では実効 16」→「OpenWrt 24.10.0(本ラボ構成)では」とバージョン刻印 【PLAUSIBLE / C+D】
- P2-12. [build-log.md:495] `/c/Users/penan/...` → `<user>` に置換(公開鍵情報のみで実害低だが、バンドル素材のため) 【CONFIRMED / F】
- P2-13. [lab/ipoe/deploy.sh:51,73] chmod パターンに `lab/ipoe/*.sh`(直下)を追加 【PLAUSIBLE / B】
- P2-14. [lab/ipoe/deploy.sh:72-78] destroy→再 provision 後は accept-new が変更鍵を拒否。失敗メッセージに `ssh-keygen -R <fe80アドレス>` の案内を追加 【PLAUSIBLE / B】
- P2-15. [lab/ipoe/lab-mode.sh:144] Kea リース削除は test-matrix R9 のとおり stop→rm→start の順に 【PLAUSIBLE / B】
- P2-16. [lab/ipoe/tests/run-checks.ps1:94-95,136-137] Windows ping.exe は unreachable 応答でも成功になり得る。`TTL=` を含む応答で判定するよう変更し、**WAN 断状態で偽陽性テストを 1 回実走** 【PLAUSIBLE / B】
- P2-17. [lab/ipoe/tests/run-checks.sh:7-9] ヘッダの EXPECT_SRC4 例に pppoe:203.0.113.2 を追加(ps1 と揃える) 【PLAUSIBLE / B】
- P2-18. [lab/ipoe/make-bundle.sh:26] `lab-hosts.conf`・`.lab-mode` をバンドルから除外。再実行時の `lab/lab` 入れ子も防止 【PLAUSIBLE / B】
- P2-19. [lab/ipoe/proxmox/provision.sh:44] SPLIT_INET 既定 0(同居)は README「分離必須」と逆。既定を 1 にするか、少なくとも既定で作った環境で R4 を実施したときに検出できる注意を README/test-matrix に 【PLAUSIBLE / B】
- P2-20. [lab/ipoe/client/setup-client.sh:22] netplan は MAC 完全一致。`CLIENT_LAN_MAC` 環境変数を build.md / runbook に追記 【PLAUSIBLE / B】
- P2-21. [build-toranomaki.py:829,862,1012,478-499] 講師向け指示 4 件が本文/footer に残存 → notes へ移動(「ステータス」スライドは削除または非表示化)。1282-1283 のタイトル・ゴール同文重複も修正 【PLAUSIBLE / F】
- P2-22. [study-guide.md:27-28,653]「⚠未検証の演習を実走せよ」→ 全演習実測済みなので stale。文言を現状に合わせる。build-log:1955 の「study-queue.md 相当」も実在ファイル名に 【PLAUSIBLE / F】
- P2-23. [build.md] §5.6(###)→§5.5(##)の順序・レベル乱れ、[study-guide.md:356-492] §2 の後の §1.35〜§1.6 → 節番号整理 or 冒頭に読み順 1 行 【PLAUSIBLE / F+E】
- P2-24. [research-notes.md:125]「892FJ という型番の一次情報はなく」vs 全資料の「892FJ」呼称 → 実機 `show version` で正式型番を確定して統一 【PLAUSIBLE / A】※物理作業。ユーザーに依頼
- P2-25. [handson.md:4] 時間仮案の注記(「通し実測は未実施」)を追加(P1-6 とセット) 【PLAUSIBLE / C】

---

## P3 — 記載追加(D: 盲点。ラボ改修ではなく注記が主)

- P3-1. **切戻し偽陽性**: ラボの BRAS は無条件で PPPoE を受けるため切戻しは必ず成功する。実案件では IPoE 開通に伴い PPPoE アカウントが廃止されることがある → test-matrix Phase 3 と README「できないこと」に「切戻し成功は ISP 側アカウント存続を検証していない。切替前に ISP へ書面確認」を明記。ヒアリングシートに「切替後も PPPoE 認証が生きているか」を追加
- P3-2. **BR 無検査**: ラボ BR は何でも通すため、CE の導出誤り・PSID 外ポートが顕在化しない → MAP-E 実機検証手順で `map-enforce` nft を既定 ON に格上げ(setup-map-br.sh に enforce サブコマンド追加は小改修)。test-matrix No.1-2 の確認点に「PSID 外ポートが落ちることの確認」を追加
- P3-3. **無応答の原因空間**: 実網の Solicit 無応答は DUID 以外に「開通未反映・契約突合 NG・ひかり電話契約変更」でも起きる → test-matrix Phase 1 手順 5 に切り分け表を追加(research-notes §1.5 と接続)
- P3-4. **HGW 不在**: 現場多数派の HGW 配下構成(フィルタ既定値・フレッツ・ジョイントによる自動配信で HGW が勝手に MAP-E 終端→二重終端等)はラボ未カバー → runbook §8 に「HGW 配下構成は未カバー」を明記。中古 HGW 収容の検証をバックログ最上位に追加
- P3-5. **AFTR 無制限**: ラボの AFTR は conntrack 任せでセッション上限・タイマが実質無制限 → README「できないこと」に一言。`ct count` による上限模擬(R14)をバックログに
- P3-6. **共有 L2 の事故半径**: 受講者の 1 台が RA を撒くと全員が壊れる(9-N の一般化)→ runbook §2 に「複数人で実機を触る回は RA Guard 付きスイッチ、無ければ結線は常に 1 台」ルールと復旧手順(NGN-SIM setup 再実行 + wan6 再接続)を明記
- P3-7. **タイムスケール**: ラボは RA 間隔 30 秒・PPPoE 残留 60 秒など実網より 1〜2 桁短い → README §10 に「時間感覚は持ち帰らない」を 1 項目
- P3-8. **DNS 配布の忠実度**: 実 NGN は RDNSS を配らない(DHCPv6 のみ)。radvd の RDNSS を落とす「実網忠実モード」をコメントで用意
- P3-9. その他 1 行注記: DHCPv6 リレー非経由の限界 / リース flush はラボ固有の作法(現場の切り分けではない) / accel-ppp のコミット固定 + tarball 同梱 / runbook §0 に vSwitch 種別(標準/vDS)確認 / スナップショット復元後の時刻同期 / spoof-aftr 成功は方式判別ロジックの検証ではない / build.md の MAP ルール表直下に「この値はラボ専用」 / README §10 に MTU 1500 の根拠(光ネクスト IPoE) / 892FJ は EoL、現場提案には使わない / test-matrix Phase 0 に固定 IP PPPoE (`kotei@isp-a.example`) を 1 回触る導線

---

## P4 — 分かりやすさ(E: ペルソナ由来。スライド枚数は増やさない方針)

- P4-1. [setsumeikai 3-3 冒頭] NAPT の本質 2 行を追加: 「NAT は アドレス+ポートの組 で通信を区別している。だからポートを分担すれば 1 個のアドレスを共有できる」(P1 向け・最重要)
- P4-2. [setsumeikai 2-3 表の下] 「※ このほかに固定 IP のオプション契約(第 3 の形)があります」の 1 行(2-5 の事故事例で突然出てくるため)
- P4-3. [setsumeikai 0-4] たとえの補正 1 行: 「正確には、速いのは IPv6 ではなく IPoE という通り方です」(IPv6=速い の誤解防止)
- P4-4. [setsumeikai 3-1] 「IPv4 と IPv6 は互換性がなく、直接は通信できません」の 1 行(トンネルの必然性の土台)
- P4-5. [setsumeikai 3-2] 「※ DS-Lite も網側で 1 契約あたりのポート数に上限があります」の 1 行(P2 が「DS-Lite なら無制限」と誤解して提案する事故の防止。P3-5 と整合)
- P4-6. [setsumeikai 0-2] IPoE 行を「認証なしで繋がる。利用者は回線契約で識別される」に(IPv4 屋の「誰でも繋がるのか」を初出で回収)
- P4-7. [setsumeikai 2-2] 「1 本の回線に 2 つの接続が同居し、CPE の経路設定で振り分けます」の 1 行
- P4-8. [setsumeikai 想定問答] Q7「IPoE にしたら外から入られやすくなりませんか」(study-guide 壁10 の要約を移植)と Q8「DS-Lite なら接続数は無制限ですか」を追加(巻末 md のみ、枚数不変)
- P4-9. [setsumeikai 1-6] 「よくある誤解」枠に 1 行昇格: 「DHCPv6 を併用しても自動生成は止まりません(止める/止めないは別のフラグ)」(現状ノート送りで、P3 中堅が一生訂正に触れない)
- P4-10. [setsumeikai 1-4] 「PD 方式(まとめ借り方式)」に「= DHCPv6 のプレフィックス委任機能」の括弧を追加
- P4-11. [setsumeikai 冒頭] 「配布物 = この md(または notes 付き pptx)」の 1 行(想定問答・補足が配布に落ちない問題)
- P4-12. [handson 4-3] 「もっと壊したい人へ」に代表 3 件の題名を添える(R7 二重終端 / R9 プレフィックス変更追従 / R13 外→内 IPv6 直接着信)
- P4-13. [handson 演習 4] 「実案件では AFTR は DNS 名で公開されます(gw.transix.jp 等)。ラボでは固定値」の 1 行(天下り解消)
- P4-14. [handson 4-3] **G3(安心感)の 3 行を追加**: 「調べた VNE が DS-Lite 系なら今日の構成そのまま。MAP-E 系なら OpenWrt CE + `lab-mode.sh mape` で事前検証できる。環境を使いたいときの窓口は ____」— 窓口名はユーザー記入
- P4-15. [build-setsumeikai.py 2-3 統合表] footer に結論 1 行「違いは NAT がどこにあるか。それだけです」

---

## 要実走(修正とは別の検証課題 — 物理・要ユーザー同席)

1. handson 演習 6/7/8/9 を 892FJ で通しで実走し、「出てくる出力」を実測値に置き換える(P0-5/P0-9 とセット)
2. lab-mode.sh 修正後の PD/RA × status/mape/restore 実走(P0-1〜P0-3 とセット)
3. run-checks.ps1 の WAN 断偽陽性テスト(P2-16)
4. 『プロフェッショナルIPv6 第2版』の節番号・ページ番号の全数照合(study-guide 自身が配布前必須と規定。PDF はユーザーの Google Drive)
5. 892FJ の正式型番確定(P2-24)

## バックログ追加(build-log §5 へ)

- 16: HGW 実機の収容検証(P3-4。最上位)
- 17: AFTR セッション上限の模擬 = R14(P3-5)
- 18: chap-secrets からユーザを消して「切戻し不能」を演習化(P3-1)
- 19: 現場持ち出し A4 フローチャート / 営業向け契約確認 1 枚 / 事前事後クイズ 5 問(フェーズ5 では作らないとユーザー決定済み。将来候補として記録)

## 監査で「問題なし」を確認した主な範囲(再確認不要)

- 機密リーク: 顧客名・実顧客 IP・パスワード・トークン・秘密鍵とも**なし**(F が網羅 Grep 済み。唯一の軽微案件は P2-12)
- MAP-E の計算(EA-bits/PSID/IID/240=15×16/1008)・MTU 体系(1500/1460/1454/1452/MSS1420)・出口アドレス 3 値・RFC 引用番号・日本のサービス→方式対応・EUI-64 例: 全ファイルで検算一致
- 参照リンク・アンカー: 全て実在。build-log の主要 Check 節の証拠貼付は良好。未検証事項(IPsec/安全率/DUID-LL)の伝播も適切
- provision.sh の安全ガード、deploy.sh の過去バグ修正、setup 系の冪等性、run-checks.sh の偽陽性対策本体、kea-pd-route.sh: いずれも問題なし

## 見送り(直さないと決めたもの)

- (Opus が修正中に追加したくなったものをここに書く)
