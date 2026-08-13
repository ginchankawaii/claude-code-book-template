# 構築ログ / PDCA 記録

**サイクル 1〜7 が完了しています。**(VM 起動 → IPv6 配布 → **MAP-E / DS-Lite で IPv4 が通り
`run-checks.sh` が両方式で `PASS` するところまで**実測済み)。
トラブル再現レシピ(R1/R2/R3/R4/R5/R6/D1 の 7 件)まで実走済み。runbook 執筆と持ち込みバンドルも完了。
**実機 Cisco 892FJ での DS-Lite 検証(サイクル 4)も完了**し、実機 Windows 11 から
出口 `203.0.113.1` / MTU 1460 / 5MB 完走を確認しました(H1 / H2 確定)。
**CML(Cat8000v / IOS XE 17.15.01a)での MAP-E 検証(サイクル 7)も実施済み**ですが、
目的だった実効ポート数は**測れませんでした**(MAP-E を有効にすると転送エンジンが落ちるため)。
残っている未確認は §3 のトラッカーと §5 のバックログにあります。

動かせば必ず設計と食い違う箇所が出ます。それを場当たりに直して忘れるのではなく、
**1 サイクルずつ記録して次に活かす**ためのファイルです。

このファイルが最終的に [runbook-vmware.md](runbook-vmware.md)(会社で人間が手作業する手順書)の
素材になります。**会社では AI が使えないので、ここに書いていないことは会社で再現できません。**

---

## 0-A. 作業環境(2026-08 に変更)

**サイクル 1 まではクラウド上の Claude Code セッションで、人間が出力をコピペして進めていた。**
クラウドのコンテナは自宅 LAN に到達できない(`192.168.11.20:22` 不到達、`ssh` 未インストール、
外向きは HTTPS プロキシのみ)ため、1 コマンドごとに往復が発生して遅かった。

**サイクル 2 以降は自宅 LAN 内の PC(サーフェス / WSL2)で Claude Code を動かす。**
そこから直接 SSH できるので、試行錯誤をエージェント側で完結できる。

| 接続先 | アドレス | 入り方 |
|---|---|---|
| Proxmox ホスト | `192.168.11.20` | `ssh root@192.168.11.20` |
| ラボ VM 4 台 | IPv6 リンクローカル | `ssh labadmin@fe80::…%vmbr0`(ホスト上から) |
| OpenWrt-CE (9010) | 管理 NIC なし | `qm terminal 9010`(抜けるのは Ctrl-O) |

**VM の接続先は `./provision.sh ips` で毎回取得すること。**
リンクローカルは MAC 由来なので安定しているが、`destroy` → 再作成すると MAC が変わる。

```
ssh root@192.168.11.20 'cd /root/ipoe-lab/lab/ipoe/proxmox && ./provision.sh ips'
```

### コピーが 3 か所ある問題と、正本の決め方

同じスクリプトが **3 か所**に存在する。ここを曖昧にすると
「ホストでちょっと直して動いた」変更が記録に残らず、**会社で再現できなくなる**。

| 場所 | 役割 | 編集してよいか |
|---|---|---|
| **GitHub のブランチ** | **正本(single source of truth)** | ここを直す |
| 作業機の作業コピー(`~/work/...`) | 正本の複製。ここで編集して commit / push する | ○ |
| Proxmox ホスト `/root/ipoe-lab` | **配布先**。git 管理外 | **×** |
| 各 VM の `~/ipoe` | **配布先**。git 管理外 | **×** |

**ルール**:

1. **直すのは必ず作業コピー(git 管理下)。** ホストや VM で直接直さない
2. 直したら **`./lab/ipoe/deploy.sh`** でホストと VM に配る
3. 動いたら **その場で commit / push**。「ホストと VM だけが新しい」状態を残さない
4. 作業を始める前に **`git pull`**(このリポジトリは複数のセッションから触られる)

配布はリポジトリのルートから:

```
./lab/ipoe/deploy.sh          # ホスト + Linux VM 全台
./lab/ipoe/deploy.sh host     # ホストだけ
./lab/ipoe/deploy.sh vms      # VM だけ
```

`deploy.sh` は未コミットの変更があると警告する(ホストだけ新しい状態を作らないため)。
`rsync` は Proxmox に無い場合があるので `tar` を `ssh` に流す方式にしている。
作業機から VM のリンクローカルには届かない(WSL2 は NAT のため)ので、
**ホストを経由して**配る。OpenWrt-CE は管理NICが無いので対象外(`qm terminal 9010`)。

### セッションが 2 つある間の分担

クラウド側(設計・レビュー)とローカル側(実行)が同じブランチを触るため、
**同時に同じファイルを編集しない**こと。

| | 触る範囲 |
|---|---|
| ローカル(実行担当) | `lab/` 配下、`build-log.md` の Do / Check / Act |
| クラウド(設計・レビュー担当) | `docs/` の設計・教材。**サイクル実行中は `lab/` を触らない** |

どちらも**作業前に `git pull`**。競合したらローカル側(実測が入っている方)を優先する。

---

## 0. 回し方

1 サイクル = 1 つの見出し。**Plan だけ先に書いて実行し、Do 以降は実行しながら書く。**

| | 何を書くか |
|---|---|
| **Plan** | このサイクルで何を確かめるか。**成功条件を先に書く**(後から都合よく解釈しないため) |
| **Do** | 実際に叩いたコマンドと出力。**うまくいかなかったものも消さずに残す**(会社で同じ罠を踏むので) |
| **Check** | 期待と違った点。エラーメッセージは原文で。「なぜそうなったか」の推定も書く |
| **Act** | 直したファイルと commit。**ドキュメント側の修正も必ず含める**(コードだけ直すとまた食い違う) |

**ルール**:

- **1 サイクルで直すのは「詰まった原因」だけ**。気づいた改善案は §3 のバックログに積んで、そのサイクルでは触らない
- コマンドの出力は**成功したものも貼る**。runbook に「正常時はこう出る」を書くための材料になる
- 所要時間を測る。勉強会の時間割([study-guide.md](study-guide.md) §2)は現在すべて仮案で、ここの実測で確定させる

---

## 1. サイクル一覧

| # | 目的 | 状態 | 所要 | 主な学び |
|---|---|---|---|---|
| 1 | Proxmox に 5 VM を作って起動する | **完了**(成功条件 4 件すべて達成) | 約 3 分(2 回) | gzip は警告でも終了コード 2 を返し `set -e` で即死する。冪等性の無い分岐に副作用を置くと再実行で隠れる。guest-agent 無しでも IPv6 リンクローカルで VM に入れる |
| 2 | 4 台の Linux に setup スクリプトを流し、IPv6 が降りるところまで | **完了**(成功条件 6 件すべて達成) | 約 5 分(4 台の setup 計 2.6 分 + CPE 設定。分離した INET-SIM は未計測) | `ssh` は使わなくても stdin を吸うので `while read` の中では `-n` が必須。OpenWrt の `uclient-fetch` は AAAA を選ぶと A へフォールバックしない。PPPoE を上げると netifd が物理NICの IPv6 を無効化するが、**RA 自体は届いている** |
| 3 | MAP-E / DS-Lite で IPv4 が通り、`run-checks.sh` が PASS するまで | **完了**(両方式で `PASS=10 FAIL=0`) | 約 90 分(大半は DNS の切り分け) | 期待値表は完全に正しかった。「ping は通るのに DNS だけ死ぬ」に **3 つの独立した原因**が重なりうる: 送信元制限付き既定経路 / dnsmasq の listen インタフェース / CPE のリバインド保護 |
| 4 | 実機 CPE(892FJ)を収容する | **完了**(成功条件 4 件すべて達成。H1 / H2 確定) | 約 120 分 | 見た目では 10G と 1G の RJ45 を区別できない。**NIC 名は udev でリネームされているので名前から物理位置を逆算できない**。RA 方式でないと `ipv6 address autoconfig` は何も取得しない。classic IOS は `ip tcp adjust-mss` が無いと 5MB 転送で詰まる |
| 5 | トラブル再現レシピを実走して再現条件を確定 | **完了**(R1/R2/R3/R4/R5/R6/D1 の 7 件) | 約 150 分 | **7 件中 5 件が「レシピのままでは想定と違った」**(R1/R3/R5/R6/D1。R4 は再現したが手順に注意が要る)。R3 は 240 でなく 16 で詰まる / R4 は待受の対照実験が無いと誤判定する / R5 は MSS clamp と PMTU キャッシュの 2 つを外さないと再現しない |
| 6 | runbook-vmware.md を書き上げ、Box バンドルを作る | **完了**(runbook 執筆 + `make-bundle.sh`) | — | 実走の一次記録があれば runbook は一気に書ける。逆に記録が無いと書けない。**同居構成(VNE+INET)をそのまま会社に持ち込ませない**注意書きが最重要だった |
| 7 | CML の Cat8000v で MAP-E の実効ポート数を数える | **完了**(ただし目的は未達。理由は下記) | 約 90 分 | **設定が入ることと動くことは別物。**`show nat64 map-e` が完璧な値を返す裏で転送エンジン(QFP)が落ちていた。ドキュメントに「非対応」と書いてある構成もパーサは通す。CML の cat8000v は設定の 1 行目が `platform console serial` でないと startup-config として認識されない |

---

## 2. サイクル記録

### サイクル 1: Proxmox に 5 VM を作って起動する

#### Plan

**目的**: `provision.sh` を実走し、VM が 5 台立ち上がって SSH で入れる状態にする。

**前提(前回の preflight で確認済み)**:

| 項目 | 値 |
|---|---|
| PVE バージョン | 9.1 |
| ストレージ | `local-lvm`(lvmthin / スナップショット可) |
| SSH 公開鍵 | `/root/.ssh/id_rsa.pub` あり |

**まだ確認していないこと**:

- `local-lvm` の空き容量が足りるか(**必要 70GB 程度**)
- VMID 9001-9004 / 9010 が空いているか
- `vmbr1`〜`vmbr4` が他用途(CML 等)で使われていないか
- ラボ内から Ubuntu / OpenWrt のイメージをダウンロードできるか(初回のみ必要)

**成功条件**:

1. `qm list` に 5 台(9001 ngn-sim / 9002 vne-inet / 9003 bras / 9004 lab-client / 9010 openwrt-ce)が `running` で並ぶ
2. `labadmin` で 4 台の Linux VM に SSH で入れる
3. 各 VM の中で `lab/ipoe/detect-ifs.sh` を読み込むと、MAC から NIC 名が解決される
   (`ACCESS_IF` / `CORE_IF` / `INET_IF` が空でない)
4. `vmbr1`〜`vmbr4` に `bridge-mcsnoop 0` が入っている(**入っていないと RA/ND/DHCPv6 が死ぬ**)

**やらないこと**: setup スクリプトの実行(サイクル 2)。実機の接続(サイクル 4)。

#### Do

**手順 1: リポジトリをホストに持ち込む**

ホストに `git` が入っておらず、`apt-get install git` は enterprise リポジトリの 401 で失敗する。
`unzip` の有無も不明なため、**`tar` でアーカイブを展開する**方法に統一した(`tar` は PVE 標準)。

```
cd /root
curl -fsSL "https://github.com/<owner>/<repo>/archive/refs/heads/<branch>.tar.gz" | tar xz
mv -f <repo>-<branch をダッシュ化した名前> ipoe-lab
chmod +x ipoe-lab/lab/ipoe/proxmox/provision.sh
```

**手順 2: 事前検証(何も変更しない)**

```
cd /root/ipoe-lab/lab/ipoe/proxmox
STORAGE=local-lvm ./provision.sh preflight
```

出力(正常時。runbook にはこれを「期待される出力」として載せる):

```
[検証] 環境を確認します
  PVE バージョン: 9.1 (ディスク取り込み: import-from)
  ストレージ種別: lvmthin / スナップショット: yes
  VMID 9001-9010: すべて空き
  公開鍵: /root/.ssh/id_rsa.pub
  ブリッジ vmbr1-4: すべて未使用 (これから作成)
[完了] 事前検証のみ実行しました (何も変更していません)
```

**手順 3: ホスト環境の実測(サイクル 4 と CML 併用の判断材料)**

```
free -h        →  総メモリ 251Gi / 空き 247Gi
pvesm status   →  local-lvm (lvmthin) 空き 1023229952 KiB ≒ 975GB
                  local (dir) 空き 87961884 KiB ≒ 84GB  ← イメージ置き場
                  QNAP-10G (nfs) 空き 15074678784 KiB ≒ 14TB
qm list        →  VMID 100 CML (stopped, 65536MB 割当) のみ
ip -br link    →  UP:   nic2 (vmbr0 のポート), nic11
                  DOWN: nic0, nic1, nic3, nic4, nic5, nic7, nic8, nic9, nic10
```

**手順 4: VM 作成(実行) — 1 回目: [2/4] で黙って停止した**

```
STORAGE=local-lvm ./provision.sh
```

```
[1/4] ブリッジを準備します
  vmbr1: 追加 (アクセス網 (PG-ACCESS相当), uplink=none)
  vmbr2: 追加 (NGN網内 (PG-CORE相当), uplink=none)
  vmbr3: 追加 (模擬インターネット (PG-INET相当), uplink=none)
  vmbr4: 追加 (CPE配下のクライアント側LAN, uplink=none)
warning: nic6: interface not recognized - please check interface configuration
  ネットワーク設定を反映しました
[2/4] イメージを準備します
  Ubuntu 24.04 クラウドイメージを取得中...
  ... 595.32M  8.47MB/s    in 46s
  OpenWrt 24.10.0 イメージを取得中...
  ...  12.98M  1.58MB/s    in 8.2s

gzip: /var/lib/vz/template/iso/openwrt-24.10.0-x86-64-generic-ext4-combined.img.gz: decompression OK, trailing garbage ignored
（ここでプロンプトに戻る。[3/4] が出ない）
```

#### Check

**preflight は 4 項目すべて合格。想定外はなかった。** 判明した事実:

- **メモリに余裕がある(251GB)**。CML(64GB)とラボ(7.5GB)を**同時に動かせる**。
  → §3.5 の H3(CML で IOS XE の MAP-E CLI を確認)は、ラボ構築を止めずに並行して実施できる。
  当初「CML を止めないとラボが動かないかもしれない」と懸念していたが、その制約は無い。
- **ディスクも余裕(local-lvm 975GB 空き)**。当初の見積り 70GB に対して十分。
  QNAP(14TB / NFS)を使う必要はなく、**スナップショットが速い local-lvm のままでよい**と確定。
- **空き物理 NIC が 9 本ある**(nic0/1/3/4/5/7/8/9/10 はすべて NO-CARRIER)。
  サイクル 4 で 892FJ を繋ぐ `ACCESS_UPLINK` はここから選ぶ。
  **`nic2` と `nic11` は使用中なので選ばないこと**(nic2 = vmbr0 の管理系、
  nic11 = キャリアあり。QNAP 10G と推定。**要確認**)。

**手順 4 で見つかった不具合 2 件**

**① `gunzip` の終了コード 2 で `set -e` が発動し、スクリプトが黙って停止していた(致命的)**

OpenWrt の配布 `.img.gz` は展開すると `decompression OK, trailing garbage ignored` という
**警告**を出す。gzip は**警告でも終了コード 2 を返す**仕様で、`set -euo pipefail` の下では
これが即死につながる。**展開自体は成功しているのにスクリプトが止まる**ため、
エラーメッセージが 1 行も出ずに `[3/4]` に進まないという分かりにくい症状になっていた。

再現確認(手元で検証):

```
$ gzip -c file > f.gz && printf 'GARBAGE' >> f.gz
$ gunzip -f f.gz; echo "終了コード = $?"
gzip: f.gz: decompression OK, trailing garbage ignored
終了コード = 2      ← 展開は成功しているが 0 ではない
```

**② `qemu-img resize` がダウンロード分岐の中にあり、再実行時にスキップされる**

`if [ ! -f "$OPENWRT_IMG" ]` の**中**に resize があったため、① で停止した状態から
再実行すると「イメージは既存」と判定されて `if` ブロック全体が飛ばされ、
**2G への拡張が永久に行われない**。OpenWrt のディスクが小さいまま進み、
後で `opkg install` の段階で容量不足として現れる(原因が遠く、追いにくい)。

**③ `warning: nic6: interface not recognized`(既存構成由来・無害)**

`/etc/network/interfaces` に `nic6` の記述があるが実機に存在しない。
ラボが作った設定とは無関係で、`ifreload -a` は成功している(`vmbr1-4` は作成済み)。
**このホスト固有のノイズ**として記録しておく。会社環境では出ない可能性が高い。

**手順 4: VM 作成(実行) — 2 回目: 完走した**

```
[1/4] ブリッジを準備します
  vmbr1: 既存 (ラボ用) のためスキップ      ← 1 回目で作成済み。冪等に動いた
  vmbr2: 既存 (ラボ用) のためスキップ
  vmbr3: 既存 (ラボ用) のためスキップ
  vmbr4: 既存 (ラボ用) のためスキップ
[2/4] イメージを準備します
  Ubuntu イメージ: 既存を使用
  OpenWrt イメージ: 既存を使用
  OpenWrt イメージを 2G に拡張しました    ← 修正②が効いた箇所 (1 回目は飛ばされていた)
  注意: snippets 対応ストレージがないため guest-agent は入りません (qm guest cmd は使えない)
[3/4] VM を作成します
  VM 9001 (ngn-sim): 作成
  VM 9002 (vne-inet): 作成
  VM 9003 (bras): 作成
  VM 9004 (lab-client): 作成
  VM 9010 (openwrt-ce): 作成 (net0=LAN/vmbr4, net1=WAN/vmbr1)
[4/4] VM を起動します
  VM 9001〜9004: 起動 (generating cloud-init ISO)
  VM 9010: 起動
[完了] 検証ラボの土台ができました   (ストレージ: local-lvm / lvmthin / snapshot=yes)
```

**所要時間**: 1 回目(イメージ取得込み) 約 2 分 + 2 回目 約 1 分。
**2 回目にイメージ取得が走らないので、再実行は速い**(会社環境でも同じはず)。

**手順 4 で見つかった不具合 3 件目: 接続先の確認手段が無かった**

`snippets` に対応したストレージ(`local` は既定で iso/vztmpl/backup のみ)が無いため
**guest-agent が VM に入らず、`qm guest cmd` で IP を取れない**。
一方で完了メッセージは「各VMのIPを確認」と書いているだけで、**手段を示していなかった**。
`qm terminal` で 1 台ずつコンソールに入って `ip a` を読むしかない状態で、
4 台ぶんやると地味に時間を食う。会社環境(人間が手順書を見て作業する)ではここで止まる。

