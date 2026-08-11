# IPv6 / IPoE ハンズオン — 実機を触って、環境が変わるのを見る

**対象**: 説明会(`setsumeikai.md`)を受けた人
**時間**: 150 分(休憩 10 分 × 1 を含む)
**やること**: **実機のルータ(Cisco 892FJ)にコマンドを打つ。**その間、司会が裏で網の方式を切り替える
**使う端末**: 実機の Cisco 892FJ(コンソール接続)と、**Windows の検証用 PC**

> **時間配分は仮案です。**通しでの実測はまだしていません。
> **初回はパイロットとして、各演習の実測時間をメモしながら回してください。**
>
> | | 内訳 |
> |---|---|
> | 0-2 実機を消す / 0-3 設定を入れる | 10 + 10 分 |
> | 第1部 アドレスが降りてくるのを見る | 30 分 |
> | 第2部 IPv4 を通す | 40 分 |
> | 休憩 | 10 分 |
> | 第3部 壊す | 40 分 |
> | 第4部 戻して終わる | 10 分 |

---

## この資料の作り(前の版から変えたところ)

**受講者はサーバを触りません。実機のルータだけを触ります。**

| 誰が | 何をするか |
|---|---|
| **司会(講師)** | `lab-mode.sh` で網の方式を切り替える。**「いま RA 方式です」と宣言する** |
| **受講者** | **実機の 892FJ にログインして、IOS のコマンドを打つ**。出力を読む |

**同じコマンドを打っても、網の方式が変わると出力が変わります。**
そこを見るのがこのハンズオンです。

**各演習は必ずこの 3 点セットで書いてあります。**

1. **打つコマンド**(そのまま写せる形)
2. **出てくる出力**(何が出れば正解か)
3. **いま何が起きたのか**(← ここが一番大事。コマンドを打つだけでは何も残りません)

---

## 0-0b. 検証ラボ 構成図(図 1 枚)

`docs/ipoe-lab/topology.png` をそのまま貼ります。右側に読み方を添えます。

- **上の枠がハイパーバイザ。**中は全部 仮想マシン(NTT の網も VNE も Linux VM)
- **枠の外(下)が物理。**物理 NIC → 物理スイッチ → 実機 CPE → 検証 PC
- **今日あなたが触るのは赤枠の 2 つだけ**(実機 CPE と 検証 PC)。青枠は司会が動かします
- 迷ったときの目印: **PG-ACCESS = アドレスが配られる場所 / VNE = IPv4 を取り出す場所 / INET-SIM = 行き先**
- 図の一番下に**方式ごとの経路と出口アドレス**

> **司会へ:** このページは飛ばさないこと。ここが入っていないと以降が全部ぼやけます。
> **ホワイトボードにも同じ絵を描いて、演習中ずっと残しておいてください。**「いまどこの話か」を毎回この絵で指します。

---

## 0-1. 今日の進め方

```
   ┌──────────────┐        ┌────────────────────────┐
   │  司会の端末   │        │   受講者(あなた)        │
   │              │        │                        │
   │ lab-mode.sh  │        │  コンソールケーブル     │
   │  ra / pd     │        │       ↓                │
   │  mape/dslite │        │   [ Cisco 892FJ ]      │
   │  break ...   │        │       ↓ FastEthernet0  │
   └──────┬───────┘        │   [ 検証用 PC ]        │
          │                └────────────────────────┘
          │ ssh                        │ 物理ケーブル
    ┌─────┴──────────────────────────┐ │
    │ NGN-SIM / VNE / INET-SIM       │─┘
    │ (NTT の網と VNE の代わり)       │
    └────────────────────────────────┘
```

**あなたが触るのは 892FJ と検証用 PC だけです。**サーバ側は司会が動かします。

### 司会が使うコマンド(受講者は打ちません)

```bash
./lab-mode.sh status              # いま何方式か
./lab-mode.sh ra                  # ひかり電話なし相当に切り替え
./lab-mode.sh pd                  # ひかり電話あり相当に切り替え
./lab-mode.sh dslite <CEのIPv6>   # IPv4 の運び方を DS-Lite に
./lab-mode.sh mape                # IPv4 の運び方を MAP-E に (CE は OpenWrt)
./lab-mode.sh break mtu           # MTU 障害を注入
./lab-mode.sh break dns           # IPv6 だけ死んだサイトを作る
./lab-mode.sh restore             # 障害を戻す
```

