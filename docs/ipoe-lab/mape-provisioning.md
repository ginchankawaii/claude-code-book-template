# MAP-E のルール配布(プロビジョニング)をラボで再現する

C1111-8P / 2026-08-13 構築 · **2026-08-14 実施完了**

> ## 結果: **通った**
>
> ```
> PC → curl http://203.0.113.80/
>   src 198.51.100.20      ← MAP-E の共有 IPv4
> ```
>
> **C1111-8P は、本番と同じ経路(ルール配布サーバからの自動取得)で MAP-E が動きます。**
> サイクル 9 の「手動 BMR で 6/6 クラッシュ」は、**本番に存在しない経路での結果**でした。
> 詳細は [build-log.md](build-log.md) サイクル 12。

---

## 0. なぜこれを作ったか — **ラボの設計不良の是正**

これまでラボの MAP-E 検証は、**CPE に `basic-mapping-rule` を手で書く**方式でやっていました。
OpenWrt がその方式で動くため、それで成立しているように見えていました。

**しかし本番はその方式ではありません。**

日本の MAP-E サービス(OCN バーチャルコネクト、v6プラス 等)では、
CPE は MAP ルールを手で設定されません。**起動時にプロビジョニングサーバから取得します。**
これは JAIPA(日本インターネットプロバイダー協会)が公開している
「IPv6 マイグレーション技術の国内標準プロビジョニング方式」= **HB46PP**
(HTTP-Based IPv4 over IPv6 Provisioning Protocol)で標準化されています。

Cisco IOS XE でこれにあたるのが `nat64 provisioning mode jp01` です。

つまり **ラボには本番に存在する構成要素(ルール配布サーバ)が丸ごと欠けており、
本番に存在しない経路(手書き BMR)だけを検証していた**ことになります。

これは実機検証の結論にも直接効きます。C1111-8P は手書き BMR で **6/6 クラッシュ**しました
([c1111-mape-defect.md](c1111-mape-defect.md))。しかしそれは
**本番で通る道ではない経路での結果**です。本番の経路で動くかどうかは、まだ分かっていません。
それを確定させるためにサーバを建てました。

> **この検証で決まったこと**
>
> | 結果 | 判定 |
> |---|---|
> | ルールを取得して転送できた | ✅ **これ。**落ちるのは手書き BMR 経路だけで、本番経路は生きている → **C1111-8P で郡山の案件に進める** |
> | 同じように QFP が落ちる | 起きなかった |
> | ルールを取得できない | 起きなかった。ただし **Cisco の `jp01` は HB46PP ではなく OCN 独自形式**だった(§2 参照) |

---

## 1. HB46PP の流れ(本番で起きていること)

```
  CPE                          DNS                    プロビジョニングサーバ
   |                            |                              |
   |-- TXT? 4over6.info ------->|                              |
   |<-- "v=v6mig-1 url=... t=b" |                              |
   |                                                           |
   |-- GET /rule.cgi?vendorid=..&product=..&capability=map_e -->|
   |<-- 200 JSON { map_e: { br, rules:[...] } } ---------------|
   |
   +-- 自分の委譲プレフィックスから EA ビットを展開し、
       共有 IPv4 アドレスと PSID を **自分で計算する**
```

**サーバは「この CPE の IPv4 は何番」を配りません。**
BMR(IPv6 プレフィックス + IPv4 プレフィックス + `ea_length` + `psid_offset`)を配るだけで、
CPE が自分の委譲プレフィックスから導出します。ここが MAP-E の肝です。

仕様: <https://github.com/v6pc/v6mig-prov/blob/master/spec.md>

---

## 1-B. ただし Cisco の `jp01` は HB46PP ではなかった(実測)

ラボのサーバは **2 つの方式に自動で応答し分けます**。要求のクエリパラメータで見分けます。

| 方式 | 要求 | 応答の器 | 使う CPE |
|---|---|---|---|
| **jp01** | `?ipv6Prefix=...&ipv6PrefixLength=...&code=<APIキー>` | `basicMapRules` | **Cisco IOS XE**(OCN バーチャルコネクト) |
| **HB46PP** | `?vendorid=...&product=...&capability=...` | `map_e` / `dslite` | 国内標準対応の CPE(DNS TXT で発見) |