#### Act

- `build-log.md` にホスト実測値と上記 3 件を記録(このセクション)
- **`provision.sh ips` モードを追加**(3 件目の対策)
  - **IPv6 リンクローカルアドレスで接続先を解決する。** リンクローカルは MAC から
    決まるので DHCP に依存せず、家庭 LAN のルータのリース表を見に行く必要もない
  - `ff02::1`(全ノードマルチキャスト)へ ping して近隣キャッシュを埋め、
    `ip -6 neigh` の結果を VM の net0 MAC と突き合わせて一覧表示する
  - IPv4 のブロードキャストは撒かないので、同居している家庭 LAN に影響しない
  - `ip -6 neigh` のパースは列位置ではなく **`lladdr` の次のトークン**を取る形にした
    (iproute2 の版で列位置が変わるため。最初は `$3` を見ていて誤っていた)
  - `ping6` / `ping -6` の両方に対応(ディストリによってどちらかしか無い)
  - 完了メッセージも「`./provision.sh ips` を使う」に修正し、
    リンクローカルでの `scp` の書き方(`[fe80::xxxx%vmbr0]`)を明示した
  - guest-agent を使いたい場合の手順(`pvesm set local --content ...,snippets` +
    作り直し)も併記した

**手順 5: 成功条件の確認**

```
qm list
  9001 ngn-sim     running  2048  9.50
  9002 vne-inet    running  2048  9.50
  9003 bras        running  2048  9.50
  9004 lab-client  running  1024  9.50
  9010 openwrt-ce  running   512  2.00

vmbr1 mcsnoop=0 / vmbr2 mcsnoop=0 / vmbr3 mcsnoop=0 / vmbr4 mcsnoop=0   ← 全て 0 (必須)

./provision.sh ips
  9001 ngn-sim     bc:24:11:e5:63:1b  fe80::be24:11ff:fee5:631b%vmbr0
  9002 vne-inet    bc:24:11:b9:3f:b1  fe80::be24:11ff:feb9:3fb1%vmbr0
  9003 bras        bc:24:11:50:eb:7c  fe80::be24:11ff:fe50:eb7c%vmbr0
  9004 lab-client  bc:24:11:3b:bf:e2  fe80::be24:11ff:fe3b:bfe2%vmbr0
  9010 openwrt-ce  bc:24:11:73:e4:24  (未検出)          ← 下記④のとおり ips 側のバグ
```

**成功条件 1(5 台 running)と 4(mcsnoop=0)は達成。** 2(SSH)と 3(detect-ifs.sh)は確認中。

**④ `ips` モードが net0 を管理NICと決め打ちしていた(自作バグ)**

Linux VM は net0 が管理(vmbr0)だが、**OpenWrt-CE は net0=LAN(vmbr4) / net1=WAN(vmbr1)** で
構成が違う。`ips` は net0 の MAC を無条件に管理NICとして扱っていたため、
OpenWrt については **vmbr4 側の MAC を vmbr0 の近隣キャッシュから探す**という
成立しない検索をしていた。結果「未検出」と表示され、しかも
「`qm terminal` で `ip a` を確認」という**解決しない指示**を出していた。

→ 管理ブリッジ(`bridge=<MGMT_BRIDGE>`)を含む `netN:` 行から MAC を取る形に修正。
  該当 NIC が無い場合は「`vmbr0` に NIC なし」と**事実を表示**するようにした。

**⑤ OpenWrt に `map` / `ds-lite` を入れる経路が無い(サイクル 3 の前提が崩れる)**

④ で明確になった構造上の問題。OpenWrt-CE は

- 管理NICを持たない(vmbr4 と vmbr1 のみ)
- ラボ内に本物のインターネットは無い(INET-SIM は模擬)

ため、**`opkg update && opkg install map ds-lite` が実行できない**。
これらは既定イメージに含まれないので、**MAP-E / DS-Lite の CE 役が成立しない** =
サイクル 3 が始まらない。トラッカー V2 として挙げていた懸念が現実だったことが確定した。

→ `provision.sh` に `OPENWRT_MGMT=1`(既定 0)を追加。OpenWrt に net2 を足して
  管理ブリッジ経由で外に出られるようにする。**既定を 0 にしたのは、会社環境で
  検証機を社内 LAN に足を出すことがポリシー上の問題になりうるため**。
  必要なときだけ明示的に有効化する。

**手順 6: SSH と NIC 名の確認(成功条件 2 / 3)**

```
ssh labadmin@fe80::be24:11ff:fee5:631b%vmbr0 'hostname; ip -br link'
```

4 台すべて SSH 成功。NIC 名の実測値:

| VM | 管理 | ラボ側 |
|---|---|---|
| 9001 ngn-sim | `eth0` | `ens19`(02:ac:…:01) / `ens20`(02:c0:…:01) |
| 9002 vne-inet | `eth0` | `ens19`(02:c0:…:02) / `ens20`(02:1e:…:02) |
| 9003 bras | `eth0` | `ens19`(02:ac:…:03) / `ens20`(02:1e:…:03) |
| 9004 lab-client | `eth0` | `ens19`(02:c1:…:04) |

**設計時に想定した `eth1` / `eth2` とは一致しなかった。** `eth0` + `ens19` / `ens20` という
混在パターンで、MAC 判別方式にしていなかったら全スクリプトが動かなかった。
`detect-ifs.sh` を上の 4 パターンで検証し、いずれも正しく解決することを確認済み
(ラボ側 NIC はこの時点では DOWN。各 setup スクリプトが `ip link set up` する)。

**⑥ 検証クライアント (9004) を設定するスクリプトが存在しなかった**

`setup-ngn.sh` / `setup-map-br.sh` / `setup-aftr.sh` / `setup-inet.sh` / `setup-bras.sh` は
あるが、**クライアント用が無い**。cloud-init は管理NIC (`eth0`) しか設定しないので、
LAN 側 (`ens19`) は **DOWN のまま誰も上げない**。

さらに深刻なのは経路で、既定経路が管理NIC側(家庭 LAN)を向いたままだと
**`run-checks.sh` の通信が CPE を通らずに家庭 LAN へ抜けてしまい、検証にならない**。
「PASS したのに実は CPE を通っていない」という最悪の偽陽性になる。

→ `lab/ipoe/client/setup-client.sh` を新規作成:

- `detect-ifs.sh` に `LAN_IF`(`02:c1:*`)を追加して LAN 側 NIC を解決
- netplan で **MAC 一致**の設定を書く(NIC 名は環境で変わるため)。
  `dhcp4: true` + `accept-ra: true` + `route-metric: 50`
  (cloud-init 管理の `eth0` より小さい metric にして既定経路を CPE 側に寄せる)
- **既定経路を切り替える前に** `curl` / `ping` の不足を導入する
  (切り替え後は外に出られなくなるため、順序が重要)
- 適用後に「既定経路が LAN 側を向いているか」「グローバル IPv6 が付いたか」を自己判定して表示
- `revert` / `show` モードを用意

**副作用として正しい性質**: 既定経路を CPE 側に向けてもクライアントの管理は
**IPv6 リンクローカルで継続できる**(リンクローカルは既定経路を使わない)。
`ips` モードでリンクローカル管理に寄せていたことが、ここで効いた。
- §3.1 のトラッカー B1/B2/B3/B6 を更新、B7/B8 を追加
- 持ち込み方法を `git clone` 前提から **tar アーカイブ展開**に確定(ホストに git が無いため)。
  この方法は会社環境でもそのまま使えるので、runbook の手順 1 に採用する
- **`provision.sh` を修正**:
  - `gunzip` の終了コードを `|| gz_rc=$?` で受け、`0` と `2` を成功として扱う。
    それ以外は原因を表示して中断する
    (`if ! gunzip; then rc=$?` と書くと**否定後の 0 を拾ってしまう**ため使えない。
     最初の修正案がこの罠を踏んでおり、手元テストで発覚した)
  - 展開後に `[ -s "$OPENWRT_IMG" ]` で空ファイルを検出する
  - `qemu-img resize` をダウンロード分岐の**外**に出し、
    `stat -c %s` が 2GiB 未満のときだけ実行する(再実行しても安全な形にした)
  - 判定は `qemu-img info --output=json` の解析ではなく `stat -c %s` を使う
    (raw イメージなのでファイルサイズ = 仮想サイズ。依存を増やさない)

---

### サイクル 2: setup スクリプトを流し、IPv6 が降りるところまで

#### Plan

**目的**: 4 台の Linux に setup スクリプトを流し、CPE(OpenWrt)に **RA 方式 / PD 方式の両方**で
IPv6 が降ることを確認する。クライアントが CPE 経由でグローバル IPv6 を持つところまで。

**先に片付ける前提条件(サイクル 1 で判明した blocker)**:

1. **OpenWrt に `map` / `ds-lite` を入れる経路を作る**(トラッカー V2)
   既存の 9010 に後から管理 NIC を足せる(作り直し不要):
   ```
   qm set 9010 --net2 virtio,bridge=vmbr0
   qm terminal 9010          # コンソールで eth2 を DHCP クライアントとして設定
   # uci で eth2 を wan ゾーンの dhcp インタフェースにしてから
   opkg update && opkg install map ds-lite
   ```
   **設定手順を確定してここに記録する**(会社では人間が同じことをやる)。
   `wan` ゾーンに入れて DHCP サーバを立てないこと(家庭 LAN を汚さないため)。
2. **`setup-client.sh` を実際に流す**(サイクル 1 で新規作成、未実行)

**実行順序**:

| # | VM | コマンド |
|---|---|---|
| 1 | 9001 ngn-sim | `sudo ./ipoe/ngn/setup-ngn.sh pd` |
| 2 | 9002 vne-inet | `sudo ./ipoe/inet/setup-inet.sh` |
| 3 | 9003 bras | `sudo ./ipoe/bras/setup-bras.sh` |
| 4 | 9010 openwrt-ce | uci で WAN 側を DHCPv6-PD に設定 |
| 5 | 9004 lab-client | `sudo ./ipoe/client/setup-client.sh` |

> VNE の `setup-map-br.sh` / `setup-aftr.sh` は**サイクル 3**。
> このサイクルは「IPv6 が降りる」までに絞る。

**成功条件**:

1. `setup-ngn.sh pd` が完走し、`radvd` と `kea-dhcp6-server` が `active (running)`
2. CPE(OpenWrt)の WAN 側に `2001:db8:100a:500::/56` 由来の IPv6 が付く
3. CPE の LAN 側(`br-lan`)に `/64` が切り出され、RA が流れる
4. `lab-client` にグローバル IPv6 が付き、**既定経路が CPE 側を向く**
5. `tcpdump` で **RS → RA** と **Solicit → Advertise → Request → Reply** が観測できる
6. `setup-ngn.sh ra` に切り替えると `2001:db8:1014:300::/64` の RA 方式になる
   (※ VNE 側の `setup-map-br.sh` はまだ流していないので IPv4 は通らない。それは正常)

**このサイクルで閉じるトラッカー項目**: B4, B12, N1〜N8, V2

**やらないこと**: MAP-E / DS-Lite の疎通(サイクル 3)。実機 892FJ(サイクル 4)。
トラブル再現レシピ(サイクル 5)。

**記録すること**:

- 各スクリプトの**所要時間**(勉強会の時間割を確定するため。現在すべて仮案)
- `apt-get` が管理経路で通るか(N1)。通らない場合の回避手順
- OpenWrt の設定コマンド全文(会社で人間が打つのでコピペできる形で)
- **失敗した出力も消さずに残す**

#### Do

**実行環境**: 自宅 LAN 内の Windows PC (Git Bash) から直接 SSH。
サイクル 1 のクラウドセッションと違い、エージェント側で試行錯誤が完結した。

**手順 0: 作業機からホストへの鍵の設置(最初の関門)**

作業機の公開鍵が Proxmox ホストに入っておらず、`deploy.sh` が最初の 1 コマンドで止まった。

```
debug1: Offering public key: /c/Users/<user>/.ssh/id_ed25519 ED25519 SHA256:xKpF...
debug1: Authentications that can continue: publickey,password
root@192.168.11.20: Permission denied (publickey,password).
```

`ssh-copy-id` は root パスワードを対話で要求するため、**人間が 1 回だけ手で実行する**必要がある
(エージェントのシェルは stdin が `/dev/null` なのでプロンプトが即 EOF になり、
`Permission denied, please try again.` が 3 回消費されて終わる)。

```
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@192.168.11.20    # 作業機の Git Bash で
```

**これは 1 回だけ**。ホスト → VM の鍵はサイクル 1 で登録済みなので、以降は無人で回せる。

**手順 1: 配布**

```
./lab/ipoe/deploy.sh
```

所要 **47 秒**(ホスト + Linux VM 4 台)。ホストは `client/` が無い数コミット前の状態だった。

**手順 2〜4: Linux 3 台の setup**(所要時間は apt のダウンロード込み)

| # | VM | コマンド | 所要 |
|---|---|---|---|
| 1 | 9001 ngn-sim | `sudo ./ipoe/ngn/setup-ngn.sh pd` | **37 秒** |
| 2 | 9002 vne-inet | `sudo ./ipoe/inet/setup-inet.sh` | **39 秒** |
| 3 | 9003 bras | `sudo ./ipoe/bras/setup-bras.sh` | **66 秒**(accel-ppp ソースビルド込み) |
| 5 | 9004 lab-client | `sudo ./ipoe/client/setup-client.sh` | **12 秒** |

`setup-ngn.sh ra` への切替は **14 秒**(パッケージ導入済みのため)。

**手順 5: OpenWrt-CE の設定コマンド全文**(会社では人間が `qm terminal 9010` で打つ)

```sh
# ① 管理NICを足す (Proxmox ホスト側。ホットプラグで再起動不要だった)
qm set 9010 --net2 virtio,bridge=vmbr0

# ② OpenWrt 側: 管理インタフェースを wan ゾーンの DHCP クライアントとして作る
#    (DHCP サーバは立てない。家庭/社内 LAN を汚さないため)
uci set network.mgmt=interface
uci set network.mgmt.device='eth2'
uci set network.mgmt.proto='dhcp'
uci commit network
uci add_list firewall.@zone[1].network='mgmt'     # zone[1] = wan
uci commit firewall
/etc/init.d/network reload
/etc/init.d/firewall reload

# ③ ラボの IPv6 を一時的に落としてから opkg (理由は Check ⑤)
ifdown wan6
opkg update
opkg install map ds-lite tcpdump-mini
ifup wan6

# ④ 検証中は管理NICを無効化する (家庭LANへ抜ける偽陽性を防ぐ)
uci set network.mgmt.disabled='1'
uci commit network
/etc/init.d/network reload

# ⑤ PPPoE と IPoE を同居させるための恒久設定 (理由は Check ⑧)
uci set network.wan_dev=device
uci set network.wan_dev.name='eth1'
uci set network.wan_dev.ipv6='1'
uci commit network
```

PPPoE を試すとき(演習 1-A / Phase 0)の追加設定:

```sh
uci set network.wanppp=interface
uci set network.wanppp.proto='pppoe'
uci set network.wanppp.device='eth1'
uci set network.wanppp.username='user1@isp-a.example'
uci set network.wanppp.password='pass1'
uci set network.wanppp.ipv6='0'
uci commit network
uci add_list firewall.@zone[1].network='wanppp'
uci commit firewall
/etc/init.d/firewall reload
ifup wanppp
# 検証が終わったら: uci set network.wanppp.disabled='1'; uci commit network
```

**手順 6: 成功条件の確認 — 6 件すべて達成**

条件 5(`tcpdump -ni ens19` を NGN 側で実行しながら CPE を再取得させた):

```
09:51:04.697688 IP6 fe80::ac:ff:fe00:10 > ff02::2: ICMP6, router solicitation, length 16
09:51:04.698285 IP6 fe80::ac:ff:fe00:1 > fe80::ac:ff:fe00:10: ICMP6, router advertisement, length 56
09:51:04.835607 IP6 fe80::ac:ff:fe00:10.546 > ff02::1:2.547: dhcp6 solicit
09:51:04.838420 IP6 fe80::ac:ff:fe00:1.547 > fe80::ac:ff:fe00:10.546: dhcp6 advertise
09:51:08.441436 IP6 fe80::ac:ff:fe00:10.546 > ff02::1:2.547: dhcp6 request
09:51:08.446007 IP6 fe80::ac:ff:fe00:1.547 > fe80::ac:ff:fe00:10.546: dhcp6 reply
```

条件 2/3(PD 方式):

```
ubus call network.interface.wan6 status → "address": "2001:db8:100a:500::", "mask": 56
br-lan → inet6 2001:db8:100a:500::1/60
ip -6 route show default → default from 2001:db8:100a:500::/56 via fe80::ac:ff:fe00:1 dev eth1
```

条件 4(lab-client):

```
ens19  192.168.1.247/24 metric 50  2001:db8:100a:500::cf0/128  2001:db8:100a:500:c1:ff:fe00:4/64
default via 192.168.1.1 dev ens19 proto dhcp src 192.168.1.247 metric 50
default via fe80::be24:11ff:fe73:e424 dev ens19 proto ra metric 50
```

条件 6(RA 方式に切替):

```
eth1 → inet6 2001:db8:1014:300:ac:ff:fe00:10/64
default from 2001:db8:1014:300::/64 via fe80::ac:ff:fe00:1 dev eth1
br-lan の 2001:db8:100a:500::1/60 は deprecated に落ちた (正しい挙動)
```

**手順 7: PPPoE(N7 / N8)**

```
pppd: Remote message: Authentication succeeded
pppd: PAP authentication succeeded
pppd: local IP address 100.64.1.0 / remote IP address 100.64.0.1
BRAS: ppp0 | user1@isp-a.example | 02:ac:00:00:00:10 | 100.64.1.0 | pppoe | active
```

#### Check

**成功条件は 6 件すべて達成。** ただし**不具合 8 件**と**設計との差異 3 件**が出た。

**① `deploy.sh` が 4 台中 1 台にしか配らず、しかも正常終了していた(致命的・自作バグ)**

「VM 1 台に配布しました」と表示して終了コード 0 で終わる。**気づきにくい**。

```bash
while read -r ll; do
  ssh ... "${PVE_USER}@${PVE_HOST}" "tar cz ... | ssh ... ${CIUSER}@'${ll}' ..."
done <<< "$lls"
```

ループ内の `ssh` に `-n` が無いため、**`ssh` が herestring の stdin を読み尽くし**、
2 行目以降が `read` に渡らずループが 1 回で終わっていた。
`ssh` は「使わなくても stdin を全部吸う」ので、`while read` の中で呼ぶときは
`-n`(または `< /dev/null`)が必須。

