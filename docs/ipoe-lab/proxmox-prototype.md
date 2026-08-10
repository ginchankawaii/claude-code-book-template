# Proxmox プロトタイプ構築手順(自宅検証用)

会社の VMware に構築する前に、自宅の Proxmox で同じ構成を小さく組んで理解するための手順。
**役割・アドレス計画は本番設計([README.md](README.md))と同一**にしてあるので、ここで作った設定ファイルはそのまま VMware 版に持っていけます。

## 0. プロトタイプの構成(Linux 4 VM + CPE)

理解が目的なので、既定では VNE と INET-SIM を 1 VM に同居させて VM 数を減らします。

> ⚠️ **DS-Lite の網側 NAT を検証するなら `SPLIT_INET=1` で分離してください。** 同居させると
> AFTR の masquerade が当たらず、**ポート開放不可 (R4) が逆の結果になります**。
> `SPLIT_INET=1 ./provision.sh` で 9005 `inet-sim` が追加され、実測で網側 NAT の成立を
> 確認済みです([build-log.md §3.3-A](build-log.md))。

| VM | 役割 | 目安スペック |
|---|---|---|
| NGN-SIM | RA / DHCPv6-PD 配布、網内ルーティング | 2vCPU / 2GB |
| VNE+INET | MAP-E BR + DS-Lite AFTR + Web/DNS(スクリプトを同一 VM で順に実行) | 2vCPU / 2GB |
| BRAS | PPPoE 終端(accel-ppp をソースビルドするため 2GB 推奨) | 2vCPU / 2GB |
| lab-client | CPE 配下の検証クライアント(`run-checks.sh` 実行用) | 1vCPU / 1GB |
| INET-SIM(分離時のみ / 9005) | 模擬インターネット。`SPLIT_INET=1` で分離する。**R4 を検証するなら必須** | 1vCPU / 1GB |
| OpenWrt-CE | リファレンス CPE(MAP-E / DS-Lite / PPPoE を切替) | 1vCPU / 512MB |
| 実機 CPE | Cisco 892FJ 系(後述。物理 NIC 経由) | — |

合計 **8vCPU / 7.5GB**(同居時)〜 **9vCPU / 8.5GB**(`SPLIT_INET=1` で分離時)程度。`provision.sh` の割当値と一致させています。

## 0.5 いちばん早い方法: 自動構築スクリプト

以下の §1〜§3 を手作業でやる代わりに、**Proxmox ホスト上で 1 コマンド**打てば「ブリッジ 4 本 + VM 5 台(`SPLIT_INET=1` なら 6 台)」が数分で立ち上がります。中身は §1〜§3 とまったく同じことをしているので、手順を理解したい場合は先に §1 以降を読んでください。

```bash
# Proxmox ホスト上で(リポジトリを clone した場所で)

# ① まず環境確認だけ。何も変更せず、PVE版数・ストレージ種別・VMID衝突・
#    既存ブリッジ・スナップショット可否を報告して終わる
sudo lab/ipoe/proxmox/provision.sh preflight

# ② 問題なければ本実行(STORAGE は省略すると自動検出する)
sudo lab/ipoe/proxmox/provision.sh
sudo STORAGE=<pvesm status で見た名前> lab/ipoe/proxmox/provision.sh   # 明示する場合

# 実機 892FJ を繋ぐ場合は物理NICを指定(vmbr1 にアップリンクされる)
sudo ACCESS_UPLINK=enp3s0 lab/ipoe/proxmox/provision.sh

# ブリッジだけ作る / 作った VM を消してやり直す
sudo lab/ipoe/proxmox/provision.sh bridges
sudo lab/ipoe/proxmox/provision.sh destroy
```

> **`preflight` から始めてください。** 本実行の前に必ず同じ検証が走りますが、`preflight` なら
> 何も変更せずに環境だけ報告します。
>
> **公開鍵**: `sudo` 実行なので既定は `/root/.ssh/id_rsa.pub` です。呼び出しユーザの鍵を使うなら
> `sudo SSHKEY=~/.ssh/id_rsa.pub ...` と明示してください(チルダは呼び出し側で展開されます)。

