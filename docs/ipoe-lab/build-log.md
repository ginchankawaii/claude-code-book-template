# 構築ログ / PDCA 記録

ラボは**一度も動かしていません**。動かせば必ず設計と食い違う箇所が出ます。
それを場当たりに直して忘れるのではなく、**1 サイクルずつ記録して次に活かす**ためのファイルです。

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
| 2 | 4 台の Linux に setup スクリプトを流し、IPv6 が降りるところまで | **完了**(成功条件 6 件すべて達成) | 約 5 分(setup 計 2.6 分 + CPE 設定) | `ssh` は使わなくても stdin を吸うので `while read` の中では `-n` が必須。OpenWrt の `uclient-fetch` は AAAA を選ぶと A へフォールバックしない。PPPoE を上げると netifd が物理NICの IPv6 を無効化するが、**RA 自体は届いている** |
| 3 | MAP-E / DS-Lite で IPv4 が通り、`run-checks.sh` が PASS するまで | **次はこれ**(前提の V2 は解決済み) | — | — |
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
debug1: Offering public key: /c/Users/penan/.ssh/id_ed25519 ED25519 SHA256:xKpF...
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

`setup-inet.sh` は DNS を **203.0.113.53 (IPv4)** で作っており、`2001:db8:cafe::53` は存在しない。
`2001:418:3ff::1:53` は実網 NTT の DNS で、Kea が配っている値がそのまま使われている。
**IPv6 が降りるところまで**というサイクル 2 の範囲では影響しないが、
`run-checks.sh` の名前解決項目はここで落ちる可能性が高い(バックログ 8)。

**⑪ ホスト側が数コミット古かった(前提どおり)**

`/root/ipoe-lab/lab/ipoe/` に `client/` も `deploy.sh` も無かった。`deploy.sh` で解消。

#### Act

**修正したファイルと commit**:

| ファイル | 内容 | commit |
|---|---|---|
| `lab/ipoe/deploy.sh` | ループ内 `ssh` に `-n` を追加(不具合①) | `ae873bc` |
| `lab/ipoe/bras/setup-bras.sh` | `install -D` で `/etc/ppp` ごと作る(不具合②) | `f6a6439` |
| `lab/ipoe/proxmox/owrt-console.sh` | **新規**。シリアルの unix ソケットに socat して非対話でコマンドを流す(不具合④) | 下記 |
| `docs/ipoe-lab/build-log.md` | このセクション。トラッカー更新 | 下記 |

**`owrt-console.sh` の設計メモ**:

- 終了マーカーの `echo` を末尾に付け、`awk` がマーカー行を見たら `exit` する。
  `awk` が閉じると `socat` が SIGPIPE で死ぬので、**固定 sleep で待たずに「終わった時点で」戻る**
- マーカーは**クォート付きで送る**。こうすると端末エコー行は
  `root@OpenWrt:~# echo "__OWRT_DONE_9010__"` になり行頭がマーカーにならないので、
  `index($0,m)==1` が「コマンドのエコー」ではなく「実際の出力」だけに当たる
- 多重クォート(`ssh` → `bash` → `socat` → `ash`)は壊れやすい。
  **コマンドはファイルに書いて stdin で渡す**のが確実(`grep -E "zone\[[0-9]\]"` で実際に詰まった)
- 先頭に Ctrl-C(`\003`)を送ると、前回の失敗で継続プロンプトに落ちていても復帰できる

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

### サイクル 3〜6

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
| B4 | `bridge-mcsnoop 0` が実際に効いて RA が通る | VM 間で `ping6` / `tcpdump` で RA 受信 | **OK** サイクル 2 で確定。RA(`ff02::1`)と DHCPv6(`ff02::1:2`)のマルチキャストが両方通り、RS→RA と Solicit→Advertise→Request→Reply を観測 |
| B5 | `detect-ifs.sh` の MAC 判定が Ubuntu 24.04 で機能する | VM 内で `. detect-ifs.sh; echo $ACCESS_IF` | **OK** 実測 NIC 名は `eth0`/`ens19`/`ens20` で想定と違ったが、MAC 判別なので 4 パターンすべて解決。`LAN_IF`(02:c1)を追加 |
| B6 | `import-from`(PVE 9.1)でディスク取り込みが通る | provision.sh の出力 | **OK** 5 台すべて作成・起動できた |
| B7 | ホストからイメージをダウンロードできる(`wget` で Ubuntu 600MB / OpenWrt 50MB) | provision.sh の出力 | **OK** Ubuntu 595MB/46秒、OpenWrt 13MB/8秒。ただし展開で gzip 終了コード 2 → スクリプト即死(修正済み) |
| B8 | `nic11` は何に使われているか(QNAP 10G と推定)。サイクル 4 で誤って使わないため | `ip -4 addr show nic11` / `cat /etc/network/interfaces` | |
| B9 | `snippets` 対応ストレージが無く guest-agent が入らない | 完了メッセージの注意書き | **該当**。`provision.sh ips`(IPv6 リンクローカル)で代替。guest-agent が必要なら `pvesm set local --content iso,vztmpl,backup,snippets` + 作り直し |
| B10 | `provision.sh ips` が 4 台(+OpenWrt)を検出できる | `./provision.sh ips` | **OK**(Linux 4 台)。OpenWrt は管理NICが無いので対象外。net0 決め打ちのバグを修正済み |
| B11 | 4 台すべてに SSH で入れる | `ssh labadmin@fe80::…%vmbr0` | **OK** 鍵認証で 4 台とも成功 |
| B12 | クライアント (9004) の LAN 側が設定される | `setup-client.sh` → `ip route show default` | **OK** 12 秒で完走。`ens19` に `192.168.1.247/24` と `2001:db8:100a:500:c1:ff:fe00:4/64`、既定経路は v4/v6 とも metric 50 で CPE 側を向いた。管理は リンクローカルで継続できた |