**② `setup-bras.sh` が `/etc/ppp` 不在で落ちる**

```
install: cannot create regular file '/etc/ppp/chap-secrets': No such file or directory
```

accel-ppp を**ソースからビルド**しているため `ppp` パッケージが入らず、
`/etc/ppp` が作られない。`set -e` で以降の nft 投入と `accel-ppp` 起動に到達しなかった。

**③ `setup-bras.sh` は再実行すると `apt-get` が全滅する(仕様上の罠・未修正)**

スクリプト自身が `ip route replace default via 203.0.113.80` で**既定経路を奪う**ため、
2 回目以降の実行では冒頭の `apt-get update` がインターネットに出られない。

```
Could not connect to archive.ubuntu.com:80 (185.125.190.81), connection timed out
default via 203.0.113.80 dev ens20            ← metric 0 でこちらが勝つ
default via 192.168.11.65 dev eth0 metric 100
```

今回はパッケージが導入済みだったので実害なく完走した。**初回実行では apt が先に走るので問題ない。**
`setup-client.sh` には「既定経路を切り替える前にコマンドを揃える」という同じ配慮が
コメント付きで入っているが、`setup-bras.sh` には無い。**再実行前提なら要修正**(バックログ 6)。

**④ `qm terminal` はスクリプトから駆動できない**

```
2026/08/10 17:18:10 socat[32530] E tcgetattr(0, 0x5ed366afd0e0): Inappropriate ioctl for device
```

`qm terminal` は socat の PTY 端点を使うので tty を要求し、パイプで流すと即死する。
管理NICを持たない OpenWrt を**自動で設定する手段が無かった**。
→ Proxmox が VM ごとに作る unix ソケット `/var/run/qemu-server/<vmid>.serial0` に
直接 socat する `owrt-console.sh` を新規作成した(Act 参照)。**人間は `qm terminal` のままでよい。**

**⑤ `opkg update` が全滅する(IPv6 の罠。会社でも必ず踏む)**

管理NICで IPv4 の到達性があるのに、すべてのリポジトリで失敗した。

```
Connecting to 2a04:4e42:8c::644:80
Connection error: Connection failed
* opkg_download: ... wget returned 4.
```

原因は **CPE が「グローバル IPv6 アドレスを持っているが、そのアドレスで本物のインターネットに
出られない」状態**にあること。OpenWrt の PD 既定経路は**送信元制限付き**で入る:

```
default from 2001:db8:100a:500::/56 via fe80::ac:ff:fe00:1 dev eth1  metric 512
ip -6 route get 2a04:4e42:8c::644 → RTNETLINK answers: Network unreachable
```

`uclient-fetch`(OpenWrt の `wget`)は AAAA を選んだあと **A へフォールバックしない**。
Ubuntu VM 側の `apt` は同じ状況でも 3ms で ENETUNREACH になって IPv4 に落ちたので通っていた
(**v6 経路が「無い」方が速く失敗して安全**という逆説的な差)。
→ 回避策は `ifdown wan6` してから `opkg`、終わったら `ifup wan6`。

**⑥ OpenWrt の rootfs がサイクル 1 の 2G 拡張どおりになっていない**

```
df -h /  →  /dev/root  98.3M  26.7M  69.6M  28% /
```

サイクル 1 の修正②は**イメージファイル**を 2G に拡張したが、**中のパーティション/ファイルシステムは
98MB のまま**。今回は 70MB 空きがあり `map` / `ds-lite` / `tcpdump-mini` が入ったので実害なし。
サイクル 3 以降で追加パッケージを入れるなら顕在化する(バックログ 7)。

**⑦ `br-lan` に降りるのは `/64` ではなく `/60`(成功条件の記述と差異)**

成功条件 3 は「`/64` が切り出され」と書いたが、実際は OpenWrt 既定の `ip6assign '60'` により
`2001:db8:100a:500::1/60` が付いた。**動作としては正常**で、条件の書き方が実装を知らなかっただけ。

**⑧ PPPoE を上げると IPoE(DHCPv6)が死ぬ — 演習 1-A の前提に関わる重大な発見**

`ifup wanppp` の後、`wan6` が上がらなくなった。

```
"up": false, "pending": true
odhcp6c[6555]: Failed to send RS (Network unreachable)
odhcp6c[6555]: Failed to send SOLICIT message to ff02::1:2 (Network unreachable)
```

`ip -6 addr show dev eth1` が**リンクローカルすら返さない**。原因は netifd が
PPPoE の搬送路にした物理デバイスの IPv6 を無効化すること:

```
cat /proc/sys/net/ipv6/conf/eth1/disable_ipv6 → 1
```

**重要なのは切り分け結果**: この状態でも **RA は eth1 に届いている**。

```
tcpdump -ni eth1 -nn -c 2 "icmp6[icmp6type]==134"
09:03:28.741815 IP6 fe80::ac:ff:fe00:1 > ff02::1: ICMP6, router advertisement, length 88
09:03:49.314972 IP6 fe80::ac:ff:fe00:1 > ff02::1: ICMP6, router advertisement, length 88
```

つまり **N7 の前提(PPPoE 中も NGN の RA が CPE WAN に届く)は成立する**。
届かないのではなく、**CPE 側が受け取れない設定になる**のが問題。
`disable_ipv6` を 0 に戻して `ifup wan6` すると、PPPoE を維持したまま IPv6 が復活した。

**⑨ PPPoE の認証は CHAP ではなく PAP でネゴされた**

トラッカー N8 は「`chap-secrets` 認証が通る」だが、実際にネゴされたのは **PAP**。
`chap-secrets` は accel-ppp の**認証情報ストアのモジュール名**であって認証方式ではない。
`accel-ppp.conf` の `[modules]` に `auth_pap` が含まれ、OpenWrt 側が PAP を選んだ。
**認証は通っており動作は正常**だが、教材で「CHAP で認証される」と書くと誤り。

**⑩ ラボ内 DNS(`2001:db8:cafe::53`)に到達できない(サイクル 3 で効く可能性)**

キャプチャ末尾に NGN からの ICMPv6 到達不能が並んだ。

```
2001:db8:1014:300::1 > 2001:db8:100a:500::1: ICMP6, destination unreachable,
  unreachable address 2001:db8:cafe::53
2001:db8:1014:300::1 > 2001:db8:100a:500::1: ICMP6, destination unreachable,
  unreachable route 2001:418:3ff::1:53
```

> **訂正(レビュー指摘により修正)**: 当初ここに「`2001:db8:cafe::53` は存在しない」
> 「`2001:418:3ff::1:53` は Kea が配っている」と書いたが、**どちらも誤り**だった。

正しくは以下:

- `2001:db8:cafe::53` は **`setup-inet.sh:66` が付与している**
  (`ip -6 addr replace 2001:db8:cafe::53/64 dev "${INET_IF}"`)。
  Kea も radvd も配る DNS はこの値(`kea-dhcp6.conf:66` / `kea-dhcp6-stateless.conf:14` /
  `radvd.conf:22`)で、**ラボ設定に `2001:418:3ff::1:53` は一切出てこない**
- 到達しなかった本当の理由は、NGN の経路 `2001:db8:cafe::/64 via 2001:db8:ff00::2`
  (`setup-ngn.sh:38`)の **next-hop `2001:db8:ff00::2` がまだ存在しない**こと。
  このアドレスを付けるのは `setup-map-br.sh:35` / `setup-aftr.sh:42` で、
  どちらも**サイクル 3 のスクリプト**なので、サイクル 2 時点では VNE の CORE 側が未設定だった
- `2001:418:3ff::1:53` は実網 NTT の DNS。**管理NIC(`mgmt`)を有効にしていた時間帯**に
  家庭 LAN 側から学習したものと推定される(この時点では eth2 が家庭 LAN の RA/DHCPv6 を受けていた)

**つまり「DNS が無い」のではなく「VNE の CORE 側が未設定で経路が繋がっていない」だけ。**
サイクル 3 で `setup-map-br.sh` / `setup-aftr.sh` を流したあとに再確認する(バックログ 8)。

**⑪ ホスト側が数コミット古かった(前提どおり)**

`/root/ipoe-lab/lab/ipoe/` に `client/` も `deploy.sh` も無かった。`deploy.sh` で解消。

#### Act

**修正したファイルと commit**:

| ファイル | 内容 | commit |
|---|---|---|
| `lab/ipoe/deploy.sh` | ループ内 `ssh` に `-n` を追加(不具合①) | `ae873bc` |
| `lab/ipoe/bras/setup-bras.sh` | `install -D` で `/etc/ppp` ごと作る(不具合②) | `f6a6439` |
| `lab/ipoe/proxmox/owrt-console.sh` | **新規**。シリアルの unix ソケットに socat して非対話でコマンドを流す(不具合④) | `270e3ab` |
| `docs/ipoe-lab/build-log.md` | このセクション。トラッカー更新 | `270e3ab` |

**サイクル完了後のレビューで追加修正(`768f305`)**

サイクル 2 の完了後、別モデル(fable)のサブエージェント 2 体に
「`lab/` のスクリプト」と「`docs/` と実装の突き合わせ」をレビューさせた。
**自分では見つけられなかった不具合が 6 件出た**ので、まとめて修正した。

| ファイル | 内容 | 深刻度 |
|---|---|---|
| `proxmox/owrt-console.sh` | 毎回 `OWRT_WAIT` 秒ブロック + 成功時に非ゼロ終了(上記 ⑫) | 高 |
| `deploy.sh` | `\|\| true` が `&&` 連鎖全体にかかり、**tar 失敗を飲み込んで「OK」と表示**していた | 中〜高 |
| `proxmox/provision.sh` | `pvesm status` の空きは `$6` だが `$5`(Used)を読んでいた。満杯ほど「空きが多い」と誤報告 | 中 |
| `proxmox/provision.sh` | 所有タグは作成の最後に付くので、作成途中で失敗した VM を `destroy` が掃除できない。案内どおり操作しても堂々巡りになる | 中 |
| `bras/setup-bras.sh` | `git clone` が無条件で、ビルド失敗後の再実行が `already exists` で毎回止まる | 中 |
| `inet/setup-inet.sh` | `systemctl enable --now X && systemctl restart X` は `set -e` が発火せず、**起動していないのに成功バナー**を出す | 中 |

ドキュメント側では、**この build-log 自身の記述の誤りが 2 件**指摘された(⑩ の訂正、
冒頭の「一度も動かしていません」)。実装と突き合わせるレビューを別に立てる価値があった。

**`owrt-console.sh` の設計メモ**:

- マーカーは**クォート付きで送る**。こうすると端末エコー行は
  `root@OpenWrt:~# echo "__OWRT_DONE_9010__"` になり行頭がマーカーにならないので、
  行頭一致の判定が「コマンドのエコー」ではなく「実際の出力」だけに当たる
- 先頭に Ctrl-C(`\003`)を送ると、前回の失敗で継続プロンプトに落ちていても復帰できる
- 出力は**ファイルに落としてポーリング**し、マーカーを見たら `socat` を明示的に
  `kill` + `wait` する。詳細は下の「⑫」を参照

> **⑫ サイクル 2 の実行中、`owrt-console.sh` 自身が毎回 `OWRT_WAIT` 秒ブロックしていた
> (レビュー指摘により発覚・修正済み)**
>
> 当初の設計は「`awk` がマーカーを見て `exit` すれば `socat` が SIGPIPE で死ぬので、
> 終わった時点で戻る」だったが、**この前提が誤り**だった。`socat` が SIGPIPE を受けるのは
> **次に書き込もうとしたとき**で、コンソールはマーカー以降なにも喋らないため、
> `socat` は `timeout` に達するまで生き残る。
> 結果、**どんなに速いコマンドでも必ず `OWRT_WAIT` 秒かかっていた**(実測 180 秒)。
>
> さらに `set -euo pipefail` の下では、**成功時こそ**パイプラインが 141(SIGPIPE)を返して
> `set -e` が発火するため、`PIPESTATUS` を読む行と時間切れ時のエラーメッセージは
> **到達不能コード**になっていた。
>
> 修正の途中で 2 つ回り道をした(どちらも「速くならない」形で現れるので原因が見えにくい):
>
> - `socat -t <秒>` は EOF 後の待ち時間として期待どおりに効かず、1 秒台で切れて空振りした
> - 送信側をプロセス置換にしても、**残った `sleep` が `ssh` の stderr を握る**ため
>   `ssh` 越しに呼ぶと結局 `ssh` が EOF を待って同じだけかかる
>
> 最終形は「出力をファイルに落とし、0.5 秒間隔でマーカーを探し、見えたら `socat` を
> `kill` + `wait` する」。**180 秒 → 1.96 秒**になった。
>
> なお当初この Act に「多重クォートで詰まった」と書いたが、**実際の原因はこの WAIT ブロック**
> だった可能性が高い(ファイル渡しへの変更と `OWRT_WAIT` 短縮を同時に行ったため切り分けできていない)。
> ただし多重クォート(`ssh` → `bash` → `socat` → `ash`)が壊れやすいのは事実なので、
> **コマンドはファイルに書いて stdin で渡す**運用は維持する。

**ラボの引き継ぎ状態**(サイクル 3 の開始点):

- NGN = **PD モード**(`2001:db8:100a:500::/56`、期待値 共有IPv4=198.51.100.10 / PSID=5)
- CPE = PD 受領済み、`map` / `ds-lite` / `tcpdump-mini` 導入済み
- CPE の管理NIC(`mgmt`)と PPPoE(`wanppp`)は **`disabled='1'` で停止**。
  必要なときだけ `uci set network.<name>.disabled='0'; uci commit network; /etc/init.d/network reload`
- Kea のリースは ra→pd 切替時に §4 の手順でクリア済み

**ドキュメント側の修正**:

- 成功条件 3 の「`/64`」は `ip6assign` 次第であることを Check ⑦ に明記
- N8 の「CHAP」は実際には PAP であることを Check ⑨ に明記
- §3 のトラッカー B4 / B12 / N1〜N8 / V2 を更新
- §5 のバックログに 6(`setup-bras.sh` の再実行耐性)/ 7(OpenWrt の rootfs 拡張)/
  8(ラボ内 IPv6 DNS)を追加

---

### サイクル 3: MAP-E / DS-Lite で IPv4 が通り、`run-checks.sh` が PASS するまで

#### Plan

**目的**: CPE 配下のクライアントから **IPv4 over IPv6 で IPv4 が通る**ことを確認する。
MAP-E と DS-Lite の両方式について、`run-checks.sh` を PASS させる。

**前提(サイクル 2 で確保済み)**:

| 項目 | 状態 |
|---|---|
| NGN-SIM | **PD モード**(`2001:db8:100a:500::/56` を委譲) |
| CPE (OpenWrt) | PD 受領済み。`map` / `ds-lite` / `tcpdump-mini` 導入済み |
| lab-client | 既定経路が CPE 側。グローバル IPv6 あり |
| BRAS / INET-SIM | 起動済み |

**PD モードなので、MAP-E の期待値は既定値**([build.md](build.md) §3 の表):

| 項目 | 期待値 |
|---|---|
| ユーザプレフィックス | `2001:db8:100a:500::/56` |
| 共有 IPv4 | `198.51.100.10` |
| PSID | 5 |
| CE の MAP アドレス | `2001:db8:100a:500:0:c633:640a:5` |
| BR アドレス | `2001:db8:9999::1` |
| 利用可能ポート | 16 × 15 ブロック = 240(PSID=5 なら 4176-4191 等) |

**成功条件**:

1. `setup-map-br.sh` が完走し、`ip -6 tunnel show` に `map0` が出る(V1)
2. CPE の MAP-E 自動計算値が上の表と一致する(V3)。**一致しない場合は値をそのまま記録し、
   どちらが正しいかを判定する**(CPE の実装差か、設計値の誤りか)
3. lab-client から `run-checks.sh` が **FAIL=0** で終わる(V6)
4. MTU 実測が **1460**(encaplimit ありなら 1452)になる(V7)
5. DS-Lite に切り替えても IPv4 が通る(V5)
6. **ラボ内 IPv6 DNS(`2001:db8:cafe::53`)への到達が回復する**(バックログ 8)。
   サイクル 2 で不達だったのは VNE の CORE 側が未設定だったためという仮説の検証

**やらないこと**: 実機 892FJ(サイクル 4)。CML の Cat8000v をラボに繋ぐ(サイクル 4)。
トラブル再現レシピ(サイクル 5)。ポート数 240 の実測(V4 はサイクル 5 の R3 とまとめる)。

**記録すること**:

- CPE が自動計算した値の**全文**(期待値表との照合に使う)
- 各方式の切替所要時間(勉強会の時間割用)
- **失敗した出力も消さずに残す**

#### Do

**結果: MAP-E / DS-Lite の両方式で `run-checks.sh` が PASS=10 FAIL=0。**

**手順 1: MAP-E BR の起動(9002)** — 所要 **4 秒**

```
sudo ./ipoe/vne/setup-map-br.sh
[VNE] MAP-E BR 起動: BR=2001:db8:9999::1, CE=2001:db8:100a:500:0:c633:640a:5, 共有IPv4=198.51.100.10

map0: ip/ipv6 remote 2001:db8:100a:500:0:c633:640a:5 local 2001:db8:9999::1 encaplimit none
198.51.100.10 dev map0 scope link
ens19  UP  2001:db8:ff00::2/64        ← CORE 側。サイクル 2 で不達だった next-hop がここで出現
```

**手順 2: CPE に MAP-E を設定**([build.md](build.md) §5 の値をそのまま投入)

```sh
uci set network.wanmap=interface
uci set network.wanmap.proto='map'
uci set network.wanmap.maptype='map-e'
uci set network.wanmap.peeraddr='2001:db8:9999::1'
uci set network.wanmap.ipaddr='198.51.100.0'
uci set network.wanmap.ip4prefixlen='24'
uci set network.wanmap.ip6prefix='2001:db8:1000::'
uci set network.wanmap.ip6prefixlen='40'
uci set network.wanmap.ealen='16'
uci set network.wanmap.psidlen='8'
uci set network.wanmap.offset='4'
uci set network.wanmap.encaplimit='ignore'
uci set network.wanmap.mtu='1460'
uci set network.wanmap.tunlink='wan6'
uci commit network
uci add_list firewall.@zone[1].network='wanmap'
uci commit firewall
/etc/init.d/network reload && /etc/init.d/firewall reload
```

**手順 3: 期待値の照合(V3) — 全項目一致**

