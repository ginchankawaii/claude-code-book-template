#!/usr/bin/env python3
"""IPv6/IPoE 勉強会「虎の巻」PowerPoint 生成スクリプト

  usage: pip install python-pptx && python3 build-toranomaki.py [出力パス]

内容の正本は docs/ipoe-lab/study-guide.md。本スクリプトはそれを
プレゼン形式に落としたもの。内容を直す場合は study-guide.md も併せて直すこと。

フォントは Windows 標準の「Meiryo UI」を指定している (会社 PC で開く前提)。
Mac/Linux で開く場合は自動で代替フォントになる。
"""
import sys
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR

FONT = "Meiryo UI"
NAVY = RGBColor(0x1F, 0x33, 0x55)
ACCENT = RGBColor(0x00, 0x7A, 0xCC)
WARN = RGBColor(0xC0, 0x39, 0x2B)
GRAY = RGBColor(0x55, 0x55, 0x55)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

OUT = sys.argv[1] if len(sys.argv) > 1 else "toranomaki.pptx"


def _run(paragraph, text):
    """段落に run を追加してテキストを入れる (add_run() は引数を取らない)"""
    r = paragraph.add_run()
    r.text = text
    return r


def _style(run, size, bold=False, color=NAVY):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color


def _put(paragraph, text, size, bold=False, color=NAVY, align=PP_ALIGN.LEFT):
    if align is not None:
        paragraph.alignment = align
    r = _run(paragraph, text)
    _style(r, size, bold, color)
    return r


def _textbox(slide, x, y, w, h):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tb.text_frame.word_wrap = True   # 未指定だと箱が自動縮小され中央寄せに見える
    return tb


def title_slide(prs, title, subtitle, lines):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    band = _textbox(s, 0.6, 1.6, 12.1, 1.4)
    tf = band.text_frame
    _put(tf.paragraphs[0], title, 40, True, NAVY)
    p = tf.add_paragraph()
    _put(p, subtitle, 18, False, ACCENT)

    box = s.shapes.add_textbox(Inches(0.7), Inches(3.4), Inches(12.0), Inches(3.0))
    tf = box.text_frame
    tf.word_wrap = True
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        _put(p, ln, 14, False, GRAY)
        p.space_after = Pt(8)
    return s


def section_slide(prs, num, title, goal):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(7.5))
    bg.fill.solid()
    bg.fill.fore_color.rgb = NAVY
    bg.line.fill.background()
    box = _textbox(s, 1.0, 2.4, 11.3, 2.6)
    tf = box.text_frame
    tf.word_wrap = True
    _put(tf.paragraphs[0], num, 20, True, RGBColor(0x7F, 0xB8, 0xE0))
    p = tf.add_paragraph()
    _put(p, title, 36, True, WHITE)
    p = tf.add_paragraph()
    p.space_before = Pt(16)
    _put(p, "ゴール: " + goal, 16, False, RGBColor(0xD5, 0xE5, 0xF2))
    return s


def bullet_slide(prs, title, bullets, footer=None):
    """bullets: [(indent, text, style)] style: '' / 'b'(太字) / 'w'(警告赤) / 'c'(コード)"""
    s = prs.slides.add_slide(prs.slide_layouts[6])
    tb = _textbox(s, 0.55, 0.35, 12.2, 0.9)
    _put(tb.text_frame.paragraphs[0], title, 28, True, NAVY)
    rule = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.55), Inches(1.22), Inches(12.2), Pt(2.5))
    rule.fill.solid()
    rule.fill.fore_color.rgb = ACCENT
    rule.line.fill.background()

    box = _textbox(s, 0.65, 1.5, 12.0, 5.3)
    tf = box.text_frame
    tf.word_wrap = True
    for i, (ind, text, st) in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.level = ind
        size = 20 - 3 * ind
        color, bold = NAVY if ind == 0 else GRAY, False
        if st == "b":
            bold = True
        elif st == "w":
            color, bold = WARN, True
        elif st == "c":
            color = RGBColor(0x0B, 0x60, 0x40)
        r = _put(p, text, size, bold, color)
        if st == "c":
            r.font.name = "Consolas"
        p.space_after = Pt(7 if ind == 0 else 4)

    if footer:
        fb = _textbox(s, 0.65, 6.85, 12.0, 0.5)
        _put(fb.text_frame.paragraphs[0], footer, 12, False, ACCENT)
    return s


def qa_slide(prs, wall_no, question, answer, dissent=None, ref=None):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    tb = _textbox(s, 0.55, 0.3, 12.2, 0.7)
    _put(tb.text_frame.paragraphs[0], f"つまずきの壁 {wall_no}", 22, True, ACCENT)

    y = 1.05
    # 生徒
    qb = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.55), Inches(y), Inches(12.2), Inches(1.05))
    qb.fill.solid()
    qb.fill.fore_color.rgb = RGBColor(0xEF, 0xF5, 0xFA)
    qb.line.color.rgb = ACCENT
    tf = qb.text_frame
    tf.word_wrap = True
    tf.margin_left, tf.margin_top = Inches(0.18), Inches(0.1)
    p = tf.paragraphs[0]
    _put(p, "生徒: ", 16, True, ACCENT)
    _put(p, question, 16, False, NAVY)

    y += 1.3
    ab = _textbox(s, 0.7, y, 12.0, 3.0)
    tf = ab.text_frame
    tf.word_wrap = True
    for i, ln in enumerate(answer):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        if i == 0:
            _put(p, "先生: ", 16, True, NAVY)
            _put(p, ln, 16, False, NAVY)
        else:
            p.level = 1
            _put(p, ln, 14, False, GRAY)
        p.space_after = Pt(6)

    if dissent:
        db = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.7), Inches(5.05), Inches(11.9), Inches(1.15))
        db.fill.solid()
        db.fill.fore_color.rgb = RGBColor(0xFD, 0xF1, 0xEF)
        db.line.color.rgb = WARN
        tf = db.text_frame
        tf.word_wrap = True
        tf.margin_left, tf.margin_top = Inches(0.18), Inches(0.08)
        p = tf.paragraphs[0]
        _put(p, "対立意見(懐疑的な同僚): ", 13, True, WARN)
        _put(p, dissent, 13, False, GRAY)

    if ref:
        fb = _textbox(s, 0.7, 6.45, 11.9, 0.6)
        tf = fb.text_frame
        tf.word_wrap = True
        _put(tf.paragraphs[0], "教科書 / ラボ: " + ref, 12, False, ACCENT)
    return s