C1111-8P が実際に喋った内容(ラボのサーバで捕獲):

```
GET /rule.cgi/?ipv6Prefix=2001:DB8:1014:300::&ipv6PrefixLength=64&code=<APIキー>
User-Agent: cisco-IOS
```

Cisco の 15M&T ドキュメントに載っている OCN の URL 仕様
`https://rule.map.ocn.ad.jp/?ipv6Prefix=<address>&ipv6PrefixLength=<prefixLength>&code=<API Key>`
と**同じ形**です。`api-key` が `code=` として乗ります。

**jp01 の応答形式(実機が受理した形)**:

```json
{
  "basicMapRules": [
    { "brIpv6Address": "2001:db8:9999::1",
      "ipv6Prefix": "2001:db8:1000::", "ipv6PrefixLength": "40",
      "ipv4Prefix": "198.51.100.0",    "ipv4PrefixLength": "24",
      "eaBitLength": "16", "psIdOffset": "4" }
  ]
}
```

> **値は必ず文字列にすること。** 数値で返すと、ルータは domain を作るところまで行って
> **BMR を黙って破棄します**（エラーは一切出ません）。Content-Type も
> `application/json; charset=utf-8` が必要です。

---

## 2. ラボに建てたもの

| 要素 | 値 |
|---|---|
| プロビジョニングサーバ | `2001:db8:cafe::a1`(INET-SIM 上。既存の web `::80` とは別アドレス) |
| 発見用 DNS TXT | `4over6.info` → `v=v6mig-1 url=https://prov.lab.example/rule.cgi t=b` |
| HTTPS | `https://prov.lab.example/rule.cgi`(443) |
| HTTP | `http://prov.lab.example:8080/rule.cgi` ※ |
| DS-Lite 用 FQDN | `aftr.lab.example` → `2001:db8:8888::1` |
| 応答 JSON | INET-SIM の `/etc/mape-ruleserver/response.json` |
| ログ | INET-SIM の `/var/log/mape-ruleserver.log` |

※ HTTP を 80 番にしていないのは、INET-SIM の nginx が `listen [::]:80` で
ワイルドカード待受しており IPv6 の 80 番を先に掴んでいるためです。
HB46PP の TXT は URL をそのまま配れるので、ポートが既定でなくても問題ありません。

**HTTP と HTTPS は両方常時上がっています。** Cisco の `rule-server` が `http://` を
受け付けるかは公開情報から確定できないため、朝にサーバを建て直さずどちらも試せるようにしてあります。

配布するルール(ラボの BR と同じ値):

```json
"map_e": {
  "version": 0,
  "mesh": false,
  "br": "2001:db8:9999::1",
  "rules": [
    { "ipv6": "2001:db8:1000::/40", "ipv4": "198.51.100.0/24",
      "ea_length": 16, "psid_offset": 4 }
  ]
}
```

`version: 0` は draft-ietf-softwire-map-03 を指します。Cisco の
`nat64 provisioning mode jp01 version draft-ietf-softwire-map-03` と同じ意味です。

### 導出される期待値(検証済み)

参照実装 `lab/ipoe/ce/hb46pp-client.py` で計算し、ラボの既存設定と**完全一致**することを確認済みです。

| NGN のモード | CPE の委譲プレフィックス | 共有 IPv4 | PSID | MAP CE アドレス | ポート数 |
|---|---|---|---|---|---|
| `pd`(ひかり電話あり相当) | `2001:db8:100a:500::/56` | `198.51.100.10` | 5 | `2001:db8:100a:500:0:c633:640a:5` | 240 |
| `ra`(ひかり電話なし相当) | `2001:db8:1014:300::/64` | `198.51.100.20` | 3 | `2001:db8:1014:300:0:c633:6414:3` | 240 |

240 = 15 レンジ × 16 連続ポート(`psid_offset` 4、PSID 長 8 ビット → 256 分割)。

---

## 3. 朝の手順

> **前提** NGN は現在 `ra` モードです(`radvd.conf` にプレフィックスあり)。
> この手順は `ra` モード前提で書いています。`pd` に切り替える場合は
> 上の表の `pd` 行の値に読み替えてください。