| 項目 | [build.md](build.md) §3 の期待値 | CPE の自動計算値 |
|---|---|---|
| 共有 IPv4 | `198.51.100.10` | `198.51.100.10/32` ✅ |
| PSID(先頭ポートブロック) | `4176-4191` | `4176-4191` ✅ |
| CE の MAP アドレス | `2001:db8:100a:500:0:c633:640a:5` | 同一(トンネル端点) ✅ |
| MTU | 1460 | 1460 ✅ |

```
map-wanmap@eth1: <POINTOPOINT,NOARP,UP,LOWER_UP> mtu 1460
    inet 198.51.100.10/32 scope global map-wanmap
    link/tunnel6 2001:0db8:100a:0500:0000:c633:640a:0005 peer 2001:0db8:9999::1

nft: snat ip to 198.51.100.10:4176-4191   / :8272-8287 / :12368-12383 / :16464-16479 ...
```

**手順 4: `run-checks.sh`(MAP-E) — 最終 PASS=10 FAIL=0**

```
PASS: IPv4 ping / IPv6 ping / A 解決 / AAAA 解決 / HTTP over IPv4 / HTTP over IPv6
PASS: TCP 5MB over IPv4 / TCP 5MB over IPv6 / IPv4 fragment / IPv6 fragment
src: 198.51.100.10                          ← 共有 IPv4 で出ている = MAP-E 成立
INFO: IPv4 パス MTU >= 1460 (payload 1432 通過)   ← V7 期待値どおり
=== 結果: PASS=10 FAIL=0 ===
```

**手順 5: DS-Lite への切替** — CPE 側は 1 行ずつ、AFTR は既定値のまま

```sh
# CPE
uci set network.wanmap.disabled='1'
uci set network.wandsl=interface
uci set network.wandsl.proto='dslite'
uci set network.wandsl.peeraddr='2001:db8:8888::1'
uci set network.wandsl.mtu='1460'
uci set network.wandsl.tunlink='wan6'
uci commit network
uci add_list firewall.@zone[1].network='wandsl'
uci commit firewall
/etc/init.d/network restart

# VNE (CE_WAN6 の既定値 = CPE の br-lan アドレスで一致したため引数不要だった)
sudo ./ipoe/vne/setup-aftr.sh
```

```
ds-wandsl@eth1: mtu 1460
    inet 192.0.0.2 peer 192.0.0.1/32        ← RFC 6333 どおり (B4=192.0.0.2 / AFTR=192.0.0.1)
[VNE] DS-Lite AFTR 起動: AFTR=2001:db8:8888::1, B4=2001:db8:100a:500::1
=== 結果: PASS=10 FAIL=0 ===
```

**MAP-E に復帰**(サイクル 4 の開始点として)。`uci set network.wandsl.disabled='1'` +
`uci set network.wanmap.disabled='0'` + `/etc/init.d/network restart` で戻る。

#### Check

**成功条件は 6 件すべて達成。** ただし **DNS が通るまでに 3 つの原因が重なっていた**。
どれも「ping は通るのに名前解決だけ死ぬ」という同じ症状に化けるので、切り分け順序ごと残す。

**① CPE 自身が発信する UDP が `Network unreachable` になる(OpenWrt の `sourcefilter`)**

`run-checks.sh` の DNS 2 項目だけが FAIL。CPE から調べると:

```
ping -c2 2001:db8:cafe::53          → 0% packet loss     (通る!)
nslookup www.lab.example 2001:db8:cafe::53 → connection timed out
ip -6 route get 2001:db8:cafe::53   → RTNETLINK answers: Network unreachable
ip -6 route get 2001:db8:cafe::53 from 2001:db8:100a:500::1 → 成功
```

原因は OpenWrt が PD 受領時に入れる**送信元制限付きの既定経路**:

```
default from 2001:db8:100a:500::/56 via fe80::ac:ff:fe00:1 dev eth1  metric 512
```

`ping` は通るのに UDP は通らない。**送信元未定(`::`)のままの経路探索が失敗する**ためで、
ICMP ソケットとは経路選択の経路が違う。これが「疎通はあるのに DNS だけ死ぬ」の正体。

→ `uci set network.wan6.sourcefilter='0'` で既定経路から `from` が外れ、送信されるようになった。

```
default via fe80::ac:ff:fe00:1 dev eth1  metric 512
ip -6 route get 2001:db8:cafe::53 → src 2001:db8:100a:500:0:c633:640a:5
tcpdump -ni eth1: 2001:db8:100a:500:0:c633:640a:5.59351 > 2001:db8:cafe::53.53: A? www.lab.example.
```

**② INET-SIM の dnsmasq が CORE 側から来たクエリを黙って捨てていた(設計バグ)**

送信されるようになっても応答が返らない。NGN(9001)で見ると**転送はできている**:

```
ens19 In  IP6 2001:db8:100a:500:0:c633:640a:5.36196 > 2001:db8:cafe::53.53: A? www.lab.example.
ens20 Out IP6 2001:db8:100a:500:0:c633:640a:5.36196 > 2001:db8:cafe::53.53: A? www.lab.example.
(応答なし。再送も同じ)
```

VNE(9002)で `-i any` で見ると **`ens19 In` で到達しているのに応答が 1 パケットも出ない**。
`nft list ruleset` は空でファイアウォールではない。9002 自身からは引ける。

原因は `setup-inet.sh` が書く dnsmasq 設定:

```
interface=ens20      ← INET 側だけ
bind-interfaces
```

**CPE からの DNS クエリは NGN 経由なので CORE 側(`ens19`)に着く。**
dnsmasq は listen 対象外のインタフェースに届いたクエリを**黙って捨てる**(応答を返さない)。
さらに厄介なことに、**INET 側で `tcpdump` してもクエリが見えない**(CORE 側に来ているため)ので、
「どこにも届いていない」ように見える。

→ `interface=${CORE_IF}` を追加する形に `setup-inet.sh` を修正。追加した瞬間に解決した。

**③ CPE の DNS リバインド保護がラボの応答を破棄していた(OpenWrt の既定)**

②を直すと CPE 自身は引けるようになったが、**クライアントからはまだ失敗**する。
ただし所要が **7937ms → 37ms** と即失敗に変わっており、性質が変わっている。CPE のログ:

```
daemon.warn dnsmasq[1]: possible DNS-rebind attack detected: www.lab.example
```

ラボは**ドキュメント用アドレス**(`2001:db8::/32` / `203.0.113.0/24`)を使っている。
OpenWrt の `rebind_protection`(既定 1)は、上流が「private/予約レンジ」を返す応答を
**リバインド攻撃とみなして破棄**する。**ラボがドキュメントアドレスを使う限り必ず踏む。**

→ ラボのドメインだけ例外にする(保護は残す):

```sh
uci add_list dhcp.@dnsmasq[0].rebind_domain='lab.example'
uci commit dhcp && /etc/init.d/dnsmasq restart
```

**④ DS-Lite で AFTR の NAT が効かない(VNE と INET-SIM の同居による artifact)**

DS-Lite でも PASS=10 だが、INET-SIM から見た送信元が期待と違う:

| 方式 | INET-SIM から見た送信元 |
|---|---|
| MAP-E | `198.51.100.10`(共有 IPv4。正しい) |
| DS-Lite | **`192.168.1.247`**(クライアントの私設アドレスがそのまま) |

`setup-aftr.sh` の masquerade は `oifname "${INET_IF}"` 条件だが、
**VNE と INET-SIM が同一 VM(9002)** なので宛先 `203.0.113.80` はローカル配送になり、
`ens20` から出ていかない = ルールが当たらない。

**本番の 5 VM 構成(INET-SIM を分ける)では発生しない**プロトタイプ固有の現象。
ただし **「DS-Lite は網側 NAT だからポート開放できない」という教材の中心的な論点が、
この構成では実演できない**(R4 の再現に影響する)。バックログ 9 へ。

**⑤ `ip -d link` と `timeout` が BusyBox に無い**

OpenWrt 側で `ip -d link show` は使えず(usage が出る)、`timeout` も未実装。
CPE 上で確認するときは `ip link show` + `tcpdump -c N` を使う。サイクル 2 でも同じ罠を踏んだ。

#### Act

**修正したファイル**:

| ファイル | 内容 |
|---|---|
| `lab/ipoe/inet/setup-inet.sh` | dnsmasq の listen に **CORE 側インタフェースを追加**(不具合②)。理由をコメントで明記 |
| `docs/ipoe-lab/build.md` | CPE 必須設定に `sourcefilter='0'` と `rebind_domain` を追加(不具合①③) |
| `docs/ipoe-lab/build-log.md` | このセクション。トラッカー V1〜V7 更新、バックログ 9 追加 |

**ラボの引き継ぎ状態**(サイクル 4 の開始点):

- CPE = **MAP-E 有効**(`198.51.100.10/32`)。DS-Lite は `wandsl.disabled='1'` で待機
- NGN = PD モード / VNE = BR と AFTR の両方が起動済み(同時起動可)
- CPE に恒久的に入れた設定: `wan6.sourcefilter='0'` / `rebind_domain='lab.example'` /
  `wan_dev(eth1).ipv6='1'`(サイクル 2)

#### 3.3-A. INET-SIM を分離して DS-Lite の網側 NAT を成立させた(バックログ 9 の解消)

**runbook で会社に「VNE と INET-SIM を分けろ」と指示した以上、その構成を自分で
一度も動かしていないのはまずい**ので、自宅ラボも分離構成にして実測した。

`provision.sh` に **`SPLIT_INET=1`** を追加(既定 0 = 従来どおり 9002 に同居)。
`SPLIT_INET=1` で **9005 `inet-sim`**(1vCPU / 1GB、`02:1E:00:00:00:05` / vmbr3)が作られる。

```
SPLIT_INET=1 STORAGE=local-lvm ./provision.sh     # 既存 5 台はスキップされ 9005 だけ作られる (1分52秒)
```

**結果 — 出口アドレスが期待どおりに変わった**:

| 構成 | DS-Lite の出口 IPv4 | 意味 |
|---|---|---|
| 同居(9002 に相乗り) | `192.168.1.247` | **クライアントの私設アドレスがそのまま**。網側 NAT が効いていない |
| **分離(9005)** | **`203.0.113.1`** | **AFTR の INET 側アドレス。網側 NAT が成立** |

```
EXPECT_SRC4=203.0.113.1 ./ipoe/tests/run-checks.sh
INFO: 出口 IPv4 = 203.0.113.1 / 出口 IPv6 = 2001:db8:100a:500::cf0
PASS: 出口 IPv4 が 203.0.113.1
=== 結果: PASS=11 FAIL=0 ===
```

MAP-E も分離構成で回帰確認済み(`EXPECT_SRC4=198.51.100.10` で `PASS=11 FAIL=0`)。

**これで R4(DS-Lite でポート開放不可)が実演できる状態になった。**
同居構成のままだと、R4 は「開放できてしまう」という**逆の結果**になる。

**分離作業で踏んだ罠: 同一サブネットのプライマリアドレスを消すとセカンダリも道連れになる**

9002 から INET-SIM の役割を外すため `ip addr del 203.0.113.80/24` したところ、
**同じ /24 の `203.0.113.53` と `203.0.113.1`(VNE 自身のアドレス)まで消えた**。
Linux は `promote_secondaries` が 0 のとき、プライマリ削除でセカンダリを破棄する。

```
ens20  UP  2001:db8:cafe::1/64 fe80::1e:ff:fe00:2/64      ← 203.0.113.1 が消えている
```

→ `setup-map-br.sh` / `setup-aftr.sh` を再実行して復旧(冪等なので一発で戻る)。
**会社で「INET-SIM を別 VM に移す」作業をするときは、移す側のアドレスを消した直後に
VNE のスクリプトを再実行してください。**

**新しく足した `stop` サブコマンドもここで検証した**:

```
sudo ./ipoe/vne/setup-map-br.sh stop
[VNE] MAP-E BR を停止しました (トンネル・共有IPv4の復路を削除)
ip -6 tunnel show | grep -c map0 → 0
```

---

### サイクル 5: トラブル再現レシピ R1/R3/R4/R5 を実走して再現条件を確定

#### Plan

**目的**: [test-matrix.md](test-matrix.md) §4 のレシピが**実際に再現するか**を確かめ、
**再現しない場合はその条件**を記録する。勉強会でレシピを配る前に、
「書いてあるとおりにやったのに症状が出ない」を潰しておく。

**前提**: サイクル 3 完了状態(分離構成 / MAP-E 有効 / `run-checks.sh` PASS=11)。

**成功条件**(「再現すること」ではなく **「再現条件が確定すること」**):

1. **R4**(DS-Lite ポート開放不可): 分離構成で**ポートフォワードが効かない**ことを確認。
   バックログ 9 の解消後なので今度こそ成立するはず(R4a)
2. **R3**(MAP-E ポート制限): 240 ポートの飛び飛び構造を実測。
   **BR は制限を強制しない**ので、CE 実装だけで症状が出るか / `map-enforce` が必要かを確定(R3a、V4)
3. **R5**(MTU ブラックホール): `break-pmtu` で **TCP 5MB だけ FAIL** になるか。
   **OpenWrt 既定の `mtu_fix`(MSS clamp)で潰されて再現しない可能性**が懸念事項(R5a)
4. **R1**(RA 方式に PD 設定): NGN を `ra` にして CPE を PD 要求のままにしたときの症状(R1a)
5. 各レシピの**戻し方が実際に効く**こと(残すと次の検証を汚すため)

**やらないこと**: R2(PPPoE セッション残留)は BRAS の LCP タイムアウト 60 秒待ちが要るので今回は対象外。
R6 / D1 も次回。実機 892FJ(サイクル 4)。

#### Do

**R1・R3・R4・R5 の 4 件を実走。すべて「レシピのままでは想定と違う」ことが判明した。**

**R3: MAP-E ポート制限 — 240 ではなく 16 で詰まる**

まず CPE が持つポート集合を実測。**期待どおり 15 ブロック × 16 = 240 ポート**:

```
4176-4191  8272-8287  12368-12383  16464-16479  20560-20575  24656-24671
28752-28767  32848-32863  36944-36959  41040-41055  45136-45151  49232-49247
53328-53343  57424-57439  61520-61535           ← 間隔 4096、ブロック数 15
```

`a=0`(ポート 0-4095)のブロックが**構造的に存在しない**。psid-offset=4 の効果で、
**well-known ポートは原理的に使えない**。RFC 7597 の計算どおり
(`(a << 12) | (PSID << 4) | j`、PSID=5)。

次に配下から同時接続を張って上限を測った:

| 同時接続数 | HTTP 200 が返った数 |
|---|---|
| 300 本 | **16** |
| 100 本 | **16** |

**240 ではなく 16 で頭打ち。**原因は nft のカウンタで確定した:

```
nat 1 (4176-4191):   counter packets 3462 bytes 207720   ← 全部ここを通る
nat 4 (8272-8287):   counter packets 0 bytes 0           ← 一度も使われない
nat 7 (12368-12383): counter packets 0 bytes 0           ← 同上
```

**R4: DS-Lite でポート開放不可 — 再現した**

CPE にポートフォワード(`tcp dport 8080 → 192.168.1.247:8000`)を設定。
クライアントで `python3 -m http.server 8000` を起動。

対照実験(**これが無いと結果が無意味になる**):

```
CPE(LAN 側)から  wget http://192.168.1.247:8000/  →  <!DOCTYPE HTML>   ← 待受は生きている
クライアントの外向き                              →  src: 203.0.113.1  ← DS-Lite も生きている
```

その状態で INET-SIM から着信を試みる:

```
203.0.113.1:8080     rc=7   (接続拒否。AFTR の共有アドレスはポート転送しない)
192.0.0.2:8080       rc=28  (B4 アドレスは経路上存在しない)
192.168.1.247:8000   rc=28  (私設アドレス)
```

**CPE の設定は入っていて LAN 側では機能しているのに、インターネット側から到達できる
アドレスが存在しない。** DNAT ルールの宛先が `ip daddr 192.0.0.2`(RFC 6333 の B4 アドレス)
になっている時点で、そもそも公開できる先が無いことが読み取れる。

**R5: MTU ブラックホール — 前提を 2 つ満たさないと再現しない**

`setup-aftr.sh break-pmtu` を投入しただけでは **`TCP 5MB` が PASS のまま**で再現しなかった。
2 つの前提を足して初めて `FAIL: TCP 5MB over IPv4` になった。

| 手順 | 結果 |
|---|---|
| `break-pmtu` のみ | `PASS=11 FAIL=0`(**再現せず**) |
| + `mtu_fix='0'`(MSS clamp を切る) | `PASS=11 FAIL=0`(**まだ再現せず**) |
| + 両端で `ip route flush cache` | **`FAIL: TCP 5MB over IPv4` / 他は全 PASS** ← 再現 |

#### Check

**① R3 は 240 ではなく 16 で詰まる(OpenWrt の nft ルール生成の問題)**

nftables の `snat` は**終端判定**で、マッチしたらそこで評価が止まる。
OpenWrt の map プロトコルが生成する 15 本の snat ルールは
**すべて同じマッチ条件**(`meta nfproto ipv4 meta l4proto tcp oifname "map-wanmap"`)なので、
**先頭ルールだけが永久に使われ、残り 14 ブロックは死んでいる**。

カウンタが 0 のまま動かないことで確定した。先頭ブロックの 16 ポートを使い切ると
SNAT のポート割当に失敗し、新規接続が落ちる(実測 284/300 が接続不可)。

**教材への影響が大きい**:

- test-matrix R3 の「240 を超える**滞留する**同時セッションを張る」は、
  **OpenWrt が CE のときは誤り**。16 本で再現する
- 同レシピの「ラボの BR はポート制限を**強制しない**ため症状が出ないことがある」も外れ。
  **CE 側が先に詰まる**ので `map-enforce` を入れるまでもなかった
- 逆に言うと **OpenWrt の MAP-E は実効 16 ポート**。実網の v6プラス(240)や
  OCN バーチャルコネクト(1008)の感覚で使うと、CE の実装差を過小評価する

**これが OpenWrt 固有なのか、設定で直るのかは未確認。**
実機 CPE(IOS XE 等)では NAT エンジンがポート集合を正しく扱うはずなので、
**ラボ固有の癖として扱い、実機検証時に必ず数え直すこと**(バックログ 10)。

**⓪ R1 の症状は「IPv6 が付かない」ではない。WAN は正常で LAN 側だけが死ぬ**

NGN を `ra` にしたまま CPE を PD 要求(`proto dhcpv6`)で残したときの実測:

