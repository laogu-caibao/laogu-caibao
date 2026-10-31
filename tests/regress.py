#!/usr/bin/env python3
"""回归测试：对样本公司跑 collect，检查验收标准。

验收标准（数据层）：
  1. 目标期关键科目（营收、归母、扣非、经营现金流、总资产、总负债、归母权益）均取自公告原文，
     且与至少一个结构化接口差异 ≤0.1%（状态“一致”）；金融类扣非允许缺省。
  2. 底稿中每个可用单元格都有来源（chosen_from 非空）。
  3. 无 error 级问题。
  4. 门禁通过、勾稽无 fail、综合判断层字段齐全、报告无荐股及预期差用语。
用法：python3 tests/regress.py [代码 ...]   不带参数跑默认样本；--offline 只用缓存复现
"""
import json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SAMPLES = [  # 覆盖：周期(B)、成熟(A)、成长(C)、科技/科创板、银行、保险、券商、亏损地产
    ("601899", "紫金矿业", "周期·有色"), ("000333", "美的集团", "成熟·家电（合并及公司表、千元、括号费用）"),
    ("300750", "宁德时代", "成长·创业板"), ("002594", "比亚迪", "成长·汽车（单位为：千元）"),
    ("688981", "中芯国际", "科技·科创板"), ("600036", "招商银行", "银行（无框线表格、百万元）"),
    ("601318", "中国平安", "保险"), ("600030", "中信证券", "券商（主要数据含调整前/后列）"),
    ("000002", "万科A", "地产·亏损"), ("600519", "贵州茅台", "成熟·白酒（附注列为纯数字）"),
]
BANNED = ("买入", "卖出", "增持", "目标价", "推荐", "看多", "看空", "上涨空间", "抄底", "加仓", "减仓", "止损", "超预期", "不及预期")
KEYS = ["rev", "np_parent", "np_ded", "ocf", "ta", "tl", "eq_parent"]


def run(code, out, offline):
    env = dict(os.environ, **({"CBFX_OFFLINE": "1"} if offline else {}))
    t0 = time.time()
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "analyze.py"), code, "--out", out, "--recollect"],
                       capture_output=True, text=True, env=env, timeout=900)
    line = next((l for l in r.stdout.splitlines() if l.startswith("报告：")), None)
    if not line:
        return None, time.time() - t0, (r.stderr or r.stdout)[-500:]
    d = os.path.dirname(line[3:])
    doc = json.load(open(os.path.join(d, "底稿.json"), encoding="utf-8"))
    doc["_analysis"] = json.load(open(os.path.join(d, "分析.json"), encoding="utf-8"))
    doc["_report"] = open(line[3:], encoding="utf-8").read()
    return doc, time.time() - t0, None


def check(doc):
    t = doc["meta"]["target_period"]
    fin = doc["meta"]["company_type"] != "general"
    bad = []
    for k in KEYS:
        c = doc["fields"].get(k, {}).get("values", {}).get(t)
        if not c or not c["usable"]:
            if not (fin and k == "np_ded"):
                bad.append(f"{k}:{c['status'] if c else '无'}")
            continue
        if c["chosen_from"] != "pdf":
            bad.append(f"{k}:非原文({c['chosen_from']})")
        elif c["status"] not in ("一致", "原文自洽") and not (c["status"] == "单一来源" and k == "np_ded"):
            bad.append(f"{k}:{c['status']}")
    orphan = sum(1 for f in doc["fields"].values() for c in f["values"].values() if c["usable"] and not c["chosen_from"])
    errs = [i["msg"] for i in doc["issues"] if i["level"] == "error"]
    # 分析层：每个有值的指标都必须列出输入；报告不得出现荐股用语
    a = doc["_analysis"]
    no_input = [m["name"] for m in a["metrics"].values() if m["value"] is not None and not m["inputs"]]
    if no_input:
        bad.append("指标无输入出处:" + "、".join(no_input))
    g = a.get("gate") or {}
    if g.get("status") != "pass":
        bad.append("门禁未过:" + "；".join(g.get("reasons", [])))
    rf = [r["label"] for r in doc.get("reconciliations", []) if r["status"] == "fail"]
    if rf:
        bad.append("勾稽不通过:" + "、".join(rf))
    for k in ("risks", "tracking_new", "bridge", "persistence"):
        if k not in a:
            bad.append(f"分析缺 {k}")
    hit = [w for w in BANNED if w in doc["_report"]]
    if hit:
        bad.append("荐股用语:" + "、".join(hit))
    return bad, orphan, errs


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    offline = "--offline" in sys.argv
    out = os.environ.get("CBFX_OUT", os.path.join(ROOT, "out"))
    samples = [s for s in SAMPLES if not args or s[0] in args] or [(a, a, "") for a in args]
    rows, ok_all = [], True
    for code, name, kind in samples:
        doc, sec, err = run(code, out, offline)
        if not doc:
            rows.append(f"| {code} {name} | {kind} | — | — | — | ❌ 运行失败：{err} |"); ok_all = False; continue
        bad, orphan, errs = check(doc)
        f0 = doc["filings"][0] if doc["filings"] else {}
        ok = not bad and not orphan and not errs
        ok_all &= ok
        cov = "、".join(f"{k}{v}" for k, v in doc["coverage_target"].items())
        rows.append(f"| {code} {name} | {kind} | {doc['meta']['target_period']} | {f0.get('parsed_fields', 0)} 科目，{cov} | {doc['_analysis']['archetype']['name']} | "
                    f"{'✅' if ok else '❌ ' + '；'.join(bad + errs[:3] + ([f'无来源单元格 {orphan}'] if orphan else []))} | {sec:.0f}s |")
    print("| 公司 | 类型 | 目标期 | 原文解析 / 目标期覆盖 | 分型 | 验收 | 耗时 |\n|---|---|---|---|---|---|---|")
    print("\n".join(rows))
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
