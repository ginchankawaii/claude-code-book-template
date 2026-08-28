# [mechanical 審査用] 案A/B/C/D が筐体に入るかの検算スクリプト (自動生成 2026-08-28)
#   cad/mindclip_case.py を実際に評価して数値を出す。既存ファイルは一切変更しない。
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""案A/B/C/D を mindclip_case.py のパラメータ空間で再計算し、筐体に入るかを実数で検算する。
   実行方法: python3 eval_fit.py
   手法: mindclip_case.py のソースを読み、パラメータ行だけを置換して exec し、
         check_layout() を呼んで assert 通過可否と外形寸法を取る。
         cadquery のジオメトリ構築 (build_*) は呼ばないので数秒で終わる。"""
import os, re, sys, io, contextlib, textwrap

SRC = "/home/user/claude-code-book-template/hardware/cad/mindclip_case.py"
raw = open(SRC, encoding="utf-8").read()
# __main__ ブロックを落とす (STL/レンダ生成を走らせない)
raw = raw.split('if __name__ == "__main__":')[0]

def patch(src, overrides):
    """トップレベルの `NAME = <値>` 行を置換する。"""
    for k, v in overrides.items():
        pat = re.compile(r"^(%s\s*=\s*)([^\n#]*)" % re.escape(k), re.M)
        new, n = pat.subn(lambda m: "%s%s" % (m.group(1), v), src, count=1)
        assert n == 1, f"param {k} not found"
        src = new
    return src

def run(variant, overrides=None, label=""):
    overrides = overrides or {}
    os.environ["MINDCLIP_VARIANT"] = variant
    src = patch(raw, overrides)
    ns = {"__name__": "mc_probe", "__file__": SRC}
    buf = io.StringIO()
    ok, err = True, ""
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(src, SRC, "exec"), ns)
            ns["check_layout"]()
    except AssertionError as e:
        ok, err = False, str(e)
    except Exception as e:
        ok, err = False, f"{type(e).__name__}: {e}"
    return ok, err, ns

def dims(ns):
    return dict(
        IW=ns["IW"], IH=ns["IH"], ID=ns["ID"],
        W=ns["W"], H=ns["H"], BODY_D=ns["BODY_D"], TOTAL_D=ns["TOTAL_D"],
        xiao_z0=ns["xiao"][4], xiao_z1=ns["xiao"][5],
        lid_inner=ns["BODY_D"],
        head=ns["BODY_D"] - ns["xiao"][5],
        under=ns["xiao"][4] - ns["WALL"],
        bat_top=ns["bat"][5],
        lip_z0=ns["BODY_D"] - ns["LIP_D"],
        xiao_x0=ns["xiao"][0], xiao_x1=ns["xiao"][2],
        xiao_y0=ns["xiao"][1], xiao_y1=ns["xiao"][3],
        stopx0=ns["xiao_stops"][0][0],
        GAP_BX=ns["GAP_BX"], M_TOP=ns["M_TOP"], XIAO_LIFT=ns["XIAO_LIFT"],
    )

BASE = {}
print("="*86)
print("BASELINE (v1 現行) — CAD 実行値")
print("="*86)
for v in ("allday", "slim"):
    ok, err, ns = run(v)
    d = dims(ns); BASE[v] = d
    print(f"[{v:6s}] assert={'PASS' if ok else 'FAIL '+err}")
    print(f"         外形 {d['W']:.1f} x {d['H']:.1f} x {d['TOTAL_D']:.1f} mm"
          f" / 内寸 {d['IW']:.1f} x {d['IH']:.1f} x {d['ID']:.2f} mm")
    print(f"         XIAOスタック z {d['xiao_z0']:.2f}..{d['xiao_z1']:.2f}"
          f" / 床下逃げ {d['under']:.2f} mm / リッド内面 z{d['lid_inner']:.2f}"
          f" → **XIAO上の高さ予算 {d['head']:.2f} mm**")
    print(f"         XIAO y {d['xiao_y0']:.2f}..{d['xiao_y1']:.2f}"
          f" (下の配線ギャップ GAP_BX={d['GAP_BX']}, 上マージン M_TOP={d['M_TOP']})")
    print(f"         電池上面 z{d['bat_top']:.2f} / lip帯 z{d['lip_z0']:.2f}..{d['BODY_D']:.2f}")
print()

print("="*86)
print("各案の筐体パラメータ再計算 (mindclip_case.py を実際に評価)")
print("="*86)
CASES = [
  ("案A  (基板なし・A-1/A-2)",        {}),
  ("案B  (キャリア: LIFTのみ変更)",   {"XIAO_LIFT": "1.8"}),
  ("案B  (キャリア: 提案どおり全変更)",{"XIAO_LIFT": "1.8", "GAP_BX": "1.8", "M_TOP": "1.7"}),
  ("案B' (キャリア 1.6t基板を使う)",  {"XIAO_LIFT": "2.4", "GAP_BX": "1.8", "M_TOP": "1.7"}),
  ("案C  (ピンソケット C-a')",        {"XIAO_LIFT": "7.7"}),
  ("案C  (理論下限 裸ピン C-d)",      {"XIAO_LIFT": "3.3"}),
  ("案D  (蛇の目サテライト)",          {}),
]
rows = []
for label, ov in CASES:
    line = {"label": label}
    for v in ("allday", "slim"):
        ok, err, ns = run(v, ov)
        d = dims(ns)
        line[v] = (ok, err, d)
    rows.append(line)

hdr = f"{'案':34s} | {'allday 外形D':>12s} {'Δ':>6s} {'頭上':>6s} | {'slim 外形D':>11s} {'Δ':>6s} {'頭上':>6s} | 外形H  Δ  | assert"
print(hdr); print("-"*len(hdr))
for r in rows:
    oa, ea, da = r["allday"]; os_, es, ds = r["slim"]
    st = "PASS" if (oa and os_) else ("FAIL: " + (ea or es))[:46]
    print(f"{r['label']:34s} | {da['TOTAL_D']:9.2f}mm {da['TOTAL_D']-BASE['allday']['TOTAL_D']:+6.2f} {da['head']:5.2f}mm"
          f" | {ds['TOTAL_D']:8.2f}mm {ds['TOTAL_D']-BASE['slim']['TOTAL_D']:+6.2f} {ds['head']:5.2f}mm"
          f" | {da['H']:5.1f} {da['H']-BASE['allday']['H']:+4.1f} | {st}")
print()
print("※ 外形D = 装着時の『厚み』(襟から浮く方向)。外形H = クリップの長辺(49.4mm)。")
print("※ 頭上 = XIAOスタック上面〜リッド内面のクリアランス。CADの assert 下限は 0.50mm。")