```
wan6        "up": true / eth1 に 2001:db8:1014:300:ac:ff:fe00:10/64   ← RA は正常に効いている
br-lan      2001:db8:100a:500::1/60  scope global deprecated          ← 旧 PD が失効中。新規委譲なし
map-wanmap  アドレスなし                                              ← MAP-E が上がらない
```

**WAN 側の IPv6 は普通に付く。**死ぬのは委譲プレフィックス(= LAN 側)と MAP-E。
レシピの「IPv6 アドレスが付かない」という書き方だと WAN を見に行って混乱する。

さらに切り分けの記述も実態と違った。NGN 側でキャプチャすると:

```
router advertisement (length 88)
dhcp6 solicit
dhcp6 advertise        ← 応答は返っている (IA_PD が入っていないだけ)
（Request が続かない）
```

**「PD 応答がない」のではなく、DHCPv6 のやり取り自体は成立していて IA_PD だけが無い。**
パケットは流れているので、`tcpdump` で「udp port 547 が見える」ことを確認して
「DHCPv6 は動いている」と誤読しやすい。**見るべきは Advertise の中身**。

**戻すときの注意**: `ifdown wan6 && ifup wan6` では戻らなかった。
`/etc/init.d/network restart` が必要(`map-wanmap` を作り直す必要があるため)。
これを知らないと「pd に戻したのに MAP-E が上がらない」で二次遭難する。

**② R4 は「待受を起動できているか」の対照実験が必須(危うく誤判定するところだった)**

最初の試行では `nohup python3 -m http.server &` を**多段 ssh 越しに**投げたため、
**待受が起動していなかった**。それに気づかず「着信しない = R4 再現」と読むところだった。
**着信しない理由が「仕様どおり」なのか「そもそも受け側がいない」なのかは、
外から見ると区別がつかない。**

→ `systemd-run --unit=r4test --collect` で常駐させ、
  **LAN 内から到達できることを先に示してから**外からの試行を行う手順にした。
  レシピにこの対照実験を必須手順として書く。

**③ R5 は既定の OpenWrt では再現しない(トラッカー R5a の懸念が的中)**

2 つの前提が要る:

1. **`mtu_fix`(MSS clamp)を切る**。OpenWrt は wan ゾーンの ingress/egress 両方で
   `tcp option maxseg size set rt mtu` を入れており、**TCP は最初からトンネル MTU を
   超えない**。超えないので Frag-Needed が発生せず、それを落としても何も起きない
2. **PMTU キャッシュをフラッシュする**。一度成功した経路には PMTU 1460 が学習済みで、
   やはり Frag-Needed が不要になる。**「さっきまで再現していたのに再現しなくなる」**
   という形で出るので、演習中にいちばん混乱する

**逆に言えば、`mtu_fix` が MTU ブラックホールの実務的な対処そのもの**である。
演習では「まず既定(clamp あり)で症状が出ないことを見せ、clamp を切って再現させ、
clamp を戻して直る」と回すと、対処法まで込みで体験できる。

#### Act

**⑥ 方式・モードを何度も切り替えた後、IPv6 だけが不安定になる → 真因は ULA へのフォールバック(解決済み)**

サイクル 5 で ra⇄pd と MAP-E⇄DS-Lite を何度も往復させた結果、
復旧後の `run-checks.sh` が **7 → 8 → 11** と回を追って PASS が増える状態になった。
最終的には `PASS=11 FAIL=0` に収束するが、**1 回目の結果は信用できない**。

落ちるのは毎回 IPv6 側(`IPv6 ping` / `HTTP over IPv6` / `TCP 5MB over IPv6` /
`IPv6 fragment`)で、IPv4(MAP-E)は初回から安定して PASS する。

判明している範囲:

- クライアント → CPE のリンクローカルは初回から疎通する
- CPE → `2001:db8:cafe::80` も初回から疎通する
- NGN の復路は Kea のフックが `via fe80::ac:ff:fe00:10` で正しく入っている(**N3 確定**)
- CPE の fw4 は `accept_to_wan` があり転送は許可されている
- クライアントの IPv6 は SLAAC 由来の 1 本のみ(DHCPv6 の `::cf0/128` は消えている)

近隣探索の初回タイムアウトを疑って `run-checks.sh` に**判定に数えないウォームアップ ping**を
入れたが、**それだけでは解消しなかった**。原因未特定。

**真因(切り分け後に判明)**: クライアントの IPv6 送信元が **OpenWrt 既定の ULA** に
フォールバックしていた。

```
ip -6 route get 2001:db8:cafe::80  →  src fdf9:4297:f9bc::cf0        ← ULA が選ばれている

2001:db8:100a:500:c1:ff:fe00:4/64  deprecated  preferred_lft 0sec    ← GUA が失効
fdf9:4297:f9bc::cf0/128                        preferred_lft 42105sec ← ULA は生きている
```

モードを往復させた影響で CPE の odhcpd が **preferred lifetime 0 の RA**(= 全アドレスを
deprecate する広報)を出し続けており、GUA が deprecated に落ちた。すると RFC 6724 の
送信元選択が**次に優先度の高い ULA** を選ぶ。**ラボ内に ULA の復路は存在しない**ので、
パケットは出ていくが返ってこない = 全 IPv6 項目がタイムアウトする。

**IPv4 が無傷だったのが最大のミスリード**だった。IPv4 は MAP-E トンネル経由で
送信元選択が絡まない(常に共有 IPv4)ため、初回から安定して PASS していた。
「IPv4 は通るのに IPv6 だけ死ぬ」という形になり、経路や NAT を疑って時間を溶かした。

手動 `ping -c1 -W10` が 2.8ms で成功する一方 `run-checks.sh` の
`ping -c2 -W2` が 100% ロスになる、という不可解な差も**同じ原因**
(送信元が状況で切り替わっていた)。近隣探索を疑ったのは誤りだった。

**対処(恒久)**: CPE で **ULA を無効化**する。実網の NGN も ULA は配らないので、
ラボを実網に近づける方向でもある。

```sh
uci set network.globals.ula_prefix=''
uci commit network
```

odhcpd の状態が壊れていたため、設定後に **CPE を再起動**して初めてクリーンになった
(`ifup wan6` や `odhcpd restart` では戻らなかった)。再起動後は
**3 回連続で `PASS=11 FAIL=0`**。

**再発防止**: `run-checks.sh` に「IPv6 の送信元が ULA なら警告する」判定を追加した。
これが最初から入っていれば一発で分かった。`setup-client.sh` も
**グローバル IPv6 が preferred になるまで待つ**ように修正(以前は IPv4 だけ待って
先に抜け、自己判定が誤検知していた)。

**教材としての価値**: これは付録 A.2「マルチプレフィックス問題」そのものである。
「複数のプレフィックスが同時に存在すると、送信元選択の結果で通ったり通らなかったりする」
という現象を、ラボで**意図せず再現してしまった**形。演習に組み込む価値がある。

**ラボの状態**: すべて元に戻した(`break-pmtu` → `restore-pmtu`、`mtu_fix` → `1`、
ポートフォワード削除、待受停止、MAP-E に復帰)。復帰後 `PASS=11 FAIL=0` を確認済み。

**修正したファイル**: [test-matrix.md](test-matrix.md) の R3 / R4 / R5 に再現条件を追記。

**残り**: なし(R1/R2/R3/R4/R5/R6/D1 をすべて実走)。

---

#### 3.4-A. R6 / R2 / D1 の実走結果

**R6(DNS フォールバック遅延)— 症状が出るかはクライアント実装次第(R6a 確定)**

`setup-inet.sh break-v6`(AAAA は返るが v6 の HTTP を落とす)を投入して実測:

| クライアント | 平常時 | break-v6 時 |
|---|---|---|
| `curl`(Happy Eyeballs / RFC 8305) | 8ms | **207ms** |
| `wget` | — | **15 秒でタイムアウト**(完全にハング) |

**トラッカー R6a の懸念が的中した。** `curl` では ~200ms でフォールバックしてしまい、
「数秒〜数十秒待たされる」という症状にならない。一方 `wget` は Happy Eyeballs を
持たないので完全に固まる。

**演習では必ず両方を叩かせること。**「同じ障害でもクライアントによって症状が
まったく違う」ことが体験できる。お客様から「A さんの PC では遅いが B さんは普通」と
言われたときの引き出しになる。

**R2(PPPoE セッション残留)— 完全再現(R2a)**

`killall -9 pppd`(電源断相当。正常切断させない)で切断し、即座に再接続を試みた。

```
BRAS 側:
 ppp0 | user1@isp-a.example | 02:ac:00:00:00:10 | 100.64.1.1 | pppoe | active | 00:01:11   ← 残留
      |                     | 02:ac:00:00:00:10 |            | pppoe | start  | 00:00:01   ← 新規が進めない
CPE 側: (再接続できず = 期待どおり)
```

**LCP エコー(20 秒 × 3)で約 60 秒後に残留が刈られ、新規セッションが確立した。**
このとき払い出された IPv4 は **`100.64.1.2`**(元の `.1` ではない)。
**切替後に固定 IP 前提の設定が壊れる**という実務上の落とし穴がここに現れる。

**D1(Kea の DUID-LL 限定)— OpenWrt では再現しない(設計の前提が誤り)**

DROP クラスを有効化しても **CPE は普通に PD を取得した**。キャプチャで DUID を確認:

```
client-ID hwaddr type 1 02ac00000010            ← OpenWrt = DUID-LL (0x0003)
server-ID hwaddr/time type 1 time 839664689 ... ← Kea     = DUID-LLT
```

`kea-dhcp6.conf` のコメントは「OpenWrt 等は既定で **DUID-LLT** を送るため、
最初の疎通確認で切り分けが難しくなる」と書いているが、**実測では DUID-LL を送っていた**。
DROP クラスは「DUID-LL **でない**ものを落とす」ので、OpenWrt は素通りする。

→ **OpenWrt を CE にしている限り D1 は罠として機能しない。**
   実網の癖を体験させたいなら (a) DUID-LLT を送る CPE(市販ルータや Windows)を使う、
   または (b) テストを反転させて DUID-LL を落とす、のどちらかが必要。

---

#### 3.4-B. IPv6 が断続的に死んでいた真犯人: `setup-ngn.sh` が Kea フックの復路を上書きしていた

**サイクル 3 以降ずっと悩まされていた「IPv4 は通るのに IPv6 だけ死ぬ」の真因。**
バックログ 11 で ULA を疑って一度解決したと判断したが、**それは別の問題**であり、
本命はこちらだった。

`setup-ngn.sh` は毎回これを実行していた:

```
ip -6 route replace 2001:db8:100a:500::/56 dev "${ACCESS_IF}"     # on-link
```

一方、PD 方式の**正しい復路**は Kea のフック(`kea-pd-route.sh`)が入れる:

```
2001:db8:100a:500::/56 via fe80::ac:ff:fe00:10 dev ens19          # via CE
```

**`setup-ngn.sh` を実行するたびに、フックが入れた via 経路を on-link で潰していた。**

on-link は「CE が配下アドレス宛の NS に WAN 側で応答する」実装でないと成立しないが、
**OpenWrt は応答しない**。結果:

- クライアントの IPv6 が**片方向で死ぬ**(往きは出るが返らない)
- **IPv4 は MAP-E トンネル経由なので無傷** → 「IPv4 は通るのに IPv6 だけ死ぬ」
- CPE 自身や NGN からの ping は通る → 「経路はあるのに通らない」に見える
- CPE が PD を更新する(T1 = 約 37 分)までは自然回復しない → **時間を置くと直る**

この「時間を置くと直る」性質のせいで、**収束の問題だと誤診**して何度も回り道をした。

**証明**: on-link のまま `PASS=7 FAIL=4` → 手動で via に張り替えた瞬間 `PASS=11 FAIL=0`。

**修正**: 既に via 経路がある場合は on-link を入れないようにした。

```bash
if ! ip -6 route show 2001:db8:100a:500::/56 | grep -q ' via '; then
  ip -6 route replace 2001:db8:100a:500::/56 dev "${ACCESS_IF}"
fi
```

修正後は `setup-ngn.sh pd` を再実行しても via が残り、`PASS=11 FAIL=0` を維持する。

> **設計時のコメントは正しかった。** `setup-ngn.sh` には最初から
> 「CE が MAP アドレス宛の NS に WAN 側で応答しない実装だと復路が死ぬ。
> その場合は on-link をやめ、CE の WAN GUA を next-hop に指定する」と書いてあった。
> **懸念は当たっていたのに、その懸念を書いた本人(スクリプト)が毎回上書きしていた**
> というのが、この件のいちばんの教訓。

---

### サイクル 4: 実機 CPE(Cisco 892FJ)を収容する

#### Plan

**目的**: 実機の 892FJ をラボのアクセス網に物理接続し、**IPoE の CE**および
**DS-Lite の B4** として動くことを確認する(H1 / H2)。

**成功条件**:

1. 892FJ が物理 NIC 経由でラボのアクセス網に乗り、IPv6 を取得する(H1)
2. DS-Lite トンネルが張れ、配下のクライアントから IPv4 が通る(H2)
3. 出口アドレスが AFTR の NAT 後アドレスになる(= 網側 NAT が成立している)
4. MTU が 1460 になる

**やらないこと**: MAP-E(892FJ は classic IOS のため CE 機能なし)。

#### Do

**構成**: 892FJ の `GigabitEthernet0` → R720 の物理 NIC `nic0` → `vmbr1`(PG-ACCESS)。
配下の検証クライアントは **Windows 11 実機**を `FastEthernet0` に直結。

**手順 1: 物理ポートの特定**

`nic0`〜`nic11` は標準の Linux 命名ではなく **udev / systemd.link でリネームされていた**ため、
名前から物理ポートを逆算できなかった。`lspci` と `ethtool -i` で確定させた。

| PCI | チップ | 割当 |
|---|---|---|
| `01:00.0/.1` | Intel X540-AT2(10GBASE-T) | `nic2`(管理・使用中)/ `nic3` |
| `08:00.0/.1` | Intel I350(1GbE) | **`nic0` / `nic1`** |

MAC が同一ブロック(`bc:30:5b:f3:15:d0〜d5`)なので **Dell の X540 + i350 4 ポート rNDC**。
**PCIe の増設カードではなくオンボード**である点が重要(背面 I/O パネル側にある)。

**見た目では 10G と 1G を区別できない**(どちらも RJ45)。`ethtool -p <if> 30` で
LED を点滅させるか、**挿してから `carrier` を見る**のが確実。今回は後者で `nic0` と判明した。

**手順 2: uplink の追加**

```
ACCESS_UPLINK=nic0 ./provision.sh bridges
  vmbr1: 既存 (ラボ用) に uplink nic0 を追加しました
```

> この機能は **fable レビューの指摘で直した直後**の箇所だった。修正前は既存ブリッジに
> uplink を反映せず「案内どおり再実行しても何も起きない」状態で、
> **サイクル 4 の入口で確実に詰まっていた**。

あわせて **OpenWrt-CE を停止**(`qm stop 9010`)。`/56` もトンネル対向も 1 つしかないため。

**手順 3: 892FJ の初期化と設定**

`write erase` → `reload`(Save? に **no**)→ 初期設定ダイアログ **no**。

`show ip interface brief` で実物のポート構成を確認した(**890 系は機種で違う**):

```
FastEthernet0-7   … LAN スイッチポート
FastEthernet8     … WAN (未使用)
GigabitEthernet0  … WAN ← これを使う
Vlan1             … LAN 側 SVI
BRI0 系           … ISDN (892FJ の日本向け装備)
```

**手順 4: RA 方式で IPv6 を取得(H1)**

`ipv6 address autoconfig` を入れたが **`No global unicast address is configured`**。
原因は **NGN が PD モードだったこと**。PD モードの `setup-ngn.sh` は radvd から
プレフィックスを削除するため、**プレフィックスの無い RA では SLAAC できない**。

NGN を `ra` に切り替えたところ即座に取得した。ラボ側から EUI-64 で逆算して確認:

```
2001:db8:1014:300:e6aa:5dff:fe82:364a  lladdr e4:aa:5d:82:36:4a  router  REACHABLE
```

**手順 5: DS-Lite トンネル(H2)**

```
sudo CE_WAN6=2001:db8:1014:300:e6aa:5dff:fe82:364a ./ipoe/vne/setup-aftr.sh
```

892FJ 側:

```
interface Tunnel0
 ip address 192.0.0.2 255.255.255.248
 ip mtu 1460
 ip tcp adjust-mss 1420
 tunnel source GigabitEthernet0
 tunnel mode ipv6
 tunnel destination 2001:DB8:8888::1
ip route 0.0.0.0 0.0.0.0 Tunnel0
```

ルータ自身から `ping 203.0.113.80` が **100% 成功**。
ラボ側から B4 の内側 `192.0.0.2` へも **0% loss**(双方向で成立)。

**手順 6: 実機クライアント(Windows 11)からの検証**

| 検証 | 結果 |
|---|---|
| `ping 203.0.113.80` | 0% 損失 / **TTL=62**(2 ホップ = トンネル経由) |
| `curl.exe http://203.0.113.80/` | **`src: 203.0.113.1`** = AFTR で網側 NAT 成立 |
| `nslookup www.lab.example 203.0.113.53` | `203.0.113.80` + `2001:db8:cafe::80` |
| `ping -f -l 1432`(= 1460) | **通過** |
| `ping -f -l 1472`(= 1500) | **`192.168.100.1 からの応答: パケットの断片化が必要ですが、DF が設定されています`** |
| `curl.exe .../big.bin` | `size=5242880` / 1.15 秒 |

**成功条件 4 件すべて達成。H1 / H2 が実機で確定した。**

#### Check

**① 実機の PMTUD は正しく動いた(1472 の応答元が 892FJ 自身)**

`ping -f -l 1472` の応答元が **`192.168.100.1`(892FJ の Vlan1)** だった。
実機が Frag-Needed を**自分で生成**しており、PMTUD が期待どおり機能している。
5MB 転送が完走したのは `ip tcp adjust-mss 1420` が効いているためで、
**これを省くと R5(MTU ブラックホール)を踏む**。classic IOS では必須。

**② 892FJ が自分でも RA を撒いていた**

`show ipv6 interface` に `ND router advertisements are sent every 200 seconds`。
`ipv6 unicast-routing` を有効にするとルータとして振る舞うため。
**CPE の WAN 側がアクセス網に RA を流すのは実網でもやってはいけない挙動**で、
放置すると NGN-SIM や BRAS が 892FJ をルータとして学習する。
→ `ipv6 nd ra suppress all`(版により `ipv6 nd suppress-ra`)を **WAN 側だけ**に入れる。
  **LAN 側(Vlan1)に入れてはいけない**(配下のクライアントが SLAAC できなくなる)。