**切り替えるたびに、司会は「いま何方式か」と「期待する出口アドレス」を読み上げてください。**
`lab-mode.sh` がそれを画面に出します。

---

## 0-2. まず実機をまっさらにする(10 分)

**前の案件の設定が残っていると、原因不明のトラブルになります。**必ず消してください。

```
Router# write erase
Erasing the nvram filesystem will remove all configuration files! Continue? [confirm]  ← Enter
Router# reload
System configuration has been modified. Save? [yes/no]:  no          ← ★ no と答える
Proceed with reload? [confirm]  ← Enter
```

再起動後、初期設定ダイアログが出たら **`no`** と答えてください。

### いま何が起きたか

**設定を全部消して、工場出荷に近い状態に戻しました。**
`Save?` に `yes` と答えると消したはずの設定が書き戻るので、**ここは必ず `no`** です。

---

## 0-3. 最低限の設定を入れる(10 分)

```
Router> enable
Router# configure terminal

hostname CPE
no ip domain lookup
ipv6 unicast-routing

interface GigabitEthernet0
 description WAN
 no ip address
 ipv6 address autoconfig default
 ipv6 enable
 ipv6 nd ra suppress all
 no shutdown
!
interface Vlan1
 description LAN
 ip address 192.168.100.1 255.255.255.0
 ip tcp adjust-mss 1420
 no shutdown
!
interface FastEthernet0
 description 検証用 PC
 switchport access vlan 1
 no shutdown
!
end
write memory
```

### 検証用 PC 側の設定(こちらも先にやっておく)

**検証用 PC は Windows です。**今日は全部 Windows のコマンドで進めます。
**DHCP は使いません**(892FJ の DHCP サーバは機種によって挙動が違い、そこで詰まると本題に入れないため)。
`FastEthernet0` に繋いだ有線アダプタに、**固定でこの 3 つ**を入れてください。

| 項目 | 値 |
|---|---|
| IP アドレス | `192.168.100.50` / `255.255.255.0` |
| デフォルトゲートウェイ | `192.168.100.1`(= 892FJ の Vlan1) |
| DNS サーバ | `203.0.113.53`(= 模擬インターネットの DNS) |

```powershell
netsh interface ip set address "イーサネット" static 192.168.100.50 255.255.255.0 192.168.100.1
netsh interface ip set dns     "イーサネット" static 203.0.113.53
```

> インタフェース名は `netsh interface show interface` で確認してください。
> **終わったら元に戻すのを忘れずに**(演習 9 に戻し方があります)。

### いま何が起きたか

**1 行ずつ意味があります。**

| 設定 | 意味 |
|---|---|
| `ipv6 unicast-routing` | このルータを IPv6 のルータとして動かす。**これが無いと転送しません** |
| `ipv6 address autoconfig` | **網から降ってくる RA を使って、自分でアドレスを作る**(説明会の SLAAC) |
| `ipv6 nd ra suppress all` | **自分は RA を撒かない。**入れないと網側に RA を流してしまい、実網では事故 |
| `ip tcp adjust-mss 1420` | **後半の MTU の演習で効きます。**いまは入れておくだけ |

**`GigabitEthernet0` が WAN です。**890 系は機種で構成が違うので、
`show ip interface brief` で実物を確認してから使ってください。

---

# 第1部 アドレスが降りてくるのを見る(30 分)

## 演習 1: RA 方式で IPv6 が付く — やり取りを目で見ながら(15 分)

### 【司会】

```bash
./lab-mode.sh ra
```

> **「いまラボは RA 方式です。ひかり電話なしのお客様と同じ状態です」**と宣言してください。

### 【受講者】892FJ で

**先に `debug` を仕掛けてから**インタフェースを上げ下げします。
そうすると、アドレスが付くまでのやり取りがそのまま流れます。

