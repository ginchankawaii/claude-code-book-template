# 会社 VMware 環境 構築ランブック(手動作業用)

> **このファイルだけを見て上から順に実行すれば完成する**ことを目標にしています。
> 会社環境では AI 支援が使えないため、判断が必要な箇所には**推奨をひとつ**書いてあります。
>
> 記載内容は自宅 Proxmox での実走(サイクル 1〜3・5)で**実際に動いたもの**です。
> 詰まった箇所は §9 に「症状 → 原因 → 対処」で残してあります。
> 経緯の全文は [build-log.md](build-log.md) にあります。

## 会社環境の前提(自宅との違い)

| | 自宅 Proxmox | **会社 VMware** |
|---|---|---|
| CML | あり(Cat8000v を CE に使える。MAP-E CLI 実装ありを確認済み) | **なし** |
| 実機 | 892FJ のみ | **豊富にある** ← 検証の本命 |
| CE 調達 | OpenWrt VM / CML / 892FJ | **物理ポートに実機を挿す** + OpenWrt VM |

**会社側では「物理ポート経由で実機を接続する」手順が必須です。**
ポートグループのセキュリティ 3 項目「承諾」を落とすとここで確実に詰まるため、**省略不可**として扱います。

**同時に検証できる CE は 1 台です**(BR/AFTR が静的トンネルのため)。実機は 1 台ずつ順番に。
入れ替え手順は [build-log.md §4](build-log.md) を参照。

**所要時間の目安**(自宅実測。VMware では VM 作成が手動になるぶん増えます):

| 工程 | 実測 |
|---|---|
| VM 6 台の作成〜起動 | 約 3 分(自宅はスクリプト。VMware は手動のぶん増えます) |
| Linux 5 台の setup スクリプト | 合計 約 2.5 分 |
| CPE(OpenWrt)の設定 | 約 10 分 |
| 動作確認(`run-checks.sh`) | 約 1 分 |

---

## 0. 事前準備(必要な情報・権限・払い出し依頼)

- [ ] vSphere で **ポートグループを作成できる権限**
- [ ] **空き物理 NIC を 1 本**確保(実機 CPE 収容用。PG-ACCESS のアップリンクにする)
- [ ] **静的 MAC アドレスの割当が許可されている**こと(§3 で使います)
  - 許可されない場合は §3 の代替手順(環境変数で NIC 名を直接指定)を使います
- [ ] 物理 L2 スイッチ 1 台(特別な設定は不要。MTU 1500 のまま)
- [ ] Ubuntu Server 24.04 クラウドイメージ
      `https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.img`
- [ ] OpenWrt x86/64 のイメージ
      `https://downloads.openwrt.org/releases/24.10.0/targets/x86/64/openwrt-24.10.0-x86-64-generic-ext4-combined.img.gz`
- [ ] リポジトリの `lab/ipoe` 一式(§4 の方法で持ち込みます)

> **検証機を社内 LAN に足を出してよいかを先に確認してください。**
> OpenWrt に `map` / `ds-lite` を導入する工程(§5.4)で、**一時的に社内 LAN への
> 接続が必要**になります。ポリシー上不可の場合は、パッケージを事前導入した
> イメージを用意する必要があります(§9-G)。

---

## 1. vSwitch / ポートグループの作成

ポートグループを **5 つ**作ります。

| PG | 用途 | アップリンク |
|---|---|---|
| PG-ACCESS | アクセス回線 L2(NGN-SIM / BRAS / CPE の WAN) | **物理 NIC(§2)** |
| PG-CORE | NGN 網内(IPv6 のみ) | なし(内部専用) |
| PG-INET | 模擬インターネット | なし(内部専用) |
| PG-CLIENT | CPE 配下の LAN(CPE の LAN 側 ⇔ 検証クライアント) | なし(内部専用) |
| 管理 | 各 VM の 1 枚目 NIC | 既存の管理ネットワークでよい |

**PG-ACCESS のセキュリティ 3 項目を「承諾」にします(必須)**:

- 無差別モード(Promiscuous mode): **承諾**
- MAC アドレス変更(MAC address changes): **承諾**
- 偽装転送(Forged transmits): **承諾**

> **これを落とすと PPPoE と実機ブリッジが動きません。** 症状は「PADI に応答がない」
> 「実機から RA が見えない」など、原因が遠く追いにくい形で出ます。

> **Proxmox との差**: Linux ブリッジでは `bridge-mcsnoop 0` が必要でしたが、
> vSwitch には該当設定がありません。VMware の標準 vSwitch は IGMP/MLD snooping を
> しないため、RA / DHCPv6 のマルチキャストはそのまま通ります。

---

## 2. 物理 NIC を PG-ACCESS のアップリンクに割当

```
[実機ルータ(お客様同型機)] ─┐
[HGW実機(あれば)] ──────────┼─[物理スイッチ]──[ESXiホストの空き物理NIC]
[検証用PC] ─────────────────┘                        │
                                                     └ この物理NICを PG-ACCESS の
                                                       アップリンクに割り当てる
```

- 物理スイッチは**普通の L2 スイッチでよい**(特別な設定不要、MTU 1500 のまま)
- 検証面を複数持ちたい場合は、物理スイッチを VLAN で分け、PG 側も VLAN ID 付きの
  ポートグループを複数作れば、1 本の物理 NIC で複数のアクセス網を収容できます

---

## 3. VM の作成

