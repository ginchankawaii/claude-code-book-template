#!/usr/bin/env python3
"""HB46PP クライアント (CPE 側) の参照実装 — 取得したルールから MAP-E の値を導出する

    usage:
      # ラボのサーバから取得して、この委譲プレフィックスの CPE の値を出す
      ./hb46pp-client.py --discover --prefix 2001:db8:100a:500::/56

      # URL を直接指定 (DNS を経由しない切り分け)
      ./hb46pp-client.py --url https://prov.lab.example/rule.cgi \\
                         --cacert /etc/mape-ruleserver/ca/ca.pem \\
                         --prefix 2001:db8:1014:300::/64

      # 手元の JSON から計算するだけ (ネットワーク不要)
      ./hb46pp-client.py --json response.json --prefix 2001:db8:100a:500::/56

      # 自己検証 (ラボの既知の値と一致するか)
      ./hb46pp-client.py --selftest

────────────────────────────────────────────────────────────────────────
**これは何のためのものか**

  1. **配ったルールが正しいかの検証**
     プロビジョニングサーバは「この CPE の IPv4 は何番」を配らない。
     BMR (IPv6 プレフィックス + IPv4 プレフィックス + ea_length + psid_offset)
     を配るだけで、**CPE が自分の委譲プレフィックスから自力で導出する**。
     導出が正しいかは、こちらでも同じ計算をして突き合わせるしかない。

  2. **実機の答え合わせの基準**
     C1111 が `show nat64 map-e` で出す値と、ここで計算した値を比べる。
     食い違えば、ルータの解釈かこちらのルールのどちらかが間違っている。

  3. **教材**
     「MAP-E の IPv4 アドレスとポート範囲はどこから来るのか」を、
     手で追える形で示す。勉強会の演習で使える。

**計算の中身 (RFC 7597 / draft-ietf-softwire-map-03)**

    EA ビット = 委譲プレフィックスの、ルール IPv6 プレフィックス長から
                ea_length ビット分を切り出したもの

    EA を 2 つに割る:
      上位 (32 - ルールIPv4プレフィックス長) ビット → IPv4 アドレスの下位部分
      残り                                  ビット → PSID

    ポート範囲は PSID と psid_offset から決まる:
      a = psid_offset, p = PSID長, m = 16 - a - p
      使えるポート = 各 j (1..2^a-1) について
                     (j << (16-a)) | (PSID << m) から 2^m 個の連続ポート
      j=0 を外すのは、その範囲に 0-1023 のウェルノウンポートが入るため。
      → 合計 (2^a - 1) x 2^m ポート
"""
import argparse
import ipaddress
import json
import shutil
import ssl
import subprocess
import sys
import urllib.request

DISCOVERY_FQDN = "4over6.info"


def die(msg):
    print("エラー: %s" % msg, file=sys.stderr)
    sys.exit(1)


# ── プロビジョニングサーバの発見 (DNS TXT) ──────────────────────────
def discover(nameserver=None):
    """4over6.info の TXT レコードから URL と証明書検証要否を取り出す"""
    if not shutil.which("dig"):
        die("dig がありません (apt install dnsutils)。--url で直接指定してください")
    cmd = ["dig", "+short", "-t", "TXT", DISCOVERY_FQDN]
    if nameserver:
        cmd.append("@" + nameserver)
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip()
    if not out:
        die("%s の TXT が引けません。CPE と同じ DNS を見ているか確認してください"
            % DISCOVERY_FQDN)
    txt = out.strip().strip('"')
    print("TXT レコード : %s" % txt)

    attrs = dict(kv.split("=", 1) for kv in txt.split() if "=" in kv)
    if attrs.get("v") != "v6mig-1":
        die("バージョンが v6mig-1 ではありません: %r" % attrs.get("v"))
    if "url" not in attrs:
        die("TXT に url がありません")
    # t: a=証明書検証なし / b=検証あり
    return attrs["url"], attrs.get("t", "b")


def fetch(url, verify=True, cacert=None,
          vendorid="acde48-lab", product="LAB-REF-CPE", version="1_0",
          capability="map_e,dslite"):
    q = ("?vendorid=%s&product=%s&version=%s&capability=%s"
         % (vendorid, product, version, capability))
    full = url + q
    print("要求         : GET %s" % full)

    if full.startswith("https://"):
        if not verify:
            ctx = ssl._create_unverified_context()
        elif cacert:
            ctx = ssl.create_default_context(cafile=cacert)
        else:
            ctx = ssl.create_default_context()
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ctx))
    else:
        opener = urllib.request.build_opener()

    with opener.open(full, timeout=20) as r:
        if r.status != 200:
            die("HTTP %d が返りました (仕様上 CPE は 200 と 307 以外をエラー扱いしてよい)"
                % r.status)
        return json.loads(r.read().decode("utf-8"))


