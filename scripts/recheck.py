#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
稿件数据反问 CLI · 脚本出题+机器预填 → 默认大模型作答 → 脚本封卷验收（在去AI味之前）

用法：
  python3 scripts/recheck.py 601899           # 建卷：出 稿件_数据反问.md（8 题+机器事实）
  python3 scripts/recheck.py 601899 --seal    # 封卷：解析作答 → 数据反问.json，不通过 exit 1
  python3 scripts/recheck.py 601899 --reset   # 重建问卷（重新采集/修复后用）

约定：成稿 out/<代码>/<报告期>/稿件_成稿.md；反问卷 稿件_数据反问.md；封卷记录 数据反问.json。
作答由执行本 skill 的默认大模型完成：逐题填「判定：通过/存疑/不通过」，
非通过必须在「依据：」同行写明科目+报告期+原文页码或底稿单元格；Q8 必须写具体反例。
裁定：任一不通过 → 阻断，回 collect/人工核对/analyze 修复后 --reset 重建重问；
存疑 → 可进入去AI味，但稿件必须披露存疑项。
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cbfx import recheck as rc  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve(code, period=None):
    base = os.path.join(ROOT, "out", code)
    if not os.path.isdir(base):
        sys.exit(f"[ERR] 未找到 {base}：先跑 collect/analyze 生成底稿")
    cands = [period] if period else [x for x in os.listdir(base)
                                     if os.path.isdir(os.path.join(base, x)) and x[:4].isdigit()]
    if not cands:
        sys.exit(f"[ERR] {base} 下没有报告期目录")
    d = os.path.join(base, sorted(cands)[-1])
    if not os.path.isfile(os.path.join(d, "底稿.json")):
        sys.exit(f"[ERR] {d}/底稿.json 不存在，先跑 collect.py")
    if not os.path.isfile(os.path.join(d, "稿件_成稿.md")):
        sys.exit(f"[ERR] {d}/稿件_成稿.md 不存在——先写成稿，再做数据反问")
    return d


def load_inputs(d):
    ledger = json.load(open(os.path.join(d, "底稿.json"), encoding="utf-8"))
    ana_fp = os.path.join(d, "分析.json")
    ana = json.load(open(ana_fp, encoding="utf-8")) if os.path.isfile(ana_fp) else {}
    draft = open(os.path.join(d, "稿件_成稿.md"), encoding="utf-8").read()
    traces = []
    for name, label in [("稿件.md", "稿件骨架"), ("快检报告.md", "快检报告"), ("深检报告.md", "深检报告"),
                        ("数据核对报告.md", "数据核对报告"), ("分析.json", "分析.json"), ("底稿.json", "底稿.json")]:
        p = os.path.join(d, name)
        if os.path.isfile(p):
            traces.append((label, open(p, encoding="utf-8").read()))
    if not ana:
        print("[WARN] 分析.json 缺失（先跑 analyze.py），Q3/Q6/Q7 机器事实将不完整")
    return ledger, ana, draft, traces


def do_build(d, reset):
    ledger, ana, draft, traces = load_inputs(d)
    questions = rc.build(ledger, ana, draft, traces)
    meta = dict(ledger.get("meta") or {})
    meta.setdefault("target_period", os.path.basename(d).replace("-deep", ""))
    out = os.path.join(d, "稿件_数据反问.md")
    if os.path.isfile(out) and not reset:
        print(f"[recheck] 问卷已存在，沿用 {out}（--reset 重建）")
    else:
        with open(out, "w", encoding="utf-8") as f:
            f.write(rc.render(questions, meta))
        print(f"[recheck] 问卷已出卷 → {out}")
    print("[recheck] 下一步：由默认大模型逐题作答（判定+依据，Q8 写反例），然后跑 --seal 封卷。")
    return 0


def do_seal(d):
    fp = os.path.join(d, "稿件_数据反问.md")
    if not os.path.isfile(fp):
        sys.exit(f"[ERR] {fp} 不存在——先建卷")
    text = open(fp, encoding="utf-8").read()
    rec, errors = rc.parse(text)
    if errors:
        print("[recheck] 问卷不完整/不合格，未封卷：")
        for e in errors:
            print(f"[recheck] ❌ {e}")
        print("[recheck] 逐条补齐后重跑 --seal。")
        return 1
    ov = rc.overall(rec["questions"])
    meta = json.load(open(os.path.join(d, "底稿.json"), encoding="utf-8")).get("meta") or {}
    record = {"schema": rc.SCHEMA, "code": meta.get("code") or os.path.basename(os.path.dirname(d)),
              "period": meta.get("target_period") or os.path.basename(d).replace("-deep", ""),
              "model": rec["model"], "answered_at": rec["answered_at"],
              "sealed_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
              "overall": ov, "questions": rec["questions"]}
    out = os.path.join(d, "数据反问.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    for a in rec["questions"]:
        print(f"[recheck] {a['id']} {a['verdict']}" + (f"｜{a['basis'][:40]}" if a["basis"] else ""))
    print(f"[recheck] 总体裁定：{ov}；封卷记录 → {out}")
    if ov == "fail":
        print("[recheck] ❌ 存在不通过项——回到对应层修复（collect 重新采集 / 读原文人工核对 / analyze 重跑），"
              "然后 --reset 重建重问。不得发布。")
        return 1
    if ov == "doubt":
        print("[recheck] ⚠️ 有存疑项——稿件必须如实披露存疑内容后才能进入去AI味。")
    print("[recheck] 下一步：python3 scripts/polish.py <代码> 去AI味终检。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="稿件数据反问（建卷 / 封卷）")
    ap.add_argument("code")
    ap.add_argument("--seal", action="store_true", help="封卷：解析作答并验收")
    ap.add_argument("--reset", action="store_true", help="重建问卷")
    ap.add_argument("--period", help="指定报告期目录，默认取最新一期")
    a = ap.parse_args()
    d = resolve(a.code, a.period)
    sys.exit(do_seal(d) if a.seal else do_build(d, a.reset))


if __name__ == "__main__":
    main()
