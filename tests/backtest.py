#!/usr/bin/env python3
"""历史回放评测：把分析层放回历史时点（只用当时的接口数据，不读原文、不估值、不写跟踪/分型），
看它对“之后两年出事”的公司是否给出高风险预警，对正常公司是否误报。

用法：python3 tests/backtest.py [--out /tmp/cbfx_bt] [--only 600518,600519]
结局定义（cutoff 年报之后两个年度内任一满足即“出事”）：
  ① 归母净利润转亏；② 归母净利润较 cutoff 年下降 >50%；③ 当年资产+信用减值损失 > cutoff 年归母净利润绝对值的 30%。
已知局限：东财/新浪接口给的是**追溯调整后**的数，财务造假公司（如康美）更正后的数会提前“泄露”到历史期，
因此造假样本的召回率偏乐观；正常样本的误报率不受此影响，是更可信的指标。
"""
import argparse, json, os, sys
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from cbfx.ledger import Ledger
from cbfx import analysis

# (代码, cutoff 年报, 组别, 备注)
SAMPLES = [
    ("600518", 2017, "暴雷", "康美药业：2018 年报巨亏、货币资金造假"),
    ("002069", 2013, "暴雷", "獐子岛：2014 年存货（扇贝）大额核销转亏"),
    ("000413", 2018, "暴雷", "东旭光电：2019–2020 年业绩骤降、债务违约"),
    ("002450", 2017, "暴雷", "康得新：2018 年起巨亏、财务造假"),
    ("300116", 2016, "暴雷", "坚瑞沃能（保力新）：2017 年巨额商誉减值转亏"),
    ("002680", 2017, "暴雷", "长生生物：2018 年疫苗事件"),
    ("600519", 2017, "对照", "贵州茅台"),
    ("000333", 2017, "对照", "美的集团"),
    ("000651", 2017, "对照", "格力电器"),
    ("600900", 2017, "对照", "长江电力"),
    ("002415", 2017, "对照", "海康威视"),
    ("601899", 2018, "对照", "紫金矿业"),
]


def val(doc, k, p):
    c = ((doc["fields"].get(k) or {}).get("values") or {}).get(p) or {}
    return c.get("value")


def one(args):
    code, y, grp, note, out = args
    q = lambda s: None
    r = {"code": code, "cutoff": f"{y}-12-31", "group": grp, "note": note}
    try:
        lg = Ledger(code, f"{y}-12-31", "deep", out, None, False, log=q)
        doc = lg.build()
        r["name"] = doc["meta"]["name"]
        a = analysis.Analyzer(doc, lg.out_dir, log=q, track=False, valuation=False, persist_archetype=False).run()
        r["risks"] = [(g["title"], g["severity"]) for g in a["risks"]]
        r["archetype"] = a["archetype"]["name"]
        sev = {g["severity"] for g in a["risks"]}
        conflict = [x for x in a["gate"]["reasons"] if "冲突" in x]
        r["pred"] = ("数据冲突" if conflict else "高风险" if "high" in sev else "关注" if "medium" in sev else "无")
        if conflict:
            r["risks"] = [("门禁：" + "；".join(conflict), "-")] + r["risks"]
    except Exception as e:
        r["pred"], r["error"] = "数据不可得", f"历史期：{e}"
        return r
    try:
        lo = Ledger(code, f"{y + 2}-12-31", "quick", out, None, False, log=q).build()
        base = val(lo, "np_parent", f"{y}-12-31") or val(doc, "np_parent", f"{y}-12-31")
        why = []
        for yy in (y + 1, y + 2):
            p = f"{yy}-12-31"
            np_ = val(lo, "np_parent", p)
            if np_ is None:
                continue
            imp = abs(val(lo, "asset_impair", p) or 0) + abs(val(lo, "credit_impair", p) or 0)
            if np_ < 0:
                why.append(f"{yy} 转亏（{np_ / 1e8:.1f} 亿）")
            elif base and base > 0 and np_ < 0.5 * base:
                why.append(f"{yy} 归母降 {1 - np_ / base:.0%}")
            if base and imp > 0.3 * abs(base):
                why.append(f"{yy} 减值 {imp / 1e8:.1f} 亿（>{0.3 * abs(base) / 1e8:.1f}）")
        r["outcome"] = "出事" if why else "正常"
        r["why"] = why
    except Exception as e:
        r["outcome"], r["error"] = "结局不可得", f"结局期：{e}"
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/cbfx_bt")
    ap.add_argument("--only")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    S = [s for s in SAMPLES if not a.only or s[0] in a.only.split(",")]
    with ProcessPoolExecutor(a.workers) as ex:
        res = list(ex.map(one, [(*s, a.out) for s in S]))
    L = ["# 历史回放评测结果", "", "| 组别 | 公司 | cutoff | 分析层判断 | 风险组 | 实际结局 | 依据 |", "|---|---|---|---|---|---|---|"]
    for r in res:
        rk = "；".join(f"{t}({s})" for t, s in r.get("risks", [])) or "—"
        L.append(f"| {r['group']} | {r.get('name', r['code'])}（{r['code']}） | {r['cutoff']} | {r['pred']} | {rk} | "
                 f"{r.get('outcome', '—')} | {'；'.join(r.get('why', [])) or r.get('error', '') or '—'} |")
    ok = [r for r in res if r.get("outcome") in ("出事", "正常") and r["pred"] != "数据不可得"]
    bad = [r for r in ok if r["outcome"] == "出事"]
    good = [r for r in ok if r["outcome"] == "正常"]
    tp = sum(r["pred"] == "高风险" for r in bad)
    fp = sum(r["pred"] == "高风险" for r in good)
    tp2 = sum(r["pred"] in ("高风险", "关注", "数据冲突") for r in bad)
    fp2 = sum(r["pred"] in ("高风险", "关注", "数据冲突") for r in good)
    L += ["", f"- 可评估样本 {len(ok)} 家：出事 {len(bad)}，正常 {len(good)}",
          f"- 召回（出事样本中给出高风险组）：{tp}/{len(bad)}" + ("" if not bad else f" = {tp / len(bad):.0%}"),
          f"- 误报（正常样本中给出高风险组）：{fp}/{len(good)}" + ("" if not good else f" = {fp / len(good):.0%}"),
          f"- 宽口径（高风险/关注/数据冲突 均算提示）：召回 {tp2}/{len(bad)}，误报 {fp2}/{len(good)}",
          "- “数据冲突”= 两个接口对同一历史期给出不同数（常见于事后更正/追溯调整），门禁直接拦截，本身就是需要人工核查的信号。",
          "- 局限：接口数据为追溯调整后口径，造假样本召回偏乐观；样本量小，只用于发现规则明显失灵，不用于宣称准确率。"]
    print("\n".join(L))
    json.dump(res, open(os.path.join(a.out, "backtest.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
