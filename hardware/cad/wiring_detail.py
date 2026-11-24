# 配線の拡大図（プラモ説明書の「拡大図」風）。座標は CAD の配置（mm、本体を上から見た向き）。
#   hardware/renders/allday/detail_wiring.png  … 左の区画とXIAOの上から見た拡大図
#   hardware/renders/allday/detail_parts.png   … スイッチ単体 / LED まわりを横から見た図
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams
from matplotlib.patches import Rectangle, Circle, FancyBboxPatch, Polygon
rcParams['font.family'] = 'IPAGothic'
OUT = '/home/user/claude-code-book-template/hardware/renders/allday/'
OR, BL, RD, BK = '#e8730c', '#1f6fd6', '#d32f2f', '#1b1d22'
WALLC, PART, MET = (0.70,0.76,0.86), (0.93,0.94,0.96), (0.78,0.79,0.82)

def wire(ax, pts, c, lw=4.2, dashed=False, z=5):
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color='white', lw=lw+2.2, solid_capstyle='round', zorder=z-0.1)
    ax.plot(xs, ys, color=c, lw=lw, solid_capstyle='round', dash_capstyle='round',
            linestyle=(0,(1.6,1.1)) if dashed else '-', zorder=z)
def rect(ax, x0,y0,x1,y1, fc, ec='k', lw=1.0, z=2, **kw):
    ax.add_patch(Rectangle((x0,y0), x1-x0, y1-y0, fc=fc, ec=ec, lw=lw, zorder=z, **kw))
def label(ax, xy, txt, at, color='k', fs=12.5):
    ax.annotate(txt, xy=xy, xytext=at, fontsize=fs, color=color, zorder=20,
                arrowprops=dict(arrowstyle='-', lw=1.0, color=color, shrinkA=2, shrinkB=1),
                bbox=dict(boxstyle='round,pad=0.25', fc='white', ec=color, lw=0.8))

# ---------------------------------------------------------------- top view
fig = plt.figure(figsize=(14,7.4), dpi=110)
ax = fig.add_axes([0.005,0.005,0.99,0.87]); ax.set_aspect('equal'); ax.axis('off')
ax.set_xlim(-16,58); ax.set_ylim(23.5,57)
fig.patches.append(FancyBboxPatch((0.012,0.905),0.05,0.075, boxstyle='round,pad=0.004', transform=fig.transFigure, fc='k'))
fig.text(0.037,0.955,'拡大', color='white', fontsize=15, ha='center', va='center')
fig.text(0.075,0.955,'線のつながり（フタを外して上から見た図。フタの LED は閉めた位置に描いています）', fontsize=16, va='center')
# walls
rect(ax, 0,23.5,1.6,49.4, WALLC, lw=0.8); rect(ax, 0,47.8,40,49.4, WALLC, lw=0.8); rect(ax, 38.4,23.5,40,49.4, WALLC, lw=0.8)
rect(ax, 5.85,47.8,10.85,49.4, 'white', lw=0.8, z=2.1)
for mx in (22.5,26.0,29.5): ax.add_patch(Circle((mx,48.6),0.75, fc='k', zorder=3))
rect(ax, 38.4,33.05,40,43.55, 'white', lw=0.8, z=2.1)
ax.text(20,50.2,'上の壁（マイク穴の壁）', fontsize=11, ha='center'); ax.text(41,38.3,'USB の穴', fontsize=11, va='center')
# ribs
for b in [(14.4,28.7,16.9,35.0),(14.4,42.0,16.9,47.8),(2.9,44.1,3.7,47.8),(13.0,44.1,13.8,47.8),(1.6,23.5,3.8,26.0)]:
    rect(ax, *b, (0.55,0.6,0.7), lw=0.6)