**6 台**作ります。Linux VM 5 台は 1 枚目 NIC(net0)を管理ネットワークに繋いでください。
**OpenWrt-CE だけは例外です**(下の警告を必ず読んでください)。

| VM | vCPU/RAM | net0 | net1 | net2 | 役割 |
|---|---|---|---|---|---|
| NGN-SIM | 2 / 2GB | 管理 | PG-ACCESS | PG-CORE | RA / DHCPv6-PD 配布 |
| VNE | 2 / 2GB | 管理 | PG-CORE | PG-INET | MAP-E BR + DS-Lite AFTR |
| INET-SIM | 1 / 1GB | 管理 | PG-INET | — | 模擬インターネット(Web / DNS) |
| BRAS | 2 / 2GB | 管理 | PG-ACCESS | PG-INET | PPPoE 終端(accel-ppp をソースビルドするため 2GB 必須) |
| LAB-CLIENT | 1 / 1GB | 管理 | PG-CLIENT | — | 検証クライアント(`run-checks.sh` 実行用) |
| **OpenWrt-CE** | 1 / 512MB | **PG-CLIENT(LAN)** | **PG-ACCESS(WAN)** | — | リファレンス CPE。**管理 NIC は付けない** |

> ### ⚠ OpenWrt-CE の NIC 順序を間違えると、管理 LAN に DHCP サーバを撒きます
>
> OpenWrt x86/64 の既定は **eth0 = LAN(`192.168.1.1`、DHCP サーバ有効) / eth1 = WAN** です。
> **1 枚目を管理ネットワークに繋ぐと、会社の管理 LAN に `192.168.1.1` と DHCP サーバが
> 立ち上がります。** 必ず **net0 = PG-CLIENT / net1 = PG-ACCESS** の順で作ってください。
>
> 管理 NIC は付けません。§5.4-a でパッケージを導入するときだけ**一時的に**
> 3 枚目(eth2)として足し、終わったら無効化します。

> **LAB-CLIENT を省略しないでください。** 管理 LAN に直結したホストから `run-checks.sh` を
> 流すと、通信が CPE を通らずに抜けて **「PASS したのに何も検証できていない」**
> という最悪の偽陽性になります。

> **VNE と INET-SIM は分けてください(同居させない)。** 自宅プロトタイプでは VM 数を
> 減らすため 1 台に同居させましたが、その構成では **DS-Lite の AFTR による網側 NAT が
> 効きません**(宛先がローカル配送になり `oifname` 条件の masquerade が当たらないため)。
> 「DS-Lite は網側 NAT だからポート開放できない」という**教材の中心論点が実演できず**、
> [test-matrix.md](test-matrix.md) の R4 も再現しません。詳細は
> [build-log.md](build-log.md) のバックログ 9。

### Linux VM 5 台の初期設定

自宅では cloud-init が自動でやっていた部分です。**会社では手動になります。**
5 台すべてに以下を済ませてから §4 に進んでください。

- [ ] 作業用ユーザを作成し、`sudo` を許可する(以降の手順は `sudo` 前提です)
- [ ] `openssh-server` を導入し、起動を確認(`systemctl is-active ssh`)
- [ ] **管理 NIC(net0)だけ** DHCP で疎通させる。
      ラボ側 NIC(net1 以降)は**設定しないでください** — setup スクリプトが上げます
- [ ] `apt-get update` が通ることを確認(setup スクリプトが冒頭で使います)

> **LAB-CLIENT だけは順序に注意。** `setup-client.sh` は既定経路を CPE 側へ寄せるため、
> 実行後は `apt` が使えなくなります。**必要なパッケージは先に入れてください**
> (スクリプト自身も `curl` / `ping` は事前導入しますが、追加で欲しいものがあれば先に)。

### 役割別 MAC の設定(重要)

スクリプトは **MAC から NIC の役割を判別**します。NIC 名(`ens192` 等)は環境で変わるためです。
各 VM の NIC に、以下の規則で**静的 MAC** を設定してください。

| MAC の先頭 | 役割 | 例(末尾は VM 番号) |
|---|---|---|
| `02:ac:*` | PG-ACCESS | `02:ac:00:00:00:01`(NGN-SIM) |
| `02:c0:*` | PG-CORE | `02:c0:00:00:00:01`(NGN-SIM) |
| `02:1e:*` | PG-INET | `02:1e:00:00:00:02`(VNE / INET-SIM) |
| `02:c1:*` | PG-CLIENT | `02:c1:00:00:00:04`(LAB-CLIENT) |

**静的 MAC が許可されていない場合の代替**: 各スクリプトを実行するとき、環境変数で
NIC 名を直接指定します。`ip -br link` で名前を確認してから:

```bash
sudo ACCESS_IF=ens192 CORE_IF=ens224 ./ipoe/ngn/setup-ngn.sh pd
```

### OpenWrt-CE のディスク

イメージを 2G に拡張しておきます。

```bash
gunzip openwrt-24.10.0-x86-64-generic-ext4-combined.img.gz
qemu-img resize -f raw openwrt-*.img 2G
# vmdk に変換して VM にアタッチ
qemu-img convert -f raw -O vmdk openwrt-*.img openwrt-ce.vmdk
```

> **注意**: これは**イメージファイル**を 2G にするだけで、中のファイルシステムは
> **98MB のまま**です(自宅実測: `df -h /` → `/dev/root 98.3M`)。
> `map` / `ds-lite` / `tcpdump-mini` までは収まります(使用 27MB)。
> それ以上入れる場合は OpenWrt 側でパーティション拡張が別途必要です。