```
CPE# debug ipv6 nd
CPE# configure terminal
CPE(config)# interface GigabitEthernet0
CPE(config-if)# shutdown
CPE(config-if)# no shutdown
CPE(config-if)# end
```

### 出てくる出力(まずやり取り)

```
ICMPv6-ND: Sending RS on GigabitEthernet0
ICMPv6-ND: Received RA from FE80::AC:FF:FE00:1 on GigabitEthernet0
ICMPv6-ND:   Prefix 2001:DB8:1014:300::/64 onlink autoconfig
ICMPv6-ND: Autoconfiguring address 2001:DB8:1014:300:E6AA:5DFF:FE82:364A
```

**流れ終わったら必ず止めてください。**

```
CPE# undebug all
CPE# show ipv6 interface GigabitEthernet0
```

### 出てくる出力(結果)

```
GigabitEthernet0 is up, line protocol is up
  IPv6 is enabled, link-local address is FE80::E6AA:5DFF:FE82:364A
  Global unicast address(es):
    2001:DB8:1014:300:E6AA:5DFF:FE82:364A, subnet is 2001:DB8:1014:300::/64
```

### いま何が起きたか

**3 段階です。デバッグの 4 行がそのまま対応しています。**

1. `no shutdown` した瞬間、892FJ は **`FE80::` のアドレスを自分で作りました**
   (説明会の「鶏と卵」。誰にも聞かずに作れるアドレス)
2. `Sending RS` … その `FE80::` を送信元にして、**「ルータいますか」と網に聞きました**
3. `Received RA from FE80::...` … 網が答えました。**送信元がリンクローカル**です
   - `Prefix ... onlink autoconfig` … **`autoconfig` という印**が付いているので、自分で作ってよい
   - `Autoconfiguring address` … 後半を自分で作って完成させました

**後半は MAC アドレスから作られています。**`E4:AA:5D:82:36:4A` が変形して入っているのが見えます。

> **この `Prefix ... autoconfig` の 1 行を覚えておいてください。**
> 次の演習で、**この 1 行だけが消えます。**

---

## 演習 2: PD 方式に切り替えると、アドレスが付かなくなる(15 分)

**今日いちばん大事な演習です。**

### 【司会】

```bash
./lab-mode.sh pd
```

> **「いま PD 方式にしました。ひかり電話ありのお客様と同じ状態です」**と宣言してください。

### 【受講者】さっきと まったく同じ操作を もう一度

```
CPE# debug ipv6 nd
CPE# configure terminal
CPE(config)# interface GigabitEthernet0
CPE(config-if)# shutdown
CPE(config-if)# no shutdown
CPE(config-if)# end
CPE# undebug all
CPE# show ipv6 interface GigabitEthernet0
```

### 出てくる出力

```
GigabitEthernet0 is up, line protocol is up
  IPv6 is enabled, link-local address is FE80::E6AA:5DFF:FE82:364A
  No global unicast address is configured        ← ★ 付かない
```

### いま何が起きたか — ここを 5 分かけて説明してください

**設定は 1 文字も変えていません。網の方式が変わっただけです。**

| | RA 方式 | PD 方式 |
|---|---|---|
| 網が RA で配るもの | **プレフィックス(前半)** | **「DHCPv6 で取りに来い」という指示だけ** |
| `autoconfig` の結果 | **アドレスが作れる** | **材料が無いので作れない** |

**`ipv6 address autoconfig` は、RA の中のプレフィックスからしかアドレスを作れません。**
PD 方式では網がプレフィックスを RA に載せないので、**何も取れないのです。**

### これが実案件だとどう出るか

**一番たちが悪いのは、RA 自体は届いていることです。**
さっきのデバッグ出力を、演習 1 のときと見比べてください。

```
ICMPv6-ND: Sending RS on GigabitEthernet0
ICMPv6-ND: Received RA from FE80::AC:FF:FE00:1 on GigabitEthernet0   ← RA は届いている
                                                                      ← ★ Prefix の行が無い
```

**`Received RA` は出ています。**消えたのは `Prefix ... autoconfig` の 1 行だけです。
「RA を受け取ったルータ」も、ちゃんと見えています。

