# 完成イメージ（フタを外して上から見た図）。向きは利用者の写真に合わせる:
#   USB・SD が上、マイク穴の壁が左、電池が右、左の壁（JST 側）が下。座標は CAD の配置 (mm)。
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams
from matplotlib.patches import Polygon, Circle
rcParams['font.family'] = 'IPAGothic'
OUT = '/home/user/claude-code-book-template/hardware/renders/allday/finished_view.png'
OR, BL, RD, BK = '#e8730c', '#1f6fd6', '#d32f2f', '#1b1d22'
def T(x, y): return (-y, x)                      # 設計座標 → 写真の向き
fig = plt.figure(figsize=(14, 7.6), dpi=110)
ax = fig.add_axes([0.0, 0.0, 1.0, 0.90]); ax.set_aspect('equal'); ax.axis('off')
ax.set_xlim(-51, 62); ax.set_ylim(-8, 50)
fig.text(0.02, 0.94, '完成イメージ（フタを外して上から見た図。写真と同じ向き）', fontsize=18)
def poly(b, fc, ec='k', lw=1.0, z=2, alpha=1.0, ls='-'):
    x0, y0, x1, y1 = b
    ax.add_patch(Polygon([T(x0,y0), T(x1,y0), T(x1,y1), T(x0,y1)], closed=True, fc=fc, ec=ec, lw=lw, zorder=z, alpha=alpha, ls=ls))
def wire(pts, c, lw=4.6, dashed=False, z=6):
    xs, ys = zip(*[T(*p) for p in pts])
    ax.plot(xs, ys, color='white', lw=lw+2.4, solid_capstyle='round', zorder=z-0.1)
    ax.plot(xs, ys, color=c, lw=lw, solid_capstyle='round', dash_capstyle='round',
            linestyle=(0,(1.5,1.0)) if dashed else '-', zorder=z)
def label(p, txt, at, color='k', fs=13):
    ax.annotate(txt, xy=T(*p), xytext=at, fontsize=fs, color=color, zorder=30,
                arrowprops=dict(arrowstyle='-', lw=1.1, color=color, shrinkA=2, shrinkB=1),
                bbox=dict(boxstyle='round,pad=0.3', fc='white', ec=color, lw=0.9))
WALL = (0.20, 0.21, 0.24); FLOOR = (0.36, 0.37, 0.41)
poly((0, 0, 40, 49.4), WALL, lw=1.2, z=1)
poly((1.6, 1.6, 38.4, 47.8), FLOOR, ec=(0.1,0.1,0.1), z=1.1)
poly((38.4, 33.05, 40, 43.55), (0.85,0.88,0.95), lw=0.8, z=1.2)           # USB
poly((38.4, 32.3, 40, 46.4), (0.70,0.74,0.82), lw=0.8, z=1.15)              # SD notch
poly((47.8-47.8+47.8, 5.85, 49.4, 10.85), 'w', lw=0, z=0) if False else None
poly((5.85, 47.8, 10.85, 49.4), (0.85,0.88,0.95), lw=0.8, z=1.2)            # lever slot
for mx in (22.5, 26.0, 29.5): ax.add_patch(Circle(T(mx, 48.6), 0.75, fc='white', zorder=1.3))
for b in [(14.4,28.7,16.9,35.0),(14.4,42.0,16.9,47.8),(2.9,44.1,3.7,47.8),(13.0,44.1,13.8,47.8),(1.6,5.0,3.8,9.0),(1.6,22.0,3.8,26.0)]:
    poly(b, (0.55,0.57,0.63), lw=0.6, z=1.5)
