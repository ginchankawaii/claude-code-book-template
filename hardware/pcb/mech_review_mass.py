# [mechanical 審査用] 案A/B/C/D が筐体に入るかの検算スクリプト (自動生成 2026-08-28)
#   cad/mindclip_case.py を実際に評価して数値を出す。既存ファイルは一切変更しない。
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""各案の筐体を実際にビルドして印刷部品質量と watertight を実測する (レンダはスキップ)。"""
import os, re, io, contextlib, sys, trimesh, cadquery as cq
SRC="/home/user/claude-code-book-template/hardware/cad/mindclip_case.py"
raw=open(SRC,encoding="utf-8").read().split('if __name__ == "__main__":')[0]
FIX_SEATS='''xiao_seats = [
    (xiao[0], xiao[1]+0.1, xiao[0] + 2.5, xiao[1]+2.6, WALL, WALL + XIAO_LIFT),
    (xiao[2] - 2.6, xiao[1]+0.1, xiao[2], xiao[1]+2.6, WALL, WALL + XIAO_LIFT),
    (xiao[0], xiao[3]-2.6, xiao[0] + 2.5, xiao[3]-0.1, WALL, WALL + XIAO_LIFT),
    (xiao[2] - 2.6, xiao[3]-2.6, xiao[2], xiao[3]-0.1, WALL, WALL + XIAO_LIFT),
]'''
FIX_STOPS='''xiao_stops = [
    (xiao[0] - 3.0, xiao[1]+1.6, xiao[0] - 0.15, xiao[1]+5.6, WALL, 8.1),
    (xiao[0] - 3.0, xiao[3]-7.2, xiao[0] - 0.15, xiao[3]-3.2, WALL, 8.1),
]'''
def build(variant, ov, fix, tag):
    os.environ["MINDCLIP_VARIANT"]=variant
    s=raw
    if fix:
        s=re.sub(r"xiao_seats = \[.*?\n\]",FIX_SEATS,s,flags=re.S)
        s=re.sub(r"xiao_stops = \[.*?\n\]",FIX_STOPS,s,flags=re.S)
        s=re.sub(r"^sw_rib = .*$",'sw_rib = (2.9, WALL+IH-3.2, 3.7, WALL + IH, WALL, 8.4)',s,flags=re.M)
        s=re.sub(r"^LED_POS = .*$","LED_POS = (6.9, (bat[3]+(WALL+IH-3.2))/2.0)",s,flags=re.M)
    for k,v in ov.items():
        s=re.sub(r"^(%s\s*=\s*)([^\n#]*)"%re.escape(k),lambda m:m.group(1)+v,s,count=1,flags=re.M)
    ns={"__name__":"mc","__file__":SRC}
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(s,SRC,"exec"),ns); ns["check_layout"]()
    d=os.path.join(os.path.dirname(os.path.abspath(__file__)),"massout",tag,variant)
    os.makedirs(d,exist_ok=True)
    tot=0.0; wt=True
    for nm,fn in (("body",ns["build_body"]),("lid",ns["build_lid"]),("backplate",ns["build_backplate"])):
        p=os.path.join(d,nm+".stl")
        cq.exporters.export(fn(),p,tolerance=0.05,angularTolerance=0.2)
        m=trimesh.load(p); tot+=m.volume/1000.0*1.27; wt = wt and m.is_watertight
    return ns["W"],ns["H"],ns["TOTAL_D"],tot,wt

CASES=[("v1現行(=案A/案D)",{},False),
       ("案B(1.0t基板・Y+1.7・seat修正)",{"XIAO_LIFT":"1.8","GAP_BX":"1.8","M_TOP":"1.7"},True),
       ("案B最小(1.0t基板・Y+1.5)",{"XIAO_LIFT":"1.8","GAP_BX":"1.7","M_TOP":"1.6"},True),
       ("案C(ソケット LIFT7.7)",{"XIAO_LIFT":"7.7"},False)]
print(f"{'案':32s} {'variant':7s} {'外形 WxHxD':>22s} {'印刷部品質量':>10s} {'Δ質量':>7s} watertight")
print("-"*96)
base={}
for label,ov,fix in CASES:
    for v in ("allday","slim"):
        W,H,D,m,wt=build(v,ov,fix,label.split("(")[0])
        if label.startswith("v1"): base[v]=m
        print(f"{label:32s} {v:7s} {W:6.1f} x{H:6.1f} x{D:5.1f} mm {m:8.1f} g {m-base[v]:+7.1f} {wt}")
