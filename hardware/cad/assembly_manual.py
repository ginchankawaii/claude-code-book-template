# プラモデルの説明書風の組み込み図（hardware/renders/allday/manual_*.png）
import os
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assembly_anim.py')
src = open(SRC).read(); exec(src[:src.index('def render(')])
from matplotlib.patches import FancyBboxPatch
GRAY = (0.80,0.81,0.84)

def fig_step(num, title, new, done, lift=8.0, arrows=(), notes=(), inset=False, lid_th=180.0, film=False, gap=False, out=''):
    fig = plt.figure(figsize=(10,6.4), dpi=110)
    ax = fig.add_axes([0.0,0.0,0.66,0.88], projection='3d', computed_zorder=False)
    ax.add_collection3d(Poly3DCollection(body.triangles, facecolors=shade(body,(0.36,0.48,0.66),0.22), edgecolor='none', zorder=1))
    xf = lid_xf(lid_th); led_pt = tuple(xf(LED_FOOT)[0])
    def dz(k): return lift if k in new else 0.0
    def col(k, c): return c if k in new else GRAY
    shown = set(new) | set(done)
    if 'switch' in shown:
        draw_box(ax, SWITCH, col('switch',(0.78,0.79,0.82)), dz('switch'), z=5, edge=0.8)
        draw_box(ax, LEVER, (0.15,0.15,0.16), dz('switch'), z=5)
    if 'xiao' in shown:
        d = dz('xiao')
        zled = 9 if led_pt[0] < 3 else 4.5
        for n in XW:
            o = outside(n, d, led_pt); c = XW[n][2]
            if n == 'D3': tube(ax, o[:4], c, 4.5); tube(ax, o[3:], c, zled)
            else: tube(ax, o, c, 4.5)
        tube(ax, [led_pt, (min(led_pt[0]+2,-1),led_pt[1],max(led_pt[2],13.5)), (1.0,37.2,14.6), (3.0,37.4,12.0)] + LED_BLACK_TO[::-1], '#1b1d22', zled)
        for n in XW: tube(ax, under(n, d), XW[n][2], 3.5, 3.6, (0,(1.4,1.0)))
        for (b,c) in XIAO_LAYERS: draw_box(ax, b, c if 'xiao' in new else GRAY, d, alpha=0.16, z=3, edge=0.6)
        draw_box(ax, JST_P, (0.95,0.95,0.92), 0, z=5, edge=0.8)
    if 'batt' in shown:
        d = dz('batt'); draw_box(ax, BATT, col('batt',(0.74,0.76,0.82)), d, z=4, edge=0.8)
        draw_box(ax, (4.0,8.0,6.0,23.0,3.0,11.0), (0.95,0.80,0.25), d, z=4)
    if 'jst' in shown:
        d = dz('jst'); draw_box(ax, JST_B, col('jst',(0.98,0.60,0.25)), d, z=5, edge=1.0)
        for x,c in ((3.2,'#d32f2f'),(4.2,'#1b1d22')):
            tube(ax, [(4.0,15.5+(x-3.2),7.0),(2.6+(x-3.2)*0.5,15.5,7.0),(2.6+(x-3.2)*0.5,26.0,5.0),(x,28.6+d,3.3+d)], c, 6, 3.2)
    if film:
        draw_box(ax, (1.6,38.5,2.1,46.5,6.8,10.2), (0.15,0.75,0.45), 0, z=6, edge=1.0)
    if gap:
        draw_box(ax, (14.4,35.0,16.9,42.0,1.6,3.2), (0.15,0.75,0.45), 0, alpha=0.75, z=4.6, edge=0.9)
    draw_box(ax, LEDB, (0.9,0.15,0.15), xf=xf, z=7)
    draw_box(ax, LIP, (0.24,0.26,0.30), xf=xf, z=7)
    draw_box(ax, LID, (0.30,0.32,0.36) if 'lid' in new else (0.55,0.57,0.61), xf=xf, alpha=0.9, z=8)
    for (p, v, c) in arrows:
        ax.quiver(*p, *v, color=c, linewidth=3.0, arrow_length_ratio=0.28, zorder=11)
    ax.set_xlim(-22,46); ax.set_ylim(-4,54); ax.set_zlim(0,30)
    ax.set_box_aspect((68,58,30), zoom=1.32); ax.view_init(48,-66); ax.set_axis_off()
    # step header like a model kit manual
    fig.patches.append(FancyBboxPatch((0.015,0.905),0.07,0.08, boxstyle='round,pad=0.005', transform=fig.transFigure, fc='black', ec='black'))
    fig.text(0.05,0.945,str(num),fontsize=26,color='white',ha='center',va='center',weight='bold')
    fig.text(0.10,0.945,title,fontsize=18,va='center')
    y = 0.82
    for t in notes:
        fig.text(0.675,y,t,fontsize=11.5,va='top',linespacing=1.5); y -= 0.045 * (1 + t.count('\n')) + 0.03
    if inset:
        a2 = fig.add_axes([0.665,0.05,0.32,0.30]); a2.set_xlim(0,44); a2.set_ylim(-4,16); a2.set_aspect('equal'); a2.axis('off')
        a2.add_patch(Rectangle((0,0),40,1.6,fc=(0.55,0.65,0.8),ec='k',lw=0.8))
        for x in (4,32): a2.add_patch(Rectangle((x,1.6),3,1.4,fc=(0.55,0.65,0.8),ec='k',lw=0.8))
        a2.add_patch(Rectangle((3,3.0),34,0.9,fc=(0.15,0.15,0.17),ec='k'))
        a2.add_patch(Rectangle((9,3.9),14,2.3,fc=(0.8,0.8,0.83),ec='k',lw=0.6))
        a2.add_patch(Rectangle((3,9.4),34,0.9,fc=(0.15,0.15,0.17),ec='k'))
        for i,c in enumerate(['#e8730c','#1f6fd6','#d32f2f','#1b1d22','#1b1d22']):
            a2.add_patch(Circle((13+i*2.6,2.25),0.62,fc=c,ec='k',lw=0.5))
        a2.text(0,13.4,'断面（横から）',fontsize=11)
        a2.text(24.5,7.0,'XIAO',fontsize=9); a2.text(24.5,10.9,'拡張ボード',fontsize=8)
        a2.text(37.5,0.0,'床',fontsize=8); a2.text(37.5,2.0,'1.4mm',fontsize=8)
    fig.savefig(out, dpi=110); plt.close(fig); print(out)

