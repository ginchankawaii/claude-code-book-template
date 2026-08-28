#!/usr/bin/env python3
"""netlist.json の機械検査。

  python3 hardware/pcb/validate_netlist.py

検査項目:
  1. json.load できること
  2. 全ネット接続 "REF.PIN" が宣言済み部品・宣言済みピンに解決すること
  3. configurations[].components / nets が実体と一致すること
  4. 同一構成内で1つのピンが2つのネットに現れない（ショート）こと
  5. forbidden 指定ピン・no_connect 指定ピンがどのネットにも現れないこと
  6. 各ネットが2端子以上を持つこと
  7. はんだ点(joints)が構成A1の全はんだ端子を過不足なく覆い、点数が一致すること
  8. 分圧の記載値が抵抗値から再計算した値と一致すること
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "netlist.json")

errors, warns, info = [], [], []
def err(m): errors.append(m)
def warn(m): warns.append(m)


def main():
    with open(PATH, encoding="utf-8") as f:
        nl = json.load(f)                                   # 検査1
    info.append(f"json.load OK  ({os.path.getsize(PATH)} bytes)")

    comps = {c["ref"]: c for c in nl["components"]}
    cfgs = {c["id"]: c for c in nl["configurations"]}
    if len(comps) != len(nl["components"]):
        err("部品refが重複している")

    # ---- 検査2: 接続の解決 -------------------------------------------------
    def resolve(conn, where):
        if "." not in conn:
            err(f"{where}: 接続 '{conn}' が REF.PIN 形式でない"); return None
        ref, pin = conn.split(".", 1)
        if ref not in comps:
            err(f"{where}: 未宣言の部品 '{ref}' ({conn})"); return None
        if pin not in comps[ref]["pins"]:
            err(f"{where}: 部品 {ref} に未宣言のピン '{pin}' ({conn})"); return None
        return ref, pin

    for n in nl["nets"]:
        for c in n["connections"]:
            resolve(c, f"net {n['name']}[{n['config']}]")

    # ---- 検査3: 構成の宣言と実体の一致 ------------------------------------
    for cid, cfg in cfgs.items():
        declared = set(cfg["components"])
        actual = {r for r, c in comps.items() if c["config"] == cid}
        if declared != actual:
            err(f"構成 {cid}: components 宣言 {sorted(declared)} と実体 {sorted(actual)} が不一致")
        dn = set(cfg["nets"])
        an = {n["name"] for n in nl["nets"] if n["config"] == cid}
        if dn != an:
            err(f"構成 {cid}: nets 宣言 {sorted(dn)} と実体 {sorted(an)} が不一致")

    # ---- 有効ネット（extends を解決） --------------------------------------
    def effective(cid):
        chain, cur = [], cid
        while cur:
            chain.append(cur)
            cur = cfgs[cur].get("extends")
        chain.reverse()
        nets = {}
        for c in chain:
            for n in nl["nets"]:
                if n["config"] != c:
                    continue
                if n["mode"] == "define":
                    if n["name"] in nets:
                        err(f"構成 {cid}: ネット {n['name']} が二重定義されている")
                    nets[n["name"]] = list(n["connections"])
                elif n["mode"] == "extend":
                    base = n.get("extends_net", n["name"])
                    if base not in nets:
                        err(f"構成 {cid}: extend 対象のネット {base} が未定義")
                    else:
                        nets[base] += n["connections"]
                else:
                    err(f"構成 {cid}: 未知の mode '{n['mode']}'")
        return chain, nets

    for cid in cfgs:
        chain, nets = effective(cid)
        info.append(f"構成 {cid}: 継承 {'->'.join(chain)} / 有効ネット {len(nets)}")

        # ---- 検査4: ショート ----------------------------------------------
        owner = {}
        for name, conns in nets.items():
            for c in conns:
                if c in owner and owner[c] != name:
                    err(f"構成 {cid}: ピン {c} がネット {owner[c]} と {name} の両方に接続（ショート）")
                if conns.count(c) > 1:
                    err(f"構成 {cid}: ネット {name} にピン {c} が重複")
                owner[c] = name

        # ---- 検査5: 禁止ピン ------------------------------------------------
        for ref, comp in comps.items():
            for pin, d in comp["pins"].items():
                if isinstance(d, dict) and d.get("forbidden") and f"{ref}.{pin}" in owner:
                    err(f"構成 {cid}: 使用禁止ピン {ref}.{pin} が接続されている ({d['forbidden']})")
        for nc in nl["no_connect"]:
            if nc["pin"] in owner:
                err(f"構成 {cid}: no_connect 指定の {nc['pin']} がネット {owner[nc['pin']]} に接続されている")

        # ---- 検査6: 1端子ネット --------------------------------------------
        for name, conns in nets.items():
            if len(conns) < 2:
                err(f"構成 {cid}: ネット {name} の端子が {len(conns)} 個しかない")

        # ---- 参考: 未使用ピン ------------------------------------------------
        for ref in cfgs[cid]["components"]:
            for pin, d in comps[ref]["pins"].items():
                key = f"{ref}.{pin}"
                if key in owner:
                    continue
                if any(nc["pin"] == key for nc in nl["no_connect"]):
                    continue
                if isinstance(d, dict) and d.get("use_v2"):
                    info.append(f"構成 {cid}: {key} は未接続（v2 で {d['use_v2']} に使う予約ピン）")
                else:
                    warn(f"構成 {cid}: {key} がネットにも no_connect にも現れない")

    # ---- 検査7: はんだ点 ---------------------------------------------------
    a1 = "A1_HARNESS_V15"
    _, nets_a1 = effective(a1)
    solder_eps = set()
    for name, conns in nets_a1.items():
        for c in conns:
            ref = c.split(".")[0]
            if comps[ref].get("joint_type") == "solder":
                solder_eps.add(c)
    joints = nl["design_rules"]["solder"]["joints"]
    covered = set()
    for j in joints:
        for e in j["endpoints"]:
            if e in covered:
                err(f"はんだ点 {j['id']}: 端子 {e} が複数の点に現れる")
            covered.add(e)
            if e not in solder_eps:
                err(f"はんだ点 {j['id']}: {e} は構成A1のはんだ端子ではない")
    for e in sorted(solder_eps - covered):
        err(f"はんだ端子 {e} を覆う joints エントリが無い")
    total = nl["design_rules"]["solder"]["points_total"]
    if len(joints) != total:
        err(f"points_total={total} だが joints は {len(joints)} 件")
    if cfgs[a1]["hand_solder_points"] != total:
        err(f"configurations.hand_solder_points={cfgs[a1]['hand_solder_points']} が points_total={total} と不一致")
    n3 = sum(1 for j in joints if j["conductors"] >= 3)
    if n3 != nl["design_rules"]["solder"]["air_splices_3terminal"]:
        err("3端子スプライス数の宣言と実体が不一致")
    info.append(f"はんだ点: {len(joints)}点 / はんだ端子 {len(solder_eps)}個 / 3端子スプライス {n3}箇所")

    # ---- 検査8: 分圧の再計算 -----------------------------------------------
    def ohm(ref):
        return comps[ref]["spec"]["resistance_ohm"]

    for name, rt, rb, vs in (("VBUS_SENSE", "R2", "R3", ("4.40", "5.00", "5.25")),
                             ("VBAT_SENSE", "R4", "R5", ("3.00", "3.40", "3.70", "4.20"))):
        net = next(n for n in nl["nets"] if n["name"] == name)
        d = net["divider"]
        r1, r2 = ohm(rt), ohm(rb)
        ratio = r2 / (r1 + r2)
        if abs(ratio - d["ratio"]) > 1e-6:
            err(f"{name}: ratio 宣言 {d['ratio']} != 再計算 {ratio:.6f}")
        for v in vs:
            calc = float(v) * ratio
            if abs(calc - d["out_v"][v]) > 5e-4:
                err(f"{name}: {v}V の出力 宣言 {d['out_v'][v]} != 再計算 {calc:.4f}")
        th = r1 * r2 / (r1 + r2)
        if abs(th - d["thevenin_ohm"]) > 1:
            err(f"{name}: thevenin 宣言 {d['thevenin_ohm']} != 再計算 {th:.0f}")
        tau = th * 100e-9 * 1e3
        if abs(tau - d["tau_ms"]) > 0.05:
            err(f"{name}: tau 宣言 {d['tau_ms']}ms != 再計算 {tau:.2f}ms (0.1uF)")
        info.append(f"{name}: 比 {ratio:.3f} / Rth {th/1e3:.0f}k / tau {tau:.1f}ms  再計算一致")

    # VBUS の VIH マージン（ESP32-S3 VIH = 0.75 x VDD）
    dr = nl["design_rules"]["esp32s3"]
    vih = 0.75 * dr["vdd_v"]
    if abs(vih - dr["vih_v"]) > 1e-9:
        err(f"VIH 宣言 {dr['vih_v']} != 0.75*VDD = {vih}")
    d = next(n for n in nl["nets"] if n["name"] == "VBUS_SENSE")["divider"]
    r1, r2 = ohm("R2"), ohm("R3")
    for tol, key in ((0.05, "worst_case_tol5pct"), (0.01, "worst_case_tol1pct")):
        lo = 4.40 * (r2 * (1 - tol)) / (r1 * (1 + tol) + r2 * (1 - tol))
        hi = 5.25 * (r2 * (1 + tol)) / (r1 * (1 - tol) + r2 * (1 + tol))
        if abs(lo - d[key]["low_at_4.40V"]) > 1e-3:
            err(f"VBUS {key}: low 宣言 {d[key]['low_at_4.40V']} != 再計算 {lo:.3f}")
        if abs(hi - d[key]["high_at_5.25V"]) > 1e-3:
            err(f"VBUS {key}: high 宣言 {d[key]['high_at_5.25V']} != 再計算 {hi:.3f}")
        if lo < vih:
            err(f"VBUS {key}: 最悪 {lo:.3f}V が VIH {vih:.3f}V を割る")
        if hi > dr["design_max_input_v"]:
            err(f"VBUS {key}: 最悪 {hi:.3f}V が設計上限 {dr['design_max_input_v']}V を超える")
        info.append(f"VBUS {key}: 4.40V→{lo:.3f}V (VIH余裕 {(lo-vih)*1000:+.0f}mV) / 5.25V→{hi:.3f}V  OK")

    # ---- optional_blocks -----------------------------------------------------
    for b in nl.get("optional_blocks", []):
        refs = {c["ref"]: c for c in b["components"]}
        for n in b["nets"]:
            for c in n["connections"]:
                ref, pin = c.split(".", 1)
                if ref in refs:
                    if pin not in refs[ref]["pins"]:
                        err(f"optional_block {b['id']}: {ref} にピン {pin} が無い")
                elif ref in comps:
                    if pin not in comps[ref]["pins"]:
                        err(f"optional_block {b['id']}: {ref} にピン {pin} が無い")
                else:
                    err(f"optional_block {b['id']}: 未宣言の部品 {ref}")
        if b["status"] != "not_implemented":
            err(f"optional_block {b['id']}: v1.5 では not_implemented でなければならない")
        info.append(f"optional_block {b['id']}: {len(refs)}部品 / {len(b['nets'])}ネット  (status={b['status']})")

    # ---- 採用構成の機能フラグ整合 ---------------------------------------------
    a = cfgs[a1]
    for k in ("closes_vbus_detect", "closes_battery_monitor", "removes_battery_polarity_risk"):
        if a[k] is not False:
            err(f"採用構成 {a1} の {k} は false でなければならない（A-2は不採用）")
    if a["board"] is not None or a["added_height_mm"] != 0.0 or a["case_change_required"]:
        err("採用構成A-1は 基板なし・追加高さ0・筐体変更なし でなければならない")
    info.append("採用構成A-1の機能フラグ: vbus=false / battery=false / polarity_risk_removed=false  (審査員 must_fix と整合)")

    # ---- 出力 -------------------------------------------------------------
    for m in info:
        print("  [info] " + m)
    for m in warns:
        print("  [WARN] " + m)
    for m in errors:
        print("  [FAIL] " + m)
    print()
    if errors:
        print(f"NG: {len(errors)} 件のエラー")
        return 1
    print(f"PASS: エラー0 / 警告{len(warns)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