def table_slide(prs, title, headers, rows, widths, footer=None, fsize=12):
    """セルの値が "!" で始まると、その 1 セルだけ赤の太字で強調する ("!" は表示されない)"""
    s = prs.slides.add_slide(prs.slide_layouts[6])
    tb = _textbox(s, 0.55, 0.3, 12.2, 0.8)
    _put(tb.text_frame.paragraphs[0], title, 26, True, NAVY)

    nrow, ncol = len(rows) + 1, len(headers)
    h = min(5.7, 0.42 * nrow)
    gf = s.shapes.add_table(nrow, ncol, Inches(0.55), Inches(1.25), Inches(12.2), Inches(h))
    tbl = gf.table
    tbl.first_row = False
    tbl.last_row = False
    tbl.first_col = False
    tbl.last_col = False
    tbl.horz_banding = False
    tbl.vert_banding = False
    for i, w in enumerate(widths):
        tbl.columns[i].width = Inches(w)
    for c, htxt in enumerate(headers):
        cell = tbl.cell(0, c)
        cell.text = ""
        _put(cell.text_frame.paragraphs[0], htxt, fsize + 1, True, WHITE)
        cell.fill.solid()
        cell.fill.fore_color.rgb = NAVY
    for r, row in enumerate(rows, start=1):
        for c, val in enumerate(row):
            cell = tbl.cell(r, c)
            cell.text = ""
            p = cell.text_frame.paragraphs[0]
            warn = val.startswith("!")
            _put(p, val.lstrip("!"), fsize, warn, WARN if warn else NAVY)
            cell.fill.solid()
            cell.fill.fore_color.rgb = WHITE if r % 2 else RGBColor(0xF2, 0xF6, 0xFA)
    if footer:
        fb = _textbox(s, 0.55, 1.35 + h, 12.2, 0.6)
        tf = fb.text_frame
        tf.word_wrap = True
        _put(tf.paragraphs[0], footer, 12, False, ACCENT)
    return s


def branch_slide(prs, title, root, left, right, note=None):
    """root から left / right へ分岐する図。root/left/right は (label, sublabel)"""
    s = prs.slides.add_slide(prs.slide_layouts[6])
    tb = _textbox(s, 0.55, 0.3, 12.2, 0.8)
    _put(tb.text_frame.paragraphs[0], title, 26, True, NAVY)

    def _box(x, y, w, h, label, sub, color):
        sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
        sh.fill.solid()
        sh.fill.fore_color.rgb = RGBColor(0xEF, 0xF5, 0xFA)
        sh.line.color.rgb = color
        sh.line.width = Pt(1.75)
        tf = sh.text_frame
        tf.word_wrap = True
        _put(tf.paragraphs[0], label, 15, True, NAVY, PP_ALIGN.CENTER)
        _put(tf.add_paragraph(), sub, 11, False, GRAY, PP_ALIGN.CENTER)
        return sh

    _box(5.0, 1.3, 3.3, 1.0, root[0], root[1], NAVY)
    _box(1.3, 3.2, 4.6, 1.2, left[0], left[1], ACCENT)
    _box(7.4, 3.2, 4.6, 1.2, right[0], right[1], ACCENT)
    def _line(x1, y1, x2, y2):
        cn = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
        cn.line.color.rgb = ACCENT
        cn.line.width = Pt(2.5)

    _line(6.65, 2.3, 6.65, 2.75)          # 分岐点から下へ
    _line(3.6, 2.75, 9.7, 2.75)           # 横に伸ばす
    _line(3.6, 2.75, 3.6, 3.2)            # 左の箱へ
    _line(9.7, 2.75, 9.7, 3.2)            # 右の箱へ

    if note:
        nb = _textbox(s, 0.75, 4.75, 11.8, 2.0)
        tf = nb.text_frame
        tf.word_wrap = True
        for i, ln in enumerate(note):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            _put(p, ln, 14, ln.startswith("※"), WARN if ln.startswith("※") else GRAY)
            p.space_after = Pt(6)
    return s


def diagram_slide(prs, title, boxes, note=None):
    """boxes: [(label, sublabel)] を横一列に並べて矢印でつなぐ"""
    s = prs.slides.add_slide(prs.slide_layouts[6])
    tb = _textbox(s, 0.55, 0.3, 12.2, 0.8)
    _put(tb.text_frame.paragraphs[0], title, 26, True, NAVY)

    n = len(boxes)
    bw = 11.8 / n * 0.82
    gap = (11.8 - bw * n) / max(1, n - 1)
    x = 0.75
    for i, (label, sub) in enumerate(boxes):
        sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(2.6), Inches(bw), Inches(1.5))
        sh.fill.solid()
        sh.fill.fore_color.rgb = RGBColor(0xEF, 0xF5, 0xFA)
        sh.line.color.rgb = ACCENT
        sh.line.width = Pt(1.75)
        tf = sh.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        _put(p, label, 15, True, NAVY, PP_ALIGN.CENTER)
        p2 = tf.add_paragraph()
        _put(p2, sub, 11, False, GRAY, PP_ALIGN.CENTER)
        if i < n - 1:
            ar = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x + bw), Inches(3.2), Inches(gap), Inches(0.32))
            ar.fill.solid()
            ar.fill.fore_color.rgb = ACCENT
            ar.line.fill.background()
        x += bw + gap

    if note:
        nb = _textbox(s, 0.75, 4.5, 11.8, 2.0)
        tf = nb.text_frame
        tf.word_wrap = True
        for i, ln in enumerate(note):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            _put(p, ln, 14, ln.startswith("※"), WARN if ln.startswith("※") else GRAY)
            p.space_after = Pt(6)
    return s


