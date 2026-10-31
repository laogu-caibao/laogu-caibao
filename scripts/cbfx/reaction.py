#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
行情反应 · 判断「财报结论」与「股价走势」是否背离

背离才是钩子。两类：
  A 型：财报看着好，股价却跌／不涨
  B 型：财报一般甚至差，股价却见底放量暴涨

判定要同时满足「方向相反」和「幅度显著」，否则只是正常波动，不算矛盾。
不产生任何因果解释——市场为什么这么走，公开数据回答不了，正文一律写「无法确认」。
"""
import json
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}
PREFIX = lambda c: ("sh" if c[0] == "6" else "sz") + c


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def daily(code, start, end):
    """腾讯前复权日 K，返回 [(date, close, volume)]"""
    url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"param={PREFIX(code)},day,{start},{end},320,qfq")
    try:
        d = _get(url)["data"][PREFIX(code)]
        k = d.get("qfqday") or d.get("day") or []
        return [(x[0], float(x[2]), float(x[5])) for x in k]
    except Exception:
        return []


def history(code, count=800):
    """长周期日 K（约 3 年），用于周期股的位置判断"""
    import datetime as _dt
    beg = (_dt.date.today() - _dt.timedelta(days=1100)).isoformat()
    end = _dt.date.today().isoformat()
    url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"param={PREFIX(code)},day,{beg},{end},{count},qfq")
    try:
        d = _get(url)["data"][PREFIX(code)]
        k = d.get("qfqday") or d.get("day") or []
        return [(x[0], float(x[2])) for x in k]
    except Exception:
        return []


def cyclical_hook(ledger, analysis, np_min=0.70, dd_min=-0.25):
    """
    周期股专用钩子：不看公告后几天，看「利润位置 vs 股价位置」。
    利润接近历史峰值、股价却离区间高点很远 —— 这才是周期股的矛盾。
    np_min 默认 0.70（利润至少回到历史峰值的七成），dd_min 默认 -25%。
    """
    if (analysis.get("archetype") or {}).get("archetype") != "B":
        return None
    ttm = ((ledger.get("derived") or {}).get("ttm") or {}).get("np_parent") or {}
    vals = [ttm[p] for p in sorted(ttm) if isinstance(ttm[p], (int, float))]
    if len(vals) < 6:
        return None
    cur_np, peak_np = vals[-1], max(vals)
    if peak_np <= 0:
        return None
    np_ratio = cur_np / peak_np

    code = (ledger.get("meta") or {}).get("code") or ""
    ks = history(code)
    if len(ks) < 60:
        return None
    cur_px = ks[-1][1]
    peak_px = max(x[1] for x in ks)
    dd = cur_px / peak_px - 1 if peak_px else None

    if np_ratio >= np_min and dd is not None and dd <= dd_min:
        return {"verdict": "conflict", "type": "cyclical", "strength": "strong",
                "np_ratio": np_ratio, "drawdown": dd,
                "cur_px": cur_px, "peak_px": peak_px,
                "cur_np": cur_np, "peak_np": peak_np,
                "note": "周期股不比公告后几日反应，比利润位置与股价位置"}
    return {"verdict": "none", "type": "cyclical",
            "np_ratio": np_ratio, "drawdown": dd,
            "cur_px": cur_px, "peak_px": peak_px,
            "reason": "利润与股价位置未同时极端"}


def publish_date(ledger):
    fl = (ledger.get("filings") or [])
    for f in fl:
        if f.get("publish_date"):
            return f["publish_date"]
    return None


def fundamental_tone(analysis, ledger=None):
    """
    把财报结论压成 good / weak / neutral 三档。
    只用底稿能算的东西，不用预测。
    """
    ch = {c["key"]: c for c in (analysis.get("changes") or [])}
    npq = ch.get("np_parent") or {}
    risks = analysis.get("risks") or []
    high = [r for r in risks if (r.get("severity") or "").lower() == "high"]

    np_yoy = npq.get("single_q_yoy")

    # 毛利率同比变化直接由底稿单季序列算，不依赖分析层的字段命名
    gm_chg = None
    if ledger:
        from . import brief
        gs = brief.gm_series(ledger, 6)
        if len(gs) >= 5:
            gm_chg = gs[-1][1] - gs[-5][1]

    score = 0
    if np_yoy is not None:
        score += 1 if np_yoy > 0.15 else (-1 if np_yoy < 0 else 0)
    if gm_chg is not None:
        # 毛利率大幅下滑是「增收不增利」的核心信号，单列重权重
        score += -2 if gm_chg < -0.05 else (1 if gm_chg > 0.02 else 0)
    score += -2 * len(high)

    ind = ((analysis.get("archetype") or {}).get("industry") or {}).get("em") or "—"
    tone = "good" if score >= 2 else ("weak" if score <= -1 else "neutral")
    return {"tone": tone, "score": score, "industry": ind,
            "np_yoy": np_yoy, "gm_chg": gm_chg, "high_risks": len(high)}


def judge(ledger, analysis, windows=(3, 5), band=0.03):
    """
    矛盾定义（用户口径）：股价没有反映财报方向，而非必须反向大幅。

      A 型：财报好，股价却没涨（跌 / 横盘 / 小涨）
      B 型：财报差或一般，股价却没跌（涨 / 横盘 / 小跌）

    窗口先看 3 个交易日，不够（或没命中）再看 5 个；5 日仍未命中则判 none，稿件不写这一节。
    """
    pd = publish_date(ledger)
    if not pd:
        return {"verdict": "unknown", "reason": "底稿无公告披露日"}

    import datetime as _dt
    end = _dt.date.today().isoformat()
    start = pd[:4] + "-" + str(max(1, int(pd[5:7]) - 8)).zfill(2) + "-01"
    ks = daily((ledger.get("meta") or {}).get("code", ""), start, end)
    if not ks:
        return {"verdict": "unknown", "reason": "行情取不到"}

    if pd > end:
        return {"verdict": "unknown",
                "reason": f"公告披露日为 {pd}，尚未到，暂无行情反应"}

    dates = [k[0] for k in ks]
    if pd not in dates:
        after = [d for d in dates if d > pd]
        if not after:
            return {"verdict": "unknown", "reason": "发布日后无交易日"}
        pd = after[0]

    i = dates.index(pd)
    pre20 = ks[max(0, i - 20):i]
    avg_pre = sum(x[2] for x in pre20) / len(pre20) if pre20 else None
    base = ks[i - 1][1] if i > 0 else None
    if not base:
        return {"verdict": "unknown", "reason": "缺公告前收盘价"}

    tone = fundamental_tone(analysis, ledger)
    tt = tone["tone"]

    def pick(move):
        """返回 (类型, 强度) ；强度 strong=方向相反，weak=横盘或幅度不足"""
        if move is None or tt == "neutral":
            return None
        # 反向 = 方向反了；钝化 = 方向对了但幅度不够（涨不到 band）
        # 反向也要过门槛，微跌 1-2% 算钝化不算反向
        if tt == "good":
            if move < -band:
                return ("A", "strong")
            if move < band:
                return ("A", "weak")
        if tt == "weak":
            if move > band:
                return ("B", "strong")
            if move > -band:
                return ("B", "weak")
        return None

    pmoves = {}
    for w in windows:
        post = ks[i:i + w]
        if post:
            pmoves[w] = post[-1][1] / base - 1

    for w in windows:
        post = ks[i:i + w]
        if not post:
            break
        days = len(post)
        move = post[-1][1] / base - 1
        avg = sum(x[2] for x in post) / days
        vr = (avg / avg_pre) if avg_pre else None
        hit = pick(move)

        # 钝化命中后要复核：5 日若已朝正确方向补上，说明只是反应慢，不算矛盾
        if hit and hit[1] == "weak" and 5 in windows and days < 5:
            m5 = pmoves.get(5)
            if m5 is not None:
                if hit[0] == "A" and m5 >= band:
                    hit = None
                elif hit[0] == "B" and m5 <= -band:
                    hit = None

        if hit and days >= min(w, 2):
            ctype, strength = hit
            react = None
            want_up = move > 0
            for idx, (d, c, v) in enumerate(post, start=1):
                prev = post[idx - 2][1] if idx >= 2 else base
                day = c / prev - 1 if prev else 0
                big = (day > 0.05) if want_up else (day < -0.05)
                vol = (avg_pre and v / avg_pre > 2 and ((day > 0) if want_up else (day < 0)))
                if big or vol:
                    react = {"index": idx, "date": d, "day_move": day}
                    break
            return {
                "verdict": "conflict", "type": ctype, "strength": strength,
                "window_days": days, "move": move, "volume_ratio": vr,
                "move_3d": pmoves.get(3), "move_5d": pmoves.get(5),
                "react": react, "publish_date": pd,
                "pre_close": base, "last_close": post[-1][1],
                "tone": tone,
                "note": "市场为什么这么走，公开数据无法确认；只做方向对照，不做因果解释",
            }

        if days < w:
            # 数据还没攒够，先按现有天数判，判不出就等
            break

    return {"verdict": "none", "window_days": len(ks[i:i + max(windows)]),
            "tone": tone, "publish_date": pd,
            "move_3d": pmoves.get(3), "move_5d": pmoves.get(5),
            "reason": "3 日与 5 日均未出现财报与股价的方向错位，本稿不写这一节"}


def render_block(r):
    """给稿件用的一段话；none 时返回空字符串，调用方直接跳过"""
    if r.get("verdict") == "none":
        return ""
    if r.get("verdict") == "unknown":
        return f"- 行情：{r.get('reason')}，无法判断是否背离"

    mv = r.get("move")
    vr = r.get("volume_ratio")
    tt = r["tone"]["tone"]
    tone_cn = {"good": "业绩看着不错", "weak": "业绩一般甚至偏弱",
               "neutral": "业绩平平"}[tt]
    tail = f"（量比 {vr:.1f}×）" if vr else ""
    d = r["window_days"]
    rt = r.get("react") or {}
    where = (f"{d} 个交易日内" if d >= 3 else f"公告后 {d} 个交易日")

    if r["type"] == "A":
        if r["strength"] == "strong":
            body = f"{tone_cn}，股价反而跌了 {abs(mv)*100:.1f}%"
        else:
            body = f"{tone_cn}，股价却只动了 {mv*100:+.1f}%（基本横盘）"
    else:
        if r["strength"] == "strong":
            body = f"{tone_cn}，股价反而涨了 {mv*100:.1f}%"
        else:
            body = f"{tone_cn}，股价却没怎么跌（{mv*100:+.1f}%）"

    line = f"- **矛盾（{r['type']} 型·{'反向' if r['strength']=='strong' else '钝化'}）**：{body}，{where}{tail}"
    if rt:
        line += f"；{rt['date']} 单日 {rt['day_move']*100:+.1f}% 起量"
    return line