**投入して実測した**(2 段階で確認):

**(1) 定期 RA** — NGN-SIM のアクセス側で 240 秒(RA 間隔 200 秒の 1 周期以上)キャプチャ。
RA は 15 件観測されたが**すべて NGN-SIM(`02:ac:00:00:00:01`)由来**で、
**892FJ(`e4:aa:5d:82:36:4a`)由来は 0 件**。

```
sudo timeout 240 tcpdump -nni ens19 -e 'icmp6 and ip6[40]==134'
```

**(2) solicited RA** — `all` 無しだと **RS への応答は返る版がある**(fable の指摘)ので、
`all` を付け直したうえで RS を撒いて確かめた。

```
sudo apt-get install -y ndisc6
sudo timeout 20 tcpdump -Unni ens19 -e 'icmp6 and (ip6[40]==133 or ip6[40]==134)' &
sudo rdisc6 -m -r 3 -w 2000 ens19
```

```
02:17:30.728843  02:ac:00:00:00:01 > 33:33:00:00:00:02  router solicitation    ← RS 送出
02:17:30.972484  02:ac:00:00:00:01 > 33:33:00:00:00:01  router advertisement   ← NGN-SIM が 244ms で応答
                 892FJ 由来: 0 件
```

892FJ は `ipv6 unicast-routing` 有効で同一リンク上にいるため、抑止が効いていなければ
solicited RA を返すはず。**定期 RA と RS 応答の両方が止まっていることを確認した。**

**③ IOS の DHCP サーバが ACK を返しているのに Windows が受け取れない**

`debug ip dhcp server packet` で見ると、サーバは正常に応答している:

```
DHCPDISCOVER 受信 → DHCPOFFER (192.168.100.6) → DHCPREQUEST 受信 → DHCPACK 送信
DHCPREQUEST 受信 (2 秒後) ← ACK が届かず再送
DHCPACK 送信
DHCPREQUEST 受信 (4 秒後) ← また再送
… 最終的に諦めて .7 で仕切り直し
```

クライアントは `169.254.6.164`(APIPA)のまま。ログに手がかりがある:

```
DHCPD: unicasting BOOTREPLY to client 7c4d.8f0e.b32f (192.168.100.6).
```

**まだ持っていないアドレス宛にユニキャストで返している**ため、クライアント側で
破棄されたと考えられる。L2 は正常(`Fa0 up/up`、`Access Mode VLAN: 1`、
VLAN 1 に所属、`service dhcp` 有効、プール 254 アドレス)。

**ラボの不具合ではなく実機と Windows の相互接続の挙動**。
今回は**静的 IP(`192.168.100.50/24`)で回避**して検証を継続した。
DHCP は検証の本体ではないため、ここで止まる必要はない。
**切替当日に同じことが起きうるので、静的で先に進む判断ができることが重要**(バックログ 12)。

**④ 検証クライアントは Wi-Fi を切れない**

有線側はラボなので**インターネットに出られない**。作業者は AI や手順書と会話するために
Wi-Fi を使う。「Wi-Fi を切れ」は現場では成立しない指示だった。

- `ping 203.0.113.80` は TEST-NET-3 なので **Wi-Fi 側では絶対に通らず、結果は信用できる**
- 影響するのは **DNS の引き先だけ**。`nslookup <名前> 203.0.113.53` と
  **サーバを明示すれば回避できる**

**⑤ `netsh` の DNS 設定エラーは無視してよい**

```
netsh interface ip set dns name="イーサネット" static 203.0.113.53
  構成された DNS サーバーが正しくないか、存在しません。
```

netsh が設定時点で到達性を確認できなかっただけで、**設定自体は入っている**
(`ipconfig /all` で確認)。トンネルが上がる前だったため。

#### Act

**ラボの状態**: NGN = RA 方式 / 892FJ = DS-Lite の B4 / OpenWrt-CE = 停止中。
MAP-E BR は停止(`setup-map-br.sh stop`)。

**runbook への反映**: §8 に実機手順を全面的に書き下ろし済み(erase から確認コマンドまで)。
Windows クライアント用に `run-checks.ps1` を新規作成。

#### 2.4-A. fable 全体レビューの反映(サイクル 4 後)

重大 7 件 / 中 4 件 / 小 8 件。**指摘はほぼすべて runbook §8(今回の追加分)に集中**した。
スクリプト本体で新規に見つかった重大バグは無い。

**最も重い指摘 —「自分が踏んだ罠を手順書に残していなかった」**

§8.0 のチェックリストに **「NGN-SIM を RA 方式に切り替える」が無かった**。
§5.1 のとおり構築した読者のラボは **PD 方式**のままで、
§8.2 の `ipv6 address autoconfig` では**グローバルアドレスが 1 つも取れない**。
これは Do の手順 4 で自分が実際に踏んで解決した罠そのもので、
**解決したことに満足して手順書に戻していなかった**。
症状は `No global unicast address is configured` で、しかも RA 自体は届いているため
初見では原因に辿り着けない。§8 は「このセクションだけで完結する」と宣言しているので、なおさら悪い。

**ドキュメント同士の食い違い(いずれも新旧の記述が混在していた)**

| 指摘 | 状態 |
|---|---|
| §8.1 が「Windows の IPv6 を有効化せよ」、§8.3 が「IPv6 が通らないのが正しい」 | §8.1 を**例外構成のときだけ**に格下げ。手順 4 の期待値から IPv6 を削除 |
| §8.1 が「Wi-Fi を切れ」、§8.3 が「切らなくてよい」 | §8.1 を §8.3 に合わせた。**理由付けも §8.1 が不正確**だった(TEST-NET-3 宛は Wi-Fi では通らないので誤判定はしない。影響は DNS の引き先だけ) |
| §4 の持ち込み手順が **GitHub 前提**(会社は GitHub 不可が前提) | バンドル展開を (a) に、GitHub を (b) に |
| §8.2(5) に「**私が** AFTR を張り替えます」(会社では AI が使えない前提) | VNE 上で自分で実行する手順に書き換え |
| 存在しない `§9-H` への参照 | `§9-L 末尾` に修正 |
| 冒頭ステータスが「次はサイクル 4」のまま(本文は完了済み) | build-log / runbook / README / study-guide の 4 か所を更新 |

**編集事故**: §8.1 の `.\run-checks.ps1` が **`.` + CR + `un-checks.ps1`** になっていた。
以前の編集で `\r` がエスケープとして解釈された跡。コピペ実行の第一候補の行だった。
**全 .md / .sh / .py / .ps1 を CR 走査**して、これ 1 件だけであることを確認した。

**コードの修正**

- **`provision.sh`: `ACCESS_UPLINK` に使用中 NIC を指定してもガードが無かった**(最も危険)。
  管理 NIC(nic2)やストレージ NIC(nic11)を誤指定すると、**その網がラボのアクセス網と
  L2 でつながり NGN-SIM の RA と DHCPv6 が社内 LAN に流出**する。
  既存ブリッジの衝突は検出していたのに、uplink 側だけ無防備だった。
  → `check_uplink_free()` を追加(既存ブリッジ経路・新規作成経路の両方に適用)。
  **検出できるのは「IP を持つ」「既に別ブリッジの port」の 2 つだけ**で、
  未使用に見えて実は用途がある NIC は止められない。その旨も runbook §8.0 に明記した
**ガードの動作確認**(実機で試した):

```
ACCESS_UPLINK=nic0  → vmbr1: 既存 (ラボ用)。uplink nic0 は既に接続済み   ← 正常系は通る
ACCESS_UPLINK=nic2  → ERROR: nic2 は既に vmbr0 に接続されています         ← 管理 NIC を拒否
ACCESS_UPLINK=nic11 → ERROR: nic11 には IP アドレスが付いています
                             nic11  UP  10.10.10.20/24 ...                ← ストレージ網を拒否
```

**どちらも `ip link set` を打つ前に停止**し、vmbr2〜4 の処理にも進まなかった。
`nic11` は QNAP のストレージ網(10G / MTU 9000)で、
誤指定すればストレージ網とアクセス網が L2 で直結していた。

- `setup-bras.sh`: `nft -f -` が既存チェインに追記されるため再実行でルールが増えていた。
  `setup-aftr.sh` は同じ理由で delete しているのに bras だけ抜けていた → `nft delete table` を追加
- `run-checks.ps1`: `-SkipV6` でも IPv6 送信元チェックが走り、**正しい構成なのに毎回 WARNING** が
  証跡ログに残っていた(`.sh` 版は対処済み)→ `if (-not $SkipV6)` で囲んだ
- `make-bundle.sh`: `git diff --quiet` がステージ済み変更を見ておらず「未コミット」警告がすり抜けていた
  → `--cached` も見る

**`ipv6 nd ra suppress` は `all` が要る**(Check ② 参照)。runbook を直し、実機にも投入して実測済み。

<!-- サイクル 1 と同じ形式で追記する -->

---

### サイクル 7: CML の Cat8000v で MAP-E の実効ポート数を数える(バックログ 10)

#### Plan

**目的**: バックログ 10 の決着。仮想ラボの OpenWrt は設計 240 ポートに対し**実効 16** しか
使えなかった。これが **OpenWrt 固有の癖なのか、MAP-E 一般の話なのか**が分からないままで、
勉強会で「MAP-E は 240 ポート」と教えてよいかが決められない。

892FJ は classic IOS で MAP-E 非対応のためサイクル 4 では比較できなかった。
CML の Cat8000v(IOS XE 17.15.01a)で確認する。

**成功条件**: 実機 CE が **240 個の外側ポートを使えることを実測で示す**(または使えないことを示す)。

**構成**(CML 上に 3 ノード):

```
client (Ubuntu) --- Gi2 [ Cat8000v = MAP-E CE ] Gi1 --- BR 役 (Ubuntu)
192.168.1.10           192.168.1.1  2001:db8:100a:500::1     ::9
```

クライアントから**送信元ポートを 400 個ばらけさせて UDP を撃ち**、WAN 側リンクを
キャプチャして実際に使われた外側ポートを数える。ラボと同じ MAP-E パラメータを使う
(rule /40 / ea-len 16 / PSID 長 8 / offset 4 / PSID 5 → 198.51.100.10 / 4176-4191)。

#### Do

**CML の API だけで完結させた**(GUI を使わない)。使ったエンドポイント:

| 用途 | エンドポイント |
|---|---|
| ラボ・ノード・リンク作成 | `POST /labs` / `/labs/{id}/nodes` / `/labs/{id}/interfaces` / `/labs/{id}/links` |
| 設定投入 | `PATCH /labs/{id}/nodes/{id}` の `configuration` |
| **コンソールログ取得** | `GET /labs/{id}/nodes/{id}/consoles/0/log` |
| **リンクのパケットキャプチャ** | `PUT /labs/{id}/links/{id}/capture/start` → `GET /pcap/{key}/packets` |

**手順 1: 設定が入らない(2 回はまった)**

① `configuration` を渡してノードを作ったのに `No startup-config, starting autoinstall/pnp/ztp...`。
  → CML の cat8000v は **設定の 1 行目が `platform console serial` である必要がある**。
② 設定を入れ直そうとすると
  `Cannot modify node attributes configuration in state STOPPED`。
  → 一度起動したノードは STOPPED では設定を変えられない。
  **`stop` → `wipe_disks`(状態が DEFINED に戻る)→ `PATCH` → `start` の順**でなければならない。

**手順 2: 構文が違う(公式ドキュメントと実機がずれていた)**

[IOS XE 17.x の設定ガイド](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/ip-addressing/b-ip-addressing/m_iadnat-map-e1.html)
に従って書いたが 3 か所で `% Invalid input detected`。

| 書いたもの | 結果 |
|---|---|
| `default-mapping-rule` サブモード | **存在しない**。`border-relay-address` が DMR を兼ねる |
| `port-parameters share-ratio 256 port-offet-bits 4 start-port 4096` | 拒否。**ただしこれは公式ガイドの表記 `port-offet-bits` (s が抜けている) をそのまま試したもの**なので、拒否は当然。綴りを直した下の行も拒否されるので結論は変わらない |
| `port-parameters share-ratio 256 contiguous-ports 16 start-port 4096` | 拒否 |
| `port-parameters share-ratio 256 start-port 4096 port-offset-bits 4` | 拒否 |
| **`port-parameters share-ratio 256 start-port 4096`** | **通る** |
| `port-parameters share-ratio 256 port-offset-bits 4` | 通る |

**再起動 1 回が 10 分**かかるので、**候補構文を別々の `nat64 map-e domain` に入れて 1 回のブートで
まとめて試した**(domain 11〜15)。通ったものだけ `show nat64 map-e` に値が入るので一発で分かる。

**手順 3: 導出値は設計と完全一致した**

```
MAP-E Domain 1
      Ip-v6-address 2001:DB8:100A:500::9
      Ip-v6-prefix 2001:DB8:100A:500::/56
      Ip-v4-prefix 198.51.100.10/32
      Local-Ip-v4-prefix 192.168.1.0/24
         Share-ratio 256   Contiguous-ports 16   Start-port 4096
         Share-ratio-bits 8   Contiguous-ports-bits 4   Port-offset-bits 4
      Port-set-id 5
```

**`share-ratio` と `start-port` だけ与えれば、`Contiguous-ports 16` と `Port-offset-bits 4` は
IOS XE が自分で導出する。**手計算(15 ブロック × 16 = 240)と一致した。

**手順 4: しかしパケットが 1 つも流れない**

WAN 側リンクのキャプチャが **0 パケット**。クライアント側は `sent=400 err=0` で撃てている。
コンソールログを見て理由が分かった。

```
03:32:19  %SYS-5-CONFIG_P: Configured programmatically by process CVAC Process
03:33:17  %PMAN-0-PROCFAILCRIT: A critical process qfp_ucode_c8kv has failed (rc 134)
03:33:27  %PMAN-5-EXITACTION: Critical process qfp_ucode_c8kv fault on fp_0_0 (rc=134)
```

**設定投入の約 60 秒後に転送エンジン(QFP)が落ちてルータが再起動していた。**

#### Check

**① 原因の切り分け(対照実験)**

| ブート | MAP-E の状態 | QFP クラッシュ |
|---|---|---|
| 設定なし(1 回目・2 回目) | — | **無し** |
| `map-e domain` はあるが `port-parameters` が構文エラーで入らなかった | 機能していない | **無し** |
| `port-parameters` が通った(プローブ 6 ドメイン) | 機能する | **発生** |
| `port-parameters` が通った(正しい `/56` の 1 ドメインのみ) | 機能する | **発生** |

**`port-parameters` が通って MAP-E が実際に機能する状態になった瞬間に落ちる。**
ドキュメントに「非対応」と明記されている **`/64` の BMR が原因ではない**
(それを外して正しい `/56` 1 本だけにしても落ちる)。

**② 言えること / 言えないこと**

- 言えること: **CML の Cat8000v 17.15.01a では MAP-E の転送は検証できない**
- 言えること: **設定構文と導出値は正しい**。`show nat64 map-e` は期待どおりの値を返す
- **言えないこと: 実機の IOS XE がどうか。**仮想プラットフォーム固有の可能性が高いが、断定しない

**③ ドキュメントの「非対応」はパーサでは弾かれない**

「BMR の prefix length 64 は非対応」と明記されているのに、`/64` を入れても**設定は通り、
`show` にも正常に表示された**。**設定が入ったことは動作の保証にならない。**

**④ この件の一番の教訓(勉強会で必ず伝えること)**

**`show` が正しい値を返すことと、実際に転送できることは別物。**
今回は `show nat64 map-e` が完璧な値を返している裏で、転送エンジンが死んでいた。
**検証は必ずパケットを流して測るところまでやる。設定確認で終わらせない。**

これはサイクル 3 の「`run-checks.sh` が PASS するのに網側 NAT が効いていなかった」(3.3-A)と
同じ構図で、**このラボで 2 回目**の同種の失敗である。

> **⚠ 表現の訂正(フェーズ5 レビュー)**: 3.3-A で実際に起きたのは **NAT の不適用**であって、
> 経路そのものは設計どおり(CPE → トンネル → AFTR)だった。
> 「PASS したのに CPE を通っていなかった」はサイクル 1 ⑥で**懸念として書いた仮想シナリオ**であり、
> **実際には一度も発生していない。**この誤った再話が 5 文書に増殖していたため、全て訂正した。

#### Act

- **バックログ 10 は未解決のまま。**実機の IOS XE か、RTX 等の別 CE が必要
- 勉強会では **「設計上 240 ポート」とだけ言い、「実測で 240 使えた」とは言わないこと**
- CML ラボ `B10-mape-portcount` は停止して残してある(再開すれば同じ実験を再現できる)
- 虎の巻(pptx)の第4部に、この結果を 3 枚で追加した

---

### フェーズ5: 全成果物の外部レビュー(2026-08-11)

**やったこと**: 観点の違う独立監査を 6 本並列で回し、主査が原文と突き合わせて確定させた。
指摘は [review-phase5.md](review-phase5.md) に修正指示書としてまとめてある。

| 監査 | 観点 |
|---|---|
| A | RFC・技術事実の照合 |
| B | スクリプト実装 |
| C | 検証結果の証拠性(主張に証拠が付いているか) |
| D | 前提・盲点(ラボで OK = 現場で OK と言えない箇所) |
| E | 対象者 3 類型(2年目CCNA / IPv6未経験ベテラン / 分かった振り中堅)での通読 |
| F | 一貫性・運用引き継ぎ・機密 |

**機密リークはなし**(顧客名・実顧客 IP・パスワード・トークン・秘密鍵とも不検出)。

#### 見つかった重いもの(いずれも修正済み)

**① `lab-mode.sh status` が PD 方式を必ず RA と誤報告していた。**
`grep -c ... || echo 0` と書いていたため、マッチ 0 件のとき grep が「0」を出力した上で
終了コード 1 を返し、`echo 0` も走って `0\n0` の 2 行になっていた。
`case` が `*)` に落ちて **v6mode=ra に汚染**され、バナーの出口アドレスも誤値になる。
**「嘘をつく status なら無いほうがマシ」と書いた本人の宣言に真っ向から反するバグ**だった。
前回の実走テストを RA 側だけでやったため見逃していた。

**② 「経路が間違っていた」という誤再話が 5 文書 7 か所に増殖していた。**
3.3-A で実際に起きたのは **NAT の不適用**で、経路(CPE → トンネル → AFTR)は設計どおりだった。
「PASS したのに CPE を通っていなかった」はサイクル 1 で**懸念として書いた仮想シナリオ**であり、
**一度も発生していない。**切り分け表としても誤誘導(私設アドレスのまま = 経路誤りとは限らない)。
以前に一度直した「盛られた事例」と**同型のものが別表現で残っていた**。