def build():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)

    # ---------------- 表紙 ----------------
    title_slide(
        prs,
        "IPv6 / IPoE 虎の巻",
        "PPPoE → IPoE 切替でトラブらないための 3 回シリーズ",
        [
            "対象: IPv6 をほとんど触ったことがない若手 (支店配属 1〜3 年目想定)",
            "教科書: 小川晃通『プロフェッショナル IPv6 第2版』(ラムダノート / CC BY-NC-SA)",
            "検証環境: 社内 IPoE 検証ラボ (docs/ipoe-lab/, lab/ipoe/)",
            "",
            "進め方: ラボで壊す → 「なんで?」が生まれる → 教科書の該当節を読む → もう一度ラボ",
        ],
    )

    bullet_slide(
        prs,
        "この勉強会の目的",
        [
            (0, "PPPoE → IPoE 切替案件が増えている。しかしトラブルも増えている", "b"),
            (1, "組み合わせが多い: IPv6 配布方式 × IPv4 over IPv6 方式 × CPE 機種 × 構成", ""),
            (1, "「やってみたら動かない」を客先で起こしている", "w"),
            (0, "原因は知識の欠落ではなく、原理を見たことがないこと", "b"),
            (1, "RA も DHCPv6-PD も MAP-E も、パケットを一度見れば腹に落ちる", ""),
            (1, "だから「検証環境 × 教科書」でやる。座学だけ / 手順書だけ、では身に付かない", ""),
            (0, "3 回終わったときにできるようになること", "b"),
            (1, "ひかり電話の有無から設定方式を理由付きで選べる", ""),
            (1, "「ポート開放できますか?」に方式を聞いて即答できる", ""),
            (1, "「Web は見えるがファイルが送れない」を最初の一手で切り分けられる", ""),
        ],
        footer="正本: docs/ipoe-lab/study-guide.md",
    )

    table_slide(
        prs,
        "全体の流れ",
        ["回", "テーマ", "教科書", "ラボ"],
        [
            ["第1回", "なんで IPv6 に変えなきゃいけないの?", "1, 2, 18章", "Phase 0"],
            ["第2回", "アドレスはどうやって降ってくるのか (最重要)", "6, 7, 8章", "Phase 1"],
            ["第3回", "IPv4 を IPv6 の上で運ぶ", "21, 22, 24章", "Phase 2/3, R3, R4"],
            ["補講", "セキュリティ / DNS / NGN 固有問題", "14, 16, 17章, 付録A", "R6, R13"],
        ],
        [1.1, 6.3, 2.4, 2.4],
        footer="全回で参照: 付録 A「NTT NGN での IPv6」(p.437) — 日本固有の話が全部ここにある",
        fsize=13,
    )

    # ---------------- 第1回 ----------------
    section_slide(prs, "第1回", "なんで IPv6 に変えなきゃいけないの?",
                  "「グローバルが1個、リンクローカルが1個、テンポラリが1個」と言えるようになる")

    bullet_slide(
        prs,
        "1-1. まず事実: IPv4 アドレスは在庫が尽きた",
        [
            (0, "IPv4 は約 43 億個。世界人口より少ない。スマホ 1 人 1 台で足りない", ""),
            (0, "だから 3 つの対策が同時に走っている", "b"),
            (1, "① NAT で共有する → 家庭内では昔からやっている", ""),
            (1, "② アドレスを売買・移転する → 実際に市場がある", ""),
            (1, "③ IPv6 に移る → 本命", ""),
            (0, "IPoE への切替は ③ の話。「速いから」は結果であって理由ではない", "w"),
            (0, "教科書: 18.1 在庫枯渇はどのような問題なのか (p.335) / 18.2 影響 (p.336)", ""),
            (1, "余裕があれば 18.5 IPv4 アドレス移転・売買・市場 (p.343)", ""),
        ],
    )

    bullet_slide(
        prs,
        "1-2. IPv6 アドレスの書き方 (ここで演習)",
        [
            (0, "128 ビット。16 進 4 桁を 8 ブロック、コロン区切り", ""),
            (1, "2001:0db8:1014:0300:0000:0000:0000:0001", "c"),
            (0, "省略ルールは 2 つだけ", "b"),
            (1, "① 各ブロック先頭の 0 は省略できる → 0db8 は db8、0300 は 300", ""),
            (1, "② 連続する 0 のブロックは :: に潰せる。ただし 1 箇所だけ", ""),
            (1, "2001:db8:1014:300::1", "c"),
            (0, "演習: 次を省略形にせよ (5 分、紙に書く)", "b"),
            (1, "fe80:0000:0000:0000:0200:5eff:fe00:5301", "c"),
            (1, "2001:0db8:0000:0000:0000:0000:8888:0001", "c"),
            (1, "2001:0db8:100a:0500:0000:0000:0000:0000", "c"),
            (0, "教科書: 2.2 IPv6 アドレスのテキスト表記 (p.38)", ""),
        ],
        footer="※ 答え合わせは講師が板書。ここを飛ばすと第2回以降ずっと読めないまま進む",
    )

    diagram_slide(
        prs,
        "1-3. IPv6 と IPv4 は「別のインターネット」",
        [("IPv4 の世界", "203.0.113.x"), ("互換性なし", "直接は話せない"), ("IPv6 の世界", "2001:db8::x")],
        [
            "IPv4 と IPv6 の間に自動変換はない。だから両方を同時に使う (デュアルスタック) か、",
            "どちらかを他方の上で運ぶ (共存技術) しかない。IPoE がやっているのは後者。",
            "※ 「IPv6 にしたら IPv4 が使えなくなる」は誤り。IPv6 のトンネルの中を通って使える。",
            "教科書: 2.10 IPv6 と IPv4 の違い (p.51) / 2.12 同時に使う (p.58) / 2.13 共存技術 (p.61)",
        ],
    )

    bullet_slide(
        prs,
        "1-4. ラボ演習 Phase 0 — つないで数える (25分)",
        [
            (0, "手順", "b"),
            (1, "1. クライアント VM から PPPoE でつなぐ (従来方式の状態を先に見る)", ""),
            (1, "2. ip -6 addr show", "c"),
            (1, "3. 出てきた IPv6 アドレスを種類ごとに数える", ""),
            (0, "見てほしいこと: 1 つの NIC に IPv6 アドレスが何個も付いている", "b"),
            (1, "fe80:: で始まる → リンクローカル。同じリンク内専用。消すと全部死ぬ", ""),
            (1, "2001: で始まる → グローバル。外と話せる", ""),
            (1, "もう 1 つグローバルがある → Temporary (プライバシー拡張)。定期的に変わる", ""),
            (0, "IPv4 の常識「1 NIC = 1 アドレス」がまず崩れる。ここが IPv6 の入口", "w"),
            (0, "教科書: 2.9 複数の IPv6 アドレスが設定される (p.48) / 3.5 リンクローカル (p.74)", ""),
            (1, "深掘り: 7.5 Temporary IPv6 アドレス (p.166) / 7.8 存続期間とステート (p.173)", ""),
        ],
        footer="宿題: 自宅回線のルータ / PC で IPv6 アドレスを見てきて、種類を数えて次回報告",
    )

    # ---------------- 第2回 ----------------
    section_slide(prs, "第2回", "アドレスはどうやって降ってくるのか",
                  "「ひかり電話あり = PD で /56、なし = RA で /64」を理由付きで説明できる")

    bullet_slide(
        prs,
        "2-1. IPoE とは何か (用語の整理から)",
        [
            (0, "IPoE = IP over Ethernet。PPP を挟まずに Ethernet に直接 IP を載せる方式", "b"),
            (1, "NTT の商品名ではない。接続方式の名前", "w"),
            (0, "PPPoE との違い", "b"),
            (1, "PPPoE: ID/パスワードでセッションを張る → 網終端装置 (NTE) を必ず通る", ""),
            (1, "IPoE: つないだらアドレスが降ってくる → NTE を通らない", ""),
            (0, "「IPoE は速い」の正体", "b"),
            (1, "プロトコルが速いのではなく、混雑する箱 (NTE) を通らないから", ""),
            (1, "※ VNE 側が混んでいれば普通に遅い。「速くなります」と客に約束しない", "w"),
            (0, "教科書: 付録 A.3 IPv6 PPPoE と IPv6 IPoE (p.443) ← 付箋を貼る", ""),
        ],
    )

    bullet_slide(
        prs,
        "2-2. 近隣探索プロトコル — IPv6 の心臓部",
        [
            (0, "IPv6 に ARP はない。代わりに ICMPv6 の 4 兄弟が働く", "b"),
            (1, "RS (Router Solicitation): 「ルータいますか?」", ""),
            (1, "RA (Router Advertisement): 「ここにいる。プレフィックスはこれ」", ""),
            (1, "NS (Neighbor Solicitation): 「このアドレスの MAC 教えて」= ARP 相当", ""),
            (1, "NA (Neighbor Advertisement): 「私です」", ""),
            (0, "全部 ICMPv6。だから ICMPv6 を全 deny すると IPv6 は動かない", "w"),
            (1, "教科書 14.9「ICMPv6 を無条件にすべてフィルタリングすべきではない」(p.279)", ""),
            (1, "対立意見: では全許可か? それも違う。Packet Too Big を落とすと MTU 障害になる", ""),
            (0, "教科書: 6.1 機能と利用するメッセージ (p.128) / 6.2 ルータとプレフィックス情報の発見 (p.129)", ""),
            (1, "余力があれば 6.6 IPv6 における on-link と off-link (p.154)", ""),
        ],
    )

    branch_slide(
        prs,
        "2-3. 方式は 2 つ — 分岐点は「ひかり電話」",
        ("案件受領: ひかり電話は?", "ヒアリングシートの必須項目"),
        ("なし → RA 方式", "SLAAC / /64 が 1 個"),
        ("あり → PD 方式", "DHCPv6-PD / /56 = /64 が 256 個"),
        [
            "RA 方式: ルータ広告のプレフィックス情報から端末が自分でアドレスを作る (SLAAC)。/64 が 1 個。",
            "PD 方式: DHCPv6 で「プレフィックスそのもの」が委任される。/56 = /64 が 256 個作れる。",
            "※ ヒアリングシートの「ひかり電話」欄が空欄で来たら、設定が全部変わる。必ず埋めさせる。",
            "教科書: 7.1 SLAAC の流れ (p.160) / 8.7 DHCPv6-PD (p.201) / 3.12 ユーザへの割り当て (p.89)",
        ],
    )

    bullet_slide(
        prs,
        "2-4. プレフィックス長 /64 /56 の感覚",
        [
            (0, "IPv4 と IPv6 で「もらうもの」が違う", "b"),
            (1, "IPv4: アドレスを 1 個もらう (グローバル 1 個 + 中は NAT)", ""),
            (1, "IPv6: プレフィックスを 1 個もらって、その中を自分で切る", ""),
            (0, "ホスト部は常に 64 ビット。これは SLAAC が要求している", "b"),
            (1, "だから /64 より細かく切ると SLAAC が動かない。/65 などは実務では作らない", "w"),
            (0, "/56 をもらったら", "b"),
            (1, "2001:db8:100a:0500::/56 → 0500:: 〜 05ff:: の /64 が 256 個", "c"),
            (1, "LAN を複数セグメントに分けられる。これが PD 方式の価値", ""),
            (0, "教科書: 3.12 (p.89) / 3.7 グローバルユニキャストアドレス (p.80)", ""),
        ],
    )

    bullet_slide(
        prs,
        "2-5. ラボ演習 Phase 1 — 4 兄弟を実際に見る (25分)",
        [
            (0, "手順 (RA 方式 → PD 方式を切り替えて 2 回まわす)", "b"),
            (1, "1. NGN 側で方式を切り替える", ""),
            (1, "./lab/ipoe/ngn/setup-ngn.sh ra     # ひかり電話なし相当", "c"),
            (1, "./lab/ipoe/ngn/setup-ngn.sh pd     # ひかり電話あり相当", "c"),
            (1, "2. CPE 側でキャプチャしながら再接続", ""),
            (1, "tcpdump -i any -nn 'icmp6 or udp port 546 or udp port 547'", "c"),
            (1, "3. RS → RA が見えるか / Solicit → Advertise → Request → Reply が見えるか", ""),
            (1, "4. ip -6 route と CPE の LAN 側アドレスを比べる", ""),
            (0, "DUID の罠 (Phase 1 step 5)", "w"),
            (1, "NGN は DUID-LL (type 0003) しか受け付けない。LLT を送る CPE は PD が降りない", ""),
            (1, "教科書: 8.4 DUID (p.191)。ここを知らないと「なぜか PD だけ来ない」で数時間溶ける", ""),
        ],
        footer="教科書: 8.1 IPv4 の DHCP と DHCPv6 の違い (p.180) / 8.3 DHCPv6 の概要 (p.183)",
    )

    # ---------------- 第3回 ----------------
    section_slide(prs, "第3回", "IPv4 を IPv6 の上で運ぶ",
                  "「ポート開放したい」に、方式を聞いて可否を即答できる")

    table_slide(
        prs,
        "3-1. 共存技術の分類 — 名前が多すぎる問題",
        ["分類", "代表", "日本の IPoE で使うか", "教科書"],
        [
            ["トンネル", "6to4, Teredo, ISATAP, 6rd, 4rd", "6rd/4rd の系譜が MAP-E の祖先", "第22章 (p.385)"],
            ["変換", "SIIT, NAT64 + DNS64, 464XLAT", "モバイル系。固定回線では少ない", "第23章 (p.407)"],
            ["プロキシ", "HTTP プロキシ, TRT", "ほぼ使わない", "第25章 (p.433)"],
            ["運用形態", "!DS-Lite / MAP-E / lw4o6 / A+P", "!これが本命", "!第24章 (p.421)"],
        ],
        [1.6, 4.5, 3.7, 2.4],
        footer="教科書: 21.1 バリエーション (p.381) / 21.2 ステートフルとステートレス (p.382)",
        fsize=12,
    )

    bullet_slide(
        prs,
        "3-2. サービス名と方式名を混同しない (最重要の実務知識)",
        [
            (0, "これは全部サービス名 (商品名)。教科書には出てこない", "w"),
            (1, "v6 プラス / transix / クロスパス / IPv6 オプション / v6 コネクト …", ""),
            (0, "方式名はこの 2 つ (固定回線の日本の IPoE では実質これだけ)", "b"),
            (1, "MAP-E … CE (お客様のルータ) 側で NAT する。ポートが制限される", ""),
            (1, "DS-Lite … 網側 (AFTR) で NAT する。ポート開放が原理的に不可", ""),
            (0, "案件で最初に確認すること", "b"),
            (1, "「その商品の中身は MAP-E ですか DS-Lite ですか」", ""),
            (1, "サービス名だけで設定を始めると、CPE のテンプレを間違える", "w"),
            (0, "実サービスとの対応表: docs/ipoe-lab/research-notes.md", ""),
        ],
    )

    bullet_slide(
        prs,
        "3-3. MAP-E — 1 個の IPv4 を何人で分けるか",
        [
            (0, "考え方: グローバル IPv4 を複数ユーザで共有し、ポート番号で区別する (A+P)", "b"),
            (1, "自分の IPv6 プレフィックスから、使える IPv4 とポート範囲が計算で決まる", ""),
            (1, "計算に使うのが EA bits と PSID。ステートレス = 網側に台帳がない", ""),
            (0, "ラボのパラメータ (README §2 の想定値)", "b"),
            (1, "rule-ipv6-prefix 2001:db8:1000::/40 / rule-ipv4-prefix 198.51.100.0/24", "c"),
            (1, "ea-len 16 / psid-offset 4 → 1 ユーザあたり約 4096 ポート", "c"),
            (0, "現場で刺さる罠", "w"),
            (1, "使えるポートは連続していない。飛び飛びのブロックに分かれる", ""),
            (1, "「1024〜5120 の範囲」と思って NAT 設定を書くと動かない → ラボ R12", ""),
            (1, "80/443 は基本もらえない。Web サーバ公開は MAP-E では厳しい", ""),
            (0, "教科書: 24.3 A+P (p.423) / 24.4 MAP-E、MAP-T、4rd (p.425) / 19.4 課題 (p.362)", ""),
        ],
    )

    diagram_slide(
        prs,
        "3-4. DS-Lite — NAT が網側にある。だから触れない",
        [("お客様 PC", "192.168.x.x"), ("CPE (B4)", "NAT しない"), ("AFTR", "ここで NAT"), ("インターネット", "共有グローバル")],
        [
            "MAP-E は CPE が NAT する → 自分のポート範囲内なら開放できる。",
            "DS-Lite は AFTR (事業者設備) が NAT する → お客様側から設定する手段がない。",
            "※ 「ポート開放できますか?」→ DS-Lite なら答えは「できません」。代替は PPPoE 併用か固定 IP 契約。",
            "教科書: 24.1 DS-Lite (p.421) / 19.3 NAT 機器に要求される挙動 (p.356)",
        ],
    )

    bullet_slide(
        prs,
        "3-5. MTU — 「Web は見えるがファイルが送れない」の正体",
        [
            (0, "トンネルするとヘッダが増えるので、素の 1500 バイトは通らない", "b"),
            (1, "PPPoE: 1454 / MAP-E・DS-Lite: 1460", ""),
            (1, "encaplimit (Destination Options ヘッダ) が付くと 8 バイト減って 1452", ""),
            (0, "症状の出方が独特なので覚える", "w"),
            (1, "小さいパケット (HTTP GET, ping, DNS) は通る → 「つながってる」と見える", ""),
            (1, "大きいパケット (ファイル送信、添付、画像の多いページ) だけ落ちる", ""),
            (0, "なぜ勝手に調整されないのか", "b"),
            (1, "本来は Path MTU Discovery が ICMPv6 Packet Too Big で教えてくれる", ""),
            (1, "経路のどこかで ICMPv6 を drop していると教えてもらえない = MTU ブラックホール", ""),
            (0, "教科書: 第10章 Path MTU discovery (p.215) / 9.2 IPv6 フラグメントヘッダ (p.208) / 14.9 (p.279)", ""),
        ],
        footer="ラボ R5 (MTU ブラックホール) / R11 (encaplimit 起因の片方向断) で再現する",
    )

    bullet_slide(
        prs,
        "3-6. ラボ演習 Phase 2/3 + R3/R4 — 失敗を体験する (25分)",
        [
            (0, "① MAP-E で「使えるポートを数える」", "b"),
            (1, "CPE に降りたプレフィックスから共有 IPv4 と PSID を確認する", ""),
            (1, "ポート範囲を書き出し、連続していないことを目で見る", ""),
            (0, "② R3: 範囲外のポートで通信させて失敗させる", "b"),
            (1, "「設定は正しいのに通らない」がどう見えるかを体験する", ""),
            (0, "③ R4: DS-Lite でポート開放を試して、できないことを確認する", "b"),
            (1, "CPE の設定画面にポート開放欄はあるのに効かない ← 客に説明するとき効く体験", ""),
            (0, "④ 大きいファイルを落として MTU を確認する", "b"),
            (1, "curl -o /dev/null http://203.0.113.80/big.bin   # 5MB", "c"),
            (0, "⑤ 結果を test-matrix.md §5 実績表に記録する。記録しないと次の案件で活きない", "w"),
        ],
    )

    # ---------------- 壁 Q&A ----------------
    section_slide(prs, "つまずきの壁", "現場で実際に出る質問と答え方",
                  "生徒役は若手にやらせる。読み上げるだけで理解が進む")

    qa_slide(prs, 1, "IPoE って NTT がやってるサービス名ですか?",
             ["いや、IP over Ethernet の略。PPP を挟まずに Ethernet に直接 IP を載せる接続方式の名前。",
              "PPPoE は ID/パスワードでセッションを張る工程が入るが、IPoE はそれがない。",
              "つないだら RA か DHCPv6 でアドレスが降ってくる。"],
             ref="付録 A.3 (p.443) — PPPoE と IPoE が並べて書いてある")

    qa_slide(prs, 2, "「IPoE にすると速い」って営業が言うんですけど、なんで速いんですか?",
             ["IPoE 自体が速いわけじゃない。PPPoE は網終端装置 (NTE) を必ず通り、そこの収容数が決まっていて夕方混む。",
              "IPoE はそこを通らない。つまり「速い」の理由はプロトコルではなく通る箱が違うから。",
              "客への説明もこの言い方をする。"],
             dissent="それも常に正しくない。IPoE 側の VNE が混んでれば普通に遅い。「IPoE にしたのに遅い」案件は実在する。だから「速くなります」と言い切らないこと。約束すると後で詰められる。",
             ref="付録 A.3 (p.443)")

    qa_slide(prs, 3, "IPv6 にしたら IPv4 は使えなくなるんですか?",
             ["ならない。IPoE でも IPv4 は使える。ただし IPv6 のトンネルの中を通る (MAP-E / DS-Lite)。",
              "だから「IPv4 の通信が IPv6 に依存する」という新しい壊れ方が生まれる。",
              "IPv6 側が不調なら IPv4 も道連れになる、という点が PPPoE 時代と決定的に違う。"],
             ref="21.1 共存技術のバリエーション (p.381) / 第24章 (p.421)")

    qa_slide(prs, 4, "/64 とか /56 の数字は何ですか? IPv4 の /24 みたいなもの?",
             ["考え方は同じ (前から何ビットがネットワーク部か)。ただ運用の感覚が全然違う。",
              "IPv4 は「アドレスを 1 個もらう」、IPv6 は「プレフィックスを 1 個もらって中を自分で切る」。",
              "/56 をもらえば /64 が 256 個。ホスト部は常に 64 ビット (SLAAC の要求)。"],
             ref="3.12 ユーザへの IPv6 アドレス割り当て (p.89) / 7.1 SLAAC の流れ (p.160)")

    qa_slide(prs, 5, "fe80:: のアドレスがいっぱい出てくるんですが、消していいですか?",
             ["消したら通信が全部死ぬ。リンクローカルアドレスといって、同じリンク内だけで使う。",
              "IPv6 のルーティングも近隣探索も、実はこれを使って動いている。RA の送信元も fe80::。",
              "IPv4 の 169.254.x.x とは役割が全然違う (あっちは DHCP 失敗時の敗戦処理)。"],
             ref="3.5 リンクローカルユニキャストアドレス (p.74) / 第6章 (p.127)")

    qa_slide(prs, 6, "tcpdump に ICMPv6 がめちゃくちゃ流れてるんですが、攻撃されてます?",
             ["正常。IPv6 では ICMPv6 がプロトコルの本体機能を担っている。",
              "ARP の代わり (NS/NA)、ルータ広告 (RS/RA)、Path MTU 通知、全部 ICMPv6。",
              "だから ICMPv6 を全部 drop するファイアウォール設定は IPv6 を壊す。"],
             dissent="逆に「じゃあ ICMPv6 は全許可」も間違い。RFC 4890 相当の選別が必要。ラボでやると分かるが、Packet Too Big を落とすと R5 の MTU ブラックホールが再現する。",
             ref="14.9 ICMPv6 を無条件にすべてフィルタリングすべきではない (p.279) / ラボ R5")

    qa_slide(prs, 7, "MAP-E の「ポートが制限される」って、何個使えるんですか?",
             ["方式のパラメータ次第。ラボの設定 (ea-len 16, psid-offset 4) だと 1 ユーザあたり約 4096 個。",
              "しかも連続していないブロックに分かれる。ここが罠。",
              "「1024〜5120 の範囲」のように連続だと思って NAT 設定を書くと動かない。"],
             dissent="「4096 個あれば十分」も雑。ブラウザは 1 タブで数十本張る。同時接続の多い拠点や監視系がいると足りなくなる。台数が多い案件では実測すること。",
             ref="24.3 A+P (p.423) / 24.4 (p.425) / ラボ R12 で必ず一度失敗させる")

    qa_slide(prs, 8, "客先で「ポート開放して」と言われました。IPoE でもできますよね?",
             ["方式を先に確認する。MAP-E なら自分に割り当てられたポート範囲内でのみ可 (80/443 は基本無理)。",
              "DS-Lite なら原理的に不可。NAT が網側 (AFTR) にあって、そこは触れない。",
              "ここを聞かずに「できます」と答えると案件が炎上する。"],
             ref="24.1 DS-Lite (p.421) / 19.4 IPv4 アドレス共有技術の課題 (p.362) / ラボ R4")

    qa_slide(prs, 9, "切替後に「Web は見えるけど添付ファイルが送れない」と言われました。",
             ["MTU を疑う。トンネルでヘッダが増えるので素の 1500 では通らない。",
              "想定値は PPPoE 1454 / MAP-E・DS-Lite 1460、encaplimit が付くと 1452。",
              "小さいパケットは通るので「見えるけど大きいものが落ちる」という症状になる。"],
             ref="第10章 (p.215) / 9.2 (p.208) / ラボ R5, R11 (/big.bin 5MB で再現)")

    qa_slide(prs, 10, "IPoE にしたらセキュリティは上がりますか?",
             ["下がる可能性がある。PPPoE + IPv4 NAT では「NAT があるから外から入れない」状態だったのが、",
              "IPoE で各端末にグローバル IPv6 が付くと、外から直接到達しうる。",
              "ファイアウォール設定が入っているかを必ず確認する。"],
             dissent="とはいえ「NAT はセキュリティ機能ではない」というのも教科書の立場。NAT に守られていたつもりだっただけ。この誤解をそのまま客に共有すると後々困る。",
             ref="14.1 IPv6 は IPv4 よりもセキュアというわけではない (p.263) / 14.7 (p.278) / ラボ R13")

    # ---------------- 参照系 ----------------
    table_slide(
        prs,
        "用語の対訳表 — 同じものが 3 通りの呼び方で出てくる",
        ["教科書の用語", "現場でよく言う", "機器 / 画面での表記"],
        [
            ["近隣探索プロトコル", "ND、ネイバーディスカバリ", "Neighbor Discovery / ipv6 nd"],
            ["Router Advertisement メッセージ", "RA、ルータ広告", "RA / ipv6 nd ra"],
            ["プレフィックス", "プレフィックス、接頭辞", "prefix"],
            ["SLAAC (IPv6 アドレスの自動設定)", "RA 方式、ステートレス", "SLAAC / autoconfig"],
            ["DHCPv6-PD", "PD 方式、プレフィックス委任", "IA_PD / ipv6 dhcp pool"],
            ["DUID", "ドゥーイド、クライアント識別子", "DUID-LL / DUID-LLT"],
            ["リンクローカルユニキャストアドレス", "リンクローカル、fe80", "link-local"],
            ["IPv4/IPv6 共存技術", "IPv4 over IPv6、v4v6", "transition technology"],
            ["MAP-E", "マップイー、v6 プラス系", "MAP-E / nat64 map-e (IOS XE)"],
            ["DS-Lite", "ディーエスライト、transix 系", "DS-Lite / AFTR"],
            ["A+P (ポートセット)", "ポート制限、PSID", "port-set / PSID"],
            ["Path MTU discovery", "PMTUD、MTU 探索", "path-mtu-discovery"],
        ],
        [4.3, 3.9, 4.0],
        footer="※ v6プラス / transix / クロスパス / IPv6オプション は「サービス名」。方式名ではない",
        fsize=11,
    )

    table_slide(
        prs,
        "トラブル再現レシピ → 読むべき節 (現象を見た直後に読む)",
        ["レシピ", "現象", "教科書"],
        [
            ["R1", "RA 方式なのに PD 前提設定 (最頻出)", "7.1-7.7 / 8.7 / 付録A.3"],
            ["R2", "PPPoE セッション残留", "付録A.3"],
            ["R3", "MAP-E ポート制限", "24.3 / 24.4 / 19.4"],
            ["R4", "DS-Lite でポート開放不可", "24.1 / 19.3"],
            ["R5", "MTU ブラックホール", "第10章 / 9.2 / 14.9"],
            ["R6", "DNS フォールバック遅延", "17.2 / 15.3 / 付録A.1"],
            ["R7", "二重終端 (HGW 内蔵 + 配下ルータ)", "付録B / 13.2"],
            ["R8", "v6 オプション未契約相当", "付録A.2"],
            ["R9", "プレフィックス変更で LAN が追従しない", "7.8 / 13.3"],
            ["R10", "PPPoE 併用時の経路非対称", "13.1 / 13.2"],
            ["R11", "encaplimit 起因の片方向断", "4.3 / 22.7 / 14.10"],
            ["R12", "ポートセット非連続を無視した NAT 設定", "24.3 / 24.4"],
            ["R13", "IPoE 化による外→内 IPv6 直接着信", "第14章 / 14.7"],
        ],
        [1.2, 7.4, 3.6],
        footer="レシピ本体: docs/ipoe-lab/test-matrix.md §4",
        fsize=11,
    )

    bullet_slide(
        prs,
        "教科書とラボが食い違う唯一の重要ポイント",
        [
            (0, "MAP-E のインタフェース識別子の仕様が 2 系統ある", "b"),
            (1, "RFC 7597 準拠 … 教科書 第2版 第2刷 でこちらに修正された (更新履歴に明記)", ""),
            (1, "draft-ietf-softwire-map-03 準拠 … 日本の VNE の実装はこちら", "w"),
            (0, "ラボは実サービスに合わせて draft-03 側にしている", "b"),
            (1, "OpenWrt では legacymap 1 を指定する", "c"),
            (0, "つまり: 教科書どおりに設定すると実サービスで動かないことがある", "w"),
            (1, "「教科書が間違っている」のではなく「実装が draft のまま普及した」ということ", ""),
            (1, "こういう食い違いは IPv6 の世界では珍しくない。だから検証環境が必要になる", ""),
            (0, "詳細: docs/ipoe-lab/research-notes.md", ""),
        ],
        footer="勉強会で必ず触れること。ここを知らずに現場に出ると、教科書を読んだ人ほどハマる",
    )

    bullet_slide(
        prs,
        "修了確認 — 理由付きで答えられるか (5問)",
        [
            (0, "1. ひかり電話ありの案件で、CPE に設定すべきは RA 方式か PD 方式か。なぜか", ""),
            (0, "2. 客から「Minecraft サーバを公開したい」と言われた。まず何を確認するか", ""),
            (0, "3. 「切替後、Web は見えるが大きいファイルが送れない」。最初に疑うのは何か", ""),
            (0, "4. ICMPv6 を全部 deny した。何が壊れるか 2 つ挙げよ", ""),
            (0, "5. IPoE 化で PC に付いたグローバル IPv6。セキュリティ上、何を確認するか", ""),
            (0, "", ""),
            (0, "答えを暗記させるのが目的ではない。「どの節を見ればいいか」が分かれば合格", "b"),
            (1, "現場では調べる時間がある。調べる先が分からないことが事故を生む", ""),
            (0, "次の一歩", "b"),
            (1, "自分の案件でヒアリングシート (test-matrix.md §1) を埋めてみる", ""),
            (1, "ラボで自分の案件構成を再現し、実績表 (§5) に記録を残す", ""),
        ],
    )

    bullet_slide(
        prs,
        "参考資料 / 出典",
        [
            (0, "教科書", "b"),
            (1, "小川晃通『プロフェッショナル IPv6 第2版』ラムダノート, 2021年12月", ""),
            (1, "(第2刷 2023年3月) CC BY-NC-SA。ページ番号は第2版のもの", ""),
            (1, "※ 刷によってページがずれる可能性がある。勉強会前に講師が 1 箇所確認する", "w"),
            (0, "社内資料 (本リポジトリ)", "b"),
            (1, "docs/ipoe-lab/study-guide.md … 本スライドの正本。対応表の全量はこちら", ""),
            (1, "docs/ipoe-lab/README.md … ラボ全体設計・アドレス計画", ""),
            (1, "docs/ipoe-lab/build.md … 構築手順", ""),
            (1, "docs/ipoe-lab/test-matrix.md … ヒアリングシート / 検証マトリクス / レシピ R1-R13", ""),
            (1, "docs/ipoe-lab/research-notes.md … 実サービスのパラメータ、既知の落とし穴", ""),
            (1, "docs/ipoe-lab/runbook-vmware.md … 社内 VMware 環境での構築手順", ""),
            (0, "このスライドの再生成", "b"),
            (1, "python3 docs/ipoe-lab/slides/build-toranomaki.py", "c"),
        ],
    )

    prs.save(OUT)
    print(f"saved: {OUT} ({len(prs.slides)} slides)")


if __name__ == "__main__":
    build()