poly((14.4,35.0,16.9,42.0), (0.30,0.75,0.45), ec=(0.1,0.6,0.3), lw=1.0, z=1.4, alpha=0.8)
# battery
poly((4.0,3.2,36.0,28.2), (0.85,0.86,0.90), lw=1.2, z=3)
poly((4.0,8.0,6.0,23.0), (0.96,0.80,0.25), lw=0.6, z=3.1)
ax.text(*T(21,14.0), '電池', fontsize=16, ha='center', va='center', zorder=4)
poly((36.0,3.2,38.4,28.2), (1,0.85,0.85), ec=RD, lw=1.0, z=3, ls='--')
# XIAO + SD card
poly((17.4,29.4,38.4,47.2), (0.12,0.13,0.15), lw=1.3, z=3, alpha=0.55)
poly((27.4,33.3,41.7,45.4), (0.10,0.10,0.12), ec='w', lw=1.0, z=4)
ax.text(*T(34.6,39.3), 'SD', color='w', fontsize=11, ha='center', va='center', zorder=5)
ax.text(*T(22.5,38.3), 'XIAO', color='w', fontsize=15, ha='center', va='center', zorder=5)
for (x,y) in ((27.8,46.4),(32.9,46.4),(32.9,30.2)): ax.add_patch(Circle(T(x,y),0.75, fc=(1,0.85,0.4), ec='k', zorder=7))
for x in (27.8,30.3): poly((x-0.6,42.6,x+0.6,44.2), (1,0.85,0.4), lw=0.6, z=7)
# switch
poly((4.0,44.5,12.7,47.8), (0.80,0.81,0.84), lw=1.0, z=5)
poly((7.0,47.8,8.4,49.6), (0.1,0.1,0.1), lw=0.6, z=5)
for x in (5.81, 8.35): poly((x-0.35,42.6,x+0.35,44.5), (0.85,0.65,0.3), lw=0.5, z=5)
# LED (on the lid) + resistor
ax.add_patch(Circle(T(8.2,36.0), 1.7, fc=(1,0.55,0.55), ec=RD, lw=1.4, ls='--', zorder=8, alpha=0.9))
wire([(9.3,34.6),(9.3,33.4)], '#b8b8b8', 2.4, z=8); wire([(7.1,34.6),(7.1,33.4)], '#b8b8b8', 2.4, z=8)
poly((8.5,29.0,10.1,33.4), (0.80,0.70,0.50), lw=0.8, z=8)
# JST
poly((1.6,33.2,5.8,37.8), 'white', lw=1.0, z=6); poly((1.6,28.6,5.8,33.2), (1.0,0.92,0.70), lw=1.0, z=6)
# wires: solid = on the floor, dashed = under the XIAO
wire([(3.0,15.0),(2.6,15.5),(2.6,27.6),(3.2,28.6)], RD, 3.6); wire([(4.0,15.8),(3.4,16.2),(3.4,27.6),(4.2,28.6)], BK, 3.6)
wire([(3.2,37.8),(3.2,38.9),(17.4,38.9)], RD); wire([(17.4,38.9),(27.8,38.9),(27.8,42.6)], RD, dashed=True)
wire([(4.2,37.8),(4.2,38.2),(12.0,38.2),(12.0,37.8),(17.4,37.8)], BK); wire([(17.4,37.8),(30.3,37.8),(30.3,42.6)], BK, dashed=True)
# black tube from the left switch terminal, bent toward the entry
wire([(5.81,42.6),(6.6,41.5),(10.5,41.3)], BK, 7.5, z=6.5)
wire([(10.5,41.3),(13.5,40.4),(14.6,36.6),(17.4,36.6)], BK); wire([(17.4,36.6),(32.9,36.6),(32.9,30.2)], BK, dashed=True)
wire([(10.5,41.3),(10.8,40.3),(7.6,39.2),(7.1,34.0)], BK, 3.6, z=6.6)
wire([(8.35,42.6),(8.35,41.9),(12.6,41.8),(13.8,40.0),(17.4,40.0)], BL); wire([(17.4,40.0),(32.9,40.0),(32.9,46.4)], BL, dashed=True)
wire([(9.3,29.0),(11.8,29.4),(12.4,41.0),(14.2,41.2),(17.4,41.0)], OR); wire([(17.4,41.0),(27.8,41.0),(27.8,46.4)], OR, dashed=True)
# numbered markers on the drawing + list on the right (model-kit style)
MARK = [((8.35,46.2),'1'),((5.0,41.2),'2'),((11.0,43.3),'3'),((3.7,31.0),'4'),((8.2,36.0),'5'),((11.8,33.5),'6'),
        ((15.6,38.5),'7'),((2.6,20.0),'8'),((22.0,34.5),'9'),((36.5,39.3),'10'),((20,10.0),'11'),((37.2,20.0),'12')]
for (p,n) in MARK:
    ax.add_patch(Circle(T(*p), 1.35, fc='white', ec='k', lw=1.4, zorder=40))
    ax.text(*T(*p), n, fontsize=11 if len(n)==1 else 9.5, ha='center', va='center', zorder=41, weight='bold')
ITEMS = [('1','スイッチ。レバーは左の壁の穴から外へ', 'k'),
         ('2','黒 2本の端子は壁側。チューブはすぐ曲げて入口へ', 'k'),
         ('3','切った端子は XIAO 側', RD),
         ('4','JST。下の壁にぴったり、縦に寝かせる', (0.1,0.3,0.8)),
         ('5','LED（フタ側）。足は電池のほうへ曲げる', RD),
         ('6','抵抗と橙の線。通り道を通って入口へ', OR),
         ('7','入口。5本ともここから XIAO の下へ', (0.1,0.55,0.25)),
         ('8','電池の線は下の壁ぞいの溝を通す', RD),
         ('9','XIAO。四隅の台に平らに載せる', 'k'),
         ('10','SD カード。切り欠きから外へ 1.7mm 出る', 'k'),
         ('11','電池。左の柱（マイク側）に突き当てる', 'k'),
         ('12','電池の右のすき間。何も入れない', RD)]
y = 47.0
for n,t,c in ITEMS:
    ax.add_patch(Circle((3.2, y), 1.35, fc='white', ec='k', lw=1.4, zorder=40))
    ax.text(3.2, y, n, fontsize=11 if len(n)==1 else 9.5, ha='center', va='center', zorder=41, weight='bold')
    ax.text(5.6, y, t, fontsize=13.5, va='center', color=c); y -= 3.7
ax.text(1.9, y-0.6, '実線：床の上を通る線\n点線：XIAO の下を通る線\nアンテナ：貼る場所はフィルムの\n寸法を測ってから決めます（未定）', fontsize=12.5, va='top', linespacing=1.6)
fig.savefig(OUT, dpi=110)
print(OUT)
