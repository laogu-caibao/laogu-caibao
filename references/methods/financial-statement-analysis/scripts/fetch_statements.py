#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_statements.py — 抓取 A 股上市公司三大报表（利润表 / 资产负债表 / 现金流量表）多年明细。

数据源：新浪财经 F10（vFD_ProfitStatement / vFD_BalanceSheet / vFD_CashFlow）
用途：westock CLI 的 cashflow/income 接口只返回汇总口径、缺明细科目；
      张新民框架所需的「购建固定资产支付的现金」「投资支付的现金」「取得借款收到的现金」
      「分配股利支付的现金」「未分配利润」「盈余公积」等必须从本脚本取。

输出：
  <out>/<code>_income.md   行=科目，列=报告期（升序），单位亿元
  <out>/<code>_balance.md
  <out>/<code>_cashflow.md
  同时输出同名 .json（供后续计算，值为原始字符串）

用法：
  python fetch_statements.py 000651
  python fetch_statements.py 000651 --years 2016-2025 --out F:/tmp
  python fetch_statements.py 000651 --only cashflow --unit 亿元
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from html.parser import HTMLParser

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

URLS = {
    "income": "https://money.finance.sina.com.cn/corp/go.php/vFD_ProfitStatement/stockid/{code}/ctrl/{year}/displaytype/4.phtml",
    "balance": "https://money.finance.sina.com.cn/corp/go.php/vFD_BalanceSheet/stockid/{code}/ctrl/{year}/displaytype/4.phtml",
    "cashflow": "https://money.finance.sina.com.cn/corp/go.php/vFD_CashFlow/stockid/{code}/ctrl/{year}/displaytype/4.phtml",
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


class TableCollector(HTMLParser):
    """收集页面中所有 <table> 的二维内容。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._stack = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._stack.append({"rows": [], "row": None, "cell": None})
        elif tag == "tr" and self._stack:
            self._stack[-1]["row"] = []
        elif tag in ("td", "th") and self._stack:
            if self._stack[-1]["row"] is None:
                self._stack[-1]["row"] = []
            self._stack[-1]["cell"] = []

    def handle_endtag(self, tag):
        if not self._stack:
            return
        top = self._stack[-1]
        if tag in ("td", "th"):
            if top["cell"] is not None:
                txt = re.sub(r"[\s\u3000\xa0]+", " ", "".join(top["cell"])).strip()
                if top["row"] is None:
                    top["row"] = []
                top["row"].append(txt)
                top["cell"] = None
        elif tag == "tr":
            if top["row"] is not None:
                top["rows"].append(top["row"])
                top["row"] = None
        elif tag == "table":
            self.tables.append(top["rows"])
            self._stack.pop()

    def handle_data(self, data):
        if self._stack and self._stack[-1]["cell"] is not None:
            self._stack[-1]["cell"].append(data)


def fetch(url, retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://money.finance.sina.com.cn/"})
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read()
            for enc in ("gbk", "gb18030", "utf-8"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("gbk", errors="ignore")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"抓取失败 {url} -> {last}")


def pick_table(html):
    p = TableCollector()
    p.feed(html)
    if not p.tables:
        return None
    # 取行数最多的表格（财务报表本体）
    return max(p.tables, key=lambda t: len(t))


NUM_RE = re.compile(r"^-?[\d,]+(?:\.\d+)?$")


def parse_sheet(html):
    """返回 (periods, {科目: {期: 原始字符串}})"""
    rows = pick_table(html)
    if not rows or len(rows) < 2:
        return [], {}
    header = None
    for r in rows:
        joined = "".join(r)
        if re.search(r"\d{4}-\d{2}-\d{2}", joined):
            header = r
            break
    if header is None:
        return [], {}
    periods = []
    for c in header[1:]:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", c)
        periods.append(m.group(1) if m else c.strip() or f"col{len(periods)}")
    data = {}
    for r in rows:
        if not r or r is header:
            continue
        name = re.sub(r"\s+", "", r[0])
        if not name or name in ("报告期", "报表日期", "会计年度"):
            continue
        name = re.sub(r"[\u3000\xa0]", "", name).strip()
        vals = {}
        for i, per in enumerate(periods):
            v = r[i + 1].strip() if i + 1 < len(r) else ""
            v = v.replace(",", "").replace("%", "").strip()
            if v in ("", "--", "-", "—"):
                v = ""
            vals[per] = v
        if any(v for v in vals.values()):
            data.setdefault(name, {}).update(vals)
    return periods, data


def to_yi(v):
    """新浪 F10 单位为万元 -> 亿元"""
    if v in ("", None):
        return None
    try:
        return round(float(v) / 10000.0, 2)
    except ValueError:
        return None


def collect(code, kind, years):
    periods_all, data_all = [], {}
    for y in years:
        url = URLS[kind].format(code=code, year=y)
        try:
            html = fetch(url)
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] {kind} {y}: {e}", file=sys.stderr)
            continue
        periods, data = parse_sheet(html)
        for p in periods:
            if p not in periods_all:
                periods_all.append(p)
        for k, v in data.items():
            data_all.setdefault(k, {}).update(v)
        print(f"  [ok] {kind} {y}: {len(data)} 科目 / {len(periods)} 期", file=sys.stderr)
    periods_all = sorted(set(periods_all))
    return periods_all, data_all


def write_md(path, periods, data, unit_factor):
    lines = []
    head = ["科目"] + periods
    lines.append("| " + " | ".join(head) + " |")
    lines.append("|" + "|".join(["---"] * len(head)) + "|")
    for name in sorted(data.keys()):
        cells = []
        for p in periods:
            raw = data[name].get(p, "")
            if raw == "":
                cells.append("")
            else:
                v = to_yi(raw) if unit_factor == "亿元" else raw
                cells.append("" if v is None else f"{v}")
        lines.append("| " + name + " | " + " | ".join(cells) + " |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("code", help="6 位股票代码，如 000651 / 600690")
    ap.add_argument("--years", default="2016-2025", help="抓取年份区间，如 2016-2025")
    ap.add_argument("--out", default=".", help="输出目录")
    ap.add_argument("--only", default="income,balance,cashflow", help="只抓指定报表，逗号分隔")
    ap.add_argument("--unit", default="亿元", choices=["亿元", "raw"], help="输出单位")
    ap.add_argument("--period", default="annual", choices=["annual", "all"], help="annual=只保留 12-31 年报；all=保留全部期")
    ap.add_argument("--extra", default="", help="额外保留的报告期，逗号分隔，如 2026-06-30")
    args = ap.parse_args()

    m = re.match(r"^(\d{4})\s*-\s*(\d{4})$", args.years)
    if m:
        years = list(range(int(m.group(1)), int(m.group(2)) + 1))
    else:
        years = [int(x) for x in re.findall(r"\d{4}", args.years)]
    years = sorted(set(years))

    os.makedirs(args.out, exist_ok=True)
    kinds = [k.strip() for k in args.only.split(",") if k.strip() in URLS]
    if not kinds:
        print("无有效报表类型", file=sys.stderr)
        sys.exit(1)

    for kind in kinds:
        print(f"抓取 {kind} ...", file=sys.stderr)
        periods, data = collect(args.code, kind, years)
        if not data:
            print(f"  [fail] {kind} 无数据", file=sys.stderr)
            continue
        if args.period == "annual":
            extra = {x.strip() for x in args.extra.split(",") if x.strip()}
            keep = [p for p in periods if p.endswith("-12-31") or p in extra]
            periods = sorted(set(keep))
            for k in list(data.keys()):
                data[k] = {p: v for p, v in data[k].items() if p in periods}
                if not any(data[k].values()):
                    del data[k]
        base = os.path.join(args.out, f"{args.code}_{kind}")
        write_md(base + ".md", periods, data, args.unit)
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump({"periods": periods, "data": data}, f, ensure_ascii=False, indent=1)
        print(f"  -> {base}.md  ({len(data)} 科目 × {len(periods)} 期, 单位 {args.unit})")


if __name__ == "__main__":
    main()
