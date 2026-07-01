# ENCOR シミュレーション(ラボ)問題 対策メモ

ENCOR(350-401)は2024年以降、選択問題に加えて**実際にCLIで設定を行うパフォーマンス問題(ラボ)**が数問出題されます。ここで崩れると時間も点数も失うので、フェーズ3(9月)で集中的に対策します。

## 対策の3本柱

1. **Ping-tのコマ問**: コマンドを「見て分かる」ではなく「白紙から打てる」状態にする。1日10問、8月から開始
2. **実機シミュレータで手を動かす**: Packet Tracer(無料)で十分。可能ならCML。下の頻出テーマを自分で組んで壊して直す
3. **確認コマンドをセットで覚える**: 設定したら必ずshowコマンドで確認する癖をつける(ラボ問題は設定の正しさをshowで自己検証できる)

## 優先して手を動かすテーマ(出題範囲ベースの重要度順)

| テーマ | 設定できるようにすること | 確認コマンド |
|---|---|---|
| VLAN / トランク | VLAN作成、access/trunk設定、native VLAN、DTP無効化 | `show vlan brief` `show interfaces trunk` |
| EtherChannel | LACP/PAgP/staticの違い、L2/L3チャネル | `show etherchannel summary` |
| STP | モード変更、root bridge指定(priority)、PortFast/BPDU Guard | `show spanning-tree` |
| OSPF | マルチエリア、network文とip ospfコマンド両方、passive-interface、default-information originate | `show ip ospf neighbor` `show ip route ospf` |
| EIGRP | 名前付きモード(named mode)含む基本設定 | `show ip eigrp neighbors` |
| BGP | eBGP/iBGPのneighbor設定、networkコマンド | `show ip bgp summary` |
| HSRP | グループ、priority、preempt、トラッキング | `show standby brief` |
| NAT | static / dynamic / PAT(overload) | `show ip nat translations` |
| AAA / SSH / VTY | ローカル認証、`login local`、SSH有効化(domain-name→crypto key) | `show run \| sec line vty` |
| NTP | server/client設定、タイムゾーン | `show ntp status` |
| ACL | 標準/拡張、VTYへの適用(access-class) | `show access-lists` |
| VRF | VRF作成、インターフェース割当、VRF内ルーティング | `show ip route vrf 名前` |

## 本番でのラボ問題の立ち回り

- **1問10分以内**を目安に。時間配分が最大の敵(全体120分・約100問)
- ラボは**部分点があると言われている**。全部分からなくても、確実に分かる設定だけでも入れて次へ進む
- 問題文の要求を箇条書きで整理してから打ち始める(要求の見落としが一番多い失点)
- `?` と Tab補完は使える前提で慣れておく(ただしシミュレータによっては補完が弱いので、フルコマンドで打てるのが理想)
- 設定後は必ず `show run` と該当showコマンドで確認 → **保存(`copy run start` or `write`)を忘れない**
- 分からないラボに15分以上使うくらいなら、選択問題を確実に取る方が期待値が高い

## 週末ラボ演習メニュー(9月・各60分)

1. 週1回、上の表から3テーマ選ぶ
2. Packet Tracerで白紙からトポロジを組む(ルータ2台+スイッチ2台で十分)
3. 何も見ずに設定→showで確認→詰まったらPing-t解説を見る→**もう一度白紙から**
4. 打てなかったコマンドをアプリのメモ欄に記録
