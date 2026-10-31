#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
稿件层 · 从底稿里挑矛盾、排对比表、串归因链

设计依据（用户定的成品形态）：
  - 三表不逐项讲，只给一张「多期对比表」，让观众对着看
  - 用「五看诊断」找矛盾点（方向/连续/波动/拐点/背离），矛盾点当主线
  - 归因链展开后收成一句话归因
  - 结论直接用分型 + 三档，不复述数字

本模块只做「选」和「串」，不产生新数据；所有数字来自底稿 cells。
"""
from statistics import mean, pstdev

YI = 1e8


def _f(x):
    return x if isinstance(x, (int, float)) else None


def seq_bs(ledger, field, n=8):
    """资产负债表科目：取最近 n 个报告期的余额，返回 [(period, value)]"""
    fs = (ledger.get("fields") or {}).get(field) or {}
    vals = fs.get("values") or {}
    out = []
    for p in sorted(vals)[-n:]:
        cell = vals[p]
        if cell.get("usable"):
            v = _f(cell.get("value"))
            if v is not None:
                out.append((p, v))
    return out


def seq_sq(ledger, field, n=8):
    """单季流量科目：取最近 n 期，返回 [(period, value)]"""
    sq = ((ledger.get("derived") or {}).get("single_quarter") or {}).get(field) or {}
    out = [(p, _f(sq[p])) for p in sorted(sq)[-n:]]
    return [(p, v) for p, v in out if v is not None]


def ttm_seq(ledger, field, n=8):
    """TTM 序列，用于判断方向（单季受季节性影响大，斜率会失真）"""
    t = ((ledger.get("derived") or {}).get("ttm") or {}).get(field) or {}
    out = [(p, _f(t[p])) for p in sorted(t)[-n:]]
    return [(p, v) for p, v in out if v is not None]


def _slope(vals):
    n = len(vals)
    if n < 2:
        return 0.0
    xm = (n - 1) / 2
    ym = mean(vals)
    num = sum((i - xm) * (v - ym) for i, v in enumerate(vals))
    den = sum((i - xm) ** 2 for i in range(n))
    return num / den if den else 0.0


def five_looks(vals):
    """
    五看诊断：方向 / 连续 / 波动 / 拐点 / 同比
    返回可直接进稿件的口语化描述
    """
    if len(vals) < 2:
        return {}
    s = _slope(vals[-4:]) if len(vals) >= 4 else _slope(vals)
    base = abs(mean(vals[-4:] if len(vals) >= 4 else vals)) or 1
    annual = s * 4 / base

    direction = "向上" if annual > 0.05 else ("向下" if annual < -0.05 else "基本持平")

    streak, sign = 1, None
    for i in range(len(vals) - 1, 0, -1):
        d = vals[i] - vals[i - 1]
        sg = 1 if d > 0 else (-1 if d < 0 else 0)
        if sign is None:
            sign = sg
        elif sg == sign and sg != 0:
            streak += 1
        else:
            break

    cv = pstdev(vals) / abs(mean(vals)) if len(vals) >= 3 and mean(vals) else 0
    volatility = "平稳" if cv < 0.15 else ("有波动" if cv <= 0.35 else "大幅波动")

    turning = ""
    if len(vals) >= 6:
        a, b = _slope(vals[-6:-3]), _slope(vals[-3:])
        if a * b < 0:
            turning = "斜率反转"

    yoy = None
    if len(vals) >= 5 and vals[-5]:
        yoy = (vals[-1] - vals[-5]) / abs(vals[-5])

    return {"direction": direction, "streak": streak,
            "streak_sign": sign, "volatility": volatility,
            "turning": turning, "yoy": yoy, "slope_pct": annual}


def gm_series(ledger, n=8):
    """毛利率序列（单季）"""
    rev = dict(seq_sq(ledger, "rev", n + 2))
    cost = dict(seq_sq(ledger, "cost", n + 2))
    out = []
    for p in sorted(set(rev) & set(cost))[-n:]:
        if rev[p]:
            out.append((p, (rev[p] - cost[p]) / rev[p]))
    return out


def _lvl(ts, idx=-1):
    return ts[idx][1] if len(ts) > abs(idx) else None


def detect_conflicts(ledger, n=8):
    """
    六组背离配对。每组给：名字、涉及的两个方向、强度分、证据句。
    强度分用于排序，分越高越该当主线。
    """
    rev = seq_sq(ledger, "rev", n + 1)
    npq = seq_sq(ledger, "np_parent", n + 1)
    ocf = seq_sq(ledger, "ocf", n + 1)
    ar = seq_bs(ledger, "ar", n + 1)
    inv = seq_bs(ledger, "inv", n + 1)
    cl = seq_bs(ledger, "contract_liab", n + 1)
    sales_cash = seq_sq(ledger, "sales_cash", n + 1)
    gm = gm_series(ledger, n + 1)

    r5, n5, o5 = five_looks([v for _, v in rev]), five_looks([v for _, v in npq]), five_looks([v for _, v in ocf])
    gm_now, gm_ly = _lvl(gm), _lvl(gm, -5)
    out = []

    # 1 收入涨、毛利跌
    if r5 and gm_now is not None and gm_ly is not None:
        d = gm_now - gm_ly
        if (r5.get("yoy") or 0) > 0.10 and d < -0.03:
            out.append({
                "key": "rev_up_gm_down", "score": abs(d) * 100 + (r5["yoy"] or 0) * 50,
                "name": "收入在涨，毛利率在跌",
                "evidence": f"单季营收同比 {r5['yoy']*100:+.1f}%，毛利率 {gm_ly*100:.1f}%→{gm_now*100:.1f}%（{d*100:+.1f}pct）",
                "chain": ["rev", "cost", "gm"],
            })

    # 2 利润涨、现金弱
    if n5 and o5 and (n5.get("yoy") or 0) > 0 and _lvl(ocf) is not None and _lvl(ocf) < 0:
        out.append({
            "key": "np_up_ocf_neg", "score": 60,
            "name": "利润在涨，经营现金流为负",
            "evidence": f"单季归母同比 {n5['yoy']*100:+.1f}%，经营现金流 {_lvl(ocf)/YI:+.2f} 亿",
            "chain": ["np_parent", "ocf"],
        })

    # 3 收入涨、预收跌
    if r5 and len(cl) >= 5 and cl[-5][1]:
        dc = (cl[-1][1] - cl[-5][1]) / abs(cl[-5][1])
        if (r5.get("yoy") or 0) > 0.10 and dc < -0.20:
            out.append({
                "key": "rev_up_cl_down", "score": abs(dc) * 40,
                "name": "收入在涨，预收款在缩",
                "evidence": f"营收同比 {r5['yoy']*100:+.1f}%，合同负债 {cl[-5][1]/YI:.2f}→{cl[-1][1]/YI:.2f} 亿（{dc*100:+.1f}%）",
                "chain": ["rev", "contract_liab"],
            })

    # 4 应收跑赢收入
    if r5 and len(ar) >= 5 and ar[-5][1]:
        da = (ar[-1][1] - ar[-5][1]) / abs(ar[-5][1])
        gap = da - (r5.get("yoy") or 0)
        if gap > 0.20:
            out.append({
                "key": "ar_gap", "score": gap * 60,
                "name": "应收跑得比收入快",
                "evidence": f"应收 {da*100:+.1f}%，营收 {(r5['yoy'] or 0)*100:+.1f}%，差 {gap*100:+.1f}pct",
                "chain": ["rev", "ar"],
            })

    # 5 存货跑赢收入且毛利下滑
    if r5 and len(inv) >= 5 and inv[-5][1] and gm_now is not None and gm_ly is not None:
        di = (inv[-1][1] - inv[-5][1]) / abs(inv[-5][1])
        gap = di - (r5.get("yoy") or 0)
        if gap > 0.20 and gm_now < gm_ly:
            out.append({
                "key": "inv_gap", "score": gap * 60,
                "name": "存货跑得比收入快，且毛利在跌",
                "evidence": f"存货 {di*100:+.1f}%，营收 {(r5['yoy'] or 0)*100:+.1f}%，毛利率 {gm_ly*100:.1f}%→{gm_now*100:.1f}%",
                "chain": ["rev", "inv", "cost"],
            })

    # 6 现金转正、收现比走低
    if len(ocf) >= 2 and len(sales_cash) >= 1 and len(rev) >= 1:
        cr = _lvl(sales_cash) / _lvl(rev) if _lvl(rev) else None
        if _lvl(ocf, -2) is not None and _lvl(ocf, -2) < 0 < _lvl(ocf) and cr and cr < 0.85:
            out.append({
                "key": "ocf_up_cash_down", "score": (0.85 - cr) * 120,
                "name": "现金流转正，但收现比在跌",
                "evidence": f"经营现金流 {_lvl(ocf, -2)/YI:+.2f}→{_lvl(ocf)/YI:+.2f} 亿，收现比 {cr:.2f}",
                "chain": ["ocf", "sales_cash", "ar", "ap"],
            })

    out.sort(key=lambda x: -x["score"])
    return out


def compare_table(ledger, n=6):
    """
    张新民式对比表：一行一个指标，列是最近 n 期 + 同比。
    金额统一亿元，比率带 %。
    """
    rows = []
    rev = dict(seq_sq(ledger, "rev", n + 4))
    cost = dict(seq_sq(ledger, "cost", n + 4))
    npq = dict(seq_sq(ledger, "np_parent", n + 4))
    npd = dict(seq_sq(ledger, "np_ded", n + 4))
    ocf = dict(seq_sq(ledger, "ocf", n + 4))
    periods = sorted(rev)[-n:]

    def add(label, d, fmt, kind="amt"):
        vals = [d.get(p) for p in periods]
        last = vals[-1]
        ly = d.get(periods[-5]) if len(periods) >= 5 else None
        if last is None or ly is None:
            txt = "—"
        elif kind == "ratio":
            # 比率看百分点差，不看相对变化
            txt = f"{(last - ly) * 100:+.1f}pct"
        elif ly < 0 < last:
            txt = "由负转正"
        elif ly > 0 > last:
            txt = "由正转负"
        else:
            txt = f"{(last - ly) / abs(ly) * 100:+.1f}%"
        rows.append({"label": label, "values": vals, "fmt": fmt, "yoy_text": txt})

    add("单季营收（亿）", {p: (rev[p] / YI if rev.get(p) is not None else None) for p in periods}, "{:,.2f}")
    add("单季归母（亿）", {p: (npq[p] / YI if npq.get(p) is not None else None) for p in periods}, "{:,.2f}")
    add("单季扣非（亿）", {p: (npd[p] / YI if npd.get(p) is not None else None) for p in periods}, "{:,.2f}")
    add("经营现金流（亿）", {p: (ocf[p] / YI if ocf.get(p) is not None else None) for p in periods}, "{:,.2f}")
    add("毛利率", {p: ((rev[p] - cost[p]) / rev[p] if rev.get(p) and cost.get(p) is not None else None)
                 for p in periods}, "{:.1%}", kind="ratio")
    return {"periods": periods, "rows": rows}


def conflict_liner(conflict, analysis):
    """
    针对主矛盾的一句话归因。
    「收入涨、毛利跌」优先用毛利拆分（规模效应 vs 毛利率效应），
    因为它正好把矛盾的两股力拆开。
    """
    br = (analysis or {}).get("bridge") or {}
    gs = br.get("gross_split") or {}
    if conflict.get("key") == "rev_up_gm_down" and gs:
        sc = (gs.get("scale") or 0) / YI
        mg = (gs.get("margin") or 0) / YI
        net = sc + mg
        return (f"收入增长本该带来 {sc:+.2f} 亿毛利，但毛利率下滑又吃掉 {mg:+.2f} 亿，"
                f"两股力相抵只剩 {net:+.2f} 亿。")
    if conflict.get("key") == "ocf_up_cash_down":
        return "现金流改善来自占用上游账期，不是回款变好。"
    if conflict.get("key") == "rev_up_cl_down":
        return "收入在涨而预收款在缩，说明从客户先给钱变成了自己先垫钱。"
    return one_liner(analysis)


def one_liner(analysis):
    """
    一句话归因：从利润桥里取最大拉动与最大拖累，压成一句。
    数据不足时返回 None，由调用方写"证据不足"。
    """
    br = (analysis or {}).get("bridge") or {}
    if not br:
        return None
    items = br.get("items") or br.get("parts") or []
    if not items:
        return None
    try:
        s = sorted(items, key=lambda x: -(x.get("delta") or 0))
    except Exception:
        return None
    if not s:
        return None
    lead = s[0]
    drag = s[-1]
    ld = (lead.get("delta") or 0) / YI
    dd = (drag.get("delta") or 0) / YI
    if ld <= 0:
        return None
    return (f"利润的增量几乎全部来自{lead.get('name', '?')}（{ld:+.2f} 亿），"
            f"{drag.get('name', '?')}拖了 {dd:+.2f} 亿。")
