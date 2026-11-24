# 組み込み手順のアニメーション GIF を作る（hardware/renders/allday/assembly.gif）。
# 先に cad/mindclip_case.py を実行して STL を作っておくこと。依存: trimesh matplotlib pillow、日本語フォント IPAGothic。
import sys, glob, numpy as np, trimesh, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams
from mpl_toolkits.mplot3d.art3d import Poly3DCollection, Line3DCollection
from PIL import Image
rcParams['font.family'] = 'IPAGothic'
R = '/home/user/claude-code-book-template/hardware/'
body = trimesh.load_mesh(R + 'stl/allday/mindclip_phonebody.stl')
lid = trimesh.load_mesh(R + 'stl/allday/mindclip_lid.stl')
H, BODY_D, LID_T = 49.4, 12.8, 1.8
lid.apply_transform(np.array([[1,0,0,0],[0,-1,0,H],[0,0,-1,BODY_D+LID_T],[0,0,0,1]], float))
L = np.array([0.35,-0.5,0.8]); L /= np.linalg.norm(L)

def box_quads(b, dz=0.0):
    x0,y0,x1,y1,z0,z1 = b[0],b[1],b[2],b[3],b[4]+dz,b[5]+dz
    P=lambda x,y,z:(x,y,z)
    return [[P(x0,y0,z1),P(x1,y0,z1),P(x1,y1,z1),P(x0,y1,z1)],  # top
            [P(x0,y0,z0),P(x1,y0,z0),P(x1,y0,z1),P(x0,y0,z1)],  # front (y0)
            [P(x1,y0,z0),P(x1,y1,z0),P(x1,y1,z1),P(x1,y0,z1)],  # right
            [P(x0,y1,z0),P(x1,y1,z0),P(x1,y1,z1),P(x0,y1,z1)],  # back
            [P(x0,y0,z0),P(x0,y1,z0),P(x0,y1,z1),P(x0,y0,z1)]]  # left
SH = [1.0, 0.72, 0.85, 0.6, 0.65]
def draw_box(ax, b, base, dz=0.0, alpha=1.0, z=3):
    q = box_quads(b, dz)
    cols = [tuple(min(1,c*s) for c in base)+(alpha,) for s in SH]
    order = [3,4,1,2,0]   # far faces first, top last
    ax.add_collection3d(Poly3DCollection([q[i] for i in order], facecolors=[cols[i] for i in order], edgecolors=(0,0,0,0.5), linewidths=0.6, zorder=z))
def box_tris(b):
    x0,y0,z0,x1,y1,z1 = b[0],b[1],b[4],b[2],b[3],b[5]
    m = trimesh.creation.box(extents=[x1-x0,y1-y0,z1-z0])
    m.apply_translation([(x0+x1)/2,(y0+y1)/2,(z0+z1)/2]); return m

parts = {
 'switch': ((4.0,44.5,12.7,48.5,5.35,9.05), (0.70,0.72,0.76)),
 'xiao':   ((17.4,29.4,38.4,47.2,3.0,11.3), (0.20,0.22,0.26)),
 'batt':   ((4.0,3.2,36.0,28.2,3.0,11.0),   (0.72,0.74,0.80)),
 'jst':    ((1.6,28.6,5.8,37.8,1.6,4.9),    (0.96,0.96,0.94)),
}
meshes = {k:(box_tris(v[0]),v[1]) for k,v in parts.items()}
usb = box_tris((35.8,34.6,39.6,42.0,4.9,8.1)); 
led = trimesh.creation.cylinder(radius=1.5, height=5.0); led.apply_translation([8.2,36.0,BODY_D-2.5])

def shade(m, base, alpha=1.0):
    s = np.clip(m.face_normals @ L, 0, 1)*0.6 + 0.4
    c = np.clip(np.outer(s, base), 0, 1)
    return np.column_stack([c, np.full(len(c), alpha)])

def lines(seg):  # list of polylines -> segments
    out=[]
    for pl in seg:
        for a,b in zip(pl[:-1],pl[1:]): out.append([a,b])
    return out