```
CPE# show ipv6 routers
  Router FE80::AC:FF:FE00:1 on GigabitEthernet0, last update 0 min
```

> **これは「網から受け取った RA」の一覧です。**
> よく似た `show ipv6 interface | include Router advertisement` は
> **自分が送る RA の設定値**なので、受信の確認には使えません。間違えやすいので注意。

「RA は来ている。ケーブルも問題ない。なのにアドレスが付かない」
→ **原因が見えません。**方式の食い違いを疑えるかどうかが分かれ目です。

**対処**: PD 方式のお客様には、**DHCPv6-PD に対応した CPE** が要ります。
`autoconfig` だけの設定では成立しません。

### これは実際に自社で起きた事故です

**ある事業者向け回線で、2 回続けて開通できませんでした。**

| | 担当者が想定したもの | 実際 | 結果 |
|---|---|---|---|
| **1 回目** | 動的 IP コースだと思って設定 | **固定 IP コース**だった | 失敗 |
| **2 回目** | 固定 IP と気づき、**PD 方式**だと思って設定 | **RA 方式**だった | 失敗 |

**担当者のミスとして片付けてはいけません。**その回線の公式ページには
**IPv4 の運び方は書いてあるのに、IPv6 の払い出し方式(RA か PD か)が書かれていません。**
**公開情報だけでは机上で決められない**のです。

> **だから開通後に実測するしかありません。**
> いまあなたが見た「設定は同じなのにアドレスが付かない」が、そのとき現場で起きていた光景です。
> **先に見ておけば気づけます。**それがこの演習の目的です。

---

## 第1部のまとめ(演習 2 の説明の中で読む。追加の時間は取りません)

**設定は 1 文字も変えていないのに、網の方式だけで結果が変わりました。**

| | 演習 1 (RA 方式) | 演習 2 (PD 方式) |
|---|---|---|
| `Received RA` | 出る | **出る**(ここが罠) |
| `Prefix ... autoconfig` | 出る | **出ない** |
| アドレス | **付く** | **付かない** |

**現場では「RA が来ているか」だけを見て『網は正常』と判断しがちです。**
見るべきは **`Prefix ... autoconfig` の 1 行**でした。

### 【司会】次の部に入る前に RA 方式へ戻す

```bash
./lab-mode.sh ra
```

---

# 第2部 IPv4 を通す(40 分)

## 演習 3: DS-Lite のトンネルを張る(20 分)

**ここまでで IPv6 は通っていますが、IPv4 はまだ通りません。**確かめます。

### 【受講者】検証用 PC で

```
ping 203.0.113.80
```

**通りません。**IPv6 しか降りてきていないので当然です。

### 【受講者】892FJ で、自分の WAN アドレスを確認する

```
CPE# show ipv6 interface GigabitEthernet0 | include 2001
```

**この `2001:DB8:...` の値を司会に伝えてください。**

> **なぜ伝える必要があるのか**: RA 方式のアドレスは **MAC から作られる**ので、
> **司会側では事前に分かりません。**網側のトンネルをこの値に向ける必要があります。

### 【司会】

```bash
./lab-mode.sh dslite 2001:db8:1014:300:e6aa:5dff:fe82:364a
```

### 【受講者】892FJ でトンネルを張る

```
CPE# configure terminal
CPE(config)# interface Tunnel0
CPE(config-if)#  description DS-Lite
CPE(config-if)#  ip address 192.0.0.2 255.255.255.248
CPE(config-if)#  ip mtu 1460
CPE(config-if)#  ip tcp adjust-mss 1420
CPE(config-if)#  tunnel source GigabitEthernet0
CPE(config-if)#  tunnel mode ipv6
CPE(config-if)#  tunnel destination 2001:DB8:8888::1
CPE(config-if)# exit
CPE(config)# ip route 0.0.0.0 0.0.0.0 Tunnel0
CPE(config)# end
```

### 出てくる出力

```
%LINEPROTO-5-UPDOWN: Line protocol on Interface Tunnel0, changed state to up
```

### いま何が起きたか

**1 行ずつ意味があります。**

