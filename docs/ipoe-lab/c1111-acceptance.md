# Cisco C1111-8P 受け入れ評価チェックリスト(中古入手時)

**目的**: 中古で入手した C1111-8P が、出品情報どおりで、ラボの検証機として使えるかを確認する。
**所要**: 30〜40 分(§1〜§4 の受け入れ判定まで 20 分)。

> **順番に意味があります。**
> **§1〜§3 は「返品・返金を判断するための確認」**なので先にやります。
> §4 以降(ラボ用途の確認)は、返せなくなってから困っても遅いものではありません。
>
> **§2 まで終わるまで `write erase` しないでください。**前オーナーの設定は
> 「出品どおりの個体か」「どう使われていたか」の証拠になります(消すのは §3 の最後)。

**記入して [build-log.md](build-log.md) に貼ってください。**

---

## 0. 準備

- コンソールケーブル(C1111 は **USB Type-B(青)と RJ-45** の両方あり。どちらでも可)
- ターミナル **9600 8N1**
- 電源アダプタ(付属品として届いているか、まずここを確認)

```
Router> enable
Router# terminal length 0        ← ページャを切る (出力を一気に取るため)
```

**この先、出力は全部ログに残してください。**受け入れ判定の証拠になります。

---

## 1. 個体の同一性(出品情報と合っているか)

```
show version
show inventory
show license udi
```

| 確認項目 | 期待値 | 実測 |
|---|---|---|
| 型番(PID) | `C1111-8P` | |
| シリアル(SN) | **出品ページ/写真と一致すること** | |
| IOS XE バージョン | `17.15.05`(出品どおりか) | |
| イメージ | `universalk9` | |
| Config register | `0x2102`(通常)。`0x2142` だと起動時に設定を読まない | |
| Uptime / 再起動理由 | `show version` 末尾の `Last reload reason` | |

> **シリアルが出品と違ったら、そこで止めて出品者に連絡。**以降の作業は不要です。
> **`Last reload reason` が `Watchdog`/`Critical software exception` なら要注意** — §3 で crashinfo を見ます。

---

## 2. ライセンス(この個体の一番の争点)

出品では **`securityk9` + `appxk9` が IN USE / unthrottled** と主張されていました。
**IOS XE 17.x は Smart Licensing Using Policy (SLP)** なので、確認コマンドが従来と違います。

```
show license summary
show license usage
show license status
show license all | include Throttl|Enforce|Status|Trust
show platform hardware throughput level
```

| 確認項目 | 期待値 | 実測 |
|---|---|---|
| ライセンスレベル | `network-advantage` または `network-essentials` | |
| `securityk9` | IN USE と表示されるか | |
| `appxk9` | IN USE と表示されるか | |
| スループット制限 | **`unthrottled`**(制限なし)。`250000 kbps` 等なら制限あり | |
| Trust code / 登録状態 | 未登録でも可(下記) | |

> **⚠ ここは冷静に見てください。**
> SLP では**ライセンス未登録でも機能は動きます**(Cisco が「使わせておいて後で精算」に変えたため)。
> つまり **「IN USE と表示される」= 「正規に権利がある」ではありません。**
> ラボの検証機として動かすぶんには実害ありませんが、
> **「ライセンス付き」として買った場合、出品者の言い分が正しいかは別問題**です。
> スループットが `unthrottled` であることだけは実測で確認できるので、そこを押さえます。

---

## 3. ハードウェアの健全性(返品判断の本体)

```
show environment all
show platform
show platform hardware
show memory statistics
show file systems
dir flash:
dir crashinfo:
show logging | include ERR|WARN|FAIL|Temp|Fan|Power
show processes cpu history
show interfaces status
```

| 確認項目 | 見るところ | 判定 | 実測 |
|---|---|---|---|
| 温度 | `show environment all` | 正常範囲。`Fan Fail` が無いこと | |
| 電源 | 同上 | `OK` | |
| メモリ | `show memory statistics` | Free が極端に少なくない | |
| フラッシュ | `dir flash:` | **書き込み可能・容量が仕様どおり**。Bad block エラーが出ない | |
| **クラッシュ履歴** | `dir crashinfo:` | **ファイルが無いこと。**あれば中身を確認 | |
| ログのエラー | `show logging` | ハード起因のエラーが出ていない | |
| **8 ポート全部** | `show interfaces status` | 8 ポートとも認識されている | |

