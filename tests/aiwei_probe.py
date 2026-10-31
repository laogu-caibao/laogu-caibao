#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
去AI味终检探针 · 离线验收词库、句级特征与稿件专用闸（不联网、不读底稿）

用法：python3 tests/aiwei_probe.py
覆盖：
  1. 检测器：词级黑名单、排比三连、总结腔、抽象堆叠、… 通配、表格剔除、白名单遮蔽
  2. 验收通过：改写后密度降 ≥50% 且三条稿件闸全过
  3. 验收拦截：改丢数字 / 新增数字 / 禁语 / 证据标注减少 / 字数超限（--allow-length 放行）/ 未改写 / 原文已干净
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from cbfx import aiwei  # noqa: E402

AI_TEXT = """# 贵州茅台 2026 半年报 成稿

大家好，今天聊贵州茅台的半年报。首先，公司营收显著提升，上半年营业总收入 834.2 亿元，同比增长 13.6%；归母净利润 406.5 亿元，同比增长 15.5%。此外，公司持续赋能渠道，推进智能化自动化数字化建设，经营质量可圈可点。随着白酒行业的发展，高端酒需求日益增长，公司构建了强大的渠道生态。提升产能，提升品质，提升渠道效率。

| 指标 | 2026H1 | 2025H1 | 同比 |
|---|---:|---:|---:|
| 营业总收入（亿元） | 834.2 | 734.6 | +13.6% |
| 归母净利润（亿元） | 406.5 | 352.1 | +15.5% |

综上所述，公司基本面稳健向好。【计算】核心利润获现率 1.2，利润有现金支撑。【披露】以上数字来自公司 2026 半年报原文。
"""

GOOD_TEXT = """# 贵州茅台 2026 半年报 成稿

大家好，今天聊贵州茅台的半年报。营业总收入 834.2 亿元，同比涨 13.6%；归母净利 406.5 亿元，涨 15.5%。

| 指标 | 2026H1 | 2025H1 | 同比 |
|---|---:|---:|---:|
| 营业总收入（亿元） | 834.2 | 734.6 | +13.6% |
| 归母净利润（亿元） | 406.5 | 352.1 | +15.5% |

还有个事：渠道在升级。公司把数字化铺到了直销和批发两条线。白酒卖得好，高端酒的需求越来越旺，公司这些年一直在做渠道，产能、品质、渠道效率都往上走。基本面稳。【计算】核心利润获现率 1.2，利润有现金支撑。【披露】以上数字来自公司 2026 半年报原文。
"""

CHECKS = []


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond), detail))


def has_reason(reasons, key):
    return any(key in r for r in reasons)