rect(ax, 14.4,35.0,16.9,42.0, (0.80,0.95,0.85), ec=(0.1,0.6,0.3), lw=1.0, z=1.5)
label(ax, (15.6,35.6), '入口（柱のすき間）：ここから XIAO の下へ', (6.0,24.2), color=(0.1,0.5,0.25))
rect(ax, 10.2,28.6,14.4,40.0, (0.92,0.98,0.93), ec=(0.1,0.6,0.3), lw=0.6, z=1.4, ls='--')
# battery
rect(ax, 4.0,23.5,36.0,28.2, (0.80,0.82,0.88), lw=1.0); ax.text(32,25.0,'電池', fontsize=12, ha='center')
# XIAO + pads
rect(ax, 17.4,29.4,38.4,47.2, (0.20,0.21,0.24), ec='k', lw=1.2, z=2, alpha=0.18)
ax.text(24.6,32.6,'XIAO（部品面が上）', fontsize=11, ha='center', color=(0.15,0.15,0.2), zorder=7)
top = ['D0','D1','D2','D3','D4','D5','D6']; bot = ['5V','GND','3V3','D10','D9','D8','D7']
for i in range(7):
    x = 35.4 - i*2.54
    for (y, name) in ((46.4, top[i]), (30.2, bot[i])):
        key = name in ('D1','D3','GND')
        ax.add_patch(Circle((x,y),0.75, fc=(1,0.85,0.4) if key else 'white', ec='k', lw=0.8, zorder=6))
        ax.text(x, y+(1.35 if y>40 else -1.9), name, fontsize=9.5 if not key else 11, ha='center', weight='bold' if key else 'normal', zorder=6)
for (x,name) in ((27.8,'BAT＋'),(30.3,'BAT−')):
    rect(ax, x-0.6,42.6,x+0.6,44.2, (1,0.85,0.4), lw=0.8, z=6)
