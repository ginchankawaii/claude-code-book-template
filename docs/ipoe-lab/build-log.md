# 構築ログ / PDCA 記録

ラボは**一度も動かしていません**。動かせば必ず設計と食い違う箇所が出ます。
それを場当たりに直して忘れるのではなく、**1 サイクルずつ記録して次に活かす**ためのファイルです。

このファイルが最終的に [runbook-vmware.md](runbook-vmware.md)(会社で人間が手作業する手順書)の
素材になります。**会社では AI が使えないので、ここに書いていないことは会社で再現できません。**

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
| 1 | Proxmox に 5 VM を作って起動する | **VM 起動まで完了**(成功条件の確認中) | 約 3 分(2 回) | gzip は警告でも終了コード 2 を返し `set -e` で即死する。冪等性の無い分岐に副作用を置くと再実行で隠れる。guest-agent 無しでも IPv6 リンクローカルで VM に入れる |
| 2 | 4 台の Linux に setup スクリプトを流し、IPv6 が降りるところまで | 未着手 | — | — |
| 3 | MAP-E / DS-Lite で IPv4 が通り、`run-checks.sh` が PASS するまで | 未着手 | — | — |
| 4 | 実機 CPE(892FJ)を収容する | 未着手 | — | — |
| 5 | トラブル再現レシピ R1/R3/R4/R5 を実走して再現条件を確定 | 未着手 | — | — |
| 6 | runbook-vmware.md を書き上げ、Box バンドルを作る | 未着手 | — | — |

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

### サイクル 2〜6

<!-- サイクル 1 と同じ形式で追記する -->

---

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
| B4 | `bridge-mcsnoop 0` が実際に効いて RA が通る | VM 間で `ping6` / `tcpdump` で RA 受信 | 設定値は **vmbr1-4 すべて 0** を確認。実際に RA が通るかはサイクル 2 で確認 |
| B5 | `detect-ifs.sh` の MAC 判定が Ubuntu 24.04 で機能する | VM 内で `. detect-ifs.sh; echo $ACCESS_IF` | |
| B6 | `import-from`(PVE 9.1)でディスク取り込みが通る | provision.sh の出力 | **OK** 5 台すべて作成・起動できた |
| B7 | ホストからイメージをダウンロードできる(`wget` で Ubuntu 600MB / OpenWrt 50MB) | provision.sh の出力 | **OK** Ubuntu 595MB/46秒、OpenWrt 13MB/8秒。ただし展開で gzip 終了コード 2 → スクリプト即死(修正済み) |
| B8 | `nic11` は何に使われているか(QNAP 10G と推定)。サイクル 4 で誤って使わないため | `ip -4 addr show nic11` / `cat /etc/network/interfaces` | |
| B9 | `snippets` 対応ストレージが無く guest-agent が入らない | 完了メッセージの注意書き | **該当**。`provision.sh ips`(IPv6 リンクローカル)で代替。guest-agent が必要なら `pvesm set local --content iso,vztmpl,backup,snippets` + 作り直し |
| B10 | `provision.sh ips` が 4 台(+OpenWrt)を検出できる | `./provision.sh ips` | **OK**(Linux 4 台)。OpenWrt は管理NICが無いので対象外。net0 決め打ちのバグを修正済み |

### 3.2 IPv6 の配布(サイクル 2)

