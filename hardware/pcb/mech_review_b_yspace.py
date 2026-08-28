# [mechanical 審査用] 案A/B/C/D が筐体に入るかの検算スクリプト (自動生成 2026-08-28)
#   cad/mindclip_case.py を実際に評価して数値を出す。既存ファイルは一切変更しない。
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""案B: キャステレーション・ランドを XIAO の長辺外に出すのに必要な Y 方向の成長量を実数で出す。
   ①現行 CAD のままだと assert が落ちる (LED_POS/seat の絶対座標バグ) ことを確認
   ②seat/sw_rib を相対座標に直したうえで、ランド張り出し L に対する最小 GAP_BX/M_TOP を求める"""
import os, re, io, contextlib
SRC="/home/user/claude-code-book-template/hardware/cad/mindclip_case.py"
raw=open(SRC,encoding="utf-8").read().split('if __name__ == "__main__":')[0]

# --- seat / sw_rib を xiao[1]/xiao[3] 相対に直す修正パッチ (案Bを採る場合の必須修正) ---
FIX_SEATS = '''xiao_seats = [
    (xiao[0], xiao[1]+0.1, xiao[0] + 2.5, xiao[1]+2.6, WALL, WALL + XIAO_LIFT),
    (xiao[2] - 2.6, xiao[1]+0.1, xiao[2], xiao[1]+2.6, WALL, WALL + XIAO_LIFT),
    (xiao[0], xiao[3]-2.6, xiao[0] + 2.5, xiao[3]-0.1, WALL, WALL + XIAO_LIFT),
    (xiao[2] - 2.6, xiao[3]-2.6, xiao[2], xiao[3]-0.1, WALL, WALL + XIAO_LIFT),
]'''
FIX_SWRIB = 'sw_rib = (2.9, WALL+IH-3.2, 3.7, WALL + IH, WALL, 8.4)'
FIX_STOPS = '''xiao_stops = [
    (xiao[0] - 3.0, xiao[1]+1.6, xiao[0] - 0.15, xiao[1]+5.6, WALL, 8.1),
    (xiao[0] - 3.0, xiao[3]-7.2, xiao[0] - 0.15, xiao[3]-3.2, WALL, 8.1),
]'''
FIX_NT = '''xiao_nubs_top = [
    (xiao[0] + 0.3, xiao[3] + 0.15, _CAST_L - 0.3, WALL + IH, WALL, 7.0),
    (_CAST_R + 0.3, xiao[3] + 0.15, _CAST_R + 2.3, WALL + IH, WALL, 7.0),
]'''
def patched(fix):
    s = raw
    if fix:
        s = re.sub(r"xiao_seats = \[.*?\n\]", FIX_SEATS, s, flags=re.S)
        s = re.sub(r"^sw_rib = .*$", FIX_SWRIB, s, flags=re.M)
        s = re.sub(r"xiao_stops = \[.*?\n\]", FIX_STOPS, s, flags=re.S)
        s = re.sub(r"^LED_POS = .*$", "LED_POS = (6.9, (bat[3]+ (WALL+IH-3.2))/2.0)", s, flags=re.M)
    return s

def run(variant, ov, fix):
    os.environ["MINDCLIP_VARIANT"]=variant
    s = patched(fix)
    for k,v in ov.items():
        s = re.sub(r"^(%s\s*=\s*)([^\n#]*)"%re.escape(k), lambda m:m.group(1)+v, s, count=1, flags=re.M)
    ns={"__name__":"mc","__file__":SRC}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(s,SRC,"exec"),ns); ns["check_layout"]()
        return True,"",ns
    except AssertionError as e: return False,str(e),ns
    except Exception as e: return False,f"{type(e).__name__}: {e}",ns

print("① 現行 CAD のまま 案B の提案値 (GAP_BX 1.8 / M_TOP 1.7 / LIFT 1.8) を入れる")
ok,err,ns = run("allday", {"XIAO_LIFT":"1.8","GAP_BX":"1.8","M_TOP":"1.7"}, fix=False)
print(f"   → {'PASS' if ok else 'FAIL: '+err}   ★案Bの申告どおり、現行CADのままでは通らない\n")

print("② seat/stop/sw_rib/LED_POS を相対座標に直したうえで再評価")
for ov,label in [({"XIAO_LIFT":"1.8","GAP_BX":"1.8","M_TOP":"1.7"},"案B提案値"),
                 ({"XIAO_LIFT":"1.8"},"Y据置き(ランド用余地なし)")]:
    r=[]
    for v in ("allday","slim"):
        ok,err,ns=run(v,ov,fix=True)
        r.append((v,ok,err,ns["H"],ns["TOTAL_D"]))
    s="  ".join(f"{v}:{'PASS' if ok else 'FAIL('+err[:30]+')'} H={h:.1f} D={d:.1f}" for v,ok,err,h,d in r)
    print(f"   {label:24s} {s}")

print("\n③ キャステレーション・ランド張り出し L に対する必要 Y 成長量")
print("   XIAO 基板 17.8mm(Y) の外にランドを出す。下は電池上端まで GAP_BX、上は内壁まで M_TOP。")
print(f"   {'L(片側)':>8s} {'必要GAP_BX':>11s} {'必要M_TOP':>10s} {'外形H':>7s} {'Δ':>6s}  assert(allday/slim)")
CLR_BAT, CLR_WALL = 0.3, 0.2   # 電池/内壁への逃げ (assumption)
for L in (0.8, 1.0, 1.2, 1.4, 1.6, 2.0):
    g = max(1.2, round(L+CLR_BAT,1)); m = max(0.6, round(L+CLR_WALL,1))
    ov={"XIAO_LIFT":"1.8","GAP_BX":str(g),"M_TOP":str(m)}
    res=[]
    for v in ("allday","slim"):
        ok,err,ns=run(v,ov,fix=True); res.append((ok,err,ns["H"],ns["TOTAL_D"]))
    H=res[0][2]
    print(f"   {L:6.1f}mm {g:10.1f} {m:9.1f} {H:6.1f} {H-49.4:+6.1f}   "
          f"{'PASS' if res[0][0] else 'FAIL'}/{'PASS' if res[1][0] else 'FAIL'}"
          f"  (D: allday {res[0][3]:.1f} / slim {res[1][3]:.1f})")
