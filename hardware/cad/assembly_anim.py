# 組み込み手順のアニメーション GIF（hardware/renders/allday/assembly.gif）
# 先に cad/mindclip_case.py を実行して STL を作っておくこと。依存: trimesh matplotlib pillow、フォント IPAGothic。
import numpy as np, trimesh, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams
from matplotlib.patches import Rectangle, Circle
from mpl_toolkits.mplot3d.art3d import Poly3DCollection, Line3DCollection
from PIL import Image
rcParams['font.family'] = 'IPAGothic'
R = '/home/user/claude-code-book-template/hardware/'
body = trimesh.load_mesh(R + 'stl/allday/mindclip_phonebody.stl')
BODY_D, LID_T, H, W = 12.8, 1.8, 49.4, 40.0
L = np.array([0.35, -0.5, 0.8]); L /= np.linalg.norm(L)
SH = [1.0, 0.72, 0.85, 0.6, 0.65, 0.5]

def corners(b):
    x0,y0,x1,y1,z0,z1 = b
    return np.array([[x0,y0,z0],[x1,y0,z0],[x1,y1,z0],[x0,y1,z0],[x0,y0,z1],[x1,y0,z1],[x1,y1,z1],[x0,y1,z1]], float)
FACES = [(4,5,6,7),(0,1,5,4),(1,2,6,5),(3,2,6,7),(0,3,7,4),(0,1,2,3)]  # top, front, right, back, left, bottom
def draw_box(ax, b, base, dz=0.0, alpha=1.0, z=3, xf=None, edge=0.5):
    c = corners(b); c[:,2] += dz
    if xf is not None: c = xf(c)
    quads = [[tuple(c[i]) for i in f] for f in FACES]
    # face shading from actual normals after transform
    cols=[]
    for q in quads:
        p = np.array(q); n = np.cross(p[1]-p[0], p[3]-p[0]); n = n/ (np.linalg.norm(n)+1e-9)
        s = 0.45 + 0.55*abs(n @ L)
        cols.append(tuple(min(1, v*s) for v in base) + (alpha,))
    ax.add_collection3d(Poly3DCollection(quads, facecolors=cols, edgecolors=(0,0,0,edge), linewidths=0.6, zorder=z))

def tube(ax, pts, col, z, lw=4.0, ls='solid'):
    pts = np.array(pts, float)
    ax.add_collection3d(Line3DCollection([list(zip(pts[:-1], pts[1:]))][0], colors=col, linewidths=lw, zorder=z, capstyle='round', linestyles=ls))

def shade(m, base, alpha):
    s = np.clip(m.face_normals @ L, 0, 1)*0.6 + 0.4
    c = np.clip(np.outer(s, base), 0, 1)
    return np.column_stack([c, np.full(len(c), alpha)])

# ---- parts (body coords, from the CAD layout) ----
SWITCH = (4.0,44.5,12.7,48.5,5.35,9.05); LEVER = (7.0,48.5,8.4,51.0,6.5,7.9)
BATT = (4.0,3.2,36.0,28.2,3.0,11.0)
JST_P = (1.6,33.2,5.8,37.8,1.6,4.9)   # pigtail half (on the XIAO wires)
JST_B = (1.6,28.6,5.8,33.2,1.6,4.9)   # battery half
XIAO_LAYERS = [((17.4,29.4,38.4,47.2,3.0,3.9),(0.12,0.13,0.15)),   # main PCB
               ((22.0,33.0,33.0,44.0,3.9,6.2),(0.78,0.79,0.82)),   # shield can
               ((35.8,35.6,39.6,41.0,4.3,7.5),(0.80,0.82,0.86)),   # USB-C
               ((17.4,29.4,38.4,47.2,9.4,10.3),(0.12,0.13,0.15)),  # Sense board
               ((19.0,31.0,30.0,45.0,10.3,11.3),(0.80,0.82,0.86))] # SD slot
# pads on the XIAO underside and their lanes through the gap (y35..42)
Z_UNDER = 2.25
XW = {  # name: (pad xy, lane y, colour)
 'D3':  ((27.8,46.4), 41.0, '#e8730c'),
 'D1':  ((32.9,46.4), 40.0, '#1f6fd6'),
 'B+':  ((27.8,43.4), 38.9, '#d32f2f'),
 'B-':  ((30.3,43.4), 37.8, '#1b1d22'),
 'GND': ((32.9,30.2), 36.6, '#1b1d22'),
}
def under(name, dz):   # segment under the board, attached to it
    (px,py), lane, _ = XW[name]; z = Z_UNDER + dz
    return [(px,py,z+0.6),(px,py,z),(px,lane,z),(17.4,lane,z)]