---

## 4. スクリプトの持ち込み

`git` が入っていない環境でも通る方法です(自宅の Proxmox ホストがそうでした)。

```bash
cd /root
curl -fsSL "https://github.com/<owner>/<repo>/archive/refs/heads/<branch>.tar.gz" | tar xz
mv -f <repo>-<branch をダッシュ化した名前> ipoe-lab
chmod +x ipoe-lab/lab/ipoe/*/*.sh
```

各 Linux VM に `lab/ipoe` ディレクトリごとコピーします。SSH が使えるなら:

```bash
tar cz -C <リポジトリ>/lab ipoe | ssh <user>@<VMのIP> 'tar xz -C ~'
```

> **以降、VM 上ではパスが `~/ipoe/...` になります。**
> この手順書のコマンドはその前提で書いてあります。

---

## 5. 各 VM のセットアップ

**この順序で実行してください。** 括弧内は自宅での実測時間です。

### 5.1 NGN-SIM(約 37 秒)

```bash
sudo ./ipoe/ngn/setup-ngn.sh pd     # ひかり電話あり相当(DHCPv6-PD, /56)
# sudo ./ipoe/ngn/setup-ngn.sh ra   # ひかり電話なし相当(RA, /64)に切り替える場合
```

期待される出力(末尾):

```
[NGN-SIM] PD モード (ひかり電話あり相当, 2001:db8:100a:500::/56 を委譲)
  この /56 での MAP-E 期待値: 共有IPv4=198.51.100.10, PSID=5
```

確認:

```bash
systemctl is-active radvd kea-dhcp6-server
# → active
# → active
```

### 5.2 INET-SIM(約 39 秒)

```bash
sudo ./ipoe/inet/setup-inet.sh       # 模擬インターネット(Web/DNS)
```

```
[INET-SIM] http://203.0.113.80 / http://[2001:db8:cafe::80] / DNS 203.0.113.53
  MTU/MSS 検証用: /big.bin (5MB)
```

### 5.3 VNE(約 4 秒)

```bash
sudo ./ipoe/vne/setup-map-br.sh      # MAP-E BR
sudo ./ipoe/vne/setup-aftr.sh        # DS-Lite AFTR(両方同時起動でよい)
```

```
[VNE] MAP-E BR 起動: BR=2001:db8:9999::1, CE=2001:db8:100a:500:0:c633:640a:5, 共有IPv4=198.51.100.10
[VNE] DS-Lite AFTR 起動: AFTR=2001:db8:8888::1, B4=2001:db8:100a:500::1
```

> **片方だけを検証するときは、もう片方を止めてください。**
> 残しておくと旧 CE 宛のトンネルが生き続け、切り分けを汚します。
>
> ```bash
> sudo ./ipoe/vne/setup-aftr.sh stop      # DS-Lite を止める (MAP-E だけ検証)
> sudo ./ipoe/vne/setup-map-br.sh stop    # MAP-E を止める (DS-Lite だけ検証)
> ```

### 5.4 OpenWrt-CE

コンソールで操作します(管理 NIC を持たないため)。

**(a) `map` / `ds-lite` の導入** — 一時的に社内 LAN への足が必要です

```sh
# ① 管理NICを一時的に足す (vSphere で「管理」PG の NIC を 1 枚追加。再起動不要)
# ② OpenWrt 側:
uci set network.mgmt=interface
uci set network.mgmt.device='eth2'
uci set network.mgmt.proto='dhcp'
uci commit network
/etc/init.d/network reload
#    ※ 既に ULA が配られてしまっている場合は reload では戻りません。**CPE を再起動**してください
uci add_list firewall.@zone[1].network='mgmt'     # zone[1] = wan。DHCPサーバは立てない
uci commit firewall
/etc/init.d/network reload && /etc/init.d/firewall reload

# ③ ラボの IPv6 を一時的に落としてから opkg (これをしないと必ず失敗します。理由は §9-A)
ifdown wan6
opkg update
opkg install map ds-lite tcpdump-mini
ifup wan6

# ④ 検証中は管理NICを無効化する (社内 LAN へ抜ける偽陽性を防ぐ)
uci set network.mgmt.disabled='1'
uci commit network
/etc/init.d/network reload
```

**(b) CPE に必ず入れる 4 つの設定** — 入れないと必ず詰まります

```sh
# ① PPPoE と IPoE を同居させる (これが無いと PPPoE を上げた瞬間に IPv6 が全部消えます)
uci set network.wan_dev=device
uci set network.wan_dev.name='eth1'
uci set network.wan_dev.ipv6='1'

# ② 送信元制限付きの既定経路をやめる (これが無いと名前解決が死にます。§9-B)
uci set network.wan6.sourcefilter='0'
uci commit network

# ③ DNS リバインド保護からラボのドメインを除外する (§9-C)
uci add_list dhcp.@dnsmasq[0].rebind_domain='lab.example'
uci commit dhcp

# ④ ULA を無効化する (これが無いと IPv6 が「たまに全滅」します。§9-I)
#    OpenWrt は既定で ULA (fd00::/8) を生成し LAN に配ります。
#    委譲プレフィックス由来の GUA が deprecated になった瞬間、RFC 6724 の
#    送信元選択が ULA にフォールバックし、ラボ内に ULA の復路が無いため
#    IPv6 だけが黙って全滅します (IPv4 は MAP-E トンネル経由なので無傷)。
#    実網の NGN も ULA は配りません。
uci set network.globals.ula_prefix=''
uci commit network
/etc/init.d/dnsmasq restart
```