| 設定 | 意味 |
|---|---|
| `ip address 192.0.0.2` | **RFC 6333 が DS-Lite 用に予約した `192.0.0.0/29` の中の 1 つ。**B4(トンネルの入口)は通常この `.2` を使う約束です(`.1` は AFTR 用) |
| `tunnel mode ipv6` | **IPv4 のパケットを IPv6 で包む**、という指定。説明会の「箱に詰める」がこれです |
| `tunnel destination 2001:DB8:8888::1` | **箱を開ける相手(AFTR)**。網側の装置です |
| `ip mtu 1460` | 箱の厚み 40 バイトを引いた大きさ |
| `ip tcp adjust-mss 1420` | **さらに TCP と IP のヘッダ 40 を引いた値。**これが無いと大きいファイルが落ちません |
| `ip route 0.0.0.0 0.0.0.0 Tunnel0` | **IPv4 の行き先を全部このトンネルに投げる** |

> **AFTR のアドレスは、実案件ではどうやって知るのか**
> **事業者が DNS 名で公開しています。**transix なら `gw.transix.jp`、クロスパスなら `dgw.xpass.jp`、
> v6コネクトなら `dslite.v6connect.net` です。**名前を引いて出た IPv6 アドレスを入れます。**
> ラボでは固定で `2001:DB8:8888::1` にしてあります。

### 【受講者】検証用 PC で もう一度

```
ping 203.0.113.80
```

**今度は通ります。**

---

## 演習 4: 「通った」で終わらせない — 出口アドレスを見る(10 分)

**ここが今日いちばん持ち帰ってほしいところです。**

### 【受講者】検証用 PC で

```
curl.exe http://203.0.113.80/
```

### 出てくる出力

```
lab-inet OK
src: 203.0.113.1        ← これが答え
host: 203.0.113.80
```

### いま何が起きたか

**`ping` が通っただけでは、正しい経路を通ったことになりません。**

`src:` は **「サーバから見て、どのアドレスから来たか」**です。

| 出口アドレス | 意味 |
|---|---|
| **`203.0.113.1`** | **網側の AFTR で NAT された = DS-Lite が成立している** |
| `192.168.100.x` のまま | **どこでも NAT されていない。**経路の誤り**か** NAT の不適用 |

> **実話**: 自宅の検証で、**検証スクリプトが全項目 PASS したのに、網側 NAT が効いていなかった**
> ことがあります。**トンネルは設計どおり通っていました。**その先で変換が当たっていなかっただけです。
> `ping` も `curl` も成功するので、**見た目では絶対に分かりません。**
> 気づいたのは `src:` を見たときだけでした。

**切替当日、疎通確認だけで「OK です」と言わないでください。**

### 【受講者】ついでに TTL を見る

```
ping 203.0.113.80
```

**`TTL=62` になっているはずです。**相手の Linux は `64` で返すので、
**2 減っている = ルータを 2 つ越えた**ということです(892FJ と網側の装置)。

---

## 演習 5: 892FJ では MAP-E ができない(10 分)

### 【受講者】892FJ で試してみる

```
CPE(config)# nat64 ?
```

### 出てくる出力

**`nat64` というコマンド自体がありません。**

### いま何が起きたか

**892FJ の IOS(classic IOS 15.x)には MAP-E の機能がありません。**

- **DS-Lite は組めます**(さっきやった `tunnel mode ipv6` だけで済むため)
- **MAP-E は組めません**(アドレスとポートの計算をする機能が要るため)

### これが実案件だとどう効くか

**お客様の VNE が MAP-E 系(v6プラス / OCN バーチャルコネクト等)だと、
892FJ は使えません。機器リプレース前提の見積になります。**

納入実績に 892FJ が多いなら、**契約書で VNE を確認する時点でこれが分かります。**

> MAP-E の動きを見たい人は、この後 OpenWrt の CPE で同じことをやります(時間があれば)。

---

# 休憩(10 分)

---

# 第3部 壊す(40 分)

## 演習 6: MTU ブラックホール(20 分)

**「Web は見えるのに大きいファイルだけ落ちない」を作ります。**

### 【受講者】まず正常な状態を確認する