O = R + 'renders/allday/'
fig_step(1,'スイッチをはめる', ['switch'], [], lift=10,
  arrows=[((8.35,46.5,24.0),(0,0,-8),'#e03030')],
  notes=['● 上の壁の内側の浅いくぼみへ。','● レバーを上の壁の穴から出す。','● 黒い線 2本の端子を左（壁側）に。\n   逆なら前後を裏返す。','● 接着は金属ケースと左右の柱だけ。\n   レバーの穴まわりには付けない。'],
  out=O+'manual_1.png')
fig_step(2,'XIAO を四隅の台に載せる', ['xiao'], ['switch'], lift=12,
  arrows=[((28,38,30),(0,0,-8),'#e03030')],
  notes=['● 線 5本は XIAO の裏に 1列に並べ、\n   2本の柱のすき間（緑）から外へ。','● 点線 = XIAO の下を通る線。','● USB の口を右の穴に合わせる。'],
  inset=True, gap=True, out=O+'manual_2.png')
fig_step(3,'電池を置く', ['batt'], ['switch','xiao'], lift=12,
  arrows=[((20,15.7,30),(0,0,-8),'#e03030'),((14,0.5,12),(-7,0,0),'#1f6fd6')],
  notes=['● 左の柱に突き当てる（青い矢印）。','● 右の壁との間に約 2.4mm\n   残すのが正解。詰めない。','● 底は薄い両面テープで固定。','● 電池の線は左の壁ぞいの溝へ。'],
  out=O+'manual_3.png')
fig_step(4,'電池をつなぎ、JST を寝かせる', ['jst'], ['switch','xiao','batt'], lift=9,
  arrows=[((3.7,24.0,10.0),(0,4.0,-5.0),'#e03030')],
  notes=['● 電池のプラグを、軽い力で\n   まっすぐ挿す。','● JST は左の壁にぴったり寄せ、\n   縦に寝かせる。\n   電池側が下、XIAO 側が上。','● 接着は左の壁との間に 1点だけ。','● JST の上には何も載せない。'],
  out=O+'manual_4.png')
fig_step(5,'アンテナを左の壁に貼る', [], ['switch','xiao','batt','jst'], film=True,
  arrows=[((2.0,42.5,24.0),(0,0,-10),'#e03030')],
  notes=['● 緑の位置：左の壁の内側。\n   床から 5mm より上、\n   縁から 2.5mm より下。','● マイク穴の壁・右の壁には貼らない。','● 貼ったら、外からマイク穴 3つが\n   見通せるか確かめる。'],
  out=O+'manual_5.png')
fig_step(6,'フタを閉める', ['lid'], ['switch','xiao','batt','jst'], film=True, lid_th=70.0,
  arrows=[((-6,25,30),(10,0,-6),'#e03030')],
  notes=['① 左上の角の出っ張りを\n   先に引っかける。','② 左の辺を差し込む。','③ 下の辺を押してパチン。','● 硬いときは押し込まず、\n   線の噛み込みと\n   電池のずれを見る。'],
  out=O+'manual_6.png')