**(c) 方式ごとの WAN 設定** — 検証する方式のものだけ有効にします

```sh
# --- MAP-E ---
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

# --- DS-Lite ---
uci set network.wandsl=interface
uci set network.wandsl.proto='dslite'
uci set network.wandsl.peeraddr='2001:db8:8888::1'
uci set network.wandsl.mtu='1460'
uci set network.wandsl.tunlink='wan6'
uci commit network
uci add_list firewall.@zone[1].network='wandsl'
uci commit firewall
/etc/init.d/network restart

# --- PPPoE (Phase 0 の再現用) ---
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
```

**方式の切替は `disabled` で行います**(消さずに残しておくと戻すのが速い):

```sh
uci set network.wanmap.disabled='1'    # MAP-E を止める
uci set network.wandsl.disabled='0'    # DS-Lite を使う
uci commit network && /etc/init.d/network restart
```

**MAP-E の期待値照合**(ここが最初の確認ポイント):

| 項目 | 期待値(PD 方式) | 確認コマンド |
|---|---|---|
| 共有 IPv4 | `198.51.100.10/32` | `ip -4 addr show dev map-wanmap` |
| 先頭ポートブロック | `4176-4191` | `nft list ruleset \| grep snat` |
| MTU | 1460 | `ip link show map-wanmap` |

**RA 方式に切り替えた場合は期待値が変わります**([build.md](build.md) §3 の表)。
NGN 側を `ra` にしたら **BR も張り替えが必要**です:

```bash
sudo CE_MAP_ADDR=2001:db8:1014:300:0:c633:6414:3 CE_SHARED_V4=198.51.100.20 \
  ./ipoe/vne/setup-map-br.sh
```

### 5.5 BRAS(約 66 秒。accel-ppp をソースビルドするため)

```bash
sudo ./ipoe/bras/setup-bras.sh
```

期待される出力(末尾):

```
[BRAS] PPPoE 待受開始 (<NIC名>, AC=LAB-BRAS)。セッション確認: accel-cmd show sessions
```

> **注意**: このスクリプトは自分で既定経路を INET-SIM 側へ奪います。
> **2 回目以降の実行では冒頭の `apt-get update` がタイムアウトします**(数分固まります)。
> パッケージ導入済みなら待てば完走します。急ぐなら先に
> `sudo ip route del default via 203.0.113.80` してください。

### 5.6 LAB-CLIENT(約 12 秒)

```bash
sudo ./ipoe/client/setup-client.sh
```

**出力の最後に次の 2 行が出ることを確認してください。**ここが `注意:` になっている場合、
以降の検証結果は信用できません。

```
[client] OK: 既定経路が CPE 側 (<NIC名>) を向いています
[client] OK: LAN 側にグローバル IPv6 が付いています (RA 受信できている)
```

> 実行後、このクライアントからは**本物のインターネットに出られなくなります**
> (ラボとしては正しい状態)。管理は IPv6 リンクローカルで継続できます。

---

## 6. 動作確認

**LAB-CLIENT で**実行します。

```bash
# 期待する出口アドレスを必ず渡してください。渡さないと「疎通はしているが
# 意図した経路ではない」状態 (§9-H) を見逃します
EXPECT_SRC4=198.51.100.10 ./ipoe/tests/run-checks.sh | tee $(date +%Y%m%d-%H%M)-checks.log
```

| 検証する方式 | `EXPECT_SRC4` に渡す値 |
|---|---|
| MAP-E(PD 方式 / ひかり電話あり) | `198.51.100.10` |
| MAP-E(RA 方式 / ひかり電話なし) | `198.51.100.20` |
| DS-Lite | `203.0.113.1`(AFTR で NAT された後のアドレス) |
| PPPoE(Phase 0) | **`203.0.113.2`**(BRAS が INET 側へ masquerade するため。`bras-nat` を削った「ISP NAT なし構成」のときだけ `100.64.1.x` になります) |

**期待される出力**(`EXPECT_SRC4` 指定時は **`PASS=11 FAIL=0`**。未指定なら 10):

```
INFO: IPv6 の送信元に 2001:db8:100a:500::cf0 を使います
--- 疎通 ---
PASS: IPv4 ping (203.0.113.80)
PASS: IPv6 ping (2001:db8:cafe::80)
--- DNS ---
PASS: A 解決 (www.lab.example)
PASS: AAAA 解決 (www.lab.example)
--- HTTP 到達性 (応答に出口アドレスが表示される) ---
lab-inet OK
src: 198.51.100.10          ← MAP-E なら共有 IPv4 が出る (ここが確認ポイント)
host: 203.0.113.80
PASS: HTTP over IPv4
PASS: HTTP over IPv6
--- 大サイズ TCP 転送 ---
PASS: TCP 5MB over IPv4
PASS: TCP 5MB over IPv6
--- フラグメント ---
PASS: IPv4 fragment (2000B)
PASS: IPv6 fragment (2000B)
--- MTU 実測 ---
INFO: payload 1472 不可
INFO: IPv4 パス MTU >= 1460 (payload 1432 通過)     ← 1460 が期待値
--- 出口アドレス (意図した経路を通っているか) ---
INFO: 出口 IPv4 = 198.51.100.10 / 出口 IPv6 = 2001:db8:100a:500::cf0
PASS: 出口 IPv4 が 198.51.100.10
--- DNS フォールバック体感 ---
INFO: http://www.lab.example/ 所要 41 ms (rc=0)
=== 結果: PASS=11 FAIL=0 ===
```