### 【手順 A】ラボ側の準備 — **作業機のターミナル**

```bash
ssh root@192.168.11.20 "ssh labadmin@fe80::be24:11ff:fecd:92c5%vmbr0 './ipoe/inet/setup-ruleserver.sh status'"
```

`4over6.info` の TXT と、`prov.lab.example` の AAAA が返ってくれば準備できています。
返らない場合は建て直してください:

```bash
ssh root@192.168.11.20 "ssh labadmin@fe80::be24:11ff:fecd:92c5%vmbr0 'sudo ./ipoe/inet/setup-ruleserver.sh https'"
```

### 【手順 B】要求を見る窓を開けておく — **別のターミナル(開けっぱなしにする)**

**これが今回いちばん重要です。** ルータが何を要求してくるかがここに出ます。

```bash
ssh root@192.168.11.20 "ssh labadmin@fe80::be24:11ff:fecd:92c5%vmbr0 'sudo tail -f /var/log/mape-ruleserver.log'"
```

### 【手順 C】ルータの復旧 — **ルータの特権 EXEC モード(`Router#`)**

クラッシュ状態から戻します。**設定は保存しません**(手書き BMR が残っていると、また落ちます)。

```
reload
```

- `System configuration has been modified. Save? [yes/no]:` → **`no`** と入力して Enter
- `Proceed with reload? [confirm]` → **Enter だけ**押す

> **注意** `[confirm]` の待ち受け中に `reload` と打たないこと。先頭の `r` が
> confirm に食われて、リロードが空振りします(過去 2 回踏んでいます)。

起動後、`Router>` が出たら特権 EXEC に上がります。

```
enable
```

### 【手順 D】手書き BMR が残っていないことを確認 — **特権 EXEC(`Router#`)**

```
show running-config | include nat64|map-e|basic-mapping
```

`nat64 map-e domain` や `basic-mapping-rule` が出てきたら、消してください。
**残したまま jp01 を試すと、どちらが原因で落ちたのか分からなくなります。**

**グローバル コンフィグ モード(`Router(config)#`)** に入って消す:

```
configure terminal
no nat64 map-e domain 1
end
```

### 【手順 E】時刻を合わせる — **特権 EXEC(`Router#`)**

**これを飛ばすと証明書の検証に失敗します。** ラボ CA の有効期間は 2026-08-13 からです。
ルータの初期時刻は過去(多くは 1993 年)なので、必ず現在時刻を入れてください。

```
clock set 09:00:00 14 Aug 2026
```

(実際の時刻に読み替えてください)

確認:

```
show clock
```

### 【手順 F】WAN と到達性の確認 — **特権 EXEC(`Router#`)**

```
show ipv6 interface brief
show ipv6 route
ping ipv6 2001:DB8:CAFE::A1
```

**`ping` が通ることがこの先の前提です。** 通らなければここで止めて連絡してください。
プロビジョニングサーバに届かないので、先へ進んでも意味がありません。

WAN 側に付いた IPv6 アドレスを控えてください(`GigabitEthernet0/0/0`)。
`2001:DB8:1014:300:...` のはずです。

### 【手順 G】DNS を設定する — **グローバル コンフィグ モード(`Router(config)#`)**

`4over6.info` を引けるようにします。本番でも CPE は網から配られた DNS を使います。

```
configure terminal
ip domain lookup
ip name-server 2001:DB8:CAFE::53
end
```

**特権 EXEC(`Router#`)** で確認:

```
ping ipv6 prov.lab.example
```

名前で ping が通れば、ルータから発見用 TXT も引けます。

### 【手順 H】ラボ CA をルータに登録する — **グローバル コンフィグ モード(`Router(config)#`)**

HTTPS で証明書検証(`t=b`)を通すために必要です。

```
configure terminal
crypto pki trustpoint LAB-PROV-CA
 enrollment terminal
 revocation-check none
exit
crypto pki authenticate LAB-PROV-CA
```

証明書の貼り付けを促されるので、以下をそのまま貼り、最後に **`quit`** と入力して Enter:

