#!/usr/bin/env python3
"""配图卡出图器（口播稿配套竖版卡，PNG 直出）。

用法：
    python3 scripts/cards.py --spec out/<期目录>/卡片/cards.json
    python3 scripts/cards.py --spec cards.json --outdir 某目录   # 覆盖输出目录
    python3 scripts/cards.py --list-types

设计约束（写死在代码里，不让调用方选）：
- 画布 1080x1350（竖版 4:5），深色底，手机端高对比。
- 涨红跌绿（国内习惯），tone: up=涨红 / down=跌绿 / gold / text / sub。
- 负号一律用 ASCII "-"：Hiragino Sans GB 缺 U+2212，会渲染成方框。
- 文字一律从 JSON 来，脚本里不出现任何业务数字。
"""
import argparse
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350

THEME = {
    "bg": "#0A0C10", "panel": "#15191F", "border": "#272E37",
    "text": "#F2F5F9", "sub": "#98A2B3",
    "up": "#FF4D4F", "down": "#22C97A", "gold": "#FFC24B",
}
FONT_REG = "/System/Library/Fonts/Hiragino Sans GB.ttc"
FONT_BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"


class Ctx:
    def __init__(self, theme, font_reg, font_bold):
        self.t = dict(THEME, **theme)
        self.fr = font_reg
        self.fb = font_bold
        self.img = Image.new("RGB", (W, H), self.t["bg"])
        self.d = ImageDraw.Draw(self.img)

    def f(self, size, bold=False):
        return ImageFont.truetype(self.fb if bold else self.fr, size)

    def h(self, text, font):
        b = self.d.textbbox((0, 0), text, font=font)
        return b[3] - b[1]

    def w(self, text, font):
        b = self.d.textbbox((0, 0), text, font=font)
        return b[2] - b[0]

    def fit(self, text, size, maxw, bold=True, floor=16):
        while size > floor:
            ft = self.f(size, bold)
            if self.w(text, ft) <= maxw:
                return ft
            size -= 2
        return self.f(floor, bold)

    def color(self, tone, default="text"):
        return self.t.get(tone or default, self.t[default])

    def panel(self, box, radius=28, fill=None, outline=None, width=2):
        self.d.rounded_rectangle(box, radius=radius,
                                 fill=fill or self.t["panel"],
                                 outline=outline or self.t["border"], width=width)


def title_block(c, kicker, title):
    if kicker:
        c.d.text((72, 84), kicker, font=c.f(26), fill=c.t["sub"])
    if title:
        c.d.text((72, 128), title, font=c.fit(title, 62, W - 144), fill=c.t["text"])


