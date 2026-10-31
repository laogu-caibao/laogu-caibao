#!/usr/bin/env python3
"""在底稿基础上做分析：分型 → 本期变化 → 核心指标 → 红旗 → 估值位置。

用法：
  python3 analyze.py 601899                 # 读 out/601899/<最新期>/底稿.json；没有就先采集
  python3 analyze.py 601899 --mode deep     # 深检：会重新采集深检底稿并写入 分型.json
  python3 analyze.py 601899 --period 2026-09-30
产出：同目录下 分析.json、快检报告.md / 深检报告.md
"""
import argparse, glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cbfx.ledger import Ledger
from cbfx import report_md, analysis, analysis_md


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("code")
    ap.add_argument("--period")
    ap.add_argument("--mode", choices=["quick", "deep"], default="quick")
    ap.add_argument("--out", default=os.environ.get("CBFX_OUT", "out"))
    ap.add_argument("--pdf")
    ap.add_argument("--recollect", action="store_true", help="忽略已有底稿，重新采集")
    a = ap.parse_args()
    log = lambda s: print("·", s, file=sys.stderr)
    doc = None
    if not a.recollect:
        pat = os.path.join(a.out, a.code, (a.period or "????-??-??") + ("-deep" if a.mode == "deep" else ""), "底稿.json")
        for p in sorted(glob.glob(pat), reverse=True):
            d = json.load(open(p, encoding="utf-8"))
            if d["meta"]["mode"] == a.mode:
                doc, out_dir = d, os.path.dirname(p)
                log(f"使用已有底稿：{p}（生成于 {d['meta']['generated_at']}）")
                break
    if doc is None:
        lg = Ledger(a.code, a.period, a.mode, a.out, a.pdf, True, log=log)
        doc = lg.build()
        report_md.write(doc, lg.out_dir)
        out_dir = lg.out_dir
    res = analysis.Analyzer(doc, out_dir, log=log).run()
    path = analysis_md.write(res, doc, out_dir)
    print(res["headline"])
    print(f"报告：{path}")


if __name__ == "__main__":
    main()