```
-----BEGIN CERTIFICATE-----
MIIDejCCAmKgAwIBAgIUGEt55iG6qtGU8dd6QrqaDUHwRiowDQYJKoZIhvcNAQEL
BQAwQzELMAkGA1UEBhMCSlAxETAPBgNVBAoMCElQb0UgTGFiMSEwHwYDVQQDDBhJ
UG9FIExhYiBQcm92aXNpb25pbmcgQ0EwHhcNMjYwODEzMTYwNTM0WhcNMzYwODEw
MTYwNTM0WjBDMQswCQYDVQQGEwJKUDERMA8GA1UECgwISVBvRSBMYWIxITAfBgNV
BAMMGElQb0UgTGFiIFByb3Zpc2lvbmluZyBDQTCCASIwDQYJKoZIhvcNAQEBBQAD
ggEPADCCAQoCggEBAL4X20CWpw8Y85anVcfdbYwU1rZemGV5UUg64nhTGHwHTC2c
WY+B5GUX9yWLflc8CUuQGb9MkoOOpu8ZNbJj4sDnZKJcmmpTpKLaIdCo4SFWXv5g
5vWMFHssu/VzxeooveU8JWFQLjca9pxu0URCqWrM6oMhM0pnKUsdmReMDkgDbXUt
MBfINX3jtuBBse+F/nY2aIvDd7vOf3wV9GcyjHJHMfJGNUSZq5dHGH+UNzXj8mSX
7CvXnYrBe8sPPxk2+1KF86plsuDXL6jvFPBqs7R7xmoMhoyM3Z67m3dClugwItqR
pXKhF3H9lHY/5geHW89PhTma7xDUz3Djy+JXBgsCAwEAAaNmMGQwHQYDVR0OBBYE
FEP9yPc7EP1K8bS4e//FzE4rgWfoMB8GA1UdIwQYMBaAFEP9yPc7EP1K8bS4e//F
zE4rgWfoMBIGA1UdEwEB/wQIMAYBAf8CAQAwDgYDVR0PAQH/BAQDAgEGMA0GCSqG
SIb3DQEBCwUAA4IBAQCqHSnYYDOUiUmf6lVMeDky/njue60QDwJ55AkoTX8Zw4T/
4yiuwHaTyuUNn9OJknNYYYzhQRl8jML3SVLQ01owpa1mUykGgWRcUsbxXV88jnt5
9ypTJGyYPZiGQCk/lDaJpcNcWbjR6MfBizbgW8XEhcwYZsQxLdQSubsANPlr1Aa/
n7JW/JjqZxUZk+8cSWLSVi+R6hsPBsq+Sgilv43noHtP9TNlMsEZfaf1+9dK1Y4e
nm72UndW0lPLlQ1ZTTaFAF15JoiPlBagYr0M886E1iizuDk4mV7rEXSMZAY9TSaQ
ZxgjKN6/O3Ov9qDjGfsMdJu5MYezy3fRD8f77+1k
-----END CERTIFICATE-----
quit
```

`% Do you accept this certificate? [yes/no]:` → **`yes`**

> **この証明書はラボで生成したものです。** 作り直した場合は中身が変わります。
> そのときは作業機で `./ipoe/inet/setup-ruleserver.sh ca` を実行して出し直してください。

**グローバル コンフィグ(`Router(config)#`)** のまま次へ。

### 【手順 I】NAT64 と jp01 を設定する — **グローバル コンフィグ(`Router(config)#`)**

**これが実機で通った構成そのものです。** そのまま貼れます。

```
configure terminal
nat64 settings fragmentation header disable
nat64 route 0.0.0.0/0 GigabitEthernet0/0/0
interface GigabitEthernet0/0/0
 nat64 enable
exit
nat64 provisioning mode jp01
version draft-ietf-softwire-map-03
rule-server http://prov.lab.example:8080/rule.cgi
api-key LABTESTAPIKEY123
tunnel source GigabitEthernet0/0/0
service-prefix 2001:DB8:1000::/40
exit
end
```

踏みやすい点が 3 つあります。