```
curl.exe -o NUL -w "size=%{size_download}\n" http://203.0.113.80/big.bin
```

`size=5242880`(5MB)が落ちてきます。

### 【司会】

```bash
./lab-mode.sh break mtu
```

### 【受講者】もう一度

```
curl.exe -o NUL -w "size=%{size_download}\n" http://203.0.113.80/big.bin
```

**まだ落ちてきます。再現しません。**

### 【受講者】892FJ で MSS の調整を切る

```
CPE(config)# interface Tunnel0
CPE(config-if)#  no ip tcp adjust-mss
CPE(config-if)# end
```

もう一度 `curl`。**まだ落ちてきます。**

### 【司会 + 受講者】経路の記憶を、両側で消す

**ここが一番間違えやすいところです。**
5MB を**送っているのは INET-SIM(サーバ側)**なので、
**サーバ側の記憶を消さないと、いつまでも小さいパケットのまま送られてきます。**

【司会】INET-SIM で:

```bash
ssh <INET-SIM> sudo ip route flush cache
```

【受講者】検証用 PC で(管理者権限の PowerShell):

```powershell
netsh interface ipv4 delete destinationcache
```

**ここで初めて 5MB が止まります。**

### いま何が起きたか — 3 つそろって初めて壊れる

| 段階 | なぜまだ動いたのか |
|---|---|
| ① 障害だけ入れた | **892FJ が MSS を 1420 に調整していた**ので、そもそも大きいパケットが出ていなかった |
| ② MSS 調整を切った | **経路の MTU が学習済み**だったので、まだ小さいまま送っていた |
| ③ 両側の記憶を消した | **ここで初めて 1500 で送り始めて、途中で詰まった** |

> **なぜ「両側」なのか。**
> 経路 MTU は**パケットを送る側が覚えます。**このダウンロードで大きいパケットを送るのは
> **INET-SIM(サーバ)側**です。手元の PC だけ消しても、サーバが小さいまま送り続けるので再現しません。
> **「片側だけ消して再現しない」は現場でもよくある足踏みです。**

> **⚠ この演習は 892FJ での通し実走がまだです。**
> 手順は自宅ラボの OpenWrt CE での実測(3 段階の切り分け)をもとに組み立てています。
> **実施前に司会が一度通してください。**出力が違ったら [build-log.md](../build-log.md) に記録を。

**「さっきまで再現していたのに再現しない」が起きる理由がこれです。**
現場でこれを知らないと、**直したつもりで直っていない**ことに気づけません。

### 直す

```
CPE(config)# interface Tunnel0
CPE(config-if)#  ip tcp adjust-mss 1420
CPE(config-if)# end
```

**この 1 行で直ります。**これが実務的な対処そのものです。

### 【司会】

```bash
./lab-mode.sh restore
```

---

## 演習 7: ポート開放を試して、失敗させる(15 分)

**「できません」を、根拠を持って言えるようにします。**

### 【受講者】検証用 PC で待受を立てる(Windows。PowerShell を管理者で開く)

