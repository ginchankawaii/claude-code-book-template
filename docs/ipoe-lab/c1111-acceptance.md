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

> **演習 6(MTU)を実走するときの注意**
> 資料は 0-3 で **Vlan1 にも** `ip tcp adjust-mss 1420` を入れさせているのに、
> 演習 6 の手順では **Tunnel0 の clamp しか外しません。**
> IOS の `adjust-mss` は通過するどのインタフェースでも効くので、
> **Vlan1 側が残っている限り再現しない可能性が高い**です。
> 実走時は `show run | include adjust-mss` で両方を確認し、
> **両方外して再現するか**を確かめてください(フェーズ6 の模擬研修で判明)。