| 落とし穴 | 実際 |
|---|---|
| `nat64 provisioning mode jp01 version ...` と 1 行で書く | **構文エラーになります。**17.9.5f では `version` は**サブモードの中**です(ドキュメントの 1 行表記は古い) |
| `api-key` が短い | **12〜80 文字**必要です。`LABTEST` は弾かれます |
| `service-prefix` を省く | **これが最後のピースで、無いと要求を出しません** |

`rule-server` は **HTTP URL をそのまま取ります**(`WORD  HTTP url (1-200) characters`)。
HTTPS にする場合は手順 H の CA 登録が要りますが、**まず HTTP で通すのが早い**です。

### 【手順 J】取得を叩き起こす — **グローバル コンフィグ(`Router(config)#`)**

**設定を入れただけでは要求を出しません。** WAN のアドレス再取得が引き金です。

```
configure terminal
interface GigabitEthernet0/0/0
 shutdown
 no shutdown
end
```

一度取得すると `bootflash:/mape/mape-rule.json` に**暗号化して保存**され、
以後は **約 8 分周期でリトライ**します。取り直させたいときはキャッシュを消してください。

**特権 EXEC(`CPE#`)**:

```
delete /force bootflash:/mape/mape-rule.json
```

### 【手順 K】要求が来たかを見る — **手順 B のターミナル**

ここで **手順 B の窓**を見てください。ルータが要求を出していれば、こう出ます:

```
[https] GET /rule.cgi?vendorid=...&product=...&capability=... HTTP/1.1  from 2001:db8:1014:300:...
--- クエリパラメータ ---
    vendorid       = ...
    product        = ...
--- ヘッダ ---
    Host: prov.lab.example
    ...
--> 200 application/json (543 バイト) を返しました
```

**何も出ない場合**は、そもそも届いていません。INET-SIM でパケットを直接見てください:

```bash
ssh root@192.168.11.20 "ssh labadmin@fe80::be24:11ff:fecd:92c5%vmbr0 'sudo timeout 60 tcpdump -ni any -c 20 host 2001:db8:cafe::a1'"
```

- **パケットが来ていない** → ルータが要求を出していない(設定が効いていない/DNS で詰まっている)
- **TCP は来ているが応答後に切れる** → TLS の失敗(時刻ずれか CA 未登録)

### 【手順 L】ルータ側の結果を見る — **特権 EXEC(`Router#`)**

```
show nat64 map-e
show nat64 statistics
show nat64 prefix stateless
show running-config | section nat64
```

さらに詳しく見る場合(**特権 EXEC**):

```
debug nat64 provisioning
terminal monitor
```

(止めるときは `undebug all`)

### 【手順 M】期待値と照合する

ルータが取得・導出した値を、**参照実装の計算結果**と突き合わせます。

| 項目 | 期待値(`ra` モード) | 実機の実測 |
|---|---|---|
| 共有 IPv4 アドレス | `198.51.100.20` | ✅ 一致 |
| PSID | `3` | ✅ 一致 |
| Share-ratio / 連続ポート | 256 / 16 | ✅ 一致 |
| 使えるポート数 | 240 (15×16) | ✅ 一致 |
| BR アドレス | `2001:db8:9999::1` | ✅ 一致 |
| **MAP CE アドレス** | RFC 7597 なら `...300:0:c633:6414:3` | ⚠ **`...300:c6:3364:1400:300`** |

作業機で計算し直す場合:

```bash
ssh root@192.168.11.20 "ssh labadmin@fe80::be24:11ff:fecd:92c5%vmbr0 'python3 ./ipoe/ce/hb46pp-client.py --selftest'"
```

### 【手順 N】BR を CPE の実アドレスに向ける — **作業機のターミナル**

> ⚠ **ここが一番の落とし穴です。**
>
> Cisco を `draft-ietf-softwire-map-03` で動かすと、CE の MAP アドレスの
> **インタフェース ID の並びが RFC 7597 と 1 バイトずれます**。
>
> | | インタフェース ID | アドレス |
> |---|---|---|
> | RFC 7597 5.2 | `0000:<IPv4>:<PSID>` | `2001:db8:1014:300:0:c633:6414:3` |
> | **実機(draft-03)** | `00:<IPv4>:<PSID>:00` | `2001:db8:1014:300:c6:3364:1400:300` |
>
> 中身(IPv4=198.51.100.20 / PSID=3)は同じですが**並びが違います**。
> ラボの BR はトンネル終点を静的に持つので、**RFC 7597 の方に張ったままだと IPv4 が全断**します。