```powershell
New-NetFirewallRule -DisplayName "ipoe-lab-8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
$l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, 8000)
$l.Start(); "待受開始 8000/tcp。Ctrl+C で終了"
while ($true) {
  $c = $l.AcceptTcpClient()
  $w = New-Object System.IO.StreamWriter($c.GetStream())
  $w.Write("HTTP/1.1 200 OK`r`nContent-Length: 3`r`n`r`nOK`n"); $w.Flush(); $c.Close()
  "接続がありました $(Get-Date -Format HH:mm:ss)"
}
```

**まず LAN の中から叩いて、待受が生きていることを先に証明します。**(別のウィンドウで)

```powershell
curl.exe -m5 http://192.168.100.50:8000/     # → OK が返る
```

> **この対照実験を飛ばさないでください。**
> これをやらないと、あとで届かなかったときに「DS-Lite だから」なのか
> 「そもそも待受が動いていないだけ」なのかが**区別できません。**

### 【受講者】892FJ でポート開放を設定してみる

**NAT の内側と外側を宣言してから**、静的変換を入れます。

```
CPE(config)# interface Vlan1
CPE(config-if)#  ip nat inside
CPE(config-if)# exit
CPE(config)# interface Tunnel0
CPE(config-if)#  ip nat outside
CPE(config-if)# exit
CPE(config)# ip nat inside source static tcp 192.168.100.50 8000 interface Tunnel0 8080
CPE(config)# end
```

**設定は通ります。**エラーは出ません。

```
CPE# show ip nat translations
```

変換エントリも、ちゃんと出来ています。**ここまでは「正常」に見えます。**

### 【司会】INET-SIM から外から叩く

```bash
curl -m5 http://203.0.113.1:8080/      # → 接続拒否
curl -m5 http://192.0.0.2:8080/        # → タイムアウト
```

**どちらも届きません。**LAN の中からは繋がるのに、外からは届きません。

### いま何が起きたか

**892FJ に外から見えるアドレスが 1 つも無いからです。**

```
CPE# show ip interface brief
```

- `GigabitEthernet0`(WAN)… **IPv4 アドレスが無い**(`no ip address`)
- `Tunnel0` … `192.0.0.2`。**これは RFC 6333 が決めた「トンネルの入口」で、外から見えるアドレスではありません**

**外から来た通信を受け取る場所が、そもそも存在しません。**
設定 UI 上は入るのに一切着信しないのは、これが理由です。

### お客様への説明の組み立て方

> 「お客様のルータには外から見えるアドレスが無く、通信は事業者の設備でまとめて変換されています。
> **設定でどうにかできる話ではありません。**
> 外から入る通信が必要でしたら、**固定 IP のオプション契約**が要ります」

### 後始末

```
CPE(config)# no ip nat inside source static tcp 192.168.100.50 8000 interface Tunnel0 8080
CPE(config)# interface Vlan1
CPE(config-if)#  no ip nat inside
CPE(config-if)# exit
CPE(config)# interface Tunnel0
CPE(config-if)#  no ip nat outside
CPE(config-if)# end
```

検証用 PC 側も戻します(待受を Ctrl+C で止めてから)。

```powershell
Remove-NetFirewallRule -DisplayName "ipoe-lab-8000"
```

> **⚠ この演習も 892FJ での通し実走がまだです。**
> 出力は自宅ラボの OpenWrt CE での実測(R4)をもとにしています。**実施前に司会が一度通してください。**

---

## 演習 8: 同じ障害でも、端末によって症状が違う(5 分)

### 【司会】

```bash
./lab-mode.sh break dns
```

### 【受講者】検証用 PC(Windows)で

```powershell
curl.exe -s -o NUL -w "%{time_total}`n" http://www.lab.example/
```

**0.2 秒程度で返ります。速いので、障害が起きていることに気づけません。**

### 【司会】同じ URL を、別の実装で叩いて見せる

**`wget` は Windows に入っていません。**
(PowerShell の `wget` は別物の別名で、この症状は出ません)
**司会が Linux の LAB-CLIENT で叩いて、画面を見せてください。**

```bash
ssh <LAB-CLIENT> 'wget -q -O /dev/null http://www.lab.example/'
```

### 出てくる結果

| 叩いた側 | 結果 |
|---|---|
| Windows の `curl.exe` | **0.2 秒程度。速いので気づけません** |
| Linux の `wget` | **15 秒でタイムアウト。完全に固まります** |

> 15 秒 / 0.2 秒 は、**自宅ラボの Linux クライアントで実測した値**です(サイクル 5)。
> Windows 側の数字は端末によって多少ぶれます。

### いま何が起きたか

**AAAA(IPv6 のアドレス)は返るのに、IPv6 では到達できない状態**を作りました。

- `curl` は **IPv6 を少し試して、すぐ IPv4 に切り替えます**(Happy Eyeballs)
- `wget` は **IPv6 で待ち続けます**

**「A さんの PC は遅いが B さんは普通」というお客様申告の正体がこれです。**
端末ごとに実装が違うので、**同じ環境でも症状が違います。**
**だから「私の PC では再現しません」は、障害が無いことの証明になりません。**

### 【司会】

```bash
./lab-mode.sh restore
```

---

# 第4部 戻して終わる(15 分)

## 演習 9: 元に戻す

**戻し忘れは、次の演習で「原因の分からない失敗」として出ます。**

### 【受講者】892FJ で

```
CPE# show running-config | include adjust-mss
```

**`ip tcp adjust-mss 1420` が Tunnel0 と Vlan1 の両方にあることを確認してください。**
無ければ入れ直します。

```
CPE# show running-config | include ip nat inside source
```

**何も出ないことを確認**(演習 7 の設定が残っていないこと)。

### 【司会】

```bash
./lab-mode.sh status
```

**「障害の注入: なし」になっていることを全員で確認してから解散してください。**

### 【受講者】最後に

```
curl.exe http://203.0.113.80/
```

**`src: 203.0.113.1` に戻っていれば完了です。**

### 【受講者】検証用 PC のアドレスを元に戻す

**固定で入れた IP を、自動取得に戻してから解散してください。**
戻し忘れると、席に帰ってから社内ネットワークに繋がりません。

```powershell
netsh interface ip set address "イーサネット" dhcp
netsh interface ip set dns     "イーサネット" dhcp
```

---

## 4-2. 今日 手を動かして分かったこと

1. **設定を変えなくても、網の方式が変わればアドレスが付かなくなる**(演習 2)
   - しかも **RA 自体は届いている**ので、原因が見えません
2. **`ping` が通っても、正しい経路を通ったことにはならない**(演習 4)
   - 見るべきは **出口アドレス**だけです
3. **892FJ では MAP-E ができない**(演習 5)
   - 機器と方式の組み合わせは、**契約書を見た時点で分かります**
4. **障害は 3 つそろわないと再現しない**(演習 6)
   - 「さっきまで再現していたのに」が起きます
5. **同じ障害でも端末によって症状が違う**(演習 8)

**この 5 つは、教科書にもマニュアルにも書いてありません。**

## 4-3. 次にやること — **自分の案件が来たときは、この環境を使ってください**

**今日いちばん持ち帰ってほしいのは、「自分でも試せる」ということです。**

1. **自分の担当案件の VNE を調べる**(契約書の「IPv6 接続サービス」の名称)
2. **調べた方式に合わせて、この環境を切り替えて事前検証する**

| 調べた結果 | この環境でどう試すか |
|---|---|
| **DS-Lite 系**(transix / クロスパス / v6コネクト) | **今日やった構成そのままです。**お客様と同型の CPE を持ち込んで、同じ手順で |
| **MAP-E 系**(v6プラス / OCN バーチャルコネクト / IPv6 オプション) | 司会が `lab-mode.sh mape` に切り替えます。**CE は OpenWrt を使います**(892FJ では MAP-E ができないため) |
| **RA か PD か分からない** | **両方試せます。**`lab-mode.sh ra` / `pd` を切り替えて、CPE の設定が両方で成立するか確認 |

- **環境を使いたいときの窓口**: ____________(記入してください)
- **借りるときに伝えること**: ① 案件の VNE 名 ② RA か PD か(不明可) ③ 持ち込む CPE の機種
- **同時に検証できる CPE は 1 台です。**日程は先に押さえてください

**もっと壊したい人へ**: `test-matrix.md` §4 に R1〜R13 のレシピがあります。今日やったのは 3 つだけです。

| | 内容 |
|---|---|
| **R7** | **二重終端** — HGW と配下ルータの両方が IPv4 over IPv6 を終端してしまう |
| **R9** | **プレフィックス変更への追従** — 網から降る住所が変わったとき、LAN 側が付いてこられるか |
| **R13** | **外→内の IPv6 直接着信** — NAT が無くなると外から直接届く。その是非 |

## 4-4. 参考

- 実機の設定手順(詳細): `runbook-vmware.md` §8
- 詰まったとき: `runbook-vmware.md` §9 のトラブル一覧(症状 → 原因 → 対処)
- 障害再現レシピ(全 13 種): `test-matrix.md` §4
- 実走の一次記録: `build-log.md`
- 説明会資料(座学): `slides/setsumeikai.md`
- 司会用のモード切替: `lab/ipoe/lab-mode.sh --help`
