# 構築手順

各 VM は Ubuntu Server 24.04(OpenWrt-CE のみ OpenWrt x86/64)。NIC 割当は eth0=管理、eth1 以降を [README.md](README.md) のトポロジ図どおりに接続してください。

> **NIC 名の前提**: Ubuntu 24.04 の既定では NIC 名は `eth1` ではなく `ens18`/`ens160` 等(predictable naming)になります。各スクリプトは環境変数で NIC 名を上書きできます(例: `sudo ACCESS_IF=ens19 CORE_IF=ens20 ./setup-ngn.sh ra`)。`eth1` のまま使いたい場合はカーネル引数に `net.ifnames=0` を追加してください。
設定ファイルとスクリプトは [`lab/ipoe/`](../../lab/ipoe/) にあります。各 VM にディレクトリごとコピーして実行する想定です。

> 構築が終わったら**必ず全 VM のスナップショットを取得**してください。障害注入や壊す系の検証後に数秒で初期状態へ戻せることが、このラボの価値の半分です。
>
> **永続性の注意**: setup スクリプトが投入するアドレス・経路・トンネル・nft はランタイム設定です(永続なのは sysctl と systemd unit のみ)。スナップショットは**メモリ込み**で取得し、電源 OFF からの復元や再起動後は該当 VM の setup スクリプトを再実行してください(全スクリプト冪等なので再実行で復旧します)。

## 1. NGN-SIM(NGN 網模擬)

```bash
sudo lab/ipoe/ngn/setup-ngn.sh ra   # ひかり電話なし相当: RA 方式 (/64)
sudo lab/ipoe/ngn/setup-ngn.sh pd   # ひかり電話あり相当: DHCPv6-PD 方式 (/56)
```

- `ra` モード: radvd([`ngn/radvd.conf`](../../lab/ipoe/ngn/radvd.conf))が `2001:db8:1014:300::/64` を RA(A/O フラグ)+ RDNSS で配布
- `pd` モード: kea([`ngn/kea-dhcp6.conf`](../../lab/ipoe/ngn/kea-dhcp6.conf))が `2001:db8:100a:0500::/56` を PD で委譲し、radvd はデフォルト経路広報のみ(M/O フラグ、A なし)
- どちらのモードでも NGN-SIM がアクセス網のデフォルトルータとなり、ユーザ宛プレフィックスと VNE(BR/AFTR)間をルーティングします
- **実網 NGN の癖(DUID-LL 限定)は既定で無効**です。有効化すると DUID-LL(タイプ 0003)以外の Solicit を**無応答で破棄**し、実網と同じ「無応答でハマる」を再現します。ラボが一度通ったあとに `kea-dhcp6.conf` の `client-classes`(DROP クラス)のコメントを外してください([test-matrix.md](test-matrix.md) §3 Phase 1 手順 5)
- **PD の復路経路は Kea のフックが自動投入**します。フックが動くには AppArmor の実行許可と `CAP_NET_ADMIN` の両方が必要で、`setup-ngn.sh` が両方設定します。動作確認は `journalctl -t kea-pd-route`(何も出ない場合は `dmesg | grep -i apparmor.*kea` を確認)
- PD モードの委譲プレフィックス復路は、**Kea の run_script フック(kea-pd-route.sh)が PD リース時に「要求元 CE 宛の via 経路」を自動投入**します(実網の delegating router と同じ動き。on-link 経路だと CE が NS に応答せず復路が死ぬため)。初回割当は `leases6_committed` で捕まえています(`lease6_select` というフックポイントは存在しないため、そこに書くと renew まで経路が入りません)
- **プレフィックス変更トラブルの再現**(ひかり電話契約変更相当)は、モードを `ra`→`pd` に切り替えて CPE の追従を見るだけです

## 2. BRAS(PPPoE 終端)

```bash
sudo lab/ipoe/bras/setup-bras.sh
```

- accel-ppp([`bras/accel-ppp.conf`](../../lab/ipoe/bras/accel-ppp.conf))が eth1 上で PPPoE を終端。認証は [`bras/chap-secrets`](../../lab/ipoe/bras/chap-secrets)(`user1@isp-a.example` / `pass1` など)。CPE 側でサービス名の入力を求められたら `lab-isp`。**空欄でも接続できます**(`accept-blank-service=1` を入れてあるため。これがないと空の Service-Name を送る CPE の PADI が破棄され「応答しない」事故になります)
- **accel-ppp は Debian/Ubuntu 公式リポジトリに無い**ため、setup-bras.sh はソースからビルドします(数分)。素早く済ませたい場合の代替は VyOS の `set service pppoe-server`(中身は accel-ppp)
- MTU/MRU 1454(フレッツ実網値。1492 で組むと実網の MSS 詰まりが再現できない)、動的プール `100.64.1.0/25` + 固定 IP `100.64.1.200`(`kotei@isp-a.example` 用。プールと重複させないため /25 にしている)、上流は eth2 → INET-SIM 経由で NAT
- PPPoE で断続的なパケットロスが出たら、まず ACCESS 側 NIC のオフロードを無効化(`ethtool -K eth1 tso off gso off gro off`)。virtio オフロードと PPPoE の相性問題が定番原因
- セッション操作(残留セッションの再現・強制切断):