**必ず実機で確認してから**張ってください。**特権 EXEC(`CPE#`)**:

```
show ipv6 interface brief
```

`GigabitEthernet0/0/0` に増えている方が MAP CE アドレスです。その値で BR を張ります:

```bash
ssh root@192.168.11.20 "ssh labadmin@fe80::be24:11ff:feb9:3fb1%vmbr0 'sudo CE_MAP_ADDR=2001:db8:1014:300:c6:3364:1400:300 CE_SHARED_V4=198.51.100.20 ./ipoe/vne/setup-map-br.sh'"
```

### 【手順 N-2】LAN を作って PC から確認する

**ルータ自身の `ping` では判定できません。** Cisco のドキュメントに
「local packet generation 非対応」とあります。**PC からの実トラフィックで判定**します。

**グローバル コンフィグ(`CPE(config)#`)**:

```
configure terminal
interface Vlan1
 ip address 192.168.100.1 255.255.255.0
 ip tcp adjust-mss 1420
 nat64 enable
 no shutdown
end
```

PC を `Gi0/1/0` に繋ぎ、静的 IP を設定します:

| 項目 | 値 |
|---|---|
| IP アドレス | `192.168.100.10` |
| サブネットマスク | `255.255.255.0` |
| デフォルトゲートウェイ | `192.168.100.1` |
| DNS | `203.0.113.53` |

> ⚠ **PC の Wi-Fi を切ってください。**
> 有線と Wi-Fi が両方生きていると、宛先によっては Wi-Fi 側へ抜けて
> **「ルータは正常なのに疎通しない」**という切り分け不能な状態になります。
> 実際にこれで 30 分溶かしました。**切替当日にも必ず起こります。**

**PC のコマンドプロンプト**:

```bash
curl http://203.0.113.80/
```

**`src 198.51.100.20` が出れば完了**です。ルータ側の裏取り — **特権 EXEC(`CPE#`)**:

```
show nat64 statistics
```

`Vlan1` の `IPv4 -> IPv6 MAP-E` と `Gi0/0/0` の `IPv6 -> IPv4 MAP-E` が
両方増えていれば、往復とも MAP-E を通っています。

### 【手順 O】落ちた場合の切り分け — **作業機のターミナル**

MAP-E を配ると落ちる場合、**DS-Lite だけを配って**もう一度試してください。

```bash
ssh root@192.168.11.20 "ssh labadmin@fe80::be24:11ff:fecd:92c5%vmbr0 'sudo ./ipoe/inet/setup-ruleserver.sh response dslite'"
```

(サーバの再起動は要りません。次の要求から反映されます)

ルータを再起動して同じ手順を踏み、結果を見ます。

| DS-Lite だけを配った結果 | 分かること |
|---|---|
| **正常に動く** | **プロビジョニングの仕組みは生きている。**問題は **MAP-E のデータパスに限定**される。C1111 でこの回線は無理、という判断材料になる |
| **同じように落ちる** | プロビジョニング処理そのもの、または NAT64 の有効化自体が壊れている |

戻すとき:

```bash
ssh root@192.168.11.20 "ssh labadmin@fe80::be24:11ff:fecd:92c5%vmbr0 'sudo ./ipoe/inet/setup-ruleserver.sh response both'"
```

> **DS-Lite を試す前に、ラボの AFTR を起動しておいてください。**
> `./lab-mode.sh dslite <CE の WAN 側 IPv6>`

---

## 4. 結果の記録

**落ちても落ちなくても、以下を残してください。**

- 手順 B の窓に出た**要求の全文**(クエリパラメータとヘッダ)
- 手順 I の `?` の出力
- 手順 L の `show` の出力
- 落ちた場合は `show version | include uptime|reason` と `dir crashinfo:`

判定は §0 の表のとおりです。

---

## 5. ラボ側の操作まとめ

すべて INET-SIM(`labadmin@fe80::be24:11ff:fecd:92c5%vmbr0`)で実行します。

