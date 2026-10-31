#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据反问探针 · 离线验收出卷、机器事实预填、作答解析与封卷裁定（不联网）

用法：python3 tests/recheck_probe.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from cbfx import recheck as rc  # noqa: E402

LEDGER = {
    "meta": {"code": "600519", "name": "贵州茅台", "target_period": "2026-06-30"},
    "periods": ["2026-06-30", "2026-03-31", "2025-12-31"],
    "fields": {
        "rev": {"values": {
            "2026-06-30": {"value": 8.34e10, "status": "一致", "usable": True},
            "2026-03-31": {"value": 4.0e10, "status": "一致", "usable": True},
            "2025-12-31": {"value": 1.7e11, "status": "冲突", "usable": False},
        }},
        "np_parent": {"values": {"2026-06-30": {"value": 4.065e10, "status": "一致", "usable": True}}},
    },
    "issues": [
        {"level": "error", "field": "rev", "period": "2025-12-31", "msg": "来源冲突 >1%"},
        {"level": "warn", "field": "ocf", "period": "2026-06-30", "msg": "来源间小幅差异"},
    ],
    "reconciliations": [
        {"name": "yoy_base", "label": "同比基数=原文比较列", "period": "2026-06-30", "status": "pass", "note": ""},
        {"name": "open_eq", "label": "期初=原文期初列", "period": "2026-06-30", "status": "warn", "note": "四舍五入"},
    ],
    "quote": {"snapshots": [{"source": "腾讯", "as_of": "2026-10-30", "price": 1392.05}]},
}

ANA = {
    "headline": "单季营收同比 +8.1%，归母 +5.2%",
    "gate": {"status": "draft", "reasons": ["原文未读取"]},
    "bridge": {"status": "ok", "text": "毛利 +21 亿、税金 -3 亿", "gross_split": {"scale": 1.5e9, "margin": 0.6e9}},
    "risks": [{"title": "回款变差", "severity": "high"}],
    "valuation": {"current": {"price": 1392.05}, "history": {"months": 36, "from": "2023-10", "to": "2026-10"}},
}

DRAFT = """# 贵州茅台 2026-06-30 稿件

营收 834.2 亿，同比 +8.1%，归母净利 406.5 亿。单季毛利率 91.2%，同比降 0.3 个点。
777 是一个待解释数字。
"""

TRACE = [
    ("稿件骨架", "营业总收入 834.2 亿；归母净利 406.5 亿；单季同比 +8.1%；毛利率 91.2%，降 0.3 个点"),
    ("分析.json", json.dumps(ANA, ensure_ascii=False)),
    ("底稿.json", json.dumps(LEDGER, ensure_ascii=False)),
]

LONG_BASIS = "777 已在底稿.json 备注列找到出处；其余数字与底稿单元格逐一对照一致"
CHECKS = []


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond), detail))


def has(errors, key):
    return any(key in e for e in errors)