def outside(name, dz, led_pt):
    (px,py), lane, _ = XW[name]; z = Z_UNDER + dz
    start = [(17.4,lane,z),(15.6,lane,Z_UNDER+min(dz,4)),(13.0,lane,2.4)]
    if name == 'D1':  return start + [(11.0,40.6,4.2),(8.35,41.6,6.0)]
    if name == 'GND': return start + [(11.0,39.4,4.0),(5.8,41.6,6.0)]
    if name in ('B+','B-'):
        x = 3.2 if name=='B+' else 4.2
        return start + [(9.0,39.3,2.6),(x+0.6,38.6,3.2),(x,37.8,3.3)]
    if name == 'D3':
        return start + [(10.6,37.0,4.6)] + led_path(led_pt)
def led_path(led_pt):
    x,y,z = led_pt
    if x < 3.0:   # lid open on the left: wires go over the left wall
        return [(3.0,36.0,12.0),(1.0,36.0,14.6),(min(x+2,-1),y,max(z,13.5)),(x,y,z)]
    return [(x,y,z)]
LED_BLACK_TO = [(5.2,41.4,6.2),(5.0,38.6,7.5)]

# ---- lid (closed = 0 deg, open = 180 deg about the left edge x=0, z=BODY_D) ----
def lid_xf(theta):
    th = np.radians(theta)
    def f(c):
        c = c.copy(); x = c[:,0]; z = c[:,2]-BODY_D
        c[:,0] = x*np.cos(th) - z*np.sin(th)
        c[:,2] = x*np.sin(th) + z*np.cos(th) + BODY_D
        return c
    return f
LID = (0.0,0.0,40.0,49.4,BODY_D,BODY_D+LID_T)
LIP = (1.75,1.75,2.75,47.65,10.6,BODY_D)
LEDB = (6.9,34.7,9.5,37.3,7.6,BODY_D)
LED_FOOT = np.array([[8.2,34.0,7.4]])

