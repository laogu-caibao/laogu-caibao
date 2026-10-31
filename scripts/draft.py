#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
稿件 CLI · 把底稿与分析结果压成一份可直接改写成口播的稿子

用法：
  python3 scripts/draft.py 688818
  python3 scripts/draft.py 688818 --period 2026-09-30

产出 out/<代码>/<报告期>/稿件.md：
  钩子 → 多期对比表 → 矛盾点（五看选出） → 归因链 → 一句话归因 → 分型与结论
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cbfx import brief, reaction  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(code, period=None):
    base = os.path.join(ROOT, "out", code)
    if not os.path.isdir(base):
        sys.exit(f"[ERR] 未找到 {base}，先跑 analyze.py")
    if not period:
        cands = [x for x in os.listdir(base)
                 if os.path.isdir(os.path.join(base, x)) and x[:4].isdigit()]
        if not cands:
            sys.exit(f"[ERR] {base} 下没有报告期目录")
        period = sorted(cands)[-1]
    d = os.path.join(base, period)
    if not os.path.isfile(os.path.join(d, "底稿.json")):
        sys.exit(f"[ERR] {d}/底稿.json 不存在")
    ledger = json.load(open(os.path.join(d, "底稿.json"), encoding="utf-8"))
    ana = {}
    fp = os.path.join(d, "分析.json")
    if os.path.isfile(fp):
        ana = json.load(open(fp, encoding="utf-8"))
    return ledger, ana, d, period


def fmt_row(row):
    cells = []
    for v in row["values"]:
        cells.append("—" if v is None else row["fmt"].format(v))
    tail = row.get("yoy_text") or "—"
    return cells, tail


