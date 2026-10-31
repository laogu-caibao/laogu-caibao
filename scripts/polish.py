#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
稿件去AI味终检 CLI · scan 出报告 → agent 按五招改写 → verify 验收（发布前必过）

用法：
  python3 scripts/polish.py 601899                # scan：检测 稿件_成稿.md，自动备份改写前版本
  python3 scripts/polish.py 601899 --verify       # verify：验收改写结果，不合格 exit 1
  python3 scripts/polish.py 601899 --reset        # scan：重新备份改写前版本
  python3 scripts/polish.py 任意稿子.md [--verify]  # 也接受直接文件路径

约定：成稿存 out/<代码>/<报告期>/稿件_成稿.md（在 draft.py 的稿件骨架上写出的最终口播稿）。
scan 会把当前成稿备份为 稿件_改写前.md（已存在则沿用，--reset 重建），检测报告写 稿件_AI味检测.md。
验收线：密度下降 ≥50%、字数 ±20%、残留 ≤3，外加数字冻结/禁语/证据标注三条稿件专用闸（cbfx/aiwei.py）。
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cbfx import aiwei  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve(target, period=None):
    """代码 → out/<代码>/<报告期>/稿件_成稿.md；已有的 .md 路径直接用。"""
    if os.path.isfile(target):
        return target
    base = os.path.join(ROOT, "out", target)
    if not os.path.isdir(base):
        sys.exit(f"[ERR] 未找到 {base}：股票代码需先跑 draft.py，或直接传 .md 文件路径")
    if period:
        cands = [period]
    else:
        cands = [x for x in os.listdir(base)
                 if os.path.isdir(os.path.join(base, x)) and x[:4].isdigit()]
        if not cands:
            sys.exit(f"[ERR] {base} 下没有报告期目录")
    d = os.path.join(base, sorted(cands)[-1])
    src = os.path.join(d, "稿件_成稿.md")
    if not os.path.isfile(src):
        src = find_issue_draft(target)
    if not os.path.isfile(src):
        sys.exit(f"[ERR] {os.path.join(d, '稿件_成稿.md')} 不存在——先在稿件骨架上写成稿，再跑 polish")
    return src


def find_issue_draft(code):
    """v0.7 起成稿在期目录 out/<发布日>-<公司>-<报告期>-<代码>/ 下，按代码后缀兜底定位。"""
    out = os.path.join(ROOT, "out")
    hits = []
    for name in sorted(os.listdir(out)):
        qd = os.path.join(out, name)
        f = os.path.join(qd, "稿件_成稿.md")
        if os.path.isdir(qd) and name.endswith("-" + code) and os.path.isfile(f):
            hits.append(f)
    return hits[-1] if hits else ""


def side_paths(src):
    d = os.path.dirname(os.path.abspath(src))
    _sub = os.path.join(d, "过程")          # v0.7：期目录下的过程件统一进 过程/
    if os.path.isdir(_sub):
        d = _sub
    stem = os.path.splitext(os.path.basename(src))[0]
    return (os.path.join(d, f"{stem}_改写前.md"), os.path.join(d, f"{stem}_AI味检测.md"))