**ポートの物理確認(重要。ここが中古の一番の故障箇所)**

LAN ポートに 1 本ずつケーブルを挿して、`show interfaces status` で **8 ポート全部が `connected` になるか**を確認してください。

```
show interfaces status | include connected
```

> **1 ポートでも上がらなければ返品交渉の材料。**
> 「8P」の 8 ポートスイッチが売りなので、片肺は瑕疵です。

**異音・異臭**: ファンの異音、焦げ臭さがないか。中古の電解コンデンサは経年で膨らみます。

---

### 3-9. 前オーナーのデータ確認と消去

**消す前に、何が入っていたかだけ見ておいてください**(業務設定が残っていたら、それ自体が出品者の情報管理の問題です)。

```
show running-config | include hostname|snmp|username|key|password
dir /all flash:
show archive
```

**確認したら消します。**

```
Router# write erase
Router# delete /force /recursive flash:/*.cfg      ← 設定バックアップが residual なら
Router# reload
System configuration has been modified. Save? [yes/no]: no     ← ★ 必ず no
```

再起動後、初期設定ダイアログは `no` で抜けてください。

---

## 4. ラボ用途の確認(ここからは受け入れ判定ではなく、使い道の確認)

### 4-1. MAP-E の CLI があるか ← **この個体を買った本命**

892FJ(classic IOS)では MAP-E ができず、CML の Cat8000v は QFP が落ちて測れませんでした。
**この機体で MAP-E が動けば、バックログ 10(実効ポート数)が決着します。**

```
Router# configure terminal
Router(config)# nat64 ?
Router(config)# nat64 map-e ?
Router(config)# nat64 provisioning ?
```

| 見えたもの | 意味 |
|---|---|
| `nat64 map-e domain` と `nat64 provisioning mode jp01` が両方通る | **MAP-E の CLI あり。**次は実際に転送できるかを測る(§4-2) |
| `nat64` はあるが `map-e` が出ない | NAT64 のみ。MAP-E は不可(DS-Lite は可) |
| `nat64` 自体が無い | `show license summary` のレベルを確認。`network-essentials` なら上げて再確認 |

> **⚠ CLI が通っても「動く」とは限りません。**
> Cat8000v はここまで全部通ったうえで、`port-parameters` を入れた瞬間に転送エンジンが落ちました。
> **必ずパケットを流して出口アドレスまで確認してください**([build-log.md](build-log.md) サイクル 7)。

### 4-2. DS-Lite が動くか(892FJ の代替になるか)

892FJ は EoL なので、ハンズオンの検証機をこちらに移せるかを見ます。

```
Router(config)# interface Tunnel0
Router(config-if)#  ip address 192.0.0.2 255.255.255.248
Router(config-if)#  tunnel mode ipv6
Router(config-if)#  tunnel source <WAN>
Router(config-if)#  tunnel destination 2001:DB8:8888::1
```

`tunnel mode ipv6` が通るかを確認(IOS XE では別名の可能性あり。通らなければ `tunnel mode ?` で確認)。

### 4-3. インタフェース構成の把握

C1111-8P は **WAN 側と 8 ポートスイッチ**の構成です。892FJ とポート名が違うので、
ハンズオン資料([slides/handson.md](slides/handson.md))の `GigabitEthernet0` / `Vlan1` / `FastEthernet0` が
この機体で何に当たるかを確定してください。

```
show ip interface brief
show interfaces status
show vlan brief
```

| 892FJ での役割 | 892FJ | **C1111-8P では** |
|---|---|---|
| WAN | `GigabitEthernet0` | |
| LAN(SVI) | `Vlan1` | |
| 検証 PC を挿すポート | `FastEthernet0` | |

> **ここが埋まったら、ハンズオン資料に「892FJ / C1111 の対応表」を足す必要があります**
> (どちらの機体でも回せるようにするため)。

---

## 5. 受け入れ判定

| # | 項目 | 判定 |
|---|---|---|
| 1 | シリアルが出品と一致 | |
| 2 | IOS XE が出品どおりのバージョン | |
| 3 | スループット `unthrottled` | |
| 4 | クラッシュ履歴なし | |
| 5 | 温度・電源・ファン正常 | |
| 6 | **8 ポート全部 connected** | |
| 7 | フラッシュ書き込み可 | |
| 8 | 電源アダプタ等の付属品が揃っている | |