```bash
accel-cmd show sessions
accel-cmd terminate username user1@isp-a.example
```

## 3. VNE(MAP-E BR + DS-Lite AFTR)

```bash
sudo lab/ipoe/vne/setup-map-br.sh   # MAP-E 検証時
sudo lab/ipoe/vne/setup-aftr.sh    # DS-Lite 検証時(両方同時起動も可)
```

- MAP-E BR: CE の MAP アドレス(既定 `2001:db8:100a:500:0:c633:640a:5`)との ip6tnl を張り、共有 IPv4 `198.51.100.10` を復路ルーティング。CE 側 NAT なので BR では NAT しません
- AFTR: CE の WAN アドレスとの ip6tnl + nftables masquerade(RFC 6333 の `192.0.0.1/192.0.2` を使用)。**ポート開放不可の再現はこの構成そのもの**です
- MAP ルール(CPE に設定する値):

| パラメータ | 値 |
|---|---|
| rule-ipv6-prefix | `2001:db8:1000::/40` |
| rule-ipv4-prefix | `198.51.100.0/24` |
| ea-len / psid-offset | 16 / 4 |
| BR アドレス | `2001:db8:9999::1` |

NGN-SIM のモードごとの期待値(CPE の自動計算値がこれと一致するかが最初の確認ポイント):

| NGN-SIM モード | ユーザプレフィックス | 共有 IPv4 | PSID | CE の MAP アドレス | setup-map-br.sh の実行方法 |
|---|---|---|---|---|---|
| pd(ひかり電話あり) | `2001:db8:100a:500::/56` | `198.51.100.10` | 5 | `2001:db8:100a:500:0:c633:640a:5` | そのまま実行(既定値) |
| ra(ひかり電話なし) | `2001:db8:1014:300::/64` | `198.51.100.20` | 3 | `2001:db8:1014:300:0:c633:6414:3` | `CE_MAP_ADDR=2001:db8:1014:300:0:c633:6414:3 CE_SHARED_V4=198.51.100.20` を付けて実行 |

利用可能ポートはどちらも 16 ポート × 15 ブロック = 240(例: PSID=5 なら `0x1050-0x105F` = 4176-4191 など)。**NGN-SIM のモードと BR の起動パラメータの組み合わせを間違えると全断**になるので、この表をセットで確認してください。

## 4. INET-SIM(模擬インターネット)

```bash
sudo lab/ipoe/inet/setup-inet.sh
```

- nginx が `http://203.0.113.80` / `http://[2001:db8:cafe::80]` で応答(応答ページに接続元アドレスを表示 → CPE がどの方式で出てきたか一目で判別可能)
- dnsmasq が `www.lab.example` の A/AAAA を返答
- 障害注入ヘルパ(DNS フォールバックや MTU ブラックホール再現に使用):

```bash
sudo lab/ipoe/inet/setup-inet.sh break-v6     # IPv6 だけ死んだサイトを再現
sudo lab/ipoe/inet/setup-inet.sh restore
```

**市販ルータの DS-Lite 自動設定を試すオプション**: transix 系の市販ルータ・自動設定は AFTR を FQDN(`gw.transix.jp`)の DNS 解決で発見する仕様のため、ラボ DNS がこの名前をラボ AFTR に向ければ自動設定機種が動く可能性があります(MAP-E の自動設定は VNE のルール配布サーバ依存のため模擬不可 — README「できないこと」参照)。

```bash
sudo lab/ipoe/inet/setup-inet.sh spoof-aftr   # gw.transix.jp 等 → 2001:db8:8888::1 を返す
```

※ラボ内 DNS だけの偽装であり、ラボ外に影響はありません。CPE の DNS がラボ DNS(203.0.113.53 / 2001:db8:cafe::53)を向いていることが前提。

## 5. OpenWrt-CE(リファレンス CPE)