**`src:` の行がいちばん重要です。** ここが共有 IPv4(`198.51.100.10`)になっていれば
MAP-E が成立しています。クライアントの私設アドレスがそのまま出ている場合は
CPE を通っていない可能性があります(§9-F)。

---

## 7. スナップショット取得

**全 VM を「メモリ込み」で取得します。** 障害注入や壊す系の検証後に数秒で戻せることが、
このラボの価値の半分です。

> setup スクリプトが投入するアドレス・経路・トンネル・nft は**ランタイム設定**です
> (永続なのは sysctl と systemd unit のみ)。電源 OFF からの復元や再起動後は
> **該当 VM の setup スクリプトを再実行**してください。

---

## 8. 実機 CPE の接続と検証

> **このセクションだけで完結するように書いてあります。**他のファイルを開かずに進められます。

### 8.0 始める前のチェック(5 項目)

- [ ] **旧 CE を止める。** `/56` は 1 本、BR/AFTR のトンネルは 1 対向しかありません。
      OpenWrt-CE を繋いだままリースを消すと、Renew の速いほう(ほぼ確実に OpenWrt)が
      唯一の `/56` を取り直し、実機に PD が降りません
      → Proxmox なら `qm stop 9010`、VMware なら VM を停止
- [ ] **Kea の DROP クラスが無効であることを確認。**有効のままだと、実機の DUID 種別次第で
      **PD が無応答**になります(エラーも出ないので追えません)
      → NGN-SIM で `grep -c '^ *"client-classes"' /etc/kea/kea-dhcp6.conf` が `0` であること
- [ ] **物理 NIC が PG-ACCESS のアップリンクに入っていること**(§2)。
      Proxmox で既にラボを構築済みの場合は
      `ACCESS_UPLINK=<物理NIC> ./provision.sh` を再実行すると既存ブリッジに追加されます
- [ ] **検証クライアントをどうするか決める**(§8.1)
- [ ] 実機のコンソールケーブル(9600/8/N/1)
- [ ] **`lab/ipoe/tests/` をクライアント PC にコピー**(Windows なら `run-checks.ps1`、Linux なら `run-checks.sh`)

### 8.1 検証クライアントの用意(先に決めること)

`run-checks` は **CE の配下**で実行しないと意味がありません。
実機を CE にすると LAB-CLIENT(仮想)は OpenWrt の LAN 側にいるので**使えなくなります**。

**Windows PC で問題ありません。** Windows 用の `run-checks.ps1` を用意してあります。

| 方式 | 必要なもの | 実行するもの |
|---|---|---|
| **(a) Windows PC を実機の LAN ポートに直結**(推奨) | Windows 10 1803 以降 | `lab/ipoe/tests/run-checks.ps1` |
| (b) Linux PC を直結 | 任意の Linux | `lab/ipoe/tests/run-checks.sh` |
| (c) 仮想クライアントを実機配下に入れる | **2 本目の物理 NIC** | `run-checks.sh` |

> **(c) は物理 NIC がもう 1 本要ります。**§0 のチェックリストは PG-ACCESS 用の 1 本しか
> 数えていないので、(c) を選ぶなら追加で確保してください。**(a) がいちばん簡単です。**

#### Windows PC 側の設定(物理接続だけでは通信しません)

1. **有線 NIC を「自動取得」にする**(既定ならそのまま)。
   892FJ 側で DHCP を配る設定を §8.2 に入れてあります

   ```powershell
   # 手動設定が残っている場合は自動取得に戻す (管理者権限の PowerShell)
   Get-NetAdapter                                          # 対象の ifIndex を確認
   Set-NetIPInterface -InterfaceIndex <N> -Dhcp Enabled
   Remove-NetIPAddress -InterfaceIndex <N> -Confirm:$false -ErrorAction SilentlyContinue
   Remove-NetRoute     -InterfaceIndex <N> -Confirm:$false -ErrorAction SilentlyContinue
   Set-DnsClientServerAddress -InterfaceIndex <N> -ResetServerAddresses
   ipconfig /renew
   ```

2. **Wi-Fi は切ってください。** 有線と両方生きていると、既定経路が Wi-Fi 側に向いて
   **CPE を通らない通信を「PASS」と誤判定**します(§9-F と同じ事故)

3. アドレスが降りたか確認

   ```powershell
   ipconfig /all
   # IPv4: 192.168.100.x / デフォルトゲートウェイ 192.168.100.1
   # IPv6: 2001:db8:... のグローバルアドレスが付いていること
   ```

4. 実行(PowerShell。管理者権限は不要)

   ```powershell
   # 実行ポリシーで弾かれる場合はこの窓だけ緩める
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.un-checks.ps1 -ExpectSrc4 203.0.113.1 | Tee-Object -FilePath jitsuki-checks.log
   ```

> **`run-checks.ps1` は英語表記です。**日本語を含む `.ps1` は Windows PowerShell 5.1 で
> 文字化けし、証跡ログが読めなくなるため、意図的に ASCII だけで書いてあります。
> 判定内容は `.sh` 版とまったく同じです。

### 8.2 892FJ の初期化と設定