| # | 仮説 / 未確認 | 確認方法 | 結果 |
|---|---|---|---|
| N1 | `setup-ngn.sh` の `apt-get` が管理経路経由で通る | 実行して完走するか | |
| N2 | Kea が起動する(過去に設定ミスで起動しなかった箇所) | `systemctl status kea-dhcp6-server` | |
| N3 | Kea の `leases6_committed` フックが実際に経路を入れる | PD 後に `ip -6 route` に `via <CE>` が出るか | |
| N4 | AppArmor 許可と `CAP_NET_ADMIN` が効いている | 上が失敗したら `journalctl -u kea-dhcp6-server` と `dmesg \| grep apparmor` | |
| N5 | RA 方式で CPE に /64 が降る | `ip -6 addr` / `tcpdump` | |
| N6 | PD 方式で CPE に /56 が降る | 同上 + `ip -6 route` | |
| N7 | **PPPoE 接続中も NGN の RA が CPE WAN に届く**(教材の演習 1-A の前提) | Phase 0 状態で `ip -6 addr` | |
| N8 | `accel-ppp` の `chap-secrets` 認証が通る(モジュール未ロードで全失敗した経緯あり) | `accel-cmd show sessions` | |

### 3.3 IPv4 over IPv6(サイクル 3)

| # | 仮説 / 未確認 | 確認方法 | 結果 |
|---|---|---|---|
| V1 | `ip -6 tunnel add ... mode ipip6` が実際に張れる | `setup-map-br.sh` 実行 → `ip -6 tunnel show` | |
| V2 | OpenWrt に `map` / `ds-lite` パッケージをどう入れるか(**ラボ内にインターネットが無い**) | 管理経路 or 事前導入イメージ。**手順を確定して記録すること** | **問題を確認**。OpenWrt は管理NIC無しで作られ opkg 不可。`OPENWRT_MGMT=1` を追加して net2 経由で導入する方式にした。**実際の導入はサイクル 2 で検証** |
| V3 | MAP-E で CPE の自動計算値が期待値表と一致する | `build.md` §3 の表と照合 | |
| V4 | 実際に使えるポート数が 240 で、飛び飛びである | CPE の状態表示 / 実測 | |
| V5 | DS-Lite で IPv4 が通る | `run-checks.sh` | |
| V6 | `run-checks.sh` が全項目 PASS する | 実行 | |
| V7 | MTU の実測値が 1460(encaplimit ありなら 1452)になる | `ping -M do -s ...` | |

### 3.4 トラブル再現レシピ(サイクル 5)

| # | 仮説 / 未確認 | 懸念 | 結果 |
|---|---|---|---|
| R3a | R3 が再現する | **BR はポート制限を強制しない**。enforce 用 nft の投入が必要 | |
| R4a | R4 でポート開放が本当に効かない | — | |
| R5a | R5(MTU ブラックホール)が再現する | **OpenWrt 既定の `mtu_fix`(MSS clamp)で潰されて再現しない可能性** | |
| R6a | R6(DNS フォールバック遅延)が再現する | **`curl` 自身が Happy Eyeballs で ~200ms でフォールバックし、症状が出ない可能性** | |
| R1a | R1(RA 方式に PD 設定)が再現する | — | |
| D1 | DUID DROP クラスを有効化すると無応答になる | 既定では無効(opt-in) | |

### 3.5 実機 / CML(サイクル 4)

| # | 仮説 / 未確認 | 確認方法 | 結果 |
|---|---|---|---|
| H1 | 892FJ が IPoE(RA/PD)の CE として動く | [research-notes.md](research-notes.md) §4 の表に従って設定 | |
| H2 | 892FJ が DS-Lite の B4 として動く | 同上 | |
| H3 | CML の Cat8000v で MAP-E CLI が使える | `nat64 ?` / `nat64 map-e ?` / `nat64 provisioning ?`([proxmox-prototype.md](proxmox-prototype.md) §4.1)。**タイムボックス 30 分** | |

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
| 2 | Box バンドル(アーカイブ + イメージ + ログ + 予備の VM エクスポート)を作る | 中 | サイクル 6 |
| 3 | ルールベースの本格 BR(FD.io VPP `map` プラグイン)への差し替え | 低 | 必要になったら |
| 4 | 複数 CE の同時検証(Kea の DUID 予約で複数面化) | 低 | 勉強会でペア演習が回らないと判明したら |
| 5 | 検証マトリクス No.7(VPN)の追加構築 | 低 | 案件で必要になったら |
