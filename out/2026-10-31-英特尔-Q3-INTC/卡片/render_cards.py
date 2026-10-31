#!/usr/bin/env python3
"""生成口播稿配图卡（1080x1350，竖屏，截图即用）。"""
import os
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
BG = "#0A0C10"
PANEL = "#15191F"
BORDER = "#272E37"
TXT = "#F2F5F9"
SUB = "#98A2B3"
RED = "#FF4D4F"
GREEN = "#22C97A"
GOLD = "#FFC24B"

HEI = "/System/Library/Fonts/Hiragino Sans GB.ttc"
BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"

OUT = os.path.dirname(os.path.abspath(__file__))


def f(path, size, index=0):
    return ImageFont.truetype(path, size, index=index)


def tw(d, text, font):
    b = d.textbbox((0, 0), text, font=font)
    return b[2] - b[0], b[3] - b[1]


def fit(d, text, path, size, maxw, index=0):
    while size > 16:
        ft = f(path, size, index)
        if tw(d, text, ft)[0] <= maxw:
            return ft
        size -= 2
    return f(path, 16, index)


def new():
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img), f(BOLD, 52), f(HEI, 26)


def panel(d, box, radius=28, fill=PANEL, outline=BORDER, width=2):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def title_block(d, kicker, main):
    kf = f(HEI, 26)
    d.text((72, 84), kicker, font=kf, fill=SUB)
    mf = fit(d, main, BOLD, 62, W - 144)
    d.text((72, 128), main, font=mf, fill=TXT)


def save(img, name):
    p = os.path.join(OUT, name)
    img.save(p, quality=95)
    print("✓", p)


