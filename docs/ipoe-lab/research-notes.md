# 事例調査ノート(2026-08 実施)

Web上の実際の構築事例・失敗談を調査し、本ラボ設計に反映した内容の記録。
出典は基本的に一次情報(構築した本人の記録・ベンダ公式・JANOG資料)を優先。**個別のコマンド断片は原典で要確認**(調査は検索経由の要約ベースを含む)。

## 1. 先行事例(このラボの答え合わせになるもの)

| 事例 | 要点 | URL |
|---|---|---|
| BBSakura「疑似フレッツ光網」連載 | フレッツ網をOSSで再現する国内最先端の公開事例。accel-ppp採用。「PPPoEサーバを立てる」と「フレッツ網を模擬する」は別問題(実網は PPPoE→L2TPでISP網終端装置へ中継)で、完全再現にはaccel-ppp改造が必要と判明 | [検討編](https://blog.bbsakura.net/posts/2023/12/12/175122) / [実装編1](https://blog.bbsakura.net/posts/2024/12/24/165012) / [IPoE編](https://blog.bbsakura.net/posts/2023/12/25/165138) |
| C&S「テレワークNWエンジニアの検証環境」 | 社内ラボでPPPoEサーバ+**ASAMAP(Vyatta改造)でDS-Lite AFTR/MAP-E BRを肩代わり**し市販UTMの接続検証。本ラボと同じ発想の先行例 | [その2](https://licensecounter.jp/engineer-voice/blog/articles/20200518_stay_home2.html) |
| 自作AFTRをVPSに構築 | Linuxのip6tnl+MASQUERADEだけで自前DS-Lite網側が成立した実例。**静的ip6tnlによるAFTR模擬の成立証明** | [Qiita](https://qiita.com/massgame/items/49c9f1f26c0b83f0a9fa) |
| Linux自作MAP-Eルータ群 | v6プラス/OCNvcへLinux(ip6tnl+nftables)で接続する事例が多数。MAP-Eは「静的ip6tnl+ポート制限NAPT」に帰着することの証明。encaplimit無効化が全事例で必須 | [vector](https://vector.hateblo.jp/entry/2021/02/17/142458) / [notr.app](https://www.notr.app/posts/2023/11/ubuntu-as-a-mape-router/) / [kakinaguru_zo](https://qiita.com/kakinaguru_zo/items/2764dd8e83e54a6605f2) |
| JANOG31 MAP-E相互接続試験・会場実験 | ベンダCE×BRのマトリクス試験でほぼ解消後、**ホットステージでフラグメント処理バグが新たに発覚**。「240ポートSSID」と「30ポートSSID」を提供し体感試験。検証網の作り方の教科書 | [WG](https://www.janog.gr.jp/wg/softwire-wg/) / [チュートリアル](https://www.janog.gr.jp/meeting/janog31/doc/janog31-MAP-asama-01.pdf) |
| JANOG53 IPv4 over IPv6プロビジョニング問題 | VNE毎に設定配布方式が乱立しており、市販ルータの「自動判定」はVNE依存 → **ラボで市販ルータの自動設定は再現困難**という限界の根拠 | [資料](https://www.janog.gr.jp/meeting/janog53/wp-content/uploads/2023/11/janog53-v4v6-kawashima-01-rev3.pdf) |
| VPP mapプラグイン | ルールベースの本格BRをOSSで立てる現実解(ASAMAPの後継)。`map add domain ...` 1行でMAPドメイン定義 | [CLIリファレンス](https://s3-docs.fd.io/vpp/24.02/cli-reference/clis/clicmd_src_plugins_map.html) |

## 2. 実サービスのパラメータ(ラボ模擬値を現実に近づける根拠)

| サービス | VNE | 方式 | 網側アドレス | ポート数 | 備考 |
|---|---|---|---|---|---|
| v6プラス | JPNE | MAP-E(draft-03互換) | BR `2404:9200:225:100::64` | 240(16×15ブロック、offset=4相当) | ルールは網から自動配布(独自方式) |
| OCNバーチャルコネクト | NTT Com | MAP-E(draft-03互換) | BR `2001:380:a120::9` | 1008(16×63ブロック、offset=6相当) | SNAT分散のモジュロは**63**(64にすると間欠パケロス報告あり) |
| transix | インターネットマルチフィード | DS-Lite | AFTR `gw.transix.jp` → `2404:8e00::feed:100/101` | 網側NAPT | AFTRは**DNS(AAAA)で発見**する仕様 |
| クロスパス | アルテリア | DS-Lite | AFTR `dgw.xpass.jp` | 網側NAPT | |
| v6コネクト | 朝日ネット | DS-Lite | DNS配布 | 網側NAPT | |
| MTU共通 | — | — | — | — | トンネルMTU 1460。encaplimitヘッダが付くと実質1452になり片方向断の原因 |

重要: **日本のVNEのMAP-EはRFC7597ではなくdraft-ietf-softwire-map-03互換**。OpenWrtでは `option legacymap '1'` が必要で、アドレス導出がRFC7597と異なる。本ラボの既定ルールはRFC7597(legacymapなし)で自己完結させており、実サービス設定のリハーサル時はlegacymapを立てて `CE_MAP_ADDR` を再計算する(setup-map-br.sh の環境変数で対応可)。

## 3. 調査で得た落とし穴(設計への反映込み)

### PPPoE / 網模擬
1. **accel-pppはDebian/Ubuntu公式リポジトリに無い** → ソースビルドが必要(setup-bras.shに反映)。手早く済ませるならVyOSの`set service pppoe-server`(中身はaccel-ppp)が代替
2. **仮想スイッチの無差別モード問題**(VMware=3項目承諾、VirtualBox=すべて許可)は複数ベンダ公式で裏付け。SEIL(IIJ)公式が一次情報
3. **virtio等のNICオフロードとPPPoEの相性**: TSO/checksumオフロードで断続ロス(OPNsense公式issue等複数報告)→ アクセス網側NICはオフロード無効化(build.mdに反映)
4. **フレッツ実網のPPPoE MTUは1454**。ラボを1492で組むと「ラボでは通るのに実網でMSS詰まり」が再現できない(本ラボは当初から1454)
5. **NGNのDHCPv6-PDはDUID-LLしか受理しない**(LLT/ENはSolicit無視=無応答でハマる)。独立した4件の報告で一致。CEのDUID種別確認をチェック項目化(test-matrixに反映)
6. ひかり電話HGW配下では「PD送信元をデフォルトGWにし、HGWのRAをデフォルトGWにしない」という実網の癖あり([sorah氏](https://diary.sorah.jp/2017/02/19/flets-ngn-hikaridenwa-kill-dhcpv6pd))

### MAP-E / DS-Lite
7. **encaplimit**: Linux ip6tnlが付けるDestination Optionsヘッダを実網BR/CE実装が扱えず片方向断 → `encaplimit none`(OpenWrt: `ignore`)必須(本ラボのスクリプトは対応済み)
8. **ポートセットは非連続**(16ポート×Nブロック)。素朴な連続レンジSNATでは大半のポートを捨て「一部サイトだけ繋がらない」症状に。OpenWrt素のmap.shもポート分散に難(改造事例あり)
9. **mapcalcの64bit環境バグ**: PSID自動計算が信用できない → 外部計算機で検算し手動設定が定石([計算機1](https://ipv4.web.fc2.com/map-e.html) / [計算機2](https://missing233.github.io/map-e/))
10. **フラグメント処理**は相互接続試験で実際にバグが出た領域 → UDPフラグメント・DFなし大パケットを検証項目に(test-matrixに反映)
11. **複数B4収容のAFTR**は素のLinuxでは不可(RFC1918重複をトンネル毎に分離できない)。CE 1台なら成立。複数CE同時はB4毎にip6tnl+conntrack zone分離かVPP
12. **HWオフロード×トンネルの片方向破損**(OpenWrt/GL.iNet)→ トラブル切り分けの最初の一手は「オフロード無効化」

### 市販ルータの限界(重要)
13. **市販ルータのMAP-E自動設定はVNEのルール配布サーバ依存**(方式乱立、JANOG53)。手動設定UIを持たない機種はラボでMAP-E接続不可の場合がある。DS-LiteはAFTRのFQDNがDNS発見なので、**ラボDNSで `gw.transix.jp` を模擬AFTRに向ければ自動設定機種も動く可能性がある**(setup-inet.shにオプション実装)

### Proxmox固有
14. **Linuxブリッジのmulticast snoopingでIPv6のRA/ND/DHCPv6が死ぬ**(複数の独立報告)→ `bridge-mcsnoop 0` 必須(proxmox-prototype.mdに反映)
15. VM作成時の**Firewallチェックボックス**が意図しないフレーム破棄の原因 → 検証セグメントでは無効化
16. NICは**virtio**を使う(e1000は性能3割減)。ただし古いNW OSイメージはe1000必須の場合あり

## 4. Cisco 892FJ系(890シリーズ日本向けISR)の対応状況

「892FJ」という型番の一次情報はなく、日本向けは **892J-K9(FE世代)→ 891FJ-K9(GbE+SFP)**。いずれもclassic IOS 15.x。以下は891FJ/841M(同系IOS)の実績からの整理。

| 機能 | 可否 | 根拠 |
|---|---|---|
| IPv6 IPoE(RA受信 `ipv6 address autoconfig`) | **○** | [891FJ IPoE設定例](https://www.goritarou.com/cisco891fj_ipoe/)、Cisco公式IPv6oE設定例 |
| DHCPv6-PDクライアント(ひかり電話あり構成) | **○** | Cisco IOS 15 M&T公式ドキュメント |
| PPPoE(IPv4/IPv6) | **○** | 800系の基本機能 |
| DS-Lite(`tunnel mode ipv6`でAFTRへ、B4動作) | **○**(891FJ/841Mで複数の成功報告) | [891FJ設定メモ](https://maeda577.github.io/2021/07/31/c891fj.html)、[IIJmio DS-Lite設定例](https://tofu.hatenadiary.com/entry/2021/02/10/iijmio-ds-lite-cisco-config) |
| **MAP-E**(v6プラス等、ポート制限NAPT) | **×**(classic IOS非対応。対応はIOS XEのC1100系以降) | [断念→IX2105乗換の実例](https://rarafy.com/blog/2022/05/14/nec-ix2105-dix/) |
| MAP-E系固定IP(実体は静的IPIP) | △(原理上は可能だが成功一次報告なし) | NEC IX/Yamahaには公式手順あり |
| 備考 | classic IOSのIPv4 over IPv6転送はCEFに乗らず低速になりがち。800系は受注終了・サポート終了済 | Cisco EoS/EoL告知 |

**結論: 892FJ系はIPv6非対応ではない。**「IPoE(RA/PD)+DS-LiteのCE」および「PPPoEクライアント/サーバ」としてラボで現役に使える。MAP-EのCEだけはOpenWrt等で補う。

## 5. 取り込まなかったもの(理由付き)

- **PPPoE→L2TP中継(網終端装置の再現)**: BBSakura事例のとおりaccel-ppp改造が必要な深さ。切替検証の目的には「PPPoEが終端されIPv4が出る」ことの再現で十分と判断。将来必要ならVyOSの[LAC/LNS公式レシピ](https://docs.vyos.io/en/stable/configexamples/lac-lns.html)から入る
- **ASAMAP**: 本ラボと同じ用途の先行ツールだが約10年未更新で現行カーネルでの動作が不明。ルールベースBRが必要になったらVPP mapを使う
- **WANem等による遅延・帯域模擬**: C&S事例にあるが、本ラボは機能・手順検証に割り切る(README「できないこと」参照)
