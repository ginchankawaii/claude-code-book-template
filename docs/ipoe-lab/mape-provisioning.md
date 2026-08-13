# MAP-E のルール配布(プロビジョニング)をラボで再現する

C1111-8P / 2026-08-13 構築 · 実施は未了(ルータ操作は朝)

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

> **この検証で決まること**
>
> | 結果 | 意味 | 次の判断 |
> |---|---|---|
> | ルールを取得して転送できる | 落ちるのは**手書き BMR 経路だけ**。本番経路は生きている | C1111-8P で郡山の案件に進める |
> | 同じように QFP が落ちる | **MAP-E のデータパス自体**がこの機種/ファームで壊れている | YAMAHA 等に切り替える判断材料になる |
> | ルールを取得できない(要求が来ない/形式が違う) | Cisco の `jp01` が HB46PP と別物 | 捕獲したログから応答を作り直して再試行 |

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

### 【手順 I】`jp01` のサブコマンドを確認する — **グローバル コンフィグ(`Router(config)#`)**

**先に構文を確かめます。** `rule-server` が URL を取るのか、`http://` を受けるのかは
公開情報から確定できていません。**ここの出力を後で私に見せてください。**

```
nat64 provisioning mode jp01 version draft-ietf-softwire-map-03
```

プロビジョニング サブモードに入ります(プロンプトが変わります)。そこで:

```
?
rule-server ?
api-key ?
hostname ?
service-prefix ?
tunnel ?
```

### 【手順 J】ルール配布サーバを指定する — **プロビジョニング サブモード**

手順 I の出力次第ですが、まずは HTTPS + FQDN で試してください。

```
rule-server https://prov.lab.example/rule.cgi
exit
end
```

**構文が通らなかった場合**に順に試す候補(通るものが出るまで):

```
rule-server prov.lab.example
rule-server https://prov.lab.example/rule.cgi
rule-server http://prov.lab.example:8080/rule.cgi
rule-server https://[2001:DB8:CAFE::A1]/rule.cgi
```

`api-key` が必須と言われた場合は、**中身は何でも構いません**(ラボのサーバは検証しません):

```
api-key LABTEST
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

| 項目 | 期待値(`ra` モード) |
|---|---|
| 共有 IPv4 アドレス | `198.51.100.20` |
| PSID | `3` |
| MAP CE アドレス | `2001:db8:1014:300:0:c633:6414:3` |
| BR アドレス | `2001:db8:9999::1` |
| 使えるポート数 | 240 |

作業機で計算し直す場合:

```bash
ssh root@192.168.11.20 "ssh labadmin@fe80::be24:11ff:fecd:92c5%vmbr0 'python3 ./ipoe/ce/hb46pp-client.py --url \"https://[2001:db8:cafe::a1]/rule.cgi\" --cacert /etc/mape-ruleserver/ca/ca.pem --prefix 2001:db8:1014:300::/64'"
```

### 【手順 N】BR を CPE に向けて疎通を試す — **作業機のターミナル**

ラボの BR は 1 台の CE 向けに静的トンネルを張る作りなので、CPE の MAP アドレスに合わせます。

```bash
ssh root@192.168.11.20 "ssh labadmin@fe80::be24:11ff:feb9:3fb1%vmbr0 'sudo CE_MAP_ADDR=2001:db8:1014:300:0:c633:6414:3 CE_SHARED_V4=198.51.100.20 ./ipoe/vne/setup-map-br.sh'"
```

そのうえで **ルータの特権 EXEC(`Router#`)** から:

```
ping 203.0.113.80 source Vlan1
```

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
| 止める | `sudo ./ipoe/inet/setup-ruleserver.sh stop` |

**応答 JSON を変えたいとき**は `/etc/mape-ruleserver/response.json` を直接編集してください。
**リクエストのたびに読み直す**ので、サーバの再起動は要りません。
ただし正本はリポジトリの `lab/ipoe/inet/ruleserver-response.json` です。
恒久的な変更はそちらを直して `deploy.sh` で配り直してください。

---

## 6. 未確定のこと

- **Cisco の `jp01` が HB46PP そのものかは未確認。** サブモードに `api-key` があり、
  HB46PP には `api-key` パラメータがありません(認証は `user`/`pass`/`token`)。
  JPNE 系の独自 API を実装している可能性があります。**手順 K の捕獲で確定します。**
- **C1111-8P が MAP-E の対応機種かは未確認。** Cisco Feature Navigator は
  CCO ログインが要るため、会社のアカウントで確認する必要があります。
- **`service-prefix` / `tunnel` サブコマンドの意味が不明。** 手順 I の `?` で確認します。

---

## 7. 参考

- HB46PP 仕様(JAIPA / IPv6 普及・高度化推進協議会)
  <https://github.com/v6pc/v6mig-prov/blob/master/spec.md>
- JAIPA トピックス「IPv6マイグレーション技術の国内標準プロビジョニング方式 第1.2版」
  <https://www.jaipa.or.jp/topics/2025/06/-ipv6-12.php>
- RFC 7597 (MAP-E)
- 関連: [c1111-mape-defect.md](c1111-mape-defect.md) / [c1111-acceptance.md](c1111-acceptance.md) / [build-log.md](build-log.md)