> **既存のゴミ設定は必ず消してください。** 前案件の NAT・ACL・DHCP・トンネルが残っていると、
> 症状が出ても「ラボが悪いのか設定が悪いのか」が切り分けられません。

#### (1) コンソール接続

| 項目 | 値 |
|---|---|
| ボーレート | 9600 |
| データ / パリティ / ストップ | 8 / なし / 1 |
| フロー制御 | なし |

#### (2) 設定を消す(erase)

```
enable
show version | include uptime|Version        ! 念のため機種と版数を控える
write erase
```

```
Erasing the nvram filesystem will remove all configuration files! Continue? [confirm]
```

→ **Enter**

```
reload
```

```
System configuration has been modified. Save? [yes/no]:
```

→ **no**(ここで yes にすると消したはずの設定が書き戻ります)

```
Proceed with reload? [confirm]
```

→ **Enter**。再起動後:

```
Would you like to enter the initial configuration dialog? [yes/no]:
```

→ **no**

```
Would you like to terminate autoinstall? [yes]:
```

→ **Enter**

#### (3) インターフェース名を確認する

**890 系は機種によって WAN 側のポート名が違います。**先に実物を見てください。

```
enable
show ip interface brief
```

- **LAN 側**: `FastEthernet0`〜`FastEthernet7`(スイッチポート)と `Vlan1`(SVI)
- **WAN 側**: `GigabitEthernet0` / `GigabitEthernet8` のような**ルーテッドポート**

以降は WAN を `GigabitEthernet0`、LAN を `Vlan1` として書きます。
**違っていたら読み替えてください。**

#### (4) 基本設定を入れる(コピペ可)

```
configure terminal
!
hostname LAB-892FJ
no ip domain lookup
!
line con 0
 exec-timeout 0 0
 logging synchronous
!
ipv6 unicast-routing
ipv6 cef
!
! ---- WAN: ラボのアクセス網 (PG-ACCESS) ----
interface GigabitEthernet0
 description WAN to LAB PG-ACCESS
 no ip address
 ipv6 address autoconfig default
 ipv6 enable
 no shutdown
!
! ---- LAN: 検証クライアントを繋ぐ側 ----
interface Vlan1
 description LAN for test client
 ip address 192.168.100.1 255.255.255.0
 ip tcp adjust-mss 1420
 no shutdown
!
interface FastEthernet0
 description test client
 switchport access vlan 1
 no shutdown
!
! ---- クライアントにアドレスを配る ----
ip dhcp excluded-address 192.168.100.1
!
ip dhcp pool LAN
 network 192.168.100.0 255.255.255.0
 default-router 192.168.100.1
 dns-server 203.0.113.53
!
end
write memory
```

> **`ip tcp adjust-mss 1420` は必須です。** classic IOS は PMTUD 頼みだと
> MTU ブラックホール(§9 の R5 系)を踏みます。実務でも定石です。
>
> LAN を `192.168.100.0/24` にしているのは、OpenWrt-CE の `192.168.1.0/24` と
> Proxmox 管理 LAN の `192.168.11.0/24` を避けるためです。

#### (5) WAN 側 IPv6 アドレスを確認して、こちらに知らせてください

**ここで一度止まります。**RA 方式(`autoconfig`)のアドレスは EUI-64 で決まるため、
**事前には分かりません**。実測した値で VNE 側のトンネルを張り替える必要があります。

```
show ipv6 interface GigabitEthernet0
```

```
GigabitEthernet0 is up, line protocol is up
  IPv6 is enabled, link-local address is FE80::XXXX:XXFF:FEXX:XXXX
  Global unicast address(es):
    2001:DB8:1014:300:XXXX:XXFF:FEXX:XXXX, subnet is 2001:DB8:1014:300::/64   ← これ
```

**この `2001:DB8:...` の行を教えてください。**受け取ったら私が VNE 側の AFTR を
その値で張り替えます(`sudo CE_WAN6=<値> ./ipoe/vne/setup-aftr.sh`)。

> グローバルアドレスが出ない場合は §9-E / §9-K を見てください。
> `show ipv6 interface GigabitEthernet0 | include Router advertisement` で
> RA を受けているかも確認できます。

#### (6) トンネルを張る(私が AFTR を張り替えたあと)

```
configure terminal
!
interface Tunnel0
 description DS-Lite B4
 ip address 192.0.0.2 255.255.255.248
 ip mtu 1460
 ip tcp adjust-mss 1420
 tunnel source GigabitEthernet0
 tunnel mode ipv6
 tunnel destination 2001:DB8:8888::1
 no shutdown
!
ip route 0.0.0.0 0.0.0.0 Tunnel0
!
end
write memory
```

> **NAT は入れません。** DS-Lite は網側(AFTR)が NAT します。
> ここで `ip nat` を入れると二重 NAT になり、出口アドレスの確認が無意味になります。

#### (7) 確認コマンド

```
show ipv6 interface brief
show interface Tunnel0
show ip route | include 0.0.0.0
ping 203.0.113.80                    ! ルータ自身から (Tunnel0 経由)
```

### 8.3 動作確認

§8.1 で決めたクライアントから実行します。**期待する出口アドレスを必ず渡してください。**

```bash
# Windows PC の場合 (PowerShell)
.\run-checks.ps1 -ExpectSrc4 203.0.113.1 | Tee-Object -FilePath jitsuki-checks.log

# Linux PC の場合
EXPECT_SRC4=203.0.113.1 ./run-checks.sh | tee $(date +%Y%m%d-%H%M)-jitsuki.log

```