**③ ハンズオンの演習 6/7/8/9 が 892FJ で未実走のまま「出てくる出力」を断定していた。**
さらに演習 7(MTU)は手順自体が成立しない — 5MB は**ダウンロード方向**なのに
**送信側(INET-SIM)の PMTU キャッシュを消していない**、`clear ipv6 traffic` は
統計カウンタのクリアで目的に効かない。演習 2 の「RA は届いている」の証拠に使っていた
`show ipv6 interface | include Router advertisement` は**自分が送る RA の設定値**で、
受信の証拠にならない(かつ `ra suppress all` 済みなのでそもそも出ない)。

**④ Cat8000v「CE に使える」がサイクル 7 と正面矛盾していた**(4 か所)。

#### フェーズ5 の実走確認(2026-08-11。ラボ VM で実施)

**レビューが「要実走」に挙げた 2 件のうち、VM だけで完結するものを実施した。**

**① `lab-mode.sh` の PD 側検証(P0-1 の再発防止)**

`.lab-mode` を消して実機だけを見て判定させた結果:

```
IPv6 の配り方 : PD 方式  … ひかり電話あり相当。/56 がまとめて降りる
--- 状態ファイルの中身 ---
ipv4mode=dslite
v6mode=pd
```

**バグの証拠も NGN-SIM 上で採取した**(PD 方式のとき):

```
$ grep -c '^[[:space:]]*prefix 2001:' /etc/radvd.conf
0
  ↑ 出力 / 終了コード=1        ← 「0」を出した上で 1 を返す
$ grep -c ... || echo 0
0/0/                           ← 2 行になる = case 0) に一致せず ra と誤判定していた
```

**② `mape` × RA 方式(P0-2)**

```
[lab-mode] IPv4 の運び方を MAP-E にします (RA 方式用のパラメータで起動)...
[VNE] MAP-E BR 起動: BR=2001:db8:9999::1, CE=2001:db8:1014:300:0:c633:6414:3, 共有IPv4=198.51.100.20
```

VNE 上の実体も一致:

```
map0: ip/ipv6 remote 2001:db8:1014:300:0:c633:6414:3 local 2001:db8:9999::1
198.51.100.20 dev map0 scope link
```

`ra`/`pd` 切替時に MAP-E だと「BR を張り直せ」の警告が出ることも確認した。

**③ `restore` の失敗検出(P0-3)**

VNE/INET に届かない状態で `restore` を叩くと:

```
⚠ **戻しに失敗しました: VNE INET-SIM**
障害の注入    : mtu          ← fault が残っている(正しい)
終了コード=1
```

正常な `restore` 後は `frag-needed` ルール数 0 を確認。ラボは正常状態に戻してある。

**④ この検証中に新しいバグを 1 件見つけて直した(P0-10 として追加)**

**`lab-hosts.conf` が環境変数を黙って上書きしていた。**
`VNE=... ./lab-mode.sh restore` のような 1 回だけの上書きが効かず、
**指定したつもりと違うホストに繋ぎに行く。**最初これで ③ のテストが成立せず、
「restore が失敗を検出しない」と誤診しかけた。環境変数を優先するよう修正済み。

#### 教科書の引用照合(2026-08-11。全数実施)

**レビューの「要実走 ④」。Google Drive の PDF から目次を抽出して全 45 件を照合した。**

**結果: 節番号・節タイトル・ページ番号はすべて正しかった。**
部の扉ページ(第I部 p.1 / 第II部 p.65 / 第III部 p.295 / 第IV部 p.333 / 第V部 p.379 /
付録A p.437 / 付録B p.455)も一致。

**訂正 1 件**: study-guide の R6 の行が `17.2 / 15.3 Happy Eyeballs (p.288)` と
並べて書いてあり、**p.288 が 17.2 のページに見える**(17.2 は p.326)。
両方に節タイトルとページを付けて解消した。

#### 反映のしかた

- **①③④ はコード・手順を直した。**②は 5 文書すべてを「網側 NAT が効いていなかった」に統一
- ハンズオンは**演習 3 を演習 1 に統合**(`debug ipv6 nd` を最初から仕掛ける形にして、
  演習 2 の証拠もそのデバッグ出力の差分で示す)。これで ③ の演習 2 の問題も同時に解けた
- **検証 PC を Windows に一本化**し、固定 IP・GW・DNS を 0-3 に明記(以前は資料のどこにも無く、
  演習 7 で `192.168.100.50` が突然出てきていた)
- **未実走の演習には「⚠ 実走がまだ」と明記**した。実施前に司会が通すこと(§要実走)
- 盲点(D)は README「できないこと」/ §10 / test-matrix / runbook に注記を追加し、
  ラボ改修が要るものはバックログ 16〜20 に積んだ

### サイクル 8: C1111-8P(中古)の受け入れ評価(2026-08-13)

**目的**: バックログ 10(MAP-E の実効ポート数)を測れる実機を確保する。
892FJ は MAP-E 非対応、CML の Cat8000v は QFP クラッシュで測れなかったため。

**結果: 受け入れ。全 8 判定項目 OK。**詳細は [c1111-acceptance.md §7](c1111-acceptance.md)。

**要点だけ**:

- `C1111-8P` / SN `FGL23312070` / IOS XE **17.15.05** universalk9 / ROMMON 17.5(1r)
- **`Autonomous` モード**(SD-WAN コントローラモードではない ← 中古では当たり)
- `appxk9` + `securityk9` とも **IN USE**、スループット **`unthrottled`** = 出品どおり
  - **ただし Smart Account は未登録。**SLP は未登録でも動くので、
    **「IN USE 表示」は権利の証明にはならない**
- 温度 29〜35℃ Normal / 全モジュール ok / エラーログゼロ / **クラッシュダンプなし**
- **8 ポートすべて `connected` / `a-full a-1000`**(ケーブル 1 本でペア接続 × 4 回)
- ファンレス機なので、中古で最多の故障箇所(ファン)が構造的に存在しない

**本命 — MAP-E の CLI が存在した**:

```
Router(config)# nat64 ?
  ... map-e  NAT64 MAP-E  /  provisioning  NAT64 provisioning ...
Router(config)# nat64 map-e ?
  domain  NAT64 MAP-E domain
```

**バックログ 10 をこの実機で決着できる見込み。**
ただし**サイクル 7 の教訓どおり、CLI があることと転送できることは別物**なので、
パケットを流して出口アドレスを確認するまでは「使える」と書かないこと。

**副産物 — ポート名の対応表が確定した**:

| 役割 | 892FJ | C1111-8P |
|---|---|---|
| WAN | `GigabitEthernet0` | `GigabitEthernet0/0/0` |
| LAN(SVI) | `Vlan1` | `Vlan1` |
| 検証 PC 用ポート | `FastEthernet0` | `GigabitEthernet0/1/0` |

**構成の形は 892FJ と同じ**(WAN が routed、`Gi0/1/x` が L2 スイッチ、`Vlan1` が SVI)なので、
ハンズオン資料はポート名の置換だけで 2 機種対応にできる。

**セキュリティ上の注意(記録)**: 前オーナー(出品者)の
`username yahoo privilege 15 secret 9 ...` が残っていた。`secret 9` は scrypt なので
実用上は破れないが、**パスワード不明の特権アカウントが生きている**状態。
`write erase` するまで業務ネットワークに接続しないこと。

**次サイクルでやること**: `write erase` → MAP-E の実転送テスト(バックログ 10)→
ハンズオン演習 6/7 の通し実走([review-phase5.md](review-phase5.md) の要実走 1、
および [review-phase6-training.md](review-phase6-training.md) の P0-1)。

## 3. 未検証項目トラッカー

**実走で潰すべき仮説の一覧です。** 設計時に「たぶんこうなる」で書いた箇所と、
レビューで「動かない可能性がある」と指摘された箇所を集めてあります。

サイクルを回すたびに **結果** 列を埋めてください。ここが全部埋まると
[study-queue.md 相当の ⚠未検証 印](study-guide.md)が消え、勉強会の教材が確定します。

### 3.1 基盤(サイクル 1)

| # | 仮説 / 未確認 | 確認方法 | 結果 |
|---|---|---|---|
| B1 | `local-lvm` の空きが 70GB 以上ある | `pvesm status` | **OK** 975GB 空き。QNAP 不要、local-lvm で確定 |
| B2 | VMID 9001-9004 / 9010 が空いている | `qm list` | **OK** VMID 100 (CML) のみ存在 |
| B3 | `vmbr1`〜`vmbr4` が未使用(CML と衝突しない) | `provision.sh preflight` | **OK** すべて未使用。vmbr0 のみ存在 |
| B4 | `bridge-mcsnoop 0` が実際に効いて RA が通る | VM 間で `ping6` / `tcpdump` で RA 受信 | **OK** サイクル 2 で確定。RA(`ff02::1`)と DHCPv6(`ff02::1:2`)のマルチキャストが両方通り、RS→RA と Solicit→Advertise→Request→Reply を観測 |
| B5 | `detect-ifs.sh` の MAC 判定が Ubuntu 24.04 で機能する | VM 内で `. detect-ifs.sh; echo $ACCESS_IF` | **OK** 実測 NIC 名は `eth0`/`ens19`/`ens20` で想定と違ったが、MAC 判別なので 4 パターンすべて解決。`LAN_IF`(02:c1)を追加 |
| B6 | `import-from`(PVE 9.1)でディスク取り込みが通る | provision.sh の出力 | **OK** 5 台すべて作成・起動できた |
| B7 | ホストからイメージをダウンロードできる(`wget` で Ubuntu 600MB / OpenWrt 50MB) | provision.sh の出力 | **OK** Ubuntu 595MB/46秒、OpenWrt 13MB/8秒。ただし展開で gzip 終了コード 2 → スクリプト即死(修正済み) |
| B8 | `nic11` は何に使われているか(QNAP 10G と推定)。サイクル 4 で誤って使わないため | `ip -4 addr show nic11` / `cat /etc/network/interfaces` | **確定: ストレージ網。触らないこと。** `10.10.10.20/24` / `Speed: 10000Mb/s` / **MTU 9000**(ジャンボフレーム)/ `/etc/network/interfaces` に static で定義。推定どおり QNAP 用。**サイクル 4 の `ACCESS_UPLINK` には `nic0` か `nic1` を使う**(`igb` = オンボード 1GbE / RJ45。892FJ の 1GbE と整合)。`nic3`〜`nic10` は `ixgbe`(10GbE 系)なので SFP+ だとトランシーバが要る |
| B9 | `snippets` 対応ストレージが無く guest-agent が入らない | 完了メッセージの注意書き | **該当**。`provision.sh ips`(IPv6 リンクローカル)で代替。guest-agent が必要なら `pvesm set local --content iso,vztmpl,backup,snippets` + 作り直し |
| B10 | `provision.sh ips` が 4 台(+OpenWrt)を検出できる | `./provision.sh ips` | **OK**(Linux 4 台)。OpenWrt は管理NICが無いので対象外。net0 決め打ちのバグを修正済み |
| B11 | 4 台すべてに SSH で入れる | `ssh labadmin@fe80::…%vmbr0` | **OK** 鍵認証で 4 台とも成功 |
| B12 | クライアント (9004) の LAN 側が設定される | `setup-client.sh` → `ip route show default` | **OK** 12 秒で完走。`ens19` に `192.168.1.247/24` と `2001:db8:100a:500:c1:ff:fe00:4/64`、既定経路は v4/v6 とも metric 50 で CPE 側を向いた。管理は リンクローカルで継続できた |

### 3.2 IPv6 の配布(サイクル 2)

| # | 仮説 / 未確認 | 確認方法 | 結果 |
|---|---|---|---|
| N1 | `setup-ngn.sh` の `apt-get` が管理経路経由で通る | 実行して完走するか | **OK** 37 秒で完走。ただし `getent hosts` は AAAA しか返さず、v6 は 3ms で ENETUNREACH → apt が IPv4 に落ちて成功。**v6 既定経路が「無い」から速く失敗した**のが効いている(OpenWrt との差は Do/Check ⑤) |
| N2 | Kea が起動する(過去に設定ミスで起動しなかった箇所) | `systemctl status kea-dhcp6-server` | **OK** `active (running)`。`kea-dhcp6 -t` の構文検証も通過 |
| N3 | Kea の `leases6_committed` フックが実際に経路を入れる | PD 後に `ip -6 route` に `via <CE>` が出るか | **OK(サイクル 5 で確定)** `committed 2001:db8:100a:500::/56 via fe80::ac:ff:fe00:10 dev ens19` を確認。**ただし `setup-ngn.sh` の on-link がこれを上書きしていた**(3.4-B)。NGN 再起動後はフックが次の Renew まで発火しないので注意 |
| N4 | AppArmor 許可と `CAP_NET_ADMIN` が効いている | 上が失敗したら `journalctl -u kea-dhcp6-server` と `dmesg \| grep apparmor` | **該当なし**。`kea-dhcp6-server.service.d/pd-route.conf` が読み込まれ、Kea は正常起動。N3 が未確定のため効いているかの証明は保留 |
| N5 | RA 方式で CPE に /64 が降る | `ip -6 addr` / `tcpdump` | **OK** `eth1` に `2001:db8:1014:300:ac:ff:fe00:10/64`、既定経路も `default from 2001:db8:1014:300::/64` |
| N6 | PD 方式で CPE に /56 が降る | 同上 + `ip -6 route` | **OK** `ubus` で `2001:db8:100a:500::/56` を確認。`br-lan` には `/60` が切り出される(`ip6assign '60'` のため。条件文の「/64」は誤り) |
| N7 | **PPPoE 接続中も NGN の RA が CPE WAN に届く**(教材の演習 1-A の前提) | Phase 0 状態で `ip -6 addr` | **OK(ただし要注意)** RA は PPPoE 中も `eth1` に届く(tcpdump で実証)。**が、netifd が `disable_ipv6=1` にするため CPE 側が受け取れない**。`network.wan_dev` に `ipv6 '1'` を入れると PPPoE と IPoE が同居できる(Do/Check ⑧) |
| N8 | `accel-ppp` の `chap-secrets` 認証が通る(モジュール未ロードで全失敗した経緯あり) | `accel-cmd show sessions` | **OK(方式は PAP)** `accel-cmd show sessions` に `user1@isp-a.example / 100.64.1.0 / active`。ネゴされたのは CHAP ではなく **PAP** なので教材の記述に注意(Do/Check ⑨) |

### 3.3 IPv4 over IPv6(サイクル 3)

| # | 仮説 / 未確認 | 確認方法 | 結果 |
|---|---|---|---|
| V1 | `ip -6 tunnel add ... mode ipip6` が実際に張れる | `setup-map-br.sh` 実行 → `ip -6 tunnel show` | **OK** `map0` / `dslite0` とも一発で張れた(所要 4 秒)。`modprobe ip6_tunnel` も問題なし |
| V2 | OpenWrt に `map` / `ds-lite` パッケージをどう入れるか(**ラボ内にインターネットが無い**) | 管理経路 or 事前導入イメージ。**手順を確定して記録すること** | **解決**。`qm set 9010 --net2 virtio,bridge=vmbr0` は**ホットプラグで効き再起動不要**。ただし `opkg` は `ifdown wan6` してからでないと通らない(uclient-fetch が AAAA を選び A に落ちない)。`map - 7` / `ds-lite - 9` / `tcpdump-mini` 導入済み。手順全文は サイクル 2 の Do 手順 5 |
| V3 | MAP-E で CPE の自動計算値が期待値表と一致する | `build.md` §3 の表と照合 | **OK 完全一致**。共有 IPv4 `198.51.100.10` / 先頭ポートブロック `4176-4191` / MAP アドレス `2001:db8:100a:500:0:c633:640a:5` / MTU 1460 |
| V4 | 実際に使えるポート数が 240 で、飛び飛びである | CPE の状態表示 / 実測 | **OK(構造は 240・飛び飛び)** 15 ブロック × 16 = 240、間隔 4096、`a=0` が無いので well-known ポートは使用不可。**ただし OpenWrt が実際に使えるのは先頭 16 ポートだけ**(R3a) |
| V5 | DS-Lite で IPv4 が通る | `run-checks.sh` | **OK** `PASS=10 FAIL=0`。B4=`192.0.0.2` / AFTR=`192.0.0.1`(RFC 6333 どおり)。`CE_WAN6` は既定値(CPE の br-lan)で一致し引数不要だった |
| V6 | `run-checks.sh` が全項目 PASS する | 実行 | **OK(両方式)** ただし DNS が通るまでに 3 つの原因が重なっていた(Do/Check ①②③)。うち 1 件は `setup-inet.sh` の設計バグ |
| V7 | MTU の実測値が 1460(encaplimit ありなら 1452)になる | `ping -M do -s ...` | **OK 1460**。`payload 1472 不可 / payload 1432 通過` = パス MTU 1460。`encaplimit none` で張っているので 1452 にはならない |

### 3.4 トラブル再現レシピ(サイクル 5)

| # | 仮説 / 未確認 | 懸念 | 結果 |
|---|---|---|---|
| R3a | R3 が再現する | **BR はポート制限を強制しない**。enforce 用 nft の投入が必要 | **再現(ただし条件が違う)**。OpenWrt が CE のときは **240 ではなく 16 本**で詰まる(nft の snat が終端判定で先頭ブロックしか使われない)。`map-enforce` は不要だった。ポート集合は 15 ブロック × 16 = 240 で設計どおり(V4 確定) |
| R4a | R4 でポート開放が本当に効かない | — | **OK 再現**。CPE の DNAT は LAN 側で機能するのに、外からは `203.0.113.1:8080`(拒否)/ `192.0.0.2:8080`(不達)/ 私設アドレス(不達)で全滅。**待受の対照実験が必須**(無いと誤判定する) |
| R5a | R5(MTU ブラックホール)が再現する | **OpenWrt 既定の `mtu_fix`(MSS clamp)で潰されて再現しない可能性** | **懸念が的中**。`break-pmtu` だけでは再現しない。`mtu_fix=0` と **両端の PMTU キャッシュフラッシュ**の 2 つが要る。逆に `mtu_fix` が実務的な対処そのもの |
| R6a | R6(DNS フォールバック遅延)が再現する | **`curl` 自身が Happy Eyeballs で ~200ms でフォールバックし、症状が出ない可能性** | **懸念が的中**。`curl` は 8ms→**207ms** で体感できない。`wget` は **15 秒でタイムアウト**。**症状はクライアント実装次第**なので演習では両方叩かせること |
| R1a | R1(RA 方式に PD 設定)が再現する | — | **OK 再現。ただし症状も切り分けも記述と違った**。WAN 側には RA 由来の IPv6 が普通に付き、死ぬのは委譲プレフィックスと MAP-E。DHCPv6 は `solicit`→`advertise` まで流れており「応答が無い」わけではない(IA_PD が無いだけ)。復旧には `network restart` が必要 |
| D1 | DUID DROP クラスを有効化すると無応答になる | 既定では無効(opt-in) | **OpenWrt では再現しない**。キャプチャで確認したところ OpenWrt は **DUID-LL** を送っており、DROP クラス(DUID-LL 以外を落とす)を素通りする。設計コメントの「OpenWrt は DUID-LLT を送る」が誤り |