# ── MAP-E の導出 ────────────────────────────────────────────────────
def derive(map_e, ce_prefix):
    """配布されたルールと CPE の委譲プレフィックスから MAP-E の値を導く"""
    ce = ipaddress.IPv6Network(ce_prefix, strict=False)

    matched = None
    for rule in map_e.get("rules", []):
        r6 = ipaddress.IPv6Network(rule["ipv6"], strict=False)
        if ce.subnet_of(r6):
            matched = rule
            break
    if not matched:
        die("委譲プレフィックス %s を含むルールがありません。"
            "配布されたルールと CPE のプレフィックスが噛み合っていません" % ce_prefix)

    r6 = ipaddress.IPv6Network(matched["ipv6"], strict=False)
    r4 = ipaddress.IPv4Network(matched["ipv4"], strict=False)
    k = int(matched["ea_length"])
    a = int(matched["psid_offset"])

    o = 32 - r4.prefixlen          # IPv4 サフィックス長
    p = k - o                      # PSID 長
    if p < 0:
        die("ea_length(%d) が IPv4 サフィックス長(%d) より短く、PSID を取れません"
            % (k, o))
    if r6.prefixlen + k > ce.prefixlen:
        die("委譲プレフィックス /%d では EA ビット (先頭 %d ビット目から %d ビット) を"
            "取りきれません" % (ce.prefixlen, r6.prefixlen, k))

    # EA ビット = 委譲プレフィックスの bit[r6.prefixlen .. r6.prefixlen+k)
    ea = (int(ce.network_address) >> (128 - (r6.prefixlen + k))) & ((1 << k) - 1)

    v4_suffix = ea >> p if p else ea
    psid = ea & ((1 << p) - 1) if p else 0
    ipv4 = ipaddress.IPv4Address(int(r4.network_address) + v4_suffix)

    # ポート範囲: m = 16 - a - p 個の連続ビット
    m = 16 - a - p
    if m < 0:
        die("psid_offset(%d) + PSID長(%d) が 16 を超えています" % (a, p))
    ranges = []
    # a=0 のときは j=0 の 1 レンジのみ (ウェルノウンポートを含む)
    for j in range(0 if a == 0 else 1, 1 << a):
        start = (j << (16 - a)) | (psid << m)
        ranges.append((start, start + (1 << m) - 1))

    # MAP CE アドレス (RFC 7597 5.2): 委譲プレフィックスの /64 に
    # インタフェース ID 0000:<IPv4>:<PSID> を付ける
    iid = (int(ipv4) << 16) | psid
    ce64 = int(ce.network_address) >> 64 << 64
    map_addr = ipaddress.IPv6Address(ce64 | iid)

    return {
        "rule": matched, "ce_prefix": str(ce),
        "ea": ea, "ea_length": k,
        "ipv4": ipv4, "psid": psid, "psid_length": p, "psid_offset": a,
        "contiguous_bits": m, "ranges": ranges,
        "total_ports": len(ranges) * (1 << m),
        "share_ratio": 1 << p,
        "map_address": map_addr,
        "br": map_e.get("br"),
    }