OpenWrt x86/64 を VM 化し、WAN を PG-ACCESS、LAN を検証クライアント用 PG へ。`map` / `ds-lite` / `ppp-mod-pppoe` パッケージを導入します。

```bash
opkg update && opkg install map ds-lite
```

`/etc/config/network` の要点(方式ごとに wan セクションを切替):

```
# PPPoE
config interface 'wan'
        option proto 'pppoe'
        option username 'user1@isp-a.example'
        option password 'pass1'

# MAP-E(値は上の MAP ルール表のとおり)
config interface 'wanmap'
        option proto 'map'
        option maptype 'map-e'
        option peeraddr '2001:db8:9999::1'
        option ipaddr '198.51.100.0'
        option ip4prefixlen '24'
        option ip6prefix '2001:db8:1000::'
        option ip6prefixlen '40'
        option ealen '16'
        option psidlen '8'
        option offset '4'
        option encaplimit 'ignore'
        option mtu '1460'
        option tunlink 'wan6'
# 注意(調査で判明した定番ミス):
#  - MAP-E/DS-Lite のインターフェースを fw4 の wan ゾーンに入れ忘れると全断
#  - トンネル MTU が 1280 のままだと低速・画像欠け → `ip link` で 1460 を確認
#  - 実サービス(v6プラス等)のリハーサル時のみ option legacymap '1' を追加
#    (日本の VNE は draft-03 互換。ラボ既定ルールは RFC7597 で自己完結)
#  - PSID の自動計算(mapcalc)は 64bit 環境でバグ報告あり。手動値が確実

# DS-Lite
config interface 'wandsl'
        option proto 'dslite'
        option peeraddr '2001:db8:8888::1'
        option mtu '1460'
        option tunlink 'wan6'
```

**MTU 注意**: OpenWrt の map.sh / ds-lite は `option mtu` 未指定だと **1280** に設定します(上記サンプルの `option mtu '1460'` は必須。設定後 `ip link` で確認)。

**RA 方式(ひかり電話なし)のときの LAN 側 IPv6**: /64 が 1 本しか無く PD が無いため、通常のルータ設定のままでは LAN 側に IPv6 を配れません(市販ルータが「IPv6 ブリッジ/パススルー」で対処している部分)。OpenWrt では odhcpd のリレーモードを使います:

```bash
uci set dhcp.wan6.master='1'
uci set dhcp.wan6.ra='relay';  uci set dhcp.wan6.dhcpv6='relay';  uci set dhcp.wan6.ndp='relay'
uci set dhcp.lan.ra='relay';   uci set dhcp.lan.dhcpv6='relay';   uci set dhcp.lan.ndp='relay'
uci commit dhcp && /etc/init.d/odhcpd restart
```

## 5.5 実機 CPE の接続(物理スイッチ経由)

実機検証は**物理スイッチを PG-ACCESS のアップリンク物理 NIC に接続する**構成を想定しています。物理スイッチ配下の機器は、VM(NGN-SIM / BRAS)と同じ L2 セグメントに乗るため、実機ルータから見ると「フレッツの回線に繋いだ」のと同じ見え方になります。

```
[実機ルータ(お客様同型機)] ─┐
[HGW実機(あれば)] ──────────┼─[物理スイッチ]──[ESXiホストの空き物理NIC]
[検証用PC] ─────────────────┘                        │
                                                     └ この物理NICを PG-ACCESS の
                                                       アップリンクに割り当てる
```

- 物理スイッチは**普通の L2 スイッチでよい**(特別な設定不要、MTU 1500 のまま)。PPPoE フレームも RA / DHCPv6 もこの L2 をそのまま透過する
- **必須の注意点**: PG-ACCESS のセキュリティ 3 項目(無差別モード・偽装転送・MAC アドレス変更)を「承諾」にすること。忘れると PPPoE と実機ブリッジが動かない
- 検証用 PC も同じスイッチに繋いでおくと、実機ルータの管理画面アクセスと `tcpdump` 相当のパケット確認(ポートミラー設定時)が同じ場所からできる
- 検証面を複数持ちたい場合(2 案件並行など)は、物理スイッチを VLAN で分け、PG 側も VLAN ID を付けたポートグループを複数作れば、1 本の物理 NIC でアクセス網を複数本収容できる

## 6. 動作確認

CPE 配下のクライアント(Linux)で:

```bash
lab/ipoe/tests/run-checks.sh
```

IPv6 取得 → v4/v6 疎通 → DNS(A/AAAA)→ MTU 実測 → HTTP 到達性 を PASS/FAIL で判定します。結果はそのまま切替前後のエビデンスとして保存できます。