### 8.4 機種別の可否(調査 + 自宅実測)

| 機種 | IPoE(RA/PD) | PPPoE | DS-Lite | MAP-E |
|---|---|---|---|---|
| Cisco 892FJ(classic IOS 15.x) | ○ | ○ | ○ | **×**(classic IOS に CE 機能なし) |
| IOS XE(C1100 系 / Cat8000v) | ○ | ○ | ○ | **○**(`nat64 map-e domain` / `nat64 provisioning mode jp01` を確認済み) |
| OpenWrt | ○ | ○ | ○ | ○(ただし実効 16 ポート。§9-J) |

> IOS XE の MAP-E CLI は自宅の CML(Cat8000v / IOS XE 17.15.01a)で**実装ありを確認済み**です。
> ただし確認したのは**パーサに実装があること**までで、実際のカプセル化や期待値の一致は未検証です。
> 会社の実機では `show version` と `show license boot level` を確認したうえで
> `nat64 map-e ?` を打ち直してください(`network-essentials` だと出ない可能性があります)。

## 9. トラブルシューティング(自宅で実際に踏んだもの)

### 9-A. `opkg update` が全リポジトリで失敗する

**症状**: 管理 NIC で IPv4 の到達性があるのに、`opkg update` が全部落ちる。

```
Connecting to 2a04:4e42:8c::644:80
Connection error: Connection failed
* opkg_download: ... wget returned 4.
```

**原因**: CPE が「グローバル IPv6 を持っているのに、そのアドレスでは外に出られない」状態。
OpenWrt の PD 既定経路は**送信元制限付き**で入ります。
`uclient-fetch`(OpenWrt の `wget`)は AAAA を選ぶと **A へフォールバックしません**。

**対処**: `ifdown wan6` してから `opkg`、終わったら `ifup wan6`(§5.4)。

### 9-B. ping は通るのに名前解決だけ死ぬ(その 1: CPE 側)

**症状**: `run-checks.sh` の DNS 2 項目だけが FAIL。CPE から DNS サーバに ping は通る。

```
ping -c2 2001:db8:cafe::53                → 0% packet loss
nslookup www.lab.example 2001:db8:cafe::53 → connection timed out
ip -6 route get 2001:db8:cafe::53         → Network unreachable
```

**原因**: 送信元制限付きの既定経路。**CPE 自身が発信する UDP** は送信元未定のまま
経路探索されて失敗します。ping は別経路(ICMP ソケット)なので通ってしまい紛らわしい。

**対処**: `uci set network.wan6.sourcefilter='0'`(§5.4-b)。

### 9-C. ping は通るのに名前解決だけ死ぬ(その 2: リバインド保護)

**症状**: 9-B を直しても、クライアントからの名前解決だけ失敗する。
ただし**所要時間が数秒から数十ミリ秒に変わる**(タイムアウトではなく即失敗になる)。

```
logread | grep dnsmasq
→ possible DNS-rebind attack detected: www.lab.example
```

**原因**: ラボはドキュメント用アドレス(`2001:db8::/32` / `203.0.113.0/24`)を使うため、
OpenWrt の `rebind_protection`(既定 1)が応答を破棄します。**ラボを使う限り必ず踏みます。**

**対処**: `uci add_list dhcp.@dnsmasq[0].rebind_domain='lab.example'`(§5.4-b)。

### 9-D. ping は通るのに名前解決だけ死ぬ(その 3: DNS サーバ側)

**症状**: DNS サーバ(INET-SIM)で `tcpdump` してもクエリが**見えない**。
なのにクライアントからは届いているはず。

**原因**: dnsmasq が **INET 側インタフェースしか listen していない**と、
CPE からのクエリ(NGN 経由 = **CORE 側**に着く)を黙って捨てます。
INET 側で `tcpdump` しても見えないのは、そもそも CORE 側に来ているからです。

**対処**: 現在の `setup-inet.sh` は CORE 側も listen するよう修正済みです。
手動で設定する場合は `/etc/dnsmasq.d/lab.conf` に `interface=<CORE側NIC>` を追加。

**切り分けのコツ**: DNS サーバ側は `tcpdump -i any` で見てください。
インタフェースを決め打ちすると、この種の問題は見えません。

### 9-E. PPPoE を上げた瞬間に IPv6 が全部消える

**症状**: `ifup wanppp` の後、`wan6` が上がらない。`eth1` からリンクローカルまで消える。

```
odhcp6c: Failed to send RS (Network unreachable)
cat /proc/sys/net/ipv6/conf/eth1/disable_ipv6 → 1
```

**原因**: netifd が PPPoE の搬送路にした物理 NIC の IPv6 を無効化します。
**RA 自体は届いています**(`tcpdump -ni eth1 "icmp6[icmp6type]==134"` で確認可能)。
「届かない」のではなく「受け取れない設定になる」のが問題です。

**対処**: `network.wan_dev` に `option ipv6 '1'`(§5.4-b)。

### 9-F. `run-checks.sh` が PASS するのに実は CPE を通っていない

**症状**: PASS するが、`src:` の行にクライアントの管理 LAN アドレスが出る。

**原因**: クライアントの既定経路が管理 LAN を向いたまま。

**対処**: `sudo ./ipoe/client/setup-client.sh` を実行し、
「既定経路が CPE 側を向いています」の行を確認(§5.6)。

