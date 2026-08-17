# C1111-8P で MAP-E が使えない件 — 調査記録と再検証手順

- 検出日: 2026-08-13
- 検出環境: 自宅 IPoE 検証ラボ(NTT NGN / VNE を Linux VM で模擬)
- **再現性: 2/2(100%)**
- **用途**: ① 別バージョンで再検証するときの手順書 ② MAP-E を扱うときの仕様メモ
  ③ 顧客提案で「IOS XE は要検証」と言うときの根拠

---

## 1. 要約

**Cisco C1111-8P(IOS XE 17.15.05)で MAP-E を設定すると、LAN 側にパケットが
流れた瞬間に転送エンジン(QFP)がクラッシュし、ルータが全断する。**

- **設定は正常に受理される。**エラーは一切出ない
- **`show nat64 map-e` は正しい導出値を返す**(共有 IPv4 / PSID / ポート数)
- **設定しただけでは落ちない。**トラフィックが流れると落ちる
- **特別な操作は不要。**PC を LAN ポートに繋いだだけで落ちた(`ping` すら打っていない)

---

## 2. 影響

**現場でこれが起きた場合、原因の特定は極めて困難と考えられる。**

- 設定投入時にはエラーが出ないため、作業ミスを疑う材料がない
- `show` コマンドの出力はすべて正常
- **LAN を繋いだ瞬間に全断する**ため、「配線を繋いだら壊れた」ようにしか見えない
- 復旧には `reload` が必要

**MAP-E は日本の主要な IPv4 over IPv6 方式**(v6プラス、OCN バーチャルコネクト、
BIGLOBE IPv6 オプション等)であり、**IOS XE 機を MAP-E 案件に提案する際は、
事前に実機でパケットを流すところまで検証すべき。**

---

## 3. 機器情報

| 項目 | 値 |
|---|---|
| 型番 | `C1111-8P` (VID: V01) |
| シリアル | `FGL23312070` |
| IOS XE | **`17.15.05`** / `universalk9` / RELEASE (fc3) |
| イメージ | `c1100-universalk9.17.15.05.SPA.bin` |
| ROMMON | `17.5(1r)` |
| 動作モード | `Autonomous` |
| ライセンス | `appxk9` / `securityk9`(Smart Licensing Using Policy) |
| スループット | `unthrottled` |

**機器の健全性**: 受け入れ評価時(同日午前)に全項目パス。温度 29〜35℃ 正常、
全モジュール `ok`、エラーログゼロ、**`bootflash:core/` は空**、8 ポートすべて
`connected`(1Gbps Full)。**個体不良ではない。**

---

## 4. MAP-E は当該プラットフォームのサポート機能である

- Cisco 1000 Series ISR での MAP-E サポートは **IOS XE Gibraltar 16.11.1 で導入**
- 公式ドキュメント: [IP Addressing Configuration Guide, Cisco IOS XE 17.x — MAP-E](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/ip-addressing/b-ip-addressing/m_iadnat-map-e1.html)
- **「非対応機能を無理に使った」ケースではない。**

---

## 5. 再現手順

### 5.1 網側(検証ラボ)の構成

すべて RFC ドキュメント用アドレスを使用。

| 要素 | 値 |
|---|---|
| DHCPv6-PD で委譲するプレフィックス | `2001:db8:100a:500::/56` |
| MAP-E の BR アドレス | `2001:db8:9999::1` |
| MAP ルール(IPv6) | `2001:db8:1000::/40` |
| MAP ルール(IPv4) | `198.51.100.0/24` |
| この CE の共有 IPv4 | `198.51.100.10` |
| PSID | `5` |
| 割当ポート | 240(15 ブロック × 16、先頭 4176-4191) |

### 5.2 CE(C1111-8P)の設定

```
ipv6 unicast-routing
!
interface GigabitEthernet0/0/0
 description WAN
 no ip address
 ipv6 address autoconfig default
 ipv6 address 2001:DB8:100A:500:0:C633:640A:5/128
 ipv6 enable
 ipv6 nd ra suppress all
 ipv6 dhcp client pd LAB-PD
 nat64 enable
!
interface Vlan1
 description LAN
 ip address 192.168.100.1 255.255.255.0
 ip tcp adjust-mss 1420
 ipv6 address LAB-PD 0:0:0:1::1/64
 ipv6 enable
 nat64 enable
!
interface GigabitEthernet0/1/0
 switchport access vlan 1
!
nat64 route 0.0.0.0/0 GigabitEthernet0/0/0
!
nat64 map-e domain 1
 border-relay-address 2001:DB8:9999::1
 basic-mapping-rule
  ipv6-prefix 2001:DB8:100A:500::/56
  ipv4-prefix 198.51.100.10/32
  local-ipv4-prefix 192.168.100.0/24
  port-parameters share-ratio 256 port-offset-bits 4
  port-set-id 5
```