def main():
    # ---- 1. 出卷与机器事实 ----
    qs = rc.build(LEDGER, ANA, DRAFT, TRACE)
    check("出 8 道题", [q["id"] for q in qs] == [f"Q{i}" for i in range(1, 9)],
          str([q["id"] for q in qs]))
    q1 = " ".join(qs[0]["facts"])
    check("Q1 检出待解释数字 777", "777" in q1)
    check("Q1 追溯语料含底稿", "底稿.json" in q1)
    q2 = " ".join(qs[1]["facts"])
    check("Q2 预填关键科目近 3 期", "83,400,000,000" in q2 and "归母净利润" in q2, q2[:80])
    q5 = " ".join(qs[4]["facts"])
    check("Q5 列出冲突科目与 error", "rev@2025-12-31=冲突" in q5 and "error 级问题 1 项" in q5)
    q6 = " ".join(qs[5]["facts"])
    check("Q6 预填门禁 draft 与勾稽 warn", "status=draft" in q6 and "原文未读取" in q6 and "期初=原文期初列@2026-06-30=warn" in q6)
    q7 = " ".join(qs[6]["facts"])
    check("Q7 预填行情与估值样本", "反应判定：" in q7 and "36 个月" in q7, q7[:80])

    md = rc.render(qs, LEDGER["meta"])
    check("出卷含署名/判定/依据槽位", "审查模型：" in md and md.count("判定：\n") == 8 and md.count("依据：\n") == 8)

    # ---- 2. 解析与拦截 ----
    rec, errors = rc.parse(md)
    check("空白卷：署名+8 题判定全报错", not rec["model"] and len([e for e in errors if "判定未填" in e]) == 8
          and has(errors, "未署名") and has(errors, "作答时间"), "；".join(errors[:4]))

    filled = md.replace("审查模型：\n", "审查模型：GLM-5.3-Flash\n", 1)
    filled = filled.replace("作答时间：\n", "作答时间：2026-10-31 10:00\n", 1)
    ok_all = filled.replace("判定：\n依据：\n", f"判定：通过\n依据：{LONG_BASIS}\n")
    rec, errors = rc.parse(ok_all)
    check("全通过卷：解析无错", not errors and rec["model"] == "GLM-5.3-Flash"
          and all(a["verdict"] == "通过" for a in rec["questions"]), "；".join(errors[:4]))
    check("全通过 → 裁定 pass", rc.overall(rec["questions"]) == "pass")

    short = filled.replace("判定：\n依据：\n", "判定：通过\n依据：同上\n")
    _, errors = rc.parse(short)
    check("Q8 依据 <20 字 → 拦截", has(errors, "Q8"), "；".join(errors))

    doubt_one = filled.replace("判定：\n依据：\n", "判定：通过\n依据：见底稿同值\n")\
                      .replace("判定：通过\n依据：见底稿同值", "判定：存疑", 1)
    _, errors = rc.parse(doubt_one)
    check("存疑缺依据 → 拦截", has(errors, "依据缺失"), "；".join(errors))

    fail_filled = ok_all.replace("判定：通过", "判定：不通过", 1)
    rec, errors = rc.parse(fail_filled)
    check("不通过卷解析无错（有依据）", not errors)
    check("有不通过 → 裁定 fail", rc.overall(rec["questions"]) == "fail")

    check("有存疑 → 裁定 doubt",
          rc.overall([{"verdict": "通过"}] * 7 + [{"verdict": "存疑"}]) == "doubt")
    check("题数不足 → 裁定 incomplete", rc.overall([{"verdict": "通过"}]) == "incomplete")

    # ---- 4. Q1 机器闸：待解释数字必须逐个给出出处 ----
    marker = [l for l in md.splitlines() if l.startswith("- 【待解释数字】")]
    check("出卷含待解释数字机器行（含 777）", len(marker) == 1 and "777" in marker[0], str(marker))

    untraced = filled.replace("判定：\n依据：\n", "判定：通过\n依据：与底稿核对一致\n")
    _, errors = rc.parse(untraced)
    check("通过但依据未提 777 → 拦截", has(errors, "未逐个给出出处") and has(errors, "777"), "；".join(errors[:4]))

    traced = filled.replace("判定：\n依据：\n",
                            "判定：通过\n依据：777 出自用户提供的分红明细，其余与底稿单元格一致\n")
    rec, errors = rc.parse(traced)
    check("依据逐个给出 777 出处 → 放行", not errors, "；".join(errors[:4]))

    qs2 = rc.build(LEDGER, ANA, DRAFT.replace("777 是一个待解释数字。\n", ""), TRACE)
    md2 = rc.render(qs2, LEDGER["meta"])
    m2 = [l for l in md2.splitlines() if l.startswith("- 【待解释数字】")]
    check("全部可追溯时机器行为「无」", len(m2) == 1 and m2[0].endswith("无"), str(m2))
    filled2 = md2.replace("审查模型：\n", "审查模型：M\n", 1).replace("作答时间：\n", "作答时间：T\n", 1)
    filled2 = filled2.replace("判定：\n依据：\n", "判定：通过\n依据：同上\n")
    _, errors = rc.parse(filled2)
    check("无待解释数字：通用依据不拦 Q1", not has(errors, "待解释数字"), "；".join(errors[:4]))

    rej = filled.replace("判定：\n依据：\n", "判定：通过\n依据：见底稿\n")
    rej = rej.replace("判定：通过\n依据：见底稿", "判定：不通过\n依据：Q1 存在无出处数字，退回采集层", 1)
    _, errors = rc.parse(rej)
    check("Q1 判不通过 → 豁免逐个出处（整体已阻断）", not has(errors, "未逐个给出出处"), "；".join(errors[:4]))

    # ---- 汇总 ----
    rows = [f"{'✅' if ok else '❌'} {name}" + (f"（{detail}）" if detail and not ok else "")
            for name, ok, detail in CHECKS]
    print("\n".join(rows))
    bad = sum(1 for _, ok, _ in CHECKS if not ok)
    print(f"\n{len(CHECKS) - bad}/{len(CHECKS)} 通过")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