# switch (lever up through the slot, terminals pointing down)
rect(ax, 4.0,44.5,12.7,47.8, MET, lw=1.0, z=4); rect(ax, 7.0,47.8,8.4,51.2, (0.15,0.15,0.15), lw=0.8, z=4)
ax.text(10.5,46.1,'スイッチ', fontsize=10.5, ha='center', zorder=6)
for x in (5.81,8.35): rect(ax, x-0.35,41.6,x+0.35,44.5, (0.85,0.65,0.3), lw=0.6, z=4)
rect(ax, 10.89-0.35,43.8,10.89+0.35,44.5, (0.85,0.65,0.3), lw=0.6, z=4)
ax.plot([10.2,11.6],[43.0,41.8], color='r', lw=2, zorder=7); ax.plot([10.2,11.6],[41.8,43.0], color='r', lw=2, zorder=7)
rect(ax, 4.6,40.4,7.0,44.0, (0.1,0.1,0.1), lw=0.6, z=4.5, alpha=0.35)
# LED on the lid (closed position) and its leads bent toward the battery
ax.add_patch(Circle((8.2,36.0),1.7, fc=(1,0.75,0.75), ec=RD, lw=1.4, ls='--', zorder=3))
ax.text(8.2,36.0,'LED', fontsize=9, ha='center', va='center', zorder=6)
wire(ax, [(9.3,35.4),(9.3,33.4)], '#b0b0b0', 2.4, z=5)          # anode leg
wire(ax, [(7.1,35.4),(7.1,33.4)], '#b0b0b0', 2.4, z=5)          # cathode leg
rect(ax, 8.55,29.2,10.05,33.4, (0.85,0.75,0.55), lw=0.8, z=5.5)  # resistor in heat-shrink
ax.add_patch(Rectangle((8.35,29.0),1.9,4.6, fc=(0.2,0.2,0.25,0.25), ec=(0.2,0.2,0.25), lw=0.6, zorder=5.6))
# wires (solid = above the floor in the pocket, dashed = under the XIAO)
wire(ax, [(9.3,29.0),(12.6,29.6),(12.6,41.0),(17.4,41.0)], OR); wire(ax, [(17.4,41.0),(27.8,41.0),(27.8,46.4)], OR, dashed=True)
wire(ax, [(8.35,41.6),(8.35,40.4),(12.0,40.0),(17.4,40.0)], BL); wire(ax, [(17.4,40.0),(32.9,40.0),(32.9,46.4)], BL, dashed=True)
wire(ax, [(5.5,41.6),(6.0,39.6),(11.4,39.0),(11.4,36.6),(17.4,36.6)], BK); wire(ax, [(17.4,36.6),(32.9,36.6),(32.9,30.2)], BK, dashed=True)
wire(ax, [(6.1,41.6),(6.1,37.0),(7.1,33.4)], BK)
wire(ax, [(3.2,37.8),(3.2,38.8),(11.9,38.8),(11.9,38.9),(17.4,38.9)], RD); wire(ax, [(17.4,38.9),(27.8,38.9),(27.8,42.6)], RD, dashed=True)
wire(ax, [(4.2,37.8),(4.2,38.2),(11.7,38.2),(11.7,37.8),(17.4,37.8)], BK); wire(ax, [(17.4,37.8),(30.3,37.8),(30.3,42.6)], BK, dashed=True)
# JST
rect(ax, 1.6,33.2,5.8,37.8, 'white', lw=1.0, z=4); rect(ax, 1.6,28.6,5.8,33.2, (0.98,0.88,0.6), lw=1.0, z=4)
wire(ax, [(2.6,23.5),(2.6,27.6),(3.2,28.6)], RD, 3.4); wire(ax, [(3.2,23.5),(3.4,27.6),(4.2,28.6)], BK, 3.4)
# labels
label(ax, (8.0,49.8), 'レバーは上の壁の穴から出す。左へ倒すと ON（録音）', (-15.5,53.0))
label(ax, (5.81,42.6), '左の端子（壁側）：黒 2本\nLED の短い足 と XIAO の GND', (-15.5,44.4))
label(ax, (8.35,42.2), '中央の端子：青 → XIAO の D1', (-15.5,40.8), color=BL)
label(ax, (10.9,43.4), '右の端子（XIAO 側）：根元で切る', (-15.5,48.6), color='r')
label(ax, (7.1,34.2), 'LED の短い足（−）：黒。壁側（左）', (-15.5,37.0))
label(ax, (9.3,31.2), 'LED の長い足（＋）→ 抵抗 → 橙\nXIAO 側（右）。足は電池のほうへ曲げる', (-15.5,31.4), color=OR)
label(ax, (12.6,33.0), '線の通り道', (19.5,26.4), color=(0.1,0.5,0.25))
label(ax, (3.7,35.6), 'JST：左の壁に縦に寝かせる\n上が XIAO 側、下が電池側', (-15.5,25.6))
label(ax, (27.8,46.4), '橙 → D3', (18.0,55.3), color=OR)
label(ax, (32.9,46.4), '青 → D1', (30.0,55.3), color=BL)
label(ax, (32.9,30.2), '黒 → GND', (41.5,27.0))
label(ax, (27.8,43.4), '電池の＋（印の線）→ BAT＋', (41.5,47.0), color=RD)
label(ax, (30.3,43.4), '電池の− → BAT−', (41.5,44.4))
ax.text(41.5,34.5,'実線：床の上を通る線\n点線：XIAO の下を通る線\n（裏の穴・パッドに付いている）', fontsize=11.5, va='top', linespacing=1.6)
fig.savefig(OUT+'detail_wiring.png', dpi=110); plt.close(fig)