やっていること:

| 手順 | 内容 |
|---|---|
| **事前検証** | PVE 版数・ストレージ種別とスナップショット可否・VMID 9001-9010 の衝突・既存 vmbr1-4 の用途・公開鍵・GUI 未適用のネットワーク変更をチェックし、危険なら中断 |
| ブリッジ作成 | vmbr1(ACCESS)/ vmbr2(CORE)/ vmbr3(INET)/ vmbr4(CPE配下LAN)を `bridge-mcsnoop 0` 付きで追加。**既存の別用途ブリッジには触らず中断する**(CML の External Connector 等を汚さないため) |
| イメージ取得 | Ubuntu 24.04 クラウドイメージと OpenWrt をダウンロード(2 回目以降はキャッシュ) |
| VM 作成 | 9001 ngn-sim / 9002 vne-inet / 9003 bras / 9004 lab-client / 9010 openwrt-ce(+ `SPLIT_INET=1` なら 9005 inet-sim)。cloud-init でユーザ・SSH 鍵・DHCP を設定 |
| NIC 割当 | 役割ごとに**固定 MAC** を付与(`02:AC:*`=アクセス網、`02:C0:*`=NGN網内、`02:1E:*`=模擬インターネット) |

**固定 MAC がなぜ効くか**: 各 setup スクリプトは [`lab/ipoe/detect-ifs.sh`](../../lab/ipoe/detect-ifs.sh) を読み込み、**MAC から役割を判別して NIC 名を自動で埋めます**。Ubuntu の NIC 名が `ens18` でも `eth1` でも、そのまま `sudo ./setup-ngn.sh pd` で動きます(VMware 側でも同じ MAC を手で設定すれば同じ仕組みが使えます)。