def report(d, doc=None):
    W = "─" * 70
    if doc:
        print(W)
        print(" 配布元 : %s / %s (%s)"
              % (doc.get("enabler_name", "?"), doc.get("service_name", "?"),
                 doc.get("isp_name", "?")))
        print(" 優先順 : %s   ttl=%s  auth=%s"
              % (doc.get("order"), doc.get("ttl"), doc.get("auth", "(なし)")))
    print(W)
    print(" 適用されたルール (BMR)")
    print("   IPv6 プレフィックス : %s" % d["rule"]["ipv6"])
    print("   IPv4 プレフィックス : %s" % d["rule"]["ipv4"])
    print("   ea_length           : %d" % d["ea_length"])
    print("   psid_offset         : %d" % d["psid_offset"])
    print(W)
    print(" CPE の委譲プレフィックス : %s" % d["ce_prefix"])
    print("   EA ビット           : 0x%0*x (%d ビット)"
          % ((d["ea_length"] + 3) // 4, d["ea"], d["ea_length"]))
    print(W)
    print(" 導出された値")
    print("   共有 IPv4 アドレス  : %s" % d["ipv4"])
    print("   PSID                : %d  (PSID長 %d ビット → %d 分割)"
          % (d["psid"], d["psid_length"], d["share_ratio"]))
    print("   MAP CE アドレス     : %s" % d["map_address"])
    print("   BR アドレス         : %s" % d["br"])
    print("   使えるポート        : %d 個 (%d レンジ x %d 連続ポート)"
          % (d["total_ports"], len(d["ranges"]), 1 << d["contiguous_bits"]))
    head = ", ".join("%d-%d" % r for r in d["ranges"][:4])
    tail = "%d-%d" % d["ranges"][-1] if d["ranges"] else "-"
    print("     先頭  : %s ..." % head)
    print("     末尾  : %s" % tail)
    print(W)
    print(" ラボの BR をこの CPE に向ける場合:")
    print("   CE_MAP_ADDR=%s CE_SHARED_V4=%s \\" % (d["map_address"], d["ipv4"]))
    print("     sudo ./ipoe/vne/setup-map-br.sh")
    print(W)


# ── 自己検証 ────────────────────────────────────────────────────────
# ラボの既知の値。setup-map-br.sh のコメントおよび radvd.conf のコメントと一致する。
SELFTEST_RULE = {
    "br": "2001:db8:9999::1",
    "rules": [{"ipv6": "2001:db8:1000::/40", "ipv4": "198.51.100.0/24",
               "ea_length": 16, "psid_offset": 4}],
}
SELFTEST_CASES = [
    # (説明, 委譲プレフィックス, 期待IPv4, 期待PSID, 期待MAPアドレス, 期待ポート数)
    ("PD 方式 (ひかり電話あり相当)", "2001:db8:100a:500::/56",
     "198.51.100.10", 5, "2001:db8:100a:500:0:c633:640a:5", 240),
    ("RA 方式 (ひかり電話なし相当)", "2001:db8:1014:300::/64",
     "198.51.100.20", 3, "2001:db8:1014:300:0:c633:6414:3", 240),
]


def selftest():
    ok = True
    for desc, prefix, exp_v4, exp_psid, exp_addr, exp_ports in SELFTEST_CASES:
        d = derive(SELFTEST_RULE, prefix)
        checks = [
            ("IPv4", str(d["ipv4"]), exp_v4),
            ("PSID", str(d["psid"]), str(exp_psid)),
            ("MAPアドレス", str(d["map_address"]), exp_addr),
            ("ポート数", str(d["total_ports"]), str(exp_ports)),
        ]
        bad = [c for c in checks if c[1] != c[2]]
        print("[%s] %s  (%s)" % ("OK" if not bad else "NG", desc, prefix))
        for name, got, want in checks:
            mark = "  " if got == want else "!!"
            print("   %s %-12s = %-34s (期待 %s)" % (mark, name, got, want))
        if bad:
            ok = False
    print()
    print("自己検証: %s" % ("すべて一致しました" if ok else "食い違いがあります"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="HB46PP クライアントの参照実装")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--discover", action="store_true",
                     help="4over6.info の TXT からサーバを発見する (本番と同じ経路)")
    src.add_argument("--url", help="プロビジョニングサーバの URL を直接指定")
    src.add_argument("--json", help="手元の JSON ファイルから計算する")
    src.add_argument("--selftest", action="store_true",
                     help="ラボの既知の値と一致するか自己検証する")
    ap.add_argument("--prefix", help="CPE の委譲プレフィックス (例 2001:db8:100a:500::/56)")
    ap.add_argument("--cacert", help="サーバ証明書の検証に使う CA (ラボ CA)")
    ap.add_argument("--insecure", action="store_true", help="証明書を検証しない")
    ap.add_argument("--nameserver", help="TXT を引く DNS サーバ")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if not args.prefix:
        die("--prefix で CPE の委譲プレフィックスを指定してください")

    doc = None
    if args.json:
        with open(args.json, encoding="utf-8") as f:
            doc = json.load(f)
    elif args.discover or args.url:
        if args.discover:
            url, t = discover(args.nameserver)
            verify = (t == "b") and not args.insecure
        else:
            url, verify = args.url, not args.insecure
        doc = fetch(url, verify=verify, cacert=args.cacert)
    else:
        die("--discover / --url / --json / --selftest のいずれかを指定してください")

    if "map_e" not in doc:
        die("応答に map_e がありません。返ってきた JSON: %s"
            % json.dumps(doc, ensure_ascii=False)[:400])

    report(derive(doc["map_e"], args.prefix), doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