# ---------------------------------------------------------------- side views
fig = plt.figure(figsize=(13.5,6.2), dpi=110)
fig.patches.append(FancyBboxPatch((0.012,0.88),0.05,0.09, boxstyle='round,pad=0.004', transform=fig.transFigure, fc='k'))
fig.text(0.037,0.925,'拡大', color='white', fontsize=15, ha='center', va='center')
fig.text(0.075,0.925,'部品の向き', fontsize=16, va='center')
# switch alone, terminals toward the viewer's bottom
a = fig.add_axes([0.02,0.02,0.46,0.80]); a.set_aspect('equal'); a.axis('off'); a.set_xlim(-6,22); a.set_ylim(-9,12)
rect(a, 0,0,8.7,4.0, MET, lw=1.2); rect(a, 3.0,4.0,4.4,7.0, (0.15,0.15,0.15), lw=0.8)
for x in (1.81,4.35): rect(a, x-0.35,-3.5,x+0.35,0, (0.85,0.65,0.3), lw=0.6)
rect(a, 6.89-0.35,-0.6,6.89+0.35,0, (0.85,0.65,0.3), lw=0.6)
a.plot([6.0,7.8],[-1.4,-2.8], 'r', lw=2); a.plot([6.0,7.8],[-2.8,-1.4], 'r', lw=2)
wire(a, [(1.6,-3.5),(1.0,-8.5)], BK); wire(a, [(2.0,-3.5),(2.6,-8.5)], BK); wire(a, [(4.35,-3.5),(4.35,-8.5)], BL)
a.add_patch(Rectangle((0.6,-6.0),2.4,3.0, fc=(0.1,0.1,0.1,0.35), ec='k', lw=0.6))
a.text(3.7,10.2,'スイッチ（中から上の壁を見た向き）', fontsize=13, ha='center')
label(a, (3.7,6.0), 'レバー：上の壁の穴へ', (10.5,8.0))
label(a, (1.81,-1.5), '左の端子＝壁側', (-5.8,-1.0))
label(a, (6.89,-0.3), '右の端子は切る＝XIAO 側', (9.5,1.0), color='r')
label(a, (1.0,-8.0), '黒 → LED の短い足', (8.5,-5.5))
label(a, (2.6,-8.2), '黒 → XIAO の GND', (8.5,-7.5))
label(a, (4.35,-6.5), '青 → XIAO の D1', (8.5,-3.4), color=BL)
# LED side view (cut through the LED, battery to the left)
b = fig.add_axes([0.52,0.02,0.46,0.80]); b.set_aspect('equal'); b.axis('off'); b.set_xlim(-14,16); b.set_ylim(-1,17)
rect(b, -14,12.8,16,14.6, (0.30,0.32,0.36), lw=1.0); b.text(12,15.3,'フタ', fontsize=11)
rect(b, -2.5,10.0,-1.7,12.8, (0.30,0.32,0.36), lw=0.8); rect(b, 1.7,10.0,2.5,12.8, (0.30,0.32,0.36), lw=0.8)
b.add_patch(Polygon([(-1.5,12.8),(1.5,12.8),(1.5,7.4),(-1.5,7.4)], closed=True, fc=(1,0.6,0.6), ec=RD, lw=1.2))
rect(b, -1.7,7.4,1.7,8.0, (1,0.6,0.6), ec=RD, lw=1.0)
wire(b, [(0.0,7.4),(0.0,5.0),(-6.0,5.0)], '#9a9a9a', 2.6)
rect(b, -10.5,4.2,-6.0,5.8, (0.85,0.75,0.55), lw=0.8)
b.add_patch(Rectangle((-11.0,3.9),5.6,2.2, fc=(0.2,0.2,0.25,0.25), ec=(0.2,0.2,0.25), lw=0.6))
wire(b, [(-10.5,5.0),(-13.5,5.0)], OR)
rect(b, -14,0,16,1.6, WALLC, lw=0.8); b.text(12,0.3,'床', fontsize=10)
b.annotate('', xy=(-13.5,9.5), xytext=(-6.5,9.5), arrowprops=dict(arrowstyle='->', lw=2, color=(0.1,0.4,0.8)))
b.text(-10.0,10.1,'電池の方向', fontsize=11, ha='center', color=(0.1,0.4,0.8))
b.text(1.0,16.2,'LED まわり（横から見た図）', fontsize=13, ha='center')
label(b, (0.0,6.0), '足は根元から 2〜3mm で直角に曲げ、\n電池のほうへ倒す', (3.5,4.8))
label(b, (-8.2,5.8), '長い足（＋）→ 抵抗 → 橙の線\n（チューブで覆う）', (-13.8,2.0), color=OR)
label(b, (0.0,9.5), 'LED は筒に入れて接着', (4.0,9.0), color=RD)
b.text(-13.8,-0.9+17.0-1.2,'短い足（−）は奥（壁側）で同じ向きに曲げ、黒の線へ', fontsize=11)
fig.savefig(OUT+'detail_parts.png', dpi=110); plt.close(fig)
print('ok')