VM が上がったら、各 VM に `lab/ipoe` をコピーして [§2](#2-vm-の構築) 末尾の setup コマンドを実行してください(NIC 名の指定は不要です)。

## 1. Proxmox 側のネットワーク準備

アップリンクなしの Linux ブリッジを **4 本**(アクセス網・網内・模擬インターネット・CPE 配下 LAN)作ります。プロトタイプでは PG-CORE と PG-INET を 1 本に集約してもよいですが、本番と同じ本数にしておくと VMware 移行時に迷いません。**vmbr4(CPE 配下 LAN)は省略しないでください** — 検証クライアントを CPE の下にぶら下げるために必要で、§3 の OpenWrt 作成コマンドもこれを参照します。

`/etc/network/interfaces` に追記(GUI の場合は Datacenter → Node → Network → Create → Linux Bridge):

```
auto vmbr1
iface vmbr1 inet manual
        bridge-ports enp3s0     # 実機CPE収容用の空き物理NIC。無ければ none
        bridge-stp off
        bridge-fd 0
        bridge-mcsnoop 0
#ACCESS: NGNアクセス網L2

auto vmbr2
iface vmbr2 inet manual
        bridge-ports none
        bridge-stp off
        bridge-fd 0
        bridge-mcsnoop 0
#CORE: NGN網内

auto vmbr3
iface vmbr3 inet manual
        bridge-ports none
        bridge-stp off
        bridge-fd 0
        bridge-mcsnoop 0
#INET: 模擬インターネット

auto vmbr4
iface vmbr4 inet manual
        bridge-ports none
        bridge-stp off
        bridge-fd 0
        bridge-mcsnoop 0
#CLIENT: CPE配下のクライアント側LAN
```

**Proxmox 固有の落とし穴(調査で複数の再現報告を確認済み)**:

1. **`bridge-mcsnoop 0` を必ず入れる。** Linux ブリッジの multicast snooping が有効だと RA / NA / DHCPv6 のマルチキャストが VM に届かず、「IPv6 がなんとなく死ぬ」症状になる(このラボは IPv6 が主役なので致命的)
2. **VM の NIC で Firewall チェックボックスを外す。** 意図しないフレーム破棄の原因
3. NIC モデルは **virtio**。ただしアクセス網側(PPPoE が流れる vmbr1)に挿す NIC は、断続ロスが出たら VM 内で `ethtool -K eth1 tso off gso off gro off tx off rx off` を試す(virtio オフロードと PPPoE の相性問題の定番対処)
4. VMware と違い、無差別モード許可の操作は**不要**(Linux ブリッジは元々 MAC 学習する普通のスイッチとして振る舞う)

## 2. VM の構築

Ubuntu Server 24.04 の VM を **4 台**(`SPLIT_INET=1` 相当の分離構成なら **5 台**)作り、NIC を次のとおり割当てます(net0=管理用に既存の vmbr0、net1 以降が検証用)。

| VM | net1 | net2 |
|---|---|---|
| NGN-SIM | vmbr1 (ACCESS) | vmbr2 (CORE) |
| VNE+INET | vmbr2 (CORE) | vmbr3 (INET) |
| BRAS | vmbr1 (ACCESS) | vmbr3 (INET) |
| lab-client | vmbr4 (CLIENT) | — |

`lab-client` は CPE 配下に置く検証クライアントです。**これを省いて管理 LAN 上のホストから
`run-checks.sh` を流すと、通信が CPE を通らずに抜けて「PASS したのに何も検証できていない」
状態になります**([build.md §5.7](build.md))。

各 VM に `lab/ipoe/` をコピーして実行:

§0.5 の provision.sh で VM を作った場合、NIC 名は `detect-ifs.sh` が MAC から自動解決するので**環境変数の指定は不要**です。手動で VM を作った場合は各スクリプトの環境変数で上書きできます(Ubuntu 24.04 の既定は `ens18` 等になるため。[build.md](build.md) 冒頭参照)。

```bash
# NGN-SIM(まずは PD モード=ひかり電話あり相当から。MAP-E の既定値と揃っていて迷わない)
sudo lab/ipoe/ngn/setup-ngn.sh pd

# VNE+INET(同一VMで両方実行)
sudo lab/ipoe/vne/setup-map-br.sh        # PD モードの既定値のまま
sudo lab/ipoe/vne/setup-aftr.sh
sudo lab/ipoe/inet/setup-inet.sh                # NIC は MAC から自動解決される

# BRAS(PPPoE切替前状態の再現が必要になったら)
sudo lab/ipoe/bras/setup-bras.sh
```

RA モード(ひかり電話なし相当)を試す時は **NGN-SIM と BR の値をセットで**切り替えます([build.md §3](build.md) の対応表参照):

```bash
sudo lab/ipoe/ngn/setup-ngn.sh ra
sudo CE_MAP_ADDR=2001:db8:1014:300:0:c633:6414:3 CE_SHARED_V4=198.51.100.20 \
     lab/ipoe/vne/setup-map-br.sh
```

> VNE+INET 同居時の注意: setup-inet.sh 内の「復路ルート(via 203.0.113.1 / 2001:db8:cafe::1)」は同居により自分自身を指すため不要になります(スクリプトはこの場合エラーを無視して先へ進むようにしてあります)。

## 3. OpenWrt-CE VM の作成

**[§0.5](#05-いちばん早い方法-自動構築スクリプト) の provision.sh を使った場合は VMID 9010 として作成済みです。** 手動で作る場合のみ以下を実行してください。

> ⚠️ **NIC の順番を間違えないこと。** OpenWrt x86/64 の既定は **eth0 = LAN / eth1 = WAN** です。
> したがって **1 枚目(net0)を LAN 側(vmbr4)、2 枚目(net1)を WAN 側(vmbr1)** に割り当てます。
> 逆にすると初回ブートで WAN 側 NIC に `192.168.1.1` の LAN が立ち上がり、アクセス網を汚します。

```bash
# Proxmoxホスト上で (provision.sh と同じ非EFIイメージ + SeaBIOS で揃えている)
wget https://downloads.openwrt.org/releases/24.10.0/targets/x86/64/openwrt-24.10.0-x86-64-generic-ext4-combined.img.gz
gunzip openwrt-*.img.gz
qemu-img resize -f raw openwrt-*.img 2G      # 空き領域の予約 (rootfs拡張はOpenWrt側で別途)
# 注意: これは **イメージファイル**を 2G にするだけで、中のパーティション/ファイルシステムは
# 98MB のままです (サイクル 2 実測: df -h / → /dev/root 98.3M)。
# map / ds-lite / tcpdump-mini までは実測で収まりましたが (使用 27MB)、
# それ以上入れる場合は OpenWrt 側でパーティション拡張が別途必要です。

qm create 9010 --name openwrt-ce --memory 512 --cores 1 --ostype l26 \
  --scsihw virtio-scsi-single --serial0 socket \
  --net0 virtio,bridge=vmbr4 \
  --net1 virtio=02:AC:00:00:00:10,bridge=vmbr1
qm set 9010 --scsi0 "<STORAGE>:0,import-from=$PWD/openwrt-24.10.0-x86-64-generic-ext4-combined.img"
qm set 9010 --boot order=scsi0
qm start 9010
```

`<STORAGE>` は `pvesm status` で確認した名前に置き換えてください(PVE 7.2 未満では `import-from` が使えないため `qm importdisk 9010 <img> <STORAGE>` → `qm set 9010 --scsi0 <unused0の値>` の 2 段になります)。

起動後、`opkg update && opkg install map ds-lite` の上で [build.md §5](build.md) の設定を投入します。

> ⚠️ **この `opkg` はそのままでは通りません。**(サイクル 2 で実証済み)
> OpenWrt は管理 NIC を持たずラボ内に閉じているうえ、管理 NIC を足しても
> **ラボの IPv6 が降りていると全リポジトリが `wget returned 4` で落ちます**
> (PD の既定経路が送信元制限付きで、`uclient-fetch` は AAAA から A へ
> フォールバックしないため)。
> **動く手順の全文は [build.md §5](build.md) の冒頭にあります** — 管理 NIC の追加 →
> `ifdown wan6` → `opkg` → `ifup wan6` → 管理 NIC 無効化、の順です。

**OpenWrt の MAP-E で追加すべき設定(調査反映)**:

```
config interface 'wanmap'
        option proto 'map'
        ...(build.md §5 の値)...
        option psidlen '8'
        option encaplimit 'ignore'   # 実網でも必須になる定番。片方向断の予防
```

- MTU が 1280 のままになる/LuCI の Devices タブから触ると通信断になる報告あり → 設定後に `ip link` でトンネル MTU 1460 を確認
- fw4 で MAP-E / DS-Lite インターフェースを **wan ゾーンに入れ忘れると全断**(定番ミス)
- 実サービス(v6プラス等)のリハーサルをする時だけ `option legacymap '1'` を追加(日本の VNE は draft-03 互換のため。詳細は [research-notes.md §2](research-notes.md))

## 4. 実機 892FJ 系の使いどころ

調査結果([research-notes.md §4](research-notes.md)): **IPv6 非対応ではない**。classic IOS 15.x で以下が可能。

- **できる**: IPv6 IPoE(RA 受信 / DHCPv6-PD)、PPPoE、DS-Lite(`tunnel mode ipv6` で AFTR へ)
- **できない**: MAP-E(v6プラス等)。classic IOS に CE 機能がない(対応は IOS XE の C1100 系以降)

つまりプロトタイプでは 892FJ を「**PPPoE→DS-Lite 切替の実機 CPE**」として使い、MAP-E 側の CE は OpenWrt が担当する分担になります。ラボの AFTR に対する 892FJ 側の設定骨子(891FJ 系の複数の実績記事と同型):

```
ipv6 unicast-routing
ipv6 cef
!
interface GigabitEthernet8            ! WAN (vmbr1へ接続したポート)
 ipv6 address autoconfig              ! RA方式。PD方式なら ipv6 dhcp client pd LABPD
 ipv6 enable
!
interface Tunnel0
 ip address 192.0.0.2 255.255.255.248 ! B4側 (RFC6333)
 tunnel source GigabitEthernet8
 tunnel mode ipv6                     ! IPv4 over IPv6
 tunnel destination 2001:db8:8888::1  ! ラボのAFTR
!
ip route 0.0.0.0 0.0.0.0 Tunnel0     ! NATは網側(AFTR)なのでルータでのNAT44不要
```

**重要: AFTR 側のトンネル対向合わせ。** RA 方式(`autoconfig`)の 892FJ の WAN アドレスは EUI-64 で決まるため事前に分かりません。ラボの AFTR は対向不一致の decap を破棄するので、892FJ 起動後に実アドレスを確認して AFTR を再実行します:

```bash
# 892FJ 側: show ipv6 interface gi8 で GUA を確認(または VNE 側で実測):
# VNE 側: tcpdump -ni eth1 'ip6 proto 4' で encap の送信元を見る
sudo CE_WAN6=<確認した GUA> lab/ipoe/vne/setup-aftr.sh
```

また classic IOS は PMTUD 頼みだと MTU 黒穴を踏みやすいため、LAN 側インターフェースに `ip tcp adjust-mss 1420` を入れておくのが実務でも定石です。

これで「892FJ を PPPoE で BRAS に繋いだ状態 → DS-Lite へ切替 → 切戻し」という切替リハーサルの一連が、自宅で実機込みで練習できます。
注意: classic IOS の IPv4 over IPv6 転送は CEF に乗らず低速になりがち+800 系はサポート終了済みのため、**あくまで練習台**。案件の実機検証は顧客と同型機で。

## 4.1 CML の IOS XE を MAP-E の CE として使う(自宅限定・要検証)

> ⚠️ **CML は自宅環境にしかありません。会社の VMware 環境に CML はなく、代わりに実機が豊富にあります。** つまり CML は「自宅で実機が足りない分を埋める代用品」であり、**会社側の手順書に CML を前提とした手順を書いてはいけません**。会社側は必ず「物理ポートに実機を挿す」経路になります([§4.2](#42-環境別の-ce-調達手段))。
>
> 逆に言うと、**CML で IOS XE の MAP-E 設定を確認しておけば、会社にある物理の IOS XE 機(C1100 系など)にそのまま持っていける**という連続性があります。自宅での CML 検証は、会社での実機検証のリハーサルとして機能します。

892FJ で埋まらない MAP-E の CE 役を、**CML 上の Catalyst 8000V / CSR1000v(IOS XE)で代替できます**([research-notes.md §4.1](research-notes.md))。

> ✅ **確認済み(2026-08-10 / トラッカー H3)**: CML 2.9.0 の **Cat8000v(IOS XE 17.15.01a)**で
> `nat64 map-e domain 1` と `nat64 provisioning mode jp01` が**両方とも running-config に入る**
> ことを確認しました = **MAP-E の実装あり**。`license boot level` の明示指定は不要でした
> (既定のまま通った)。実施記録は [build-log.md §3.5-A](build-log.md)。
>
> ただし確認したのは**パーサに実装があること**までです。実際のカプセル化が成立するか、
> [build.md](build.md) §3 の期待値表と一致するかは**未検証**(サイクル 4)。
> CML 上の Cat8000v は demo mode なので**性能の検証には使えません**。

### まず CLI の有無を確認する(5分)

CML で Cat8000v を 1 台起動し、コンソールで:

IOS XE の MAP-E は **トンネルインタフェースではなく `nat64` 配下**で設定します
(`tunnel mode ?` や `softwire ?` では出てきません)。叩くのは次の 3 つです。

```
show version                     ! IOS XE のバージョンとプラットフォーム名
show license boot level          ! ブートレベル(機能制限の有無。下の表で判定)

configure terminal
 nat64 ?                         ! map-e / provisioning が候補に出るか
 nat64 map-e ?                   ! domain が出るか
 nat64 provisioning ?            ! mode(jp01)が出るか
```

**判定**:

| 見えたもの | 意味 |
|---|---|
| `nat64 map-e domain` と `nat64 provisioning mode jp01` が両方通る | **MAP-E 実装あり**。CE 役に使える |
| `nat64` はあるが `map-e` が出ない | NAT64 のみ。MAP-E は不可(DS-Lite 止まり) |
| `nat64` 自体が無い | ライセンスかイメージ種別の問題。`show license boot level` を確認 |

ライセンスは 3 段階で切り分けます: ① `show license boot level` が `network-essentials` なら
`license boot level network-advantage` に上げて再起動して再確認 → ② それでも出なければ
イメージ種別(no-payload-encryption 版など)を確認 → ③ それでも出なければ仮想では非対応と結論。

> **タイムボックス: 合計 30 分**。ここで詰まっても本題(ラボ一巡)は進むので、
> 30 分で結論が出なければ「仮想では未確認」として先に進み、会社の物理 IOS XE 機で確認してください。

**結果によって次が変わります**:

| 結果 | ラボでの役割 |
|---|---|
| MAP-E CLI **あり** | Cat8000v を **MAP-E の CE** として検証マトリクス No.1〜2 に投入。OpenWrt と Cisco の 2 実装で比較でき、実装差に起因するトラブル(ポート分散・encaplimit 等)を実機ライクに観測できる |
| MAP-E CLI **なし** | DS-Lite の CE として使う(892FJ と同じ役)。MAP-E は OpenWrt が担当のまま |

### CML ノードをラボの L2 に繋ぐ

CML の **External Connector** を使ってアクセス網(vmbr1)に足を出します。CML の設置形態で経路が変わります:

- **CML が Proxmox 上の VM の場合**(推奨・簡単): CML VM に vNIC を 1 枚追加して `vmbr1` に接続 → CML 側でその NIC に紐づく External Connector を定義 → Cat8000v の WAN 側インターフェースをそれに接続
- **CML が別筐体の場合**: CML ホストの NIC → 物理スイッチ → Proxmox ホストの物理 NIC(`ACCESS_UPLINK` に指定した NIC)。実機 892FJ を繋ぐのと同じ構成([build.md §5.5](build.md))なので、物理スイッチに両方ぶら下げれば同じ L2 に乗ります

## 4.2 環境別の CE 調達手段

同じラボですが、**CE(検証対象の CPE)をどこから持ってくるかが環境によって逆転します**。

| | 自宅 Proxmox | 会社 VMware |
|---|---|---|
| CML | **あり** → Cat8000v / CSR1000v を CE に使える | **なし** |
| 実機 | 892FJ のみ(MAP-E 非対応) | **豊富にある** ← ここが本命 |
| 主な CE 調達 | OpenWrt VM + CML の IOS XE + 892FJ | **物理ポートに実機を挿す** + OpenWrt VM |
| MAP-E の CE | OpenWrt / CML の IOS XE(要検証) | 実機(顧客同型機・IOS XE 機など) |

**どちらの環境でも「アクセス網セグメントを物理ポートに出せる」ことが前提**なので、設計は共通です:

- 自宅: `ACCESS_UPLINK=<物理NIC>` で `vmbr1` に物理 NIC をアップリンク
- 会社: PG-ACCESS のアップリンクに物理 NIC を割当([build.md §5.5](build.md))

つまり**会社側では「物理スイッチ経由で実機を挿す」手順が必須ステップ**です(自宅は CML があるので内部ブリッジだけでも回りますが、会社はそうはいきません)。ポートグループのセキュリティ 3 項目「承諾」を落とすとここで詰まるため、ランブックでは省略不可の手順として扱います。

### 実機が多いことの意味と、1つの制約

会社に実機が豊富にあるのは**このラボの価値が最も出る条件**です。[test-matrix.md §5](test-matrix.md) の「機種 × 方式の実績表」が実際に埋まっていき、案件ごとの検証量が減っていきます。

ただし**現在のラボは同時 1 台の CE を前提に作ってあります**:

| 項目 | 制約 | 理由 |
|---|---|---|
| DHCPv6-PD | 既定では **/56 を 1 本だけ**委譲 | `kea-dhcp6.conf` の pd-pool が単一プレフィックス(MAP-E 期待値を固定値にするため) |
| MAP-E | **同時 1 CE のみ** | BR は CE アドレス宛の静的 ip6tnl。複数 CE のルールベース BR は素の Linux では不可([research-notes.md §3](research-notes.md) #11) |
| DS-Lite | **同時 1 B4 のみ** | AFTR も同様に静的トンネル。複数 B4 は RFC1918 重複を分離できない |
| PPPoE | **複数同時 OK** | BRAS はマルチセッション対応(むしろ R2 の再現に使う) |

**実務上の運用**: 実機は**1 台ずつ順番に**検証します(そもそも機種ごとに設定を作るので、並行させる必要は薄い)。複数台に IPv6 だけ配って native v6 の挙動を並行で見たい場合は、`kea-dhcp6.conf` に **DUID ベースの予約**を足せば機種ごとに固定プレフィックスを配れます(下記)。

## 5. 動作確認と壊す練習

1. OpenWrt-CE の LAN 側に検証クライアントを繋ぎ `lab/ipoe/tests/run-checks.sh`
2. [test-matrix.md](test-matrix.md) のシナリオ §3(切替リハーサル)を 892FJ で一巡
3. トラブル再現レシピ(R1, R5, R6 あたりから)で「壊れた状態の見え方」を体験
4. 全 VM スナップショット取得 → 以後は壊し放題

## 6. VMware(本番)へ持っていく時の差分

**前提: 会社環境では AI 支援が使えません。** 自宅の Proxmox は Claude Code で対話しながら構築できますが、会社の VMware 側は**人が手順書を見ながら手作業で構築する**ことになります。したがって成果物は「AI に投げれば直る前提のメモ」ではなく、**上から順に実行すれば完成するランブック**である必要があります。

そのため本ラボは次の分担で設計しています:

| | 自宅 Proxmox(プロトタイプ) | 会社 VMware(本番) |
|---|---|---|
| 構築方法 | `provision.sh` + Claude Code で対話的に | **手順書を見ながら手動**(AI 支援なし) |
| 主な役割 | スクリプトの不具合出し・手順の確定・実機リハーサル | 確定した手順の再現 |
| 持ち出すもの | Git リポジトリ(設定ファイル・スクリプト・手順書) | 同じものを clone/コピーして使用 |

**自宅での構築作業そのものが、会社側ランブックの素材になります。** 実際に叩いたコマンド・詰まった箇所・回避策を [`runbook-vmware.md`](runbook-vmware.md) に記録していき、会社ではそれを見ながら手を動かせる状態にします(サイクル 1〜3 の実走をもとに **執筆済み**。サイクル 4 以降で追記していきます)。

なお、ラボの構成要素(Ubuntu / OpenWrt / accel-ppp / radvd / Kea / nftables)はすべて無償・オープンソースなので、**持ち込みにライセンス上の制約はありません**。

### ハイパーバイザ側の差分

| 項目 | Proxmox(プロトタイプ) | VMware(本番) |
|---|---|---|
| セグメント | Linux ブリッジ(vmbr1〜4) | vSwitch + ポートグループ(PG-ACCESS 等) |
| 無差別モード等 | 不要(ブリッジが MAC 学習する) | **PG のセキュリティ 3 項目を「承諾」必須**(vSwitch は MAC 学習せず、登録済み vNIC MAC 宛しか配送しないため) |
| IPv6 マルチキャスト | `bridge-mcsnoop 0` が必要 | 不要(vSwitch は snooping しない) |
| VLAN でトランク | VLAN aware bridge | VLAN ID 4095 のポートグループ(VGT) |
| VM 側の設定ファイル | `lab/ipoe/` 一式 | **そのまま流用可**(ここがプロトタイプの狙い) |

つまり移行時に変わるのはハイパーバイザ側のスイッチ設定だけで、VM の中身・アドレス計画・手順書は共通です。
