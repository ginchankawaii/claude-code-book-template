# [mechanical 審査用] 案A/B/C/D が筐体に入るかの検算スクリプト (自動生成 2026-08-28)
#   cad/mindclip_case.py を実際に評価して数値を出す。既存ファイルは一切変更しない。
import os, re, io, contextlib
SRC="/home/user/claude-code-book-template/hardware/cad/mindclip_case.py"
raw=open(SRC,encoding="utf-8").read().split('if __name__ == "__main__":')[0]
def dimsof(v, lift):
    os.environ["MINDCLIP_VARIANT"]=v
    s=re.sub(r"^(XIAO_LIFT\s*=\s*)([^\n#]*)",lambda m:m.group(1)+str(lift),raw,count=1,flags=re.M)
    ns={"__name__":"mc","__file__":SRC}
    with contextlib.redirect_stdout(io.StringIO()): exec(compile(s,SRC,"exec"),ns)
    return ns["ID"], ns["TOTAL_D"], ns["BODY_D"]-ns["xiao"][5]
print("XIAO スタック下に何かを差し込んだとき (XIAO_LIFT を増やしたとき) の外形厚みの応答")
print(f"{'XIAO_LIFT':>10s} {'追加分':>7s} | {'allday ID':>9s} {'外形D':>7s} {'Δ厚み':>7s} {'頭上':>6s}"
      f" | {'slim ID':>8s} {'外形D':>7s} {'Δ厚み':>7s} {'頭上':>6s}")
print("-"*96)
for lift in [1.4,1.8,2.0,2.4,2.8,3.0,3.1,3.2,3.6,4.0,5.0,7.7]:
    ida,da,ha = dimsof("allday",lift); ids,ds,hs = dimsof("slim",lift)
    mark = "  ← alldayの無料枠の限界" if abs(lift-3.1)<1e-9 else ""
    print(f"{lift:10.2f} {lift-1.4:+7.2f} | {ida:9.2f} {da:7.2f} {da-14.6:+7.2f} {ha:6.2f}"
          f" | {ids:8.2f} {ds:7.2f} {ds-12.9:+7.2f} {hs:6.2f}{mark}")
print()
print("結論: allday は XIAO 側に **1.70mm の無料枠** がある (電池側 ID=11.20 が支配的なため)。")
print("      slim は XIAO 側が既に支配的 (ID=9.50 > 電池側8.20) → **無料枠 0.00mm、1:1 で厚みに出る**。")