### 3.5 実機 / CML(サイクル 4)

| # | 仮説 / 未確認 | 確認方法 | 結果 |
|---|---|---|---|
| H1 | 892FJ が IPoE(RA/PD)の CE として動く | [research-notes.md](research-notes.md) §4 の表に従って設定 | **OK(RA 方式)**。`ipv6 address autoconfig` で GUA を取得し、ラボ側の近隣テーブルに `2001:db8:1014:300:e6aa:5dff:fe82:364a` を確認。**PD 方式では取得できない**(radvd がプレフィックスを配らないため)。サイクル 4 参照 |
| H2 | 892FJ が DS-Lite の B4 として動く | 同上 | **OK**。`tunnel mode ipv6` + `ip mtu 1460` + `ip tcp adjust-mss 1420` で成立。実機 Windows から出口 `src: 203.0.113.1` / MTU 1460 / 5MB 完走を確認。サイクル 4 参照 |
| H3 | CML の Cat8000v で MAP-E CLI が使える | `nat64 ?` / `nat64 map-e ?` / `nat64 provisioning ?`([proxmox-prototype.md](proxmox-prototype.md) §4.1)。**タイムボックス 30 分** | **CLI は OK。転送は NG。** CML 2.9.0 / Cat8000v **IOS XE 17.15.01a** で `nat64 map-e domain 1` と `nat64 provisioning mode jp01` が**両方とも running-config に入った**(§3.5-A)。**ただしサイクル 7 で `port-parameters` 投入時に QFP がクラッシュし、転送は不可と判明。CE 役には使えない** |

#### 3.5-A. H3 の実施記録(2026-08-10)

**結論: Cat8000v(IOS XE 17.15.01a)は MAP-E の CLI を持っている。**
[proxmox-prototype.md §4.1](proxmox-prototype.md) の判定表でいう
「`nat64 map-e domain` と `nat64 provisioning mode jp01` が両方通る」に該当。

> **⚠ ただし「CE 役に使える」ではない(サイクル 7 で判明)。**
> ここで確認できたのは **CLI が受理されることと、導出値が設計どおりであること**までです。
> **`port-parameters` を投入すると QFP(転送エンジン)がクラッシュし、パケットは通りません。**
> **この時点の「CE 役に使える」という判定は誤りだったので、サイクル 7 の結果で上書きします。**

| 項目 | 実測値 |
|---|---|
| CML | 2.9.0+build.3 / ライセンス `IN_COMPLIANCE`(Learning@Cisco) |
| ノード定義 | `cat8000v` / イメージ `cat8000v-17-15-01a` |
| IOS XE | `version 17.15` / `license udi pid C8000V` |
| `license boot level` | **明示行なし(既定のまま)**。レベルを上げなくても MAP-E CLI は出た |

**やり方が普通と違うので記録しておく(会社では不要な回り道)**

CML のコンソールは**読み取り専用の API しかない**。書き込みは SSH コンソールサーバ経由だが
**パスワード認証を要求する**ため、トークンだけでは対話でコマンドを打てなかった。

```
$ ssh <console_key>@192.168.11.40
debug1: Remote protocol version 2.0, remote software version SERVER
debug1: Authentications that can continue: password
```

そこで **`?` を打つ代わりに、起動時コンフィグに判定対象のコマンドを流し込み、
パーサが受理したかを running-config の抽出で確認する**方法にした。
`?` の補完が出るかと、コマンドが実際に投入できるかは、H3 の目的(実装の有無)に対しては同値。

```
# 1) ノードを wipe して DEFINED_ON_CORE にする (STOPPED では configuration を変更できない)
PUT  /api/v0/labs/{lab}/nodes/{node}/wipe_disks

# 2) 判定対象を含むコンフィグを投入
PATCH /api/v0/labs/{lab}/nodes/{node}   {"configuration": "...(下記)..."}

# 3) 起動して running-config を抽出
PUT  /api/v0/labs/{lab}/nodes/{node}/state/start
PUT  /api/v0/labs/{lab}/nodes/{node}/extract_configuration
GET  /api/v0/labs/{lab}/nodes/{node}          → configuration を読む
```

投入したコンフィグ(抜粋):

```
platform console serial
!
hostname H3TEST
!
nat64 settings mtu minimum 1280      ← コントロール (既知の NAT64 コマンドのつもり)
nat64 map-e domain 1                 ← 判定対象 1
nat64 provisioning mode jp01         ← 判定対象 2
```

ブート時のコンソール出力:

```
%CVAC-4-CLI_FAILURE: Configuration command failure: 'nat64 settings mtu minimum 1280' was rejected
%CVAC-3-CONFIG_ERROR: 1 error(s) while applying configs generated from file objstore:/iosxe_config
```

抽出した running-config:

```
hostname H3TEST
nat64 map-e domain 1
nat64 provisioning mode jp01
```

**読み方**:

- **判定対象 2 つは running-config に載った** = パーサが受理した = **実装あり**
- `hostname H3TEST` も載っているので、**CVAC は 1 件目のエラーで中断していない**。
  「エラーが 1 件だけ」なのは、残りが通ったからであって、途中で止まったからではない
- 唯一弾かれたのは**私が入れたコントロール側**。`nat64 settings mtu minimum` は
  17.15 では通らない構文だった。NAT64 機能の不在を示すものではない
  (機能が無ければ `nat64 map-e` も同時に弾かれるはず)

**注意: 「CLI がある」と「動く」は別**。ここで確認したのは**パーサに実装があること**だけで、
実際に MAP-E のカプセル化が成立するか、期待値表([build.md](build.md) §3)どおりの
共有 IPv4 / PSID になるかは**未検証**。それはサイクル 4 で、ラボのアクセス網に繋いでから確認する。
CML 上の Cat8000v は demo mode(スループット制限あり)なので、**性能の検証には使えない**。

**所要時間**: 約 25 分(タイムボックス 30 分内)。うち大半は Cat8000v のブート待ち(2 回、各 5 分前後)。

**サイクル 4 への準備**: CML VM(VMID 100)に `net1 = vmbr1` を追加済み。

```
qm set 100 --net1 virtio,bridge=vmbr1
net1: virtio=BC:24:11:2F:40:2C,bridge=vmbr1
```

CML 側で External Connector として認識させるには **CML の再起動が必要**な見込み。
サイクル 4 を始めるときに実施する(サイクル 3 は OpenWrt-CE で進むので今は不要)。

---

## 4. CE を入れ替える手順(1 台しか同時検証できないため必読)

ラボの MAP-E BR / DS-Lite AFTR は **単一 CE 向けの静的トンネル**です。
そのため **同時に検証できる CE は 1 台だけ**で、OpenWrt → 892FJ → 別機種 と切り替えるには
毎回この手順が必要です。**これを知らずに CE を差し替えると「なぜか通らない」で溶けます。**

1. **旧 CE を物理/論理的に外す**(PG-ACCESS から切り離す、または WAN を down)
2. **Kea のリースを消す**(PD 方式の場合。同じプレフィックスを新 CE に渡すため)

   ```
   sudo systemctl stop kea-dhcp6-server
   sudo rm -f /var/lib/kea/kea-leases6.csv*
   sudo systemctl start kea-dhcp6-server
   ```

3. **新 CE を接続し、IPv6 が降りるのを待つ**。降りた **WAN 側 IPv6 アドレス**を確認する
4. **VNE 側のトンネルを新 CE 向けに張り替える**

   ```
   # DS-Lite (AFTR)
   sudo CE_WAN6=<新CEのWAN側IPv6> ./lab/ipoe/vne/setup-aftr.sh

   # MAP-E (BR) — モードに応じた期待値を build.md §3 の表から取る
   sudo CE_MAP_ADDR=<新CEのMAPアドレス> CE_SHARED_V4=<共有IPv4> ./lab/ipoe/vne/setup-map-br.sh
   ```

5. **期待値を照合する**([build.md](build.md) §3 の表)。共有 IPv4 / PSID / MAP アドレスが一致するか
6. `run-checks.sh` を流して PASS を確認する

> **`ra` / `pd` モードを切り替えたときも同じことが必要です。**
> NGN 側だけ切り替えて BR を再実行しないと、アドレスが合わずに IPv4 が全断します。

---

## 5. 改善バックログ(今のサイクルでは触らない)

サイクル中に気づいた改善案はここに積みます。**その場で直すとサイクルが終わらなくなる**ため、
1 サイクル完了後にまとめて判断します。

| # | 内容 | 優先 | 状態 |
|---|---|---|---|
| 1 | `setup-*.sh` を 1 本の `setup.sh` にまとめ、MAC から役割を自動判定する | 中 | サイクル 3 完了後 |
| 2 | Box バンドル(アーカイブ + イメージ + ログ + 予備の VM エクスポート)を作る | 中 | **完了**。`lab/ipoe/make-bundle.sh` で生成(232KB)。イメージと VM エクスポートは容量が大きく会社側で取得できるため**含めない**方針にした(取得元は runbook §0/§3 に記載) |
| 3 | ルールベースの本格 BR(FD.io VPP `map` プラグイン)への差し替え | 低 | 必要になったら |
| 4 | 複数 CE の同時検証(Kea の DUID 予約で複数面化) | 低 | 勉強会でペア演習が回らないと判明したら |
| 5 | 検証マトリクス No.7(VPN)の追加構築 | 低 | 案件で必要になったら |
| 6 | `setup-bras.sh` の再実行耐性(自分で既定経路を奪うので 2 回目の `apt-get` が死ぬ)。`setup-client.sh` と同じく「経路を切り替える前に必要なものを揃える」形にする | 中 | サイクル 3 完了後 |
| 7 | OpenWrt の rootfs がイメージ拡張(2G)に追従しておらず 98MB のまま。パーティション/FS の拡張まで `provision.sh` でやる | 中 | 追加パッケージで容量不足が出たら |
| 8 | ラボ内 IPv6 DNS(`2001:db8:cafe::53`)への到達確認 | 高 | **完了(サイクル 3)**。原因は 3 つ重なっていた(送信元制限付き既定経路 / dnsmasq の listen インタフェース / CPE のリバインド保護)。Do/Check ①②③ 参照 |
| 9 | **DS-Lite の AFTR NAT が効かない**(VNE と INET-SIM の同居による) | 高 | **完了(3.3-A)**。INET-SIM を 9005 に分離して解消。`provision.sh` に `SPLIT_INET=1` を追加 |
| 10 | **OpenWrt の MAP-E が実効 16 ポートしか使えない**(nft の snat が終端判定で、15 本のルールが同じマッチ条件のため先頭ブロックしか使われない)。ラボ固有の癖か OpenWrt のバグかは未確認。実機 CPE では NAT エンジンがポート集合を正しく扱うはずなので、**実機検証時に必ず数え直すこと** | 中 | **未解決(サイクル 7 で試したが測れず)**。892FJ は MAP-E 非対応。CML の Cat8000v は**設定構文と導出値は設計と完全一致した(240 = 15 × 16)**が、**MAP-E を有効にすると転送エンジン(QFP)が落ちて再起動**するため転送を測れなかった。**実機の IOS XE か RTX 等の別 CE が必要。**演習では「設計上 240」とだけ言い、「実測で 240 使えた」とは言わないこと |
| 11 | 方式・モードを往復させた後、`run-checks.sh` の IPv6 系が不安定になる | 中 | **完了(3.4-A)**。原因は **2 つ重なっていた**。① CPE の ULA へのフォールバック(ULA 無効化で解消)② **`setup-ngn.sh` が Kea フックの via 復路を on-link で上書き**(3.4-B。こちらが本命) |
| 12 | **892FJ の IOS DHCP サーバから Windows 11 がアドレスを取れない**。サーバは `DHCPOFFER` / `DHCPACK` を送っているのにクライアントが `DHCPREQUEST` を再送し続け、APIPA(`169.254.x.x`)のまま。ログに `unicasting BOOTREPLY to client ... (192.168.100.6)` とあり、**まだ保持していないアドレス宛にユニキャストで返している**のが原因と見られる。L2 は正常(`Fa0 up/up` / `Access Mode VLAN: 1` / プール 254 アドレス)。検証は静的 IP で回避済み | 中 | サイクル 4 で発生。**ラボの不具合ではなく実機と Windows の相互接続**。切替当日に踏みうるので §9-M に切り分けを追記する |
| 13 | **892FJ の WAN 側(GigabitEthernet0)で RA を抑止する**。`ipv6 unicast-routing` を入れると CPE 自身がアクセス網へ RA を撒く(`ND router advertisements are sent every 200 seconds`)。実網でやってはいけない挙動で、NGN-SIM や BRAS が CPE をルータとして学習してしまう。`ipv6 nd ra suppress all`(版により `ipv6 nd suppress-ra`)を **WAN 側だけ**に入れる。**`all` が必要**(無いと RS への応答は返る版がある)。**LAN 側(Vlan1)に入れてはいけない**(配下が SLAAC できなくなる) | 高 | **完了(サイクル 4 Check ②)**。runbook §8.2 / §9-N に反映し、自宅の実機にも `all` 付きで投入済み。定期 RA(240 秒キャプチャ)と RS 応答(`rdisc6` で誘発)の**両方が止まっている**ことを実測で確認した |
| 14 | **拠点間 IPsec VPN が MAP-E / DS-Lite 配下で張れるかをラボで検証する。**説明会資料 §3-5 に「発信なら張れる(両端が NAT-T 対応であること)/待ち受けは不可」と**机上の整理**を載せたが、**実測していない**。模擬勉強会で現場担当役から「『たいてい張れます』ではお客様に言えない。期日のない宿題は宿題じゃない」と指摘された。確認したいのは ① MAP-E 配下からの発信で NAT-T が通るか ② 対向(固定 IP 側)に設定変更が要るか ③ 892FJ + DS-Lite の発信で張れるか ④ 両端 MAP-E で本当に張れないか | **高** | **未着手**。ラボに VNE と INET-SIM があるので、INET-SIM 側に固定 IP の IPsec 対向を立てれば検証できる。**資料に「検証項目として積んである」と書いた以上、次のサイクルで実施すること** |
| 15 | **同時接続数の判断基準(安全率)を社内で決める。**説明会資料 §3-3 に「ピーク実測 × 安全率 2 倍 が割当ポート数を超えたら MAP-E 単独を避ける」という**判断の型**を置いたが、**安全率 2 倍は仮置き**。案件を何本か通して実績を貯め、決め直す必要がある | 中 | **仮置きのまま**。資料にもその旨を明記済み |
| 16 | **HGW(ひかり電話のホームゲートウェイ)実機をラボに収容する。**現場の多数派は HGW 配下の構成なのに、ラボには HGW 相当が無い。踏めていない事故は ① HGW の IPv6 フィルタ既定値 ② **フレッツ・ジョイントで HGW に v6プラスが自動配信され、HGW が勝手に MAP-E を終端 → 配下ルータにも設定して二重終端** ③ HGW 配下での PD/RA の癖。**なお「HGW がラボの NGN-SIM から PD を取れるか」自体が未知**(網内サーバに依存する機種がある)ので、まずそこの検証で 1 サイクル取る価値がある | **高** | **未着手**(フェーズ5 レビュー)。R7「二重終端」を OpenWrt 2 台直列で代用しているが、HGW 固有の事故は代表できていない。runbook §8 に「未カバー」と明記済み |
| 17 | **AFTR のセッション上限を模擬する(R14 として追加)。**MAP-E にはポート枯渇レシピ(R3)があるのに、DS-Lite 側は `masquerade` 一発でセッション上限・UDP タイマ・EIM/EIF が **conntrack 任せ = 実質無制限**。実 AFTR には加入者あたりの上限があるため、「ラボで動いた大量セッション・長寿命 UDP のアプリが現場で間欠死する」を再現できない。`nft ... ct count` で上限を模擬する `aftr-limit` オプションを足す | 中 | **未着手**(フェーズ5 レビュー)。README「できないこと」には注記済み |
| 18 | **「切戻せない」を演習化する。**ラボの BRAS は無条件で PPPoE を受けるため、切戻し訓練は**構造的に必ず成功する**。`chap-secrets` から該当ユーザを消すだけで「ISP 側でアカウントが止められた」状態を作れる(実装は数分) | 中 | **未着手**(フェーズ5 レビュー)。test-matrix Phase 3 と README には注意書きを追加済み |
| 19 | **BR の入口検査(`map-enforce`)を既定 ON に格上げする。**ラボの BR は何でも通すので、CE 側の導出誤りや割当ポート外の送信元が**顕在化しない**。実 BR は落とすため「ラボで PASS した CE が現場で弾かれる」が起こり得る。`setup-map-br.sh` に `enforce` サブコマンドを足し、MAP-E の実機検証手順では既定 ON にする | 中 | **未着手**(フェーズ5 レビュー)。現状は R3 の nft を opt-in の「おまけ」扱いにしている |
| 20 | **accel-ppp のコミット固定とソース同梱。**`setup-bras.sh` は GitHub の master を `--depth 1` clone してビルドしている。**1 年後に会社で再構築するとビルドが割れる / 挙動が変わる**典型。コミットを固定し、バンドルに tarball を同梱する | 中 | **未着手**(フェーズ5 レビュー)。「バンドルだけで構築できる」という目標に対する穴 |
| 21 | **勉強会の外側の成果物。**① 開通当日にポケットに入れる **A4 1 枚のフローチャート**(契約コース確認 → RA/PD を実測 → 出口アドレス確認 → runbook §9)② 受注・営業側に渡す「**契約時に確認する 3 項目**」1 枚 ③ 事前/事後の **5 問クイズ**(定着に効き、検証機の予算打診の材料にもなる) | 低 | **今回は作らない**とユーザー判断済み(フェーズ5)。将来候補として記録。**①② は「技術者教育では防げない事故」に効く**(WAKWAK の 1 回目は契約情報の伝達ミス) |