def do_scan(src, baseline, report, reset):
    text = open(src, encoding="utf-8").read()
    if reset or not os.path.isfile(baseline):
        shutil.copyfile(src, baseline)
        base_note = f"改写前版本已建档 → {baseline}"
    else:
        base_note = f"改写前版本已存在，沿用 {baseline}（--reset 可重新建档）"

    d = aiwei.density(text)
    uni = aiwei.length_uniformity(aiwei.prose_view(text))
    hits = aiwei.word_hits(text)
    para = aiwei.parallel_hits(aiwei.prose_view(text))
    summ = aiwei.summary_hits(aiwei.prose_view(text))
    abst = aiwei.abstract_hits(aiwei.prose_view(text))
    chars = len("".join(aiwei.prose_view(text).split()))

    L = [f"# 稿件去AI味检测报告：{os.path.basename(src)}", "",
         f"- 散文字数：{chars}（不含表格）｜ **AI 味密度：{d:.1f}/千字（{aiwei.level(d)}）**"]
    if uni is not None:
        L.append(f"- ⚠️ 检测到连续 5 句句长几乎一致（变异系数 {uni}）——改写时故意打破："
                 "有的句子 5 个字，有的句子拖到二十多个字才收尾。")
    L += ["", "## 词级命中（词 → 次数 → 改写方向）"]
    L += [f"- 「{w}」×{n} → {direction}" for w, n, direction in hits] or ["- 无"]
    L += ["", "## 句级结构特征"]
    if para:
        L.append(f"- 🔁 排比三连 {len(para)} 处（例：{para[0][:50]}…）→ 打破整齐感，长短句交错")
    if summ:
        L.append(f"- 🧾 总结腔 {len(summ)} 处（{[s[:24] for s in summ[:3]]}）→ 段尾总结句删一半，留给读者自己品")
    if abst:
        L.append(f"- 🏗️ 抽象名词堆叠 {len(abst)} 处（{abst[:5]}）→ 换成具体的人/物/动作")
    if not (para or summ or abst):
        L.append("- 无")
    L += ["", "## 改写优先级（五招）",
          "1. 先清词级命中（具体替换：黑名单词按方向机械改，见效最快）",
          "2. 再拆排比与总结腔（重写句子结构）",
          "3. 数字锚定：凡「显著提升」类空话，改写成底稿里的实际数值——**不是编数**",
          "4. 最后打破句长均匀（读一遍，凭语感长短交错），口语连接（然而→但是）",
          f"5. 改完跑 `python3 scripts/polish.py {src} --verify` 验收——跳过验收 = 没完成",
          "",
          "## 稿件专用闸（verify 会查，改写前先看清）",
          "- **数字冻结**：原文每个数字（含表格）必须原样保留，不得出现原文没有的新数字——数字只来自底稿",
          "- **禁语**：不荐股/无预期差词表（买入、目标价、超预期…）出现即不通过",
          "- **证据标注**：【披露】【计算】【推断】数量不得减少",
          "- 表格与数字区不改写；事实句原样保留；改写基于成稿已有事实，不编造细节、不引入「网络体」",
          "- 原文密度已 <3（干净）时不必为密度改写",
          ""]
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    print(f"[polish] 密度 {d:.1f}/千字（{aiwei.level(d)}），词级命中 {len(hits)} 种"
          + (f"，句级特征 {len(para) + len(summ) + len(abst)} 处" if (para or summ or abst) else ""))
    if d < aiwei.LEVEL_CLEAN:
        print("[polish] 原文密度已达标（干净），无需改写。")
    print(f"[polish] 检测报告 → {report}")
    print(f"[polish] {base_note}")
    if d >= aiwei.LEVEL_CLEAN:
        print("[polish] 🔴 CHECKPOINT：把密度与命中清单展示给用户，确认改写风格（轻度清洗 vs 深度重写）后再改写。")
    print("[polish] 下一步：按报告逐条改写后跑 --verify。")
    return 0


def do_verify(src, baseline, allow_length):
    if not os.path.isfile(baseline):
        sys.exit(f"[ERR] 没有改写前版本 {baseline}——先跑 scan 建档再改写")
    old = open(baseline, encoding="utf-8").read()
    new = open(src, encoding="utf-8").read()
    ok, reasons, summary = aiwei.verify_gates(old, new, allow_length=allow_length)
    for s in summary:
        print(f"[aiwei] {s}")
    if ok:
        print("[aiwei] ✅ 验收通过——稿件可发布")
        return 0
    for r in reasons:
        print(f"[aiwei] ❌ {r}")
    print("[aiwei] 验收不通过——按上述逐条重改 稿件_成稿.md 后重跑 --verify。")
    return 1


def main():
    ap = argparse.ArgumentParser(description="稿件去AI味终检（scan / verify）")
    ap.add_argument("target", help="股票代码（取 out/<代码>/<报告期>/稿件_成稿.md）或 .md 文件路径")
    ap.add_argument("--verify", action="store_true", help="验收改写结果（默认 scan 检测）")
    ap.add_argument("--period", help="指定报告期目录，默认取最新一期")
    ap.add_argument("--reset", action="store_true", help="scan 时重新备份改写前版本")
    ap.add_argument("--allow-length", action="store_true",
                    help="verify 放行字数超 ±20%（重度去味自然缩水，确认无丢失后使用）")
    a = ap.parse_args()
    src = resolve(a.target, a.period)
    baseline, report = side_paths(src)
    if a.verify:
        sys.exit(do_verify(src, baseline, a.allow_length))
    sys.exit(do_scan(src, baseline, report, a.reset))


if __name__ == "__main__":
    main()