**1〜8 がすべて OK → 受け入れ。**
**1・2・6 のいずれかが NG → 返品交渉**(同一性と物理故障は瑕疵)。
**3 が NG(throttled だった)→ 出品情報との相違として交渉の余地あり。**ラボ用途では実害は小さい。

---

## 6. 受け入れ後にやること

1. **§4-3 の対応表を確定**して、ハンズオン資料に反映(892FJ と 2 機種対応にする)
2. **バックログ 10(MAP-E 実効ポート数)を実測** — §4-1 で CLI が通った場合
3. **ハンズオン演習 6/7 を C1111 で通し実走** — [review-phase5.md](review-phase5.md) の「要実走 1」
   - **とくに演習 6 は現状の手順では再現しない疑いがあります**(下記)
4. build-log に「サイクル 8」として記録

---

## 7. 実施記録(2026-08-13)

**判定: 受け入れ(2026-08-13 クローズ)。**§5 の 8 項目すべて OK。

> **シリアルの直接照合はできなかった。**出品ページ側の `show version` / `show inventory` /
> `show license all` は**シリアルがマスクされていた**(`FGL******` / `SN: ***`)ため。
> 中古出品でシリアルを伏せるのは通常の運用(第三者に保証・サポートを主張されるのを防ぐ)。
>
> 代わりに**マスクされていない項目の指紋照合**で判断した。IOS XE のコンパイル日時、
> メモリ表記 `1336470K/6147K`、NVRAM/物理/フラッシュ容量、動作モード、config register、
> ライセンス構成、throughput、Smart Account/Trust Code の状態、シリアル接頭辞 `FGL` が**全一致**。
>
> **決め手**: 出品ページの `Next ACK deadline: Jun 27 09:38:27 2027 UTC` から逆算すると
> ライセンスカウンタの開始は **2026-06-27 09:38:27**。実機のフラッシュの最終書き込みは
> **Jun 27 2026 09:37:41**(`.geo`)で、**46 秒差**。同一セットアップ作業として辻褄が合う。
> ACK deadline は `write erase` で消えない値なので、実機で同値なら指紋一致と判断できる。

### 個体情報

| 項目 | 実測 |
|---|---|
| PID | `C1111-8P` (VID: V01) |
| シリアル(シャーシ) | `FGL23312070` |
| シリアル(Route Processor) | `FOC2329813F` |
| IOS XE | `17.15.05` / `universalk9` / RELEASE (fc3) |
| ROMMON | `17.5(1r)` |
| **動作モード** | **`Autonomous`**(SD-WAN コントローラモードではない) |
| Config register | `0x2102` |
| Last reload reason | `PowerOn`(クラッシュ由来ではない) |
| メモリ | 4194304K(4GB) |
| フラッシュ | 2908606464 bytes 中 2020450304 bytes 空き |

### ライセンス

```
appxk9      (ISR_1100_8P_Application)  1 IN USE
securityk9  (ISR_1100_8P_Security)     1 IN USE
ipbase → ipbasek9
The current throughput level is unthrottled
Smart Licensing Status: Smart Licensing Using Policy
Smart Account: <none> / Virtual Account: <none>
```

**出品の主張どおり**(appxk9 + securityk9 が IN USE、unthrottled)。
**ただし Smart Account は未登録。**SLP は未登録でも機能が動くため、
**「IN USE 表示」は権利の証明にはならない**。ラボ用途では実害なし。

### ハードウェア

| 項目 | 実測 | 判定 |
|---|---|---|
| 温度 | Int1 35℃ / Int2 29℃ / Int3 30℃ / Int4 31℃ / CPU 35℃ すべて Normal | OK |
| モジュール | `0/0 C1111-2x1GE` ok / `0/1 C1111-ES-8` ok / `R0` ok,active / `F0` ok,active / `P0 PWR-12V` ok | OK |
| CPLD / FW | 全スロット `18032301` / `17.5(1r)` | OK |
| エラーログ | `show logging \| include ERR\|WARN\|FAIL\|Temp\|Fan\|Power` → **出力ゼロ** | OK |
| クラッシュダンプ | `core/` は `.callhome`(1 バイト)と `modules` のみ | **なし** |
| pcap | `bootflash:pcap/` は空(No such file) | **なし** |

> **ファンセンサーが無いのは正常。**C1111-8P は**ファンレス**機。
> 中古で最も多い故障箇所(ファン)が構造的に存在しない。