def main():
    # ---- 1. 检测器 ----
    d = aiwei.density(AI_TEXT)
    check("AI 味文本密度达「中度」以上", d >= aiwei.LEVEL_MEDIUM, f"密度 {d:.1f}")
    hits = {w for w, _, _ in aiwei.word_hits(AI_TEXT)}
    need = {"首先", "此外", "综上所述", "显著提升", "赋能", "强大的", "可圈可点", "日益增长"}
    check("词级黑名单命中", need <= hits, f"缺：{sorted(need - hits)}")
    check("词库 ≥50 条", len(aiwei.WORD_BANK) >= 50, f"{len(aiwei.WORD_BANK)} 条")
    check("排比三连命中", len(aiwei.parallel_hits(aiwei.prose_view(AI_TEXT))) >= 1)
    check("总结腔命中", any("综上所述" in s for s in aiwei.summary_hits(aiwei.prose_view(AI_TEXT))))
    check("抽象名词堆叠命中", any("智能化自动化数字化" in a for a in aiwei.abstract_hits(aiwei.prose_view(AI_TEXT))))
    check("… 通配（随着…的发展）",
          bool(aiwei.WORD_PATTERNS["随着…的发展"].search("随着新能源汽车的发展，格局生变")))
    check("… 通配（构建…生态）",
          bool(aiwei.WORD_PATTERNS["构建…生态"].search("公司构建了强大的渠道生态")))
    check("散文视图剔除表格行", "| 营业总收入" not in aiwei.prose_view(AI_TEXT))
    check("数字冻结覆盖表格", "734.6" in aiwei.numbers(AI_TEXT))
    _orig = aiwei.WHITELIST
    try:
        aiwei.WHITELIST = ("首先",)
        check("白名单遮蔽", "首先" not in {w for w, _, _ in aiwei.word_hits(AI_TEXT)})
    finally:
        aiwei.WHITELIST = _orig

    # ---- 2. 验收通过 ----
    ok, reasons, summary = aiwei.verify_gates(AI_TEXT, GOOD_TEXT)
    check("改写稿验收通过", ok, "；".join(reasons))
    d2 = aiwei.density(GOOD_TEXT)
    check("改写后密度降 ≥50%", (d - d2) / d * 100 >= aiwei.VERIFY_DROP, f"{d:.1f} → {d2:.1f}")
    check("改写后无残留黑名单词", not aiwei.word_hits(GOOD_TEXT))
    check("数字集合一致", aiwei.numbers(AI_TEXT) == aiwei.numbers(GOOD_TEXT))

    # ---- 3. 验收拦截 ----
    dropped = GOOD_TEXT.replace("核心利润获现率 1.2", "核心利润获现率")
    ok, reasons, _ = aiwei.verify_gates(AI_TEXT, dropped)
    check("改丢数字 → 拦截", not ok and has_reason(reasons, "改丢数字"), "；".join(reasons))

    added = GOOD_TEXT.replace("渠道效率都往上走", "渠道效率都往上走，涨了 8%")
    ok, reasons, _ = aiwei.verify_gates(AI_TEXT, added)
    check("新增数字 → 拦截", not ok and has_reason(reasons, "新增数字"), "；".join(reasons))

    banned = GOOD_TEXT.replace("还有个事：", "券商给出目标价。还有个事：")
    ok, reasons, _ = aiwei.verify_gates(AI_TEXT, banned)
    check("禁语 → 拦截", not ok and has_reason(reasons, "禁语"), "；".join(reasons))

    noev = GOOD_TEXT.replace("【披露】", "")
    ok, reasons, _ = aiwei.verify_gates(AI_TEXT, noev)
    check("证据标注减少 → 拦截", not ok and has_reason(reasons, "证据标注减少"), "；".join(reasons))

    shrink = GOOD_TEXT.replace(
        "还有个事：渠道在升级。公司把数字化铺到了直销和批发两条线。白酒卖得好，高端酒的需求越来越旺，"
        "公司这些年一直在做渠道，产能、品质、渠道效率都往上走。基本面稳。", "")
    ok, reasons, _ = aiwei.verify_gates(AI_TEXT, shrink)
    check("字数超 ±20% → 拦截", not ok and has_reason(reasons, "字数变化超"), "；".join(reasons))
    ok, reasons, _ = aiwei.verify_gates(AI_TEXT, shrink, allow_length=True)
    check("--allow-length 放行字数线（其他闸仍生效）", "字数变化超" not in "；".join(reasons), "；".join(reasons))

    ok, reasons, _ = aiwei.verify_gates(AI_TEXT, AI_TEXT)
    check("未改写 → 拦截", not ok and has_reason(reasons, "密度下降不足"))

    ok, reasons, summary = aiwei.verify_gates(GOOD_TEXT, GOOD_TEXT)
    check("原文已干净 → 视为达标", ok and any("已达标" in s for s in summary), "；".join(reasons))

    # ---- 4. 引语保护与金融白名单 ----
    quoted = "公司说「首先我们要做好产品」。我们首先看毛利率。"
    n_first = [n for w, n, _ in aiwei.word_hits(quoted) if w == "首先"]
    check("引号内黑名单不命中（引语保护）", n_first == [1], f"命中 {n_first}")
    quote_only = "他在会上说“首先抓质量”。"
    check("纯引语整句不命中", "首先" not in {w for w, _, _ in aiwei.word_hits(quote_only)})
    wl = "支付业务带来资金沉淀。"
    hits_wl = {w: n for w, n, _ in aiwei.word_hits(wl)}
    check("金融白名单：「资金沉淀」不命中", "沉淀" not in hits_wl, str(hits_wl))
    check("裸「沉淀」仍命中", "沉淀" in {w for w, _, _ in aiwei.word_hits("资金在企业账上沉淀。")})
    num_keep = "公司说「目标 100 亿」。收入 50.5 亿。"
    check("引语遮蔽不影响数字冻结口径", aiwei.numbers(num_keep) == {"100", "50.5"})

    # ---- 汇总 ----
    rows = [f"{'✅' if ok else '❌'} {name}" + (f"（{detail}）" if detail and not ok else "")
            for name, ok, detail in CHECKS]
    print("\n".join(rows))
    bad = sum(1 for _, ok, _ in CHECKS if not ok)
    print(f"\n{len(CHECKS) - bad}/{len(CHECKS)} 通过")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