> **注**: `port-parameters` は `port-set-id` より**先**に投入する必要がある。
> 逆順だと `%NAT64: PSID cannot be greater than the sharing ratio` で拒否される
> (share-ratio 未設定時は既定 1 と見なされるため)。

### 5.3 トリガ

**`Gi0/1/0`(LAN)にホストを接続する。**それだけ。`ping` 等の操作は不要。

---

## 6. 切り分け実験 — 引き金は「設定」ではなく「パケット」

LAN ポートを `shutdown` してトラフィックをゼロにした状態で、設定を **1 つずつ**
投入し、各段階で 60 秒待って観察した。

| 段階 | 投入したもの | 結果 |
|---|---|---|
| 1 | WAN を up + `ipv6 dhcp client pd`(/56 取得) | 無傷 |
| 2 | WAN に MAP-E アドレス `/128` | 無傷 |
| 3 | LAN に IPv6 | 無傷 |
| 4 | **WAN に `nat64 enable`** | **無傷**(60 秒) |
| 5 | **LAN に `nat64 enable`** | **無傷**(60 秒) |
| 6 | **`nat64 route 0.0.0.0/0`** | **無傷**(60 秒) |
| 7 | 状態確認: 5 要素そろい `Packets dropped: 0` / `Nat64v4tov6` 未出現 | — |
| **8** | **LAN ポートを `no shutdown`(= PC 接続)** | **即クラッシュ** |

**結論: 設定だけでは落ちない。パケットが流れると落ちる。**

> **未切り分け**: 「インタフェースが up になった瞬間のデータパスプログラミング」か
> 「up 後に届いた最初のパケット」かは、1 秒の分解能では区別できていない。

---

## 7. 障害時のログ

```
%CPPHA-3-FAILURE: F0/0: cpp_ha_top_level_server: CPP 0 failure Stuck Thread(s) detected
%CPPHA-3-FAULT:   CPP:0.0 desc:Stuck CPP Thread det:HA class:OTHER sev:FATAL
                  id:0 cppstate:STOPPED res:UNKNOWN flags:0x2 cdmflags:0x0
%CPPHA-3-FAULTCRASH: CPP 0.0 unresolved fault detected, initiating crash dump.
%IOSXE-1-PLATFORM: R0/0: kernel: QFP0.0: Fatal Fault: SW reported: Ucode process fault
%CPPDRV-3-LOCKDOWN: QFP0.0 CPP Driver LOCKDOWN encountered due to previous fatal error
%IOSXE_OIR-6-OFFLINECARD: Card (fp) offline in slot F0
```

**1 回目のトレースバックが NAT64 ライブラリを名指ししている:**

```
cpp_nat64_svr_lib:FFFF999E0000+36A7C
cpp_nat64_svr_lib:FFFF999E0000+197A0
cpp_nat64_svr_lib:FFFF999E0000+19E3C
cpp_nat64_svr_smc_lib:FFFF99A60000+25E8
```

2 回目は `cpp_ipfrag_svr` / `cpp_sbs` 系だったが、根本の
`QFP0.0: Fatal Fault: SW reported: Ucode process fault` は同一。
**ucode が死んだ後に各プロセスが順に転ぶ、という同じ壊れ方。**

### タイミング(重要)

**syslog に出る時刻は死亡時刻ではない。**コアファイル名の時刻を見ること。

| | 引き金 | ucode コア生成 | HA が検出(syslog) |
|---|---|---|---|
| 1 回目 | 設定投入 11:47:54(トラフィック有) | **11:47:55** | 11:48:13(18 秒後) |
| 2 回目 | リンクアップ 12:30:16 | **12:30:16** | 12:30:28(12 秒後) |

---

## 8. 採取済みの証跡

```
bootflash:core/
  CPE_RP_0_qfp-ucode-tsn-le_15283_20260813-114755-UTC.core.gz    21.9 MB  (1 回目)
  CPE_RP_0_cpp_cp_svr_16368_20260813-114822-UTC.core.gz          15.5 MB  (1 回目)
  CPE_RP_0-system-report_20260813-115102-UTC.tar.gz              38.1 MB  (システムレポート)
  CPE_RP_0_qfp-ucode-tsn-le_15213_20260813-123016-UTC.core.gz    24.2 MB  (2 回目)
  CPE_RP_0_cpp_cp_svr_16238_20260813-123038-UTC.core.gz          18.0 MB  (2 回目)
```

**受け入れ評価時(同日午前)は `core/` が空だった**ため、
**個体不良ではなく MAP-E 設定が原因**という切り分けが成立している。

---

## 9. 既知不具合の調査結果

**公開されている情報の範囲では、該当するバグが見つからない。**