**8 ポート物理リンクテスト(ケーブル 1 本でペア接続、4 回)**

```
Gi0/1/0  connected  1  a-full a-1000 10/100/1000BaseTX
Gi0/1/1  connected  1  a-full a-1000 10/100/1000BaseTX
Gi0/1/2  connected  1  a-full a-1000 10/100/1000BaseTX
Gi0/1/3  connected  1  a-full a-1000 10/100/1000BaseTX
Gi0/1/4  connected  1  a-full a-1000 10/100/1000BaseTX
Gi0/1/5  connected  1  a-full a-1000 10/100/1000BaseTX
Gi0/1/6  connected  1  a-full a-1000 10/100/1000BaseTX
Gi0/1/7  connected  1  a-full a-1000 10/100/1000BaseTX
```

**8 ポートすべて 1Gbps フルデュプレックスでリンクアップ。**

### 前オーナーの痕跡(消す前に確認したもの)

```
hostname Router
username yahoo privilege 15 secret 9 $9$1LW40Z50arFkvk$...
GigabitEthernet0/0/1  192.168.1.1  YES NVRAM
```

**出品者が動作確認に使った privilege 15 アカウントが残存。**
`secret 9`(scrypt)なので実用上は破れないが、**パスワード不明の特権アカウントが生きている状態**。
→ **`write erase` するまで業務ネットワークに接続しないこと。**

フラッシュのタイムスタンプから、`Jun 27 2026` に 17.15.05 のイメージが書かれている。
出品前に出品者がアップグレードした個体と推測される。

### MAP-E の CLI(この個体を買った本命)

```
Router(config)# nat64 ?
  logging       NAT64 logging
  map-e         NAT64 MAP-E          ← ★
  map-t         NAT64 MAP-T
  prefix        NAT64 prefix
  provisioning  NAT64 provisioning   ← ★
  route         NAT64 route
  service       NAT64 service
  settings      NAT64 settings
  switchover    NAT64 switchover
  translation   NAT64 translation
  v4 / v4v6 / v6v4

Router(config)# nat64 map-e ?
  domain  NAT64 MAP-E domain
```

**MAP-E の CLI あり。**Cat8000v(CML)で QFP クラッシュにより測れなかった
**バックログ 10(実効ポート数)を、この実機で決着できる見込み。**

> **ただし CLI があることと転送できることは別物**(サイクル 7 の教訓)。
> 必ずパケットを流して出口アドレスまで確認すること。

#### MAP-E の CLI 構造(全数調査。2026-08-13)

```
(config)# nat64 provisioning mode ?
  jp01  NAT64 provisioning mode jp01          ← ★ 日本の VNE 向けモードが存在する

(config)# nat64 map-e domain 1
(config-nat64-mape)# ?
  basic-mapping-rule    Enter the NAT64 MAP-E BMR submode
  border-relay-address  MAP-E domain border-relay address
  mode                  NAT64 MAP-E Mode

(config-nat64-mape)# mode ?
  divi   Dual Stateless IPv4/IPv6
  map-e  MAP-E Mode (default)                 ← 既定が map-e なので指定不要

(config-nat64-mape)# basic-mapping-rule
(config-nat64-mape-bmr)# ?
  ipv4-prefix        IPv4 prefix              A.B.C.D/nn
  ipv6-prefix        IPv6 prefix              X:X:X:X::X/<0-128>
  local-ipv4-prefix  Local IPv4 prefix        A.B.C.D/nn
  port-parameters    NAT64 MAP-E BMR port parameters
  port-set-id        NAT64 MAP-E BMR port set id   <0-4095>

(config-nat64-mape-bmr)# port-parameters share-ratio ?
  <1-4096>
(config-nat64-mape-bmr)# port-parameters share-ratio 256 ?
  port-offset-bits  NAT64 MAP-E BMR port offset bits
  start-port        NAT64 MAP-E BMR starting port
  <cr>
```

**BMR が有効になる条件(エラーメッセージから判明)**:

```
%NAT64 MAP-E: Basic-mapping-rule for domain 1 must include ipv6-prefix,
ipv4-prefix, local-ipv4-prefix, ports-parameter, and port-set-id before it can be used.
```

**5 要素すべてが揃うまで BMR は有効化されない。**未完成のドメインは無害なまま残る。

**Cisco のモデルと RFC 7597 の対応**