W_XIAO = [  # wires from switch / LED / JST to the rib gap and under the XIAO
 ([(8.0,42.0,7.0),(12.0,40.5,4.0),(16.0,40.0,2.2),(30.0,44.0,2.2)], '#1f6fd6'),
 ([(8.2,33.0,6.0),(12.0,36.5,3.5),(16.0,37.0,2.2),(27.8,44.0,2.2)], '#e8730c'),
 ([(6.5,42.0,7.0),(12.0,38.8,3.5),(16.0,38.6,2.2),(32.8,31.0,2.2)], '#15181d'),
]
W_BATT = [([(3.0,37.8,3.0),(11.0,39.4,3.0),(16.0,36.0,2.2),(28.5,43.0,2.2)], '#d32f2f'),
          ([(3.8,37.8,3.0),(11.5,38.9,3.0),(16.0,36.4,2.2),(29.6,43.0,2.2)], '#15181d')]
W_LEAD = [([(4.0,16.0,7.0),(2.8,16.0,7.0),(2.8,27.0,6.0),(2.8,28.6,3.0)], '#d32f2f')]

steps = [
 ('0. 空の本体（USB の穴が右、マイク穴が奥）', []),
 ('1. スイッチを上の壁のくぼみにはめる', ['switch']),
 ('2. XIAO を四隅の台に載せる。線 5本は柱のすき間から下へ', ['xiao']),
 ('3. 電池を左の柱に突き当てて置く（右に約2.4mmあける）', ['batt']),
 ('4. 電池をつなぎ、JST を左の壁に縦に寝かせる', ['jst']),
 ('5. フタを左上の角から掛けて、下の辺をパチン', ['lid']),
]
order = ['switch','xiao','batt','jst','lid']
def ease(t): return 0.5-0.5*np.cos(np.pi*min(max(t,0),1))

frames=[]
FR_MOVE, FR_HOLD = 12, 8
def render(state, title):
    fig = plt.figure(figsize=(8,6), dpi=100)
    ax = fig.add_subplot(111, projection='3d', computed_zorder=False)
    ax.add_collection3d(Poly3DCollection(body.triangles, facecolors=shade(body,(0.36,0.48,0.66),0.28), edgecolor='none', zorder=1))
    for k in ['switch','xiao','batt','jst']:
        off = state.get(k)
        if off is None: continue
        draw_box(ax, parts[k][0], parts[k][1], off)
        if k=='xiao':
            draw_box(ax, (35.8,34.6,39.6,42.0,4.9,8.1), (0.78,0.8,0.84), off)
    wires=[]
    if state.get('xiao') is not None and state['xiao']<0.5: wires += W_XIAO
    if state.get('jst') is not None and state['jst']<0.5: wires += W_BATT + W_LEAD
    for pl,col in wires:
        ax.add_collection3d(Line3DCollection(lines([pl]), colors=col, linewidths=3.2, zorder=2))
    off = state.get('lid')
    if off is not None:
        draw_box(ax, (7.2,35.0,9.2,37.0,BODY_D-4.5,BODY_D), (0.9,0.2,0.2), off, 1.0, 5)
        draw_box(ax, (0.0,0.0,40.0,49.4,BODY_D,BODY_D+LID_T), (0.26,0.29,0.34), off, 0.97, 6)
    ax.set_xlim(-6,46); ax.set_ylim(-5,54); ax.set_zlim(0,38)
    ax.set_box_aspect((52,59,38), zoom=1.45); ax.view_init(48,-64); ax.set_axis_off()
    fig.text(0.03,0.94,title,fontsize=17)
    fig.subplots_adjust(0,0,1,0.95)
    fig.canvas.draw()
    im = Image.frombuffer('RGBA', fig.canvas.get_width_height(), fig.canvas.buffer_rgba()).convert('RGB')
    plt.close(fig); return im

state={}
frames.append((render(state, steps[0][0]), 1500))
for i,k in enumerate(order):
    title = steps[i+1][0]
    for f in range(FR_MOVE):
        t = ease((f+1)/FR_MOVE)
        state[k] = (1-t)*(14.0 if k=='lid' else 22.0)
        frames.append((render(state,title), 70))
    state[k]=0.0
    frames.append((render(state,title), 1400))
frames.append((render(state,'完成'), 2200))
imgs=[f[0].quantize(colors=128, method=Image.Quantize.MEDIANCUT) for f in frames]
out = R + 'renders/allday/assembly.gif'
imgs[0].save(out, save_all=True, append_images=imgs[1:], duration=[f[1] for f in frames], loop=0, optimize=True)
print(out, len(imgs))