# ───────────────────────────── 双栏对比
def draw_split(c, card):
    title_block(c, card.get("kicker"), card.get("title"))
    cols = card["columns"]
    pw = (W - 144 - 28 * (len(cols) - 1)) // len(cols)
    top, bot = 268, 1050

    for i, col in enumerate(cols):
        x = 72 + i * (pw + 28)
        c.panel((x, top, x + pw, bot))
        c.d.rounded_rectangle((x, top, x + pw, top + 8), radius=4, fill=c.color(col.get("accent")))
        c.d.text((x + 32, top + 40), col["head"], font=c.f(40, bold=True), fill=c.t["text"])
        if col.get("tag"):
            c.d.text((x + 32, top + 96), col["tag"], font=c.f(26), fill=c.t["sub"])
        c.d.line((x + 32, top + 152, x + pw - 32, top + 152), fill=c.t["border"], width=2)

        rows = col.get("rows", [])
        avail = bot - 24 - (top + 180)
        step = 150 if len(rows) <= 4 else max(110, avail // max(len(rows), 1))
        y = top + 180
        for row in rows:
            c.d.text((x + 32, y), row["label"], font=c.f(24), fill=c.t["sub"])
            tone = row.get("tone")
            vf = c.fit(row["value"], 50, pw - 64)
            c.d.text((x + 32, y + 36), row["value"], font=vf,
                     fill=c.color(tone) if tone else c.t["text"])
            if row.get("chip"):
                cf = c.f(26)
                cw = c.w(row["chip"], cf)
                c.d.rounded_rectangle((x + pw - 32 - cw - 24, y + 44, x + pw - 32, y + 96),
                                      radius=26, fill="#1D222A")
                c.d.text((x + pw - 32 - cw - 12, y + 56), row["chip"], font=cf,
                         fill=c.color(row.get("chip_tone"), "sub"))
            y += step

    if card.get("foot"):
        c.panel((72, 1100, W - 72, 1266), radius=22, fill="#10151B")
        ff = c.fit(card["foot"], 30, W - 144 - 56, bold=False)
        fy = 1183 - c.h(card["foot"], ff) // 2 - 4
        c.d.text((W // 2, fy), card["foot"], font=ff, fill="#D5DCE5", anchor="ma")


# ───────────────────────────── 缺口 / 对比两组数字
def draw_gap(c, card):
    title_block(c, card.get("kicker"), card.get("title"))

    c.panel((72, 300, W - 72, 560))
    c.d.text((112, 344), card["top"]["label"], font=c.f(28), fill=c.t["sub"])
    c.d.text((112, 384), card["top"]["value"], font=c.f(132, bold=True),
             fill=c.color(card["top"].get("tone"), "text"))

    gap = card.get("gap")
    if gap:
        gf = c.f(40, bold=True)
        gw = c.w(gap, gf)
        # 胶囊底色跟随基调：涨（up，默认）暗红，跌（down）暗绿——A 股涨红跌绿
        g_tone = card.get("gap_tone", "up")
        fill_c, line_c = ("#0E2A1E", "#1F6B45") if g_tone == "down" else ("#33141A", "#7A2A34")
        c.d.rounded_rectangle((W // 2 - gw // 2 - 40, 592, W // 2 + gw // 2 + 40, 676),
                              radius=42, fill=fill_c, outline=line_c, width=2)
        c.d.text((W // 2, 610), gap, font=gf, fill=c.color(g_tone, "up"), anchor="ma")

    c.panel((72, 708, W - 72, 968))
    c.d.text((112, 752), card["bottom"]["label"], font=c.f(28), fill=c.t["sub"])
    c.d.text((112, 794), card["bottom"]["value"], font=c.f(128, bold=True),
             fill=c.color(card["bottom"].get("tone"), "gold"))

    foot = card.get("foot")
    if foot:
        c.d.line((72, 1044, W - 72, 1044), fill=c.t["border"], width=2)
        c.d.text((72, 1084), foot["label"], font=c.f(28), fill=c.t["sub"])
        ef = c.f(44, bold=True)
        x = 72
        c.d.text((x, 1130), foot["left"], font=ef, fill=c.t["text"])
        x += c.w(foot["left"], ef) + 28
        c.d.text((x, 1130), "→", font=ef, fill=c.t["sub"])
        x += c.w("→", ef) + 28
        c.d.text((x, 1130), foot["right"], font=ef, fill=c.color(foot.get("right_tone"), "down"))


# ───────────────────────────── 三数记忆
def draw_trio(c, card):
    title_block(c, card.get("kicker"), card.get("title"))
    y = 350
    for row in card["rows"]:
        c.d.line((72, y - 50, W - 72, y - 50), fill="#1B2027", width=2)
        nf = c.f(132, bold=True)
        c.d.text((76, y), row["num"], font=nf, fill=c.color(row.get("tone"), "text"))
        if row.get("unit"):
            c.d.text((76 + c.w(row["num"], nf) + 14, y + 66), row["unit"],
                     font=c.f(44), fill=c.t["sub"])
        for i, line in enumerate(row.get("lines", [])):
            c.d.text((620, y + 44 + i * 50), line, font=c.f(34), fill=c.t["text"])
        y += 296


# ───────────────────────────── 单数字 + 三格
def draw_stat(c, card):
    c.d.text((W // 2, 372), card["label"], font=c.f(34), fill=c.t["sub"], anchor="ma")
    c.d.text((W // 2, 436), card["num"], font=c.f(190, bold=True),
             fill=c.color(card.get("tone"), "text"), anchor="ma")
    if card.get("caption"):
        c.d.text((W // 2, 676), card["caption"], font=c.f(46), fill=c.t["sub"], anchor="ma")

    stats = card.get("stats", [])
    if stats:
        c.panel((72, 800, W - 72, 990))
        cell = (W - 144 - 60) // len(stats)
        for i, st in enumerate(stats):
            x = 72 + 30 + i * cell
            c.d.text((x, 852), st["k"], font=c.f(26), fill=c.t["sub"])
            c.d.text((x, 896), st["v"], font=c.f(46, bold=True), fill=c.color(st.get("tone"), "text"))


# ───────────────────────────── 金句
def draw_quote(c, card):
    c.d.rectangle((0, 0, W, H), fill="#000000")
    y = card.get("top", 470)
    for line in card["lines"]:
        c.d.text((W // 2, y), line, font=c.f(card.get("size", 100), bold=True),
                 fill="#FFFFFF", anchor="ma")
        y += int(card.get("size", 100) * 1.4)
    y += 40
    c.d.line((W // 2 - 60, y, W // 2 + 60, y), fill="#333333", width=3)
    if card.get("sub"):
        c.d.text((W // 2, y + 60), card["sub"], font=c.f(46), fill="#9AA4B2", anchor="ma")


TYPES = {"split": draw_split, "gap": draw_gap, "trio": draw_trio, "stat": draw_stat, "quote": draw_quote}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", help="卡片配置 JSON")
    ap.add_argument("--outdir", help="覆盖配置里的输出目录")
    ap.add_argument("--list-types", action="store_true")
    a = ap.parse_args()

    if a.list_types or not a.spec:
        print("可用卡型：", "、".join(TYPES))
        for k, v in TYPES.items():
            print(f"  {k:6s} {v.__doc__ or ''}")
        return

    spec = json.load(open(a.spec, encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(a.spec))
    outdir = a.outdir or os.path.join(base, spec.get("outdir", "."))
    os.makedirs(outdir, exist_ok=True)

    for card in spec["cards"]:
        kind = card["type"]
        if kind not in TYPES:
            sys.exit(f"未知卡型：{kind}（可用：{'、'.join(TYPES)}）")
        c = Ctx(spec.get("theme", {}), spec.get("font_regular", FONT_REG), spec.get("font_bold", FONT_BOLD))
        TYPES[kind](c, card)
        p = os.path.join(outdir, card["file"])
        c.img.save(p)
        print("✓", p)


if __name__ == "__main__":
    main()