### 3.2 IPv6 の配布(サイクル 2)

| # | 仮説 / 未確認 | 確認方法 | 結果 |
|---|---|---|---|
| N1 | `setup-ngn.sh` の `apt-get` が管理経路経由で通る | 実行して完走するか | **OK** 37 秒で完走。ただし `getent hosts` は AAAA しか返さず、v6 は 3ms で ENETUNREACH → apt が IPv4 に落ちて成功。**v6 既定経路が「無い」から速く失敗した**のが効いている(OpenWrt との差は Do/Check ⑤) |
| N2 | Kea が起動する(過去に設定ミスで起動しなかった箇所) | `systemctl status kea-dhcp6-server` | **OK** `active (running)`。`kea-dhcp6 -t` の構文検証も通過 |
| N3 | Kea の `leases6_committed` フックが実際に経路を入れる | PD 後に `ip -6 route` に `via <CE>` が出るか | **未確定**。PD 自体は成立したが、NGN 側の復路は `setup-ngn.sh` が入れる `2001:db8:100a:500::/56 dev ens19`(on-link)で足りており、フック由来の `via <CE>` は確認していない。**サイクル 3 で IPv4 が通らない場合はここを疑う** |
| N4 | AppArmor 許可と `CAP_NET_ADMIN` が効いている | 上が失敗したら `journalctl -u kea-dhcp6-server` と `dmesg \| grep apparmor` | **該当なし**。`kea-dhcp6-server.service.d/pd-route.conf` が読み込まれ、Kea は正常起動。N3 が未確定のため効いているかの証明は保留 |
| N5 | RA 方式で CPE に /64 が降る | `ip -6 addr` / `tcpdump` | **OK** `eth1` に `2001:db8:1014:300:ac:ff:fe00:10/64`、既定経路も `default from 2001:db8:1014:300::/64` |
| N6 | PD 方式で CPE に /56 が降る | 同上 + `ip -6 route` | **OK** `ubus` で `2001:db8:100a:500::/56` を確認。`br-lan` には `/60` が切り出される(`ip6assign '60'` のため。条件文の「/64」は誤り) |
| N7 | **PPPoE 接続中も NGN の RA が CPE WAN に届く**(教材の演習 1-A の前提) | Phase 0 状態で `ip -6 addr` | **OK(ただし要注意)** RA は PPPoE 中も `eth1` に届く(tcpdump で実証)。**が、netifd が `disable_ipv6=1` にするため CPE 側が受け取れない**。`network.wan_dev` に `ipv6 '1'` を入れると PPPoE と IPoE が同居できる(Do/Check ⑧) |
| N8 | `accel-ppp` の `chap-secrets` 認証が通る(モジュール未ロードで全失敗した経緯あり) | `accel-cmd show sessions` | **OK(方式は PAP)** `accel-cmd show sessions` に `user1@isp-a.example / 100.64.1.0 / active`。ネゴされたのは CHAP ではなく **PAP** なので教材の記述に注意(Do/Check ⑨) |

### 3.3 IPv4 over IPv6(サイクル 3)

| # | 仮説 / 未確認 | 確認方法 | 結果 |
|---|---|---|---|
| V1 | `ip -6 tunnel add ... mode ipip6` が実際に張れる | `setup-map-br.sh` 実行 → `ip -6 tunnel show` | |
| V2 | OpenWrt に `map` / `ds-lite` パッケージをどう入れるか(**ラボ内にインターネットが無い**) | 管理経路 or 事前導入イメージ。**手順を確定して記録すること** | **解決**。`qm set 9010 --net2 virtio,bridge=vmbr0` は**ホットプラグで効き再起動不要**。ただし `opkg` は `ifdown wan6` してからでないと通らない(uclient-fetch が AAAA を選び A に落ちない)。`map - 7` / `ds-lite - 9` / `tcpdump-mini` 導入済み。手順全文は サイクル 2 の Do 手順 5 |
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
| 6 | `setup-bras.sh` の再実行耐性(自分で既定経路を奪うので 2 回目の `apt-get` が死ぬ)。`setup-client.sh` と同じく「経路を切り替える前に必要なものを揃える」形にする | 中 | サイクル 3 完了後 |
| 7 | OpenWrt の rootfs がイメージ拡張(2G)に追従しておらず 98MB のまま。パーティション/FS の拡張まで `provision.sh` でやる | 中 | 追加パッケージで容量不足が出たら |
| 8 | ラボ内に IPv6 の DNS(`2001:db8:cafe::53`)が無く、Kea が配る `2001:418:3ff::1:53`(実網 NTT)も当然届かない。`run-checks.sh` の名前解決が落ちる可能性 | 高 | サイクル 3 の冒頭で確認 |