当たって外れたもの:

| Bug ID | 内容 | 判定 |
|---|---|---|
| CSCvy30209 | VFR + 重複フラグメントで QFP クラッシュ | **別物**。`HW: QFP interrupt` であり、本件の `SW: Ucode process fault` と種類が違う。17.10.1 で修正済み(本件は 17.15.05) |
| CSCwa80826 | C11xx の IPsec ポリシー導入失敗 | **別物**。NAT64/MAP-E とも QFP クラッシュとも無関係 |
| CSCwa15085 | Stuck thread によるクラッシュ | 症状は近いが MAP-E との関連は確認できず |

---

## 10. 推奨アクション

### 10.1 提案・設計への反映(即時)

> **IOS XE 機を MAP-E 案件に提案する際、「CLI があるから対応している」と判断しないこと。**
> **事前に実機でパケットを流すところまで検証する。**

**現時点で MAP-E の CE として動作を確認できているのは OpenWrt のみ。**

| CE | MAP-E |
|---|---|
| Cisco 892FJ(classic IOS 15.x) | **非対応**(CLI 自体が無い) |
| CML Cat8000v(IOS XE 17.15.01a) | **QFP クラッシュ** |
| **実機 C1111-8P(IOS XE 17.15.05)** | **QFP クラッシュ** |
| OpenWrt 24.10.0 | 動作(ただし実効 16 ポート。別課題) |

### 10.2 バージョン切り分け

**別の IOS XE バージョンで再現するかを確認する。**手順は §5〜§6 のとおり
確立しているので、イメージを入れ替えて同じ 8 段階を実行すればよい。

**試行順(推奨)**:

| 優先 | バージョン | 理由 |
|---|---|---|
| 1 | **17.12.x**(Dublin / Extended Maintenance) | 17.15 の 1 つ前の EM リリース。成熟しており、MAP-E が生きている可能性が最も高い |
| 2 | **17.9.x**(Cupertino / Extended Maintenance) | さらに古い EM。36 か月サポート |
| 3 | 17.3.x または 16.12.x | MAP-E 導入(16.11.1)に近い世代。上 2 つが駄目な場合の最終確認 |

**留意点**:

- **フラッシュ容量**: 2.8GB 中 約 1.94GB 空き。イメージ 1 本(約 700MB)は入る
- **ROMMON**: `17.5(1r)`。古いイメージを起動する際は最低要件を確認すること
- **ライセンス**: 17.9 / 17.12 はいずれも SLP(17.15 と同じ)なので挙動は変わらない。
  **17.3.2 より前に落とすと Smart Licensing の方式自体が変わる**ので注意
- **イメージの入手は会社の Cisco アカウント(サービス契約付き)から行うこと。**
  中古機に契約は付いていない

### 10.3 Cisco への報告(サービス契約がある場合のみ)

**中古機に契約は付いていないので、この機体単体では TAC ケースを開けない。**
将来、会社の契約下の C1100 系で同じ現象を踏んだときには、
本書の §5〜§8(再現手順・ログ・コア)がそのまま使える。




---

## 11. 副次的に判明した仕様(MAP-E を扱う際の注意)

本調査の過程で判明した、ドキュメントに明記されていない挙動。

1. **パラメータの投入順に依存**
   `port-parameters`(share-ratio)を `port-set-id` より先に入れないと拒否される

2. **MAP-E アドレスは自動生成されない**
   DHCPv6-PD で /56 を受け取っても、CE の MAP-E アドレスは
   どのインタフェースにも自動では付与されない。**手で `/128` を設定する必要がある**
   (付けないと網側から NDP が引けず、戻りの通信が届かない)

3. **CE アドレスは委譲 /56 の先頭 /64 に入る**
   LAN に先頭 /64 を割り当てると
   `%Error: ... is overlapping with ... on Vlan1` で拒否される。
   **LAN には 2 番目以降の /64 を使う**

4. **`ipv4-prefix` と `local-ipv4-prefix` の意味**(公式設定例より)
   - `ipv4-prefix` = **この CE の共有 IPv4 を `/32` で**(ルール全体の /24 ではない)
   - `local-ipv4-prefix` = **CE の内側(LAN)の私設アドレス**

5. **RA 方式(SLAAC のみ)では MAP-E が成立しない**
   RFC 7597 の MAP-E は委譲プレフィックスが前提。SLAAC の /64 だけでは
   CE が自分のエンドユーザプレフィックスを確定できず、変換されずにドロップする
   (`Nat64v4tov6`)。**MAP-E の検証は DHCPv6-PD で行うこと**

6. **`nat64 provisioning mode jp01` が存在する**
   日本の VNE 向けのプロビジョニングモード。ただしサブモードに入るため、
   プロビジョニングサーバのない環境では設定しないほうがよい