| やること | コマンド |
|---|---|
| 建てる(TXT は HTTPS を案内) | `sudo ./ipoe/inet/setup-ruleserver.sh https` |
| 建てる(TXT は HTTP を案内) | `sudo ./ipoe/inet/setup-ruleserver.sh http` |
| 状態を見る | `./ipoe/inet/setup-ruleserver.sh status` |
| 要求を見る | `./ipoe/inet/setup-ruleserver.sh log` |
| 自分で疎通確認 | `./ipoe/inet/setup-ruleserver.sh selftest` |
| ルータ用 CA を出す | `./ipoe/inet/setup-ruleserver.sh ca` |
| 配る方式を絞る(切り分け) | `sudo ./ipoe/inet/setup-ruleserver.sh response {both\|mape\|dslite}` |
| 止める | `sudo ./ipoe/inet/setup-ruleserver.sh stop` |

司会用の `lab-mode.sh` からも同じことができます(Proxmox ホストで実行):

| やること | コマンド |
|---|---|
| 起動 / 停止 | `./lab-mode.sh prov on` / `./lab-mode.sh prov off` |
| 状態 / 要求を見る | `./lab-mode.sh prov status` / `./lab-mode.sh prov log` |
| ルータ用 CA | `./lab-mode.sh prov ca` |
| 配る方式を絞る | `./lab-mode.sh prov dslite` / `./lab-mode.sh prov both` |

**応答 JSON を変えたいとき**は、方式ごとに次のファイルを直接編集してください。
**リクエストのたびに読み直す**ので、サーバの再起動は要りません。

| 方式 | 配置先 | 正本(リポジトリ) |
|---|---|---|
| jp01 (Cisco / OCN) | `/etc/mape-ruleserver/response-jp01.json` | `lab/ipoe/inet/ruleserver-response-jp01.json` |
| HB46PP (国内標準) | `/etc/mape-ruleserver/response-hb46pp.json` | `lab/ipoe/inet/ruleserver-response-hb46pp.json` |

どちらを返すかは**要求のクエリパラメータで自動判別**されます(§1-B)。
恒久的な変更は正本を直して `deploy.sh` で配り直してください。

---

## 6. 確定したこと / 未確定のこと

### 確定した(実測)

- **Cisco の `jp01` は HB46PP ではない。** OCN の独自形式(`ipv6Prefix` / `code` /
  `basicMapRules`)で、Cisco の 15M&T ドキュメントの記載と一致する
- **応答の値は文字列でなければならない。** 数値だと黙って破棄される
- **`service-prefix` が無いと要求を出さない。** `tunnel source` は送信元インタフェース
- **CE の MAP アドレスは RFC 7597 と並びが違う**(draft-03)
- **C1111-8P + 17.09.05f で MAP-E の実トラフィックが通る**

### まだ未確定

- **実回線の OCN が返す JSON は未確認。** 器の名前 `basicMapRules` は
  「ルータがこの形を期待している」ことまでは確定したが、OCN 側の実物は見ていない
- **C1111-8P が MAP-E の qualify 対象プラットフォームか。** Cisco Feature Navigator は
  CCO ログインが要るため、会社のアカウントで確認する必要があります
- **240 ポートを使い切れるか。** 割当範囲内のポートを使うことは確認できたが
  (送信元ポート 4145 = 範囲 4144-4159)、15 レンジ全部は未測定(バックログ 10)
- **1 回だけ `HTTP CORE` の Segfault が出た。** 同じ入力で再現せず。
  証拠は `bootflash:core/CPE_RP_0-system-report_20260814-230256-JST.tar.gz`

---

## 7. 参考

- HB46PP 仕様(JAIPA / IPv6 普及・高度化推進協議会)
  <https://github.com/v6pc/v6mig-prov/blob/master/spec.md>
- JAIPA トピックス「IPv6マイグレーション技術の国内標準プロビジョニング方式 第1.2版」
  <https://www.jaipa.or.jp/topics/2025/06/-ipv6-12.php>
- RFC 7597 (MAP-E)
- 関連: [c1111-mape-defect.md](c1111-mape-defect.md) / [c1111-acceptance.md](c1111-acceptance.md) / [build-log.md](build-log.md)
