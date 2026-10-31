#!/usr/bin/env python3
"""采集并核对一家 A 股公司某报告期的财务底稿。

用法：
  python3 collect.py 601899                      # 最新一期，季报快检
  python3 collect.py 601899 --period 2026-09-30  # 指定报告期
  python3 collect.py 601899 --mode deep          # 年报深检（10 年年度序列 + 最近年报原文）
  python3 collect.py 601899 --pdf 本地报告.pdf    # 网络取不到原文时，用你提供的 PDF
产出：out/<代码>/<报告期>/底稿.json、数据核对报告.md、filings/、raw/
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cbfx.ledger import Ledger
from cbfx import report_md


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("code")
    ap.add_argument("--period", help="报告期，如 2026-09-30")
    ap.add_argument("--mode", choices=["quick", "deep"], default="quick")
    ap.add_argument("--out", default=os.environ.get("CBFX_OUT", "out"))
    ap.add_argument("--pdf", help="本地定期报告 PDF（替代巨潮下载）")
    ap.add_argument("--no-pdf", action="store_true", help="不取原文（只做接口互核，结论须标草稿）")
    a = ap.parse_args()
    lg = Ledger(a.code, a.period, a.mode, a.out, a.pdf, not a.no_pdf, log=lambda s: print("·", s, file=sys.stderr))
    doc = lg.build()
    path = report_md.write(doc, lg.out_dir)
    errs = sum(1 for i in doc["issues"] if i["level"] == "error")
    warns = sum(1 for i in doc["issues"] if i["level"] == "warn")
    print(f"完成：{doc['meta']['name']} {doc['meta']['target_period']}　错误 {errs}　注意 {warns}")
    print(f"底稿：{os.path.join(lg.out_dir, '底稿.json')}")
    print(f"核对报告：{path}")
    sys.exit(2 if errs else 0)


if __name__ == "__main__":
    main()