def render(st, title, inset=False):
    fig = plt.figure(figsize=(10,6.4), dpi=100)
    ax = fig.add_axes([0.0,0.0,0.66,0.90], projection='3d', computed_zorder=False)
    ax.add_collection3d(Poly3DCollection(body.triangles, facecolors=shade(body,(0.36,0.48,0.66),0.26), edgecolor='none', zorder=1))
    th = st.get('lid_th', 180.0); xf = lid_xf(th)
    led_pt = tuple(xf(LED_FOOT)[0])
    if st.get('switch') is not None:
        dz = st['switch']; draw_box(ax, SWITCH, (0.78,0.79,0.82), dz, z=5); draw_box(ax, LEVER, (0.15,0.15,0.16), dz, z=5)
    dzx = st.get('xiao')
    if dzx is not None:
        # wires under the board first, then the translucent board, then the outside runs
        zled = 9 if led_pt[0] < 3 else 4.5
        for n in XW:
            o = outside(n, dzx, led_pt)
            if n == 'D3':
                tube(ax, o[:4], XW[n][2], 4.5); tube(ax, o[3:], XW[n][2], zled)
            else:
                tube(ax, o, XW[n][2], 4.5)
        if led_pt[0] < 3: tube(ax, [led_pt, (min(led_pt[0]+2,-1),led_pt[1],max(led_pt[2],13.5)), (1.0,37.2,14.6), (3.0,37.4,12.0)] + LED_BLACK_TO[::-1], '#1b1d22', zled)
        else: tube(ax, [led_pt] + LED_BLACK_TO[::-1], '#1b1d22', 4.5)
        for n in XW: tube(ax, under(n, dzx), XW[n][2], 3.5, 3.6, (0,(1.4,1.0)))
        for (b,c) in XIAO_LAYERS: draw_box(ax, b, c, dzx, alpha=0.16, z=3, edge=0.6)
        if inset:
            ax.text(30.0, 52.0, 14.0+dzx, '点線 = XIAO の下を通る線', fontsize=11, zorder=10)
        draw_box(ax, JST_P, (0.95,0.95,0.92), 0 if st.get('jst') is not None else 0, z=5)
    if st.get('batt') is not None:
        dz = st['batt']; draw_box(ax, BATT, (0.74,0.76,0.82), dz, z=4)
        draw_box(ax, (4.0,8.0,6.0,23.0,3.0,11.0), (0.95,0.80,0.25), dz, z=4)   # PCM tape
        if st.get('jst') is not None:
            dj = st['jst']
            draw_box(ax, JST_B, (0.95,0.95,0.92), dj, z=5)
            for x,col in ((3.2,'#d32f2f'),(4.2,'#1b1d22')):
                tube(ax, [(4.0,15.5 + (x-3.2),7.0+dz),(2.6+ (x-3.2)*0.5,15.5,7.0),(2.6+(x-3.2)*0.5,26.0,5.0),(x,28.6+dj,3.3+dj)], col, 6, 3.2)
    # lid with LED
    draw_box(ax, LEDB, (0.9,0.15,0.15), xf=xf, z=7)
    draw_box(ax, LIP, (0.24,0.26,0.30), xf=xf, z=7)
    draw_box(ax, LID, (0.24,0.26,0.30), xf=xf, alpha=0.96 if th < 60 else 0.85, z=8)
    ax.set_xlim(-22,46); ax.set_ylim(-4,54); ax.set_zlim(0,30)
    ax.set_box_aspect((68,58,30), zoom=1.32); ax.view_init(48,-66); ax.set_axis_off()
    fig.text(0.03,0.94,title,fontsize=17)
    if inset:
        a2 = fig.add_axes([0.665,0.30,0.32,0.40]); a2.set_xlim(0,44); a2.set_ylim(-9,16); a2.set_aspect('equal'); a2.axis('off')
        a2.add_patch(Rectangle((0,0),40,1.6,fc=(0.55,0.65,0.8),ec='k',lw=0.8))
        for x in (4,32): a2.add_patch(Rectangle((x,1.6),3,1.4,fc=(0.55,0.65,0.8),ec='k',lw=0.8))
        a2.add_patch(Rectangle((3,3.0),34,0.9,fc=(0.15,0.15,0.17),ec='k'))
        a2.add_patch(Rectangle((9,3.9),14,2.3,fc=(0.8,0.8,0.83),ec='k',lw=0.6))
        a2.add_patch(Rectangle((3,9.4),34,0.9,fc=(0.15,0.15,0.17),ec='k'))
        for i,c in enumerate(['#e8730c','#1f6fd6','#d32f2f','#1b1d22','#1b1d22']):
            a2.add_patch(Circle((13+i*2.6,2.25),0.62,fc=c,ec='k',lw=0.5))
        a2.text(0,14.2,'断面（XIAO を横から）',fontsize=11)
        a2.text(0,-5.6,'線 5本は XIAO の下に 1列。\n重ねると基板が浮く',fontsize=10)
        a2.text(24.5,7.0,'XIAO',fontsize=9); a2.text(24.5,10.9,'拡張ボード',fontsize=8)
        a2.text(37.5,0.0,'床',fontsize=8); a2.text(37.5,2.0,'1.4mm',fontsize=8)
    fig.canvas.draw()
    im = Image.frombuffer('RGBA', fig.canvas.get_width_height(), fig.canvas.buffer_rgba()).convert('RGB')
    plt.close(fig); return im

def ease(t): return 0.5-0.5*np.cos(np.pi*min(max(t,0),1))
frames=[]; st={}
def hold(title, ms, inset=False): frames.append((render(st,title,inset), ms))
def move(key, a, b, title, n=12, inset=False):
    for f in range(n):
        st[key] = a + (b-a)*ease((f+1)/n); frames.append((render(st,title,inset), 70))

hold('0. 空の本体（USB の穴が右、マイク穴が奥）。フタは左に置いておく', 1600)
st['switch']=22.0; move('switch', 22.0, 0.0, '1. スイッチを上の壁のくぼみにはめる'); hold('1. スイッチを上の壁のくぼみにはめる', 1000)
t2 = '2. XIAO を四隅の台へ。5本の線は XIAO の下を通り、柱のすき間から出る'
st['xiao']=16.0; hold(t2, 1200, True); move('xiao', 16.0, 0.0, t2, 16, True); hold(t2, 2600, True)
t3 = '3. 電池を左の柱に突き当てて置く（右の壁との間は約2.4mmあける）'
st['batt']=20.0; move('batt', 20.0, 0.0, t3); hold(t3, 1200)
t4 = '4. 電池をつなぎ、JST を左の壁に縦に寝かせる（上に何も載せない）'
st['jst']=10.0; move('jst', 10.0, 0.0, t4, 10); hold(t4, 1400)
t5 = '5. フタを左の辺から掛けて、下の辺を押してパチン'
st['lid_th']=180.0; move('lid_th', 180.0, 0.0, t5, 22); hold('完成', 2400)

imgs=[f[0].quantize(colors=160, method=Image.Quantize.MEDIANCUT) for f in frames]
out = R + 'renders/allday/assembly.gif'
imgs[0].save(out, save_all=True, append_images=imgs[1:], duration=[f[1] for f in frames], loop=0, optimize=True)
print(out, len(imgs))