def render(ledger, ana, period, band=0.03):
    meta = (ana.get("meta") or {})
    name = meta.get("name") or (ledger.get("meta") or {}).get("name") or ""
    arch = (ana.get("archetype") or {})

    conflicts = brief.detect_conflicts(ledger, n=8)
    table = brief.compare_table(ledger, n=6)

    L = [f"# {name} {period} 稿件骨架", ""]
    L.append("> 本文件只提供素材与结构，不构成投资建议。数字全部来自底稿，未获取的一律写「未获取」。")
    L.append("")

    # 行情背离
    arch_code = (ana.get("archetype") or {}).get("archetype")
    cyc = reaction.cyclical_hook(ledger, ana) if arch_code == "B" else None
    rx = reaction.judge(ledger, ana, band=band)

    # 钩子
    L += ["## 0. 钩子", ""]
    if cyc and cyc.get("verdict") == "conflict":
        L.append(f"> 【首选·周期位置错位】利润 TTM 已到历史峰值（{cyc['np_ratio']*100:.0f}%），"
                 f"股价却比三年高点低 {abs(cyc['drawdown'])*100:.0f}%。")
        L.append("")
        if conflicts:
            L.append(f"> 【备选·财报内部矛盾】{conflicts[0]['name']}——{conflicts[0]['evidence']}")
            L.append("")
        L.append("周期股不看公告后几天的反应，看利润位置和股价位置对不对得上。")
    elif rx.get("verdict") == "conflict":
        mv, vr = rx.get("move"), rx.get("volume_ratio")
        tail = f"，量比 {vr:.1f} 倍" if vr else ""
        tn = {"good": "不错", "weak": "偏弱", "neutral": "平平"}[rx["tone"]["tone"]]
        if rx.get("strength") == "strong":
            act = f"{'跌' if rx['type']=='A' else '涨'}了 {abs(mv)*100:.0f}%"
        else:
            act = f"基本没动（{mv*100:+.1f}%）"
        L.append(f"> 【首选·财报与股价背离】财报看着{tn}，股价却{act}{tail}。")
        L.append("")
        if conflicts:
            L.append(f"> 【备选·财报内部矛盾】{conflicts[0]['name']}——{conflicts[0]['evidence']}")
            L.append("")
        L.append("背离优先于内部矛盾：观众对「股价」有体感，对「毛利率」没有。")
    elif conflicts:
        c = conflicts[0]
        L.append(f"> {c['name']}——{c['evidence']}")
        L.append("")
        L.append("本期财报与股价未背离，钩子用财报内部矛盾，但力度弱一档。")
    else:
        L.append("> 本期未检出显著矛盾，钩子需人工另找。")
    L.append("")

    # 市场反应段：判不出（none）就整段不写
    if cyc:
        if cyc.get("verdict") == "conflict":
            rb = (f"- **周期位置错位**：利润 TTM 为历史峰值 {cyc['np_ratio']*100:.0f}%，"
                  f"股价 {cyc['cur_px']:.2f} 元，距三年高点 {cyc['peak_px']:.2f} 元低 "
                  f"{abs(cyc['drawdown'])*100:.0f}%")
        else:
            rb = ""
    else:
        rb = reaction.render_block(rx)
    if rb:
        L += ["## 0.5 市场反应", "", rb, ""]
        L.append("这条只做方向对照。市场为什么这么走——订单、政策、资金行为——公开数据回答不了，"
                 "正文一律写「无法确认」，不要替市场编理由。")
        L.append("")

    # 对比表
    L += ["## 1. 多期对比表（对着看，不逐项念）", ""]
    head = "| 指标 | " + " | ".join(table["periods"]) + " | 同比 |"
    sep = "|---|" + "---:|" * (len(table["periods"]) + 1)
    L += [head, sep]
    for row in table["rows"]:
        cells, yoy = fmt_row(row)
        L.append(f"| {row['label']} | " + " | ".join(cells) + f" | {yoy} |")
    L.append("")
    L.append("讲的时候只指两三行，不要从头念到尾。")
    L.append("")

    # 矛盾点
    L += ["## 2. 矛盾点（五看诊断选出，按强度排序）", ""]
    if not conflicts:
        L.append("- 本期未检出。")
    for i, c in enumerate(conflicts[:3], 1):
        L.append(f"**{i}. {c['name']}**（强度 {c['score']:.0f}）")
        L.append(f"- 证据：{c['evidence']}")
        chain = " → ".join(c["chain"])
        L.append(f"- 归因链：{chain}")
        L.append("")

    # 五看
    rev = brief.seq_sq(ledger, "rev", 8)
    looks = brief.five_looks([v for _, v in rev])
    ttm = brief.ttm_seq(ledger, "rev", 8)
    tlooks = brief.five_looks([v for _, v in ttm]) if len(ttm) >= 4 else {}
    if looks:
        L += ["## 3. 五看诊断（营收）", ""]
        src = tlooks or looks
        L.append(f"- 方向：{src['direction']}（{'TTM' if tlooks else '单季'}斜率年化 {src['slope_pct']*100:+.1f}%）")
        L.append(f"- 连续：{'升' if looks.get('streak_sign') == 1 else '降'} {looks['streak']} 期")
        L.append(f"- 波动：{looks['volatility']}")
        L.append(f"- 拐点：{looks['turning'] or '无'}")
        if looks.get("yoy") is not None:
            L.append(f"- 同比：{looks['yoy']*100:+.1f}%")
        L.append("")

    # 归因链
    L += ["## 4. 归因链", ""]
    br = ana.get("bridge") or {}
    if br.get("text"):
        L.append(f"- 利润桥：{br['text']}")
    gs = br.get("gross_split") or {}
    if gs:
        L.append(f"- 毛利拆分：规模效应 {gs.get('scale', 0)/1e8:+.2f} 亿、"
                 f"毛利率效应 {gs.get('margin', 0)/1e8:+.2f} 亿")
    vp = br.get("volume_price") or ""
    if vp.startswith("INSUFFICIENT"):
        vp = "证据不足——量价拆分需要主营构成与销量数据，底稿未覆盖，不得自行补原因"
    L.append(f"- 量价拆分：{vp or '证据不足'}")
    L.append("")

    # 一句话
    L += ["## 5. 一句话归因", ""]
    one = brief.conflict_liner(conflicts[0], ana) if conflicts else brief.one_liner(ana)
    L.append(f"> {one}" if one else "> 本期利润桥不可用，一句话归因需人工补。")
    L.append("")

    # 结论
    L += ["## 6. 分型与结论", ""]
    L.append(f"- 分型：{arch.get('name') or '未分型'}（置信度 {arch.get('confidence') or '—'}）")
    for b in (arch.get("basis") or [])[:3]:
        L.append(f"  - {b}")
    risks = ana.get("risks") or []
    if risks:
        L.append(f"- 风险组：{len(risks)} 组")
        for r in risks[:3]:
            L.append(f"  - {r.get('title') or r.get('id') or '—'}（{r.get('severity') or '—'}）")
    L.append("")
    L.append("结论直接说分型 + 该看什么，不复述上面的数字。")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("--period")
    ap.add_argument("--band", type=float, default=0.03,
                    help="钝化门槛，默认 0.03；调严用 0.01，放宽用 0.05")
    a = ap.parse_args()
    ledger, ana, d, period = load(a.code, a.period)
    md = render(ledger, ana, period, a.band)
    out = os.path.join(d, "稿件.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[OK] {out}")


if __name__ == "__main__":
    main()
