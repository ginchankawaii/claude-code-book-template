# 役割ごとに固定した MAC アドレスから NIC 名を解決し、ACCESS_IF / CORE_IF / INET_IF を埋める。
# (このファイルは各 setup スクリプトから source される。単体実行はしない)
#
# なぜ必要か: Ubuntu 24.04 の NIC 名は predictable naming (ens18 等) で環境ごとに変わり、
# eth1/eth2 決め打ちだとスクリプトが動かない。MAC で役割を判別すれば Proxmox でも
# VMware でも同じスクリプトがそのまま通る。
#
# MAC の規則 (proxmox/provision.sh が自動で割り当てる。VMware では手動で同じ値を設定する):
#   02:ac:* … アクセス網   (PG-ACCESS / vmbr1)
#   02:c0:* … NGN 網内     (PG-CORE   / vmbr2)
#   02:1e:* … 模擬インターネット (PG-INET / vmbr3)
#   02:c1:* … CPE 配下の LAN     (PG-CLIENT / vmbr4)
#
# 環境変数で明示指定されている場合は上書きしない (手動構築や MAC 未統一の環境向け)。
#
# 実測 (2026-08 自宅 Proxmox): Ubuntu 24.04 の NIC 名は eth0(管理) / ens19 / ens20 になり、
# 設計時に想定した eth1 / eth2 とは一致しなかった。MAC 判別にしておいて正解だった箇所。

for _labif_d in /sys/class/net/*; do
  [ -e "${_labif_d}/address" ] || continue
  _labif_n=$(basename "${_labif_d}")
  # sysfs は小文字で返すが、念のため明示的に小文字化してから判定する
  case "$(tr 'A-F' 'a-f' < "${_labif_d}/address")" in
    02:ac:*) ACCESS_IF="${ACCESS_IF:-${_labif_n}}" ;;
    02:c0:*) CORE_IF="${CORE_IF:-${_labif_n}}" ;;
    02:1e:*) INET_IF="${INET_IF:-${_labif_n}}" ;;
    02:c1:*) LAN_IF="${LAN_IF:-${_labif_n}}" ;;
  esac
done
unset _labif_d _labif_n
