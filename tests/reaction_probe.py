#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
判定分布探针 · 看「财报与股价矛盾」在真实样本里出现得是否合理

只读已生成的底稿与分析结果，不重新采集。
用法：
  python3 tests/reaction_probe.py
  python3 tests/reaction_probe.py --band 0.05
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from cbfx import reaction  # noqa: E402


def collect():
    out = os.path.join(ROOT, "out")
    rows = []
    if not os.path.isdir(out):
        return rows
    for code in sorted(os.listdir(out)):
        base = os.path.join(out, code)
        if not os.path.isdir(base):
            continue
        periods = [p for p in os.listdir(base)
                   if os.path.isdir(os.path.join(base, p)) and p[:4].isdigit()]
        if not periods:
            continue
        d = os.path.join(base, sorted(periods)[-1])
        lp, ap = os.path.join(d, "底稿.json"), os.path.join(d, "分析.json")
        if not (os.path.isfile(lp) and os.path.isfile(ap)):
            continue
        rows.append((code, json.load(open(lp, encoding="utf-8")),
                     json.load(open(ap, encoding="utf-8"))))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--band", type=float, default=0.03)
    a = ap.parse_args()

    rows = collect()
    if not rows:
        sys.exit("没有可用底稿")

    print(f"判定分布（band={a.band:.0%}）\n")
    print(f"{'代码':<8}{'公司':<10}{'行业':<16}{'财报':<6}{'3日':>9}{'5日':>9}  {'结论':<6}{'强度':<6}")
    print("-" * 84)
    stat = {}
    for code, ledger, ana in rows:
        r = reaction.judge(ledger, ana, band=a.band)
        name = (ana.get("meta") or {}).get("name") or ""
        tone = (r.get("tone") or {}).get("tone") or "—"
        tone_cn = {"good": "好", "weak": "弱", "neutral": "中"}.get(tone, "—")
        mv = r.get("move") or 0
        p3 = r.get("move_3d")
        p5 = r.get("move_5d")
        verdict = r.get("verdict")
        if verdict == "conflict":
            concl = f"{r['type']} 型"
        elif verdict == "none":
            concl = "未命中"
        else:
            concl = verdict or "—"
        ind = ((r.get("tone") or {}).get("industry") or "—")[:14]
        print(f"{code:<8}{name:<10}{ind:<16}{tone_cn:<6}"
              f"{(f'{p3*100:+.1f}%' if p3 is not None else '—'):>10}"
              f"{(f'{p5*100:+.1f}%' if p5 is not None else '—'):>10}  "
              f"{concl:<6}{r.get('strength') or '—':<6}")
        stat[verdict] = stat.get(verdict, 0) + 1

    print("-" * 84)
    tot = len(rows)
    for k, v in stat.items():
        print(f"{k}: {v}（{v/tot:.0%}）")


if __name__ == "__main__":
    main()