`ea-length` が無い。**EA ビット長を与えて導出させるのではなく、導出結果を直接与える**設計。

| ラボの設計値(RFC 7597 系) | 導出 | C1111 のパラメータ |
|---|---|---|
| rule-ipv4-prefix `/24` | IPv4 サフィックス 8 bit | `ipv4-prefix 198.51.100.0/24` |
| ea-len 16 − 8 = **psid-len 8** | 共有数 2⁸ | **`port-parameters share-ratio 256`** |
| **psid-offset (a) = 4** | ブロック数 2⁴−1 = **15** | **`port-offset-bits 4`** |
| — | 1 ブロックのポート数 2^(16−4−8) = **16** | (share-ratio と offset から自動導出) |
| a=0 ブロック除外 | 先頭 2^(16−4) = **4096** から | `start-port`(省略時は自動と推定) |
| **15 × 16 = 240 ポート** | | |
| PSID 5(PD 方式の CE) | 4096 + 5×16 = **4176〜4191** | **`port-set-id 5`** |

`port-set-id` の範囲が `<0-4095>` なのは psid-len 12 まで許容するため。psid-len 8 なら有効範囲は 0〜255。

**ラボ設計値を C1111 の文法に翻訳したもの(PD 方式 / 未投入)**

```
nat64 provisioning mode jp01
!
nat64 map-e domain 1
 border-relay-address 2001:db8:9999::1
 basic-mapping-rule
  ipv6-prefix 2001:db8:1000::/40
  ipv4-prefix 198.51.100.0/24
  local-ipv4-prefix 198.51.100.10/32
  port-set-id 5
  port-parameters share-ratio 256 port-offset-bits 4
```

RA 方式で試す場合は `local-ipv4-prefix 198.51.100.20/32` / `port-set-id 3`。

> **`ipv4-prefix` と `local-ipv4-prefix` の役割分担は推定**(前者がルール全体、
> 後者がこの CE に割り当たった共有 IPv4)。実投入で確定させること。

#### Cat8000v との差(重要。ただし結論は出ていない)

**サイクル 7 では Cat8000v が `port-parameters` を受理した時点で QFP がクラッシュした。**
今回 C1111-8P では `port-parameters share-ratio 256` が**受理され、クラッシュしなかった。**

> **⚠ これをもって「実機なら動く」と書いてはいけない。**
> 上記のとおり **BMR は 5 要素が揃うまで有効化されない**ので、
> **この時点では転送パスにまだ何もプログラムされていない。**
> Cat8000v のクラッシュが「パラメータ受理の瞬間」だったのか
> 「BMR 有効化の瞬間」だったのかは、まだ切り分けられていない。
> **本当の判定は 5 要素を揃えてパケットを流したとき。**

### ポート名の対応(ハンズオン資料に反映が必要)

| 役割 | 892FJ | **C1111-8P** |
|---|---|---|
| WAN | `GigabitEthernet0` | **`GigabitEthernet0/0/0`** |
| LAN(SVI) | `Vlan1` | **`Vlan1`**(同じ) |
| 検証 PC を挿すポート | `FastEthernet0` | **`GigabitEthernet0/1/0`** |

WAN が routed port、`Gi0/1/0-7` が L2 スイッチポート、`Vlan1` が SVI という構成は
892FJ と同じ形なので、**ハンズオン資料はポート名の置換だけで C1111 に載る。**

### 未実施(次回)

- [ ] `write erase` → `reload`(前オーナーのアカウント除去)
- [ ] `nat64 map-e domain 1` / `nat64 provisioning ?` の中身確認(`mode jp01` があるか)
- [ ] ラボに接続して MAP-E の**実転送**テスト → バックログ 10 決着
- [ ] ハンズオン演習 6/7 の通し実走(下記の注意を参照)

---

> **演習 6(MTU)を実走するときの注意**
> 資料は 0-3 で **Vlan1 にも** `ip tcp adjust-mss 1420` を入れさせているのに、
> 演習 6 の手順では **Tunnel0 の clamp しか外しません。**
> IOS の `adjust-mss` は通過するどのインタフェースでも効くので、
> **Vlan1 側が残っている限り再現しない可能性が高い**です。
> 実走時は `show run | include adjust-mss` で両方を確認し、
> **両方外して再現するか**を確かめてください(フェーズ6 の模擬研修で判明)。