# ────────────────────────────── 卡 1：双栏对比
def card1():
    img, d, _, _ = new()
    title_block(d, "同一件事，两张账本", "内存涨价，一边印钞，一边绞索")

    pw = (W - 72 * 2 - 28) // 2
    lx, rx = 72, 72 + pw + 28
    top, bot = 268, 1050

    cols = [
        (lx, "闪迪 SNDK", "内存涨价的上游", RED, [
            ("营收", "110 亿美元", "+378%", RED),
            ("毛利率", "85.1%", "非GAAP", SUB),
            ("单季净利", "81 亿美元", None, None),
            ("当天股价", "-13.47%", None, GREEN),
        ]),
        (rx, "英特尔 INTC", "内存涨价的下游", GREEN, [
            ("营收", "165 亿美元", "+21%", RED),
            ("PC 芯片业务", "81 亿美元", "-5%", GREEN),
            ("四季度 PC 指引", "-20% 以上", None, GREEN),
            ("当天股价", "-28.58%", None, GREEN),
        ]),
    ]

    for x, name, tag, accent, rows in cols:
        panel(d, (x, top, x + pw, bot))
        d.rounded_rectangle((x, top, x + pw, top + 8), radius=4, fill=accent)
        d.text((x + 32, top + 40), name, font=f(BOLD, 40), fill=TXT)
        d.text((x + 32, top + 96), tag, font=f(HEI, 26), fill=SUB)
        d.line((x + 32, top + 152, x + pw - 32, top + 152), fill=BORDER, width=2)

        y = top + 180
        for label, value, chip, chip_color in rows:
            d.text((x + 32, y), label, font=f(HEI, 24), fill=SUB)
            vf = fit(d, value, BOLD, 50, pw - 64)
            d.text((x + 32, y + 36), value, font=vf, fill=chip_color if chip is None else TXT)
            if chip:
                cf = f(HEI, 26)
                cw = tw(d, chip, cf)[0]
                d.rounded_rectangle((x + pw - 32 - cw - 24, y + 44, x + pw - 32, y + 96),
                                    radius=26, fill="#1D222A")
                d.text((x + pw - 32 - cw - 12, y + 56), chip, font=cf, fill=chip_color)
            y += 150

    # 因果链
    chain = "内存涨价  →  整机成本上升  →  整机厂少下单  →  砸在英特尔收入上"
    cy0, cy1 = 1100, 1266
    panel(d, (72, cy0, W - 72, cy1), radius=22, fill="#10151B")
    cf = fit(d, chain, HEI, 30, W - 144 - 56)
    ch = tw(d, chain, cf)[1]
    d.text((W // 2, (cy0 + cy1) // 2 - ch // 2 - 4), chain, font=cf, fill="#D5DCE5", anchor="ma")

    save(img, "卡1_双栏对比.png")


# ────────────────────────────── 卡 2：指引缺口
def card2():
    img, d, _, _ = new()
    title_block(d, "英特尔四季度指引", "一个季度，差出 11–21 亿美元")

    panel(d, (72, 300, W - 72, 560))
    d.text((112, 344), "公司自己给的（亿美元）", font=f(HEI, 28), fill=SUB)
    d.text((112, 384), "150–160", font=f(BOLD, 132), fill=TXT)

    # 中间红条
    gap_txt = "差 11–21 亿美元"
    gf = f(BOLD, 40)
    gw = tw(d, gap_txt, gf)[0]
    d.rounded_rectangle((W // 2 - gw // 2 - 40, 592, W // 2 + gw // 2 + 40, 676),
                        radius=42, fill="#33141A", outline="#7A2A34", width=2)
    d.text((W // 2, 610), gap_txt, font=gf, fill=RED, anchor="ma")

    panel(d, (72, 708, W - 72, 968))
    d.text((112, 752), "市场要的（亿美元）", font=f(HEI, 28), fill=SUB)
    d.text((112, 794), "171", font=f(BOLD, 128), fill=GOLD)

    d.line((72, 1044, W - 72, 1044), fill=BORDER, width=2)
    d.text((72, 1084), "每股收益", font=f(HEI, 28), fill=SUB)
    ef = f(BOLD, 44)
    d.text((72, 1130), "上季 0.52", font=ef, fill=TXT)
    ar_x = 72 + tw(d, "上季 0.52", ef)[0] + 28
    d.text((ar_x, 1130), "→", font=ef, fill=SUB)
    d.text((ar_x + tw(d, "→", ef)[0] + 28, 1130), "四季度指引 0.25", font=ef, fill=GREEN)

    save(img, "卡2_指引缺口.png")


# ────────────────────────────── 卡 3：三数记忆
def card3():
    img, d, _, _ = new()
    title_block(d, "看完能背走的三个数", "记住这三个数")

    rows = [
        ("28.58", "%", RED, ["四十多年来最惨的", "单日跌幅"]),
        ("85.1", "%", GOLD, ["存储现在的毛利率", "（非GAAP）"]),
        ("110", "亿美元", TXT, ["闪迪一个季度", "赚的钱"]),
    ]
    y = 350
    for num, unit, color, lines in rows:
        d.line((72, y - 50, W - 72, y - 50), fill="#1B2027", width=2)
        nf = f(BOLD, 132)
        d.text((76, y), num, font=nf, fill=color)
        nwid = tw(d, num, nf)[0]
        d.text((76 + nwid + 14, y + 66), unit, font=f(HEI, 44), fill=SUB)
        for i, line in enumerate(lines):
            d.text((620, y + 44 + i * 50), line, font=f(HEI, 34), fill=TXT)
        y += 296

    save(img, "卡3_三数记忆.png")


# ────────────────────────────── 备 A：市值蒸发
def cardA():
    img, d, _, _ = new()
    d.text((W // 2, 372), "英特尔单日市值", font=f(HEI, 34), fill=SUB, anchor="ma")
    nf = f(BOLD, 190)
    d.text((W // 2, 436), "1400", font=nf, fill=TXT, anchor="ma")
    d.text((W // 2, 676), "亿美元，一夜蒸发", font=f(HEI, 46), fill=SUB, anchor="ma")

    d.rounded_rectangle((72, 800, W - 72, 990), radius=28, fill=PANEL, outline=BORDER, width=2)
    stats = [("单日跌幅", "-28.58%", GREEN), ("换手率", "8.58%", TXT), ("收盘市值", "3492 亿美元", TXT)]
    for i, (k, v, c) in enumerate(stats):
        x = 72 + 30 + i * ((W - 144 - 60) // 3)
        d.text((x, 852), k, font=f(HEI, 26), fill=SUB)
        d.text((x, 896), v, font=f(BOLD, 46), fill=c)

    save(img, "备A_市值蒸发.png")


# ────────────────────────────── 备 B：金句
def cardB():
    img = Image.new("RGB", (W, H), "#000000")
    d = ImageDraw.Draw(img)
    d.text((W // 2, 470), "业绩是过去", font=f(BOLD, 100), fill="#FFFFFF", anchor="ma")
    d.text((W // 2, 610), "估值是未来", font=f(BOLD, 100), fill="#FFFFFF", anchor="ma")
    d.line((W // 2 - 60, 790, W // 2 + 60, 790), fill="#333333", width=3)
    d.text((W // 2, 850), "跌的，是未来那部分", font=f(HEI, 46), fill="#9AA4B2", anchor="ma")
    save(img, "备B_金句.png")


if __name__ == "__main__":
    card1(); card2(); card3(); cardA(); cardB()