### 9-G. 検証機を社内 LAN に出せない場合

`map` / `ds-lite` の導入(§5.4-a)には社内 LAN への一時接続が必要です。
ポリシー上不可の場合は、**パッケージを事前に導入したイメージ**を用意してください。
自宅など外に出られる環境で §5.4-a を実施し、その VM をエクスポートして持ち込みます。

### 9-I. IPv6 が「たまに全滅」する(ULA フォールバック)

**症状**: IPv4 は普通に通るのに IPv6 だけが全滅する。時間を置くと直ったり再発したりする。

**見分け方**: `run-checks.sh` が次の警告を出します(この判定を入れてあります)。

```
警告: IPv6 の送信元に ULA (fdf9:...) が選ばれています。
```

手で見るなら:

```bash
ip -6 route get 2001:db8:cafe::80      # src が fd.. なら該当
ip -6 addr show dev <LAN側NIC>          # GUA の preferred_lft が 0 = deprecated なら該当
```

**原因**: OpenWrt は既定で ULA(`fd00::/8`)を生成して LAN に配ります。委譲プレフィックス由来の
GUA が deprecated になった瞬間、RFC 6724 の送信元選択が **ULA にフォールバック**します。
ラボ内に ULA の復路は無いので、パケットは出ていくが返ってきません。
**IPv4 は MAP-E トンネル経由で送信元選択が絡まないため無傷**で、
「IPv4 は通るのに IPv6 だけ死ぬ」という紛らわしい形になります。

**対処**: §5.4-b ④ の ULA 無効化。既に配られてしまっている場合は **CPE の再起動**が必要です
(`ifup wan6` や `odhcpd restart` では戻りません)。

### 9-J. MAP-E で同時接続が 16 で頭打ちになる(OpenWrt の癖)

**症状**: 240 ポート使えるはずなのに、同時接続が 16 本で詰まる。

**原因**: OpenWrt が生成する 15 本の nft `snat` ルールが**すべて同じマッチ条件**のため、
nftables の終端判定により**先頭ブロック(4176-4191)しか使われません**。

```bash
nft list ruleset | grep ubus:wanmap    # nat 1 だけ packets が増え、nat 4 以降は 0 のまま
```

**対処**: これは**参照 CE(OpenWrt)固有の癖**であって、ラボの故障ではありません。
実機 CE では NAT エンジンがポート集合を正しく扱うはずなので、
**実機検証のときに必ず数え直してください**。240 は「割当の構造値」です。

### 9-K. IPv4 は通るのに IPv6 だけ片方向で死ぬ(復路の on-link 上書き)

**症状**: クライアントから IPv6 が出ていくが返ってこない。CPE や NGN からの ping は通る。
**時間を置く(約 37 分)と勝手に直る。**

**見分け方**: NGN-SIM で復路を見ます。

```bash
ip -6 route show | grep 100a:500
#  via fe80::...  ← 正常 (Kea のフックが入れたもの)
#  dev ens19      ← NG (on-link。これだと OpenWrt は NS に応答しないので復路が死ぬ)
```

**原因**: `setup-ngn.sh` は初期経路として on-link を置きますが、
PD 方式の正しい復路は Kea のフック(`kea-pd-route.sh`)が入れる `via <CE のリンクローカル>` です。
**NGN-SIM を再起動するとランタイム経路が消え、setup スクリプトを再実行しても
on-link のまま**になります(フックは次の Renew = 約 37 分後まで発火しません)。

**対処**: CPE 側で PD を取り直させます。

```bash
# CPE で
ifdown wan6 && ifup wan6
# NGN-SIM で確認
journalctl -t kea-pd-route -n 3      # committed ... via ... が出ること
```

### 9-L. その他の実測メモ

- **BusyBox には `timeout` と `ip -d` がありません。** CPE 上では
  `tcpdump -c <数>` と `ip link show` を使ってください
- **`accel-ppp` の認証は PAP でネゴされます。** `chap-secrets` はファイル名(認証情報ストア)
  であって認証方式名ではありません
- **CPE の `br-lan` に降りるのは `/64` ではなく `/60`**(OpenWrt 既定の `ip6assign '60'`)。
  動作としては正常です
- **DS-Lite で AFTR の NAT が効かない構成があります。** VNE と INET-SIM を同一 VM に
  同居させると、宛先がローカル配送になり `oifname` 条件の masquerade が当たりません。
  **§3 のとおり VNE と INET-SIM を分けていれば発生しません。**
  自宅プロトタイプ(同居)での実測症状は「`run-checks.sh` は PASS するのに、
  出口アドレスがクライアントの私設アドレス `192.168.1.247` のまま」でした。
  この状態では [test-matrix.md](test-matrix.md) の **R4(ポート開放不可の再現)が
  逆の結果になり得ます**(開放できてしまう)。
  **`EXPECT_SRC4=<期待する出口アドレス> ./run-checks.sh` を必ず付けて実行してください** —
  この種の偽陽性を検出できる唯一の項目です

---

## 参照

- 設計全体: [README.md](README.md)
- 構築手順の詳細(考え方): [build.md](build.md)
- 実走の全記録(症状と原因の一次情報): [build-log.md](build-log.md)
- Proxmox 側の構築記録: [proxmox-prototype.md](proxmox-prototype.md)
- 検証マトリクス / 障害再現レシピ: [test-matrix.md](test-matrix.md)
