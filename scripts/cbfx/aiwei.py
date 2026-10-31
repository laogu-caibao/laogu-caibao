# -*- coding: utf-8 -*-
"""稿件去AI味：词级黑名单 + 句级结构特征 + 密度量化 + 验收闸（数字冻结/禁语/证据标注）。

移植自 lls-aiwei v1.0.0（MIT，作者：刘老师系列），按 lhg-cbfx 约束适配：
  - Python 3.9+（from __future__ import annotations，原码的 ``float | None`` 是 3.10 语法）
  - 「随着…的发展」「构建…生态」的 … 按通配处理（原实现 re.escape 按字面量，永不命中，按词库意图修正）
  - 密度统一按「散文视图」计算：剔除 markdown 表格行（表格是数据区，不改写、不稀释密度），
    scan 与 verify 用同一函数保证口径一致
  - 新增金融稿件专用闸（通用 aiwei 没有）：数字冻结、禁语（与 tests/regress.py BANNED 同步）、证据标注保留

阈值见 references/规则手册.md §10，本模块是它的机器版；与 rules.py（分析阈值 rules/0.3）相互独立。
"""
from __future__ import annotations

import re

# ---- 阈值（规则手册 §10）----
LEVEL_CLEAN, LEVEL_LIGHT, LEVEL_MEDIUM = 3.0, 8.0, 15.0   # 密度分级：<3 干净｜3-8 轻度｜8-15 中度｜>15 重度
VERIFY_DROP = 50.0        # 验收：密度下降 ≥50%
VERIFY_LEN_BAND = 20.0    # 验收：字数变化 ≤±20%（防改丢内容/过度发挥）
VERIFY_RESIDUE = 3        # 验收：残留黑名单词种数 ≤3

# 禁语（不荐股/无预期差措辞）。与 tests/regress.py 的 BANNED 保持同步，两边改动必须一起改。
BANNED = ("买入", "卖出", "增持", "目标价", "推荐", "看多", "看空", "上涨空间", "抄底", "加仓", "减仓", "止损", "超预期", "不及预期")

# 证据标注（SKILL.md 第 4 步：必须保留，【推断】须连同验证条件）
EVIDENCE_TAGS = ("【披露】", "【计算】", "【推断】")

# 术语白名单：命中检测前先遮蔽，黑名单不匹配白名单词（lls-aiwei 失败分支 #3）。
# 只放「黑名单词是某术语合法组成部分」的财经用语；管理层原话引用靠引语保护（见 prose_view）。
WHITELIST: tuple = ("资金沉淀", "沉淀资金")

# 引语保护：引号内内容不参与词级/句级检测（直接引语不改写不动）。
_QUOTE_RE = re.compile(r"「[^」]*」|『[^』]*』|“[^”]*”|\"[^\"]*\"")

# ── 词级 AI 味（词 → 改写方向）──
WORD_BANK = {
    # 结构套话
    "首先": "直接说第一件事", "其次": "接着说第二件事", "再者": "还有一件事",
    "此外": "另外有个事", "综上所述": "以上这些说白了就是", "总而言之": "一句话总结：",
    "值得注意的是": "有个细节要注意：", "需要指出的是": "得说清楚一点：",
    "众所周知": "（删掉，直接说事）", "不言而喻": "（删掉）", "毋庸置疑": "（删掉）",
    "在这个充满挑战的时代": "（删掉）", "随着…的发展": "改成具体时间或事件开头",
    # 动词套话
    "赋能": "帮…做到（说清帮谁做到什么）", "助力": "帮", "旨在": "是为了",
    "致力于": "一直在做", "深耕": "专注做了多年", "拥抱": "开始用",
    "拉通": "把…串起来", "对齐": "商量一致", "沉淀": "留下", "构建…生态": "把相关的事做起来",
    # 形容/副词套话
    "显著提升": "提了多少（写具体数字）", "有效提升": "提升了（写数字）",
    "极大地": "（删掉，让数字说话）", "有效地": "（删掉）", "广泛应用": "用在哪些地方（举实例）",
    "日益增长": "越来越（写数字）", "越来越高": "越来越（写数字）",
    "淋漓尽致": "拉满", "可圈可点": "能打", "行之有效": "真的管用", "卓有成效": "见效了",
    # 空洞强化
    "强大的": "强在哪（写具体）", "高效的": "快在哪（写数字）", "全面的": "全在哪（列举）",
    "深入的": "深到哪（写细节）", "专业的": "专业在哪（写证据）", "优质的": "好在哪（写标准）",
    "一站式": "到底包含哪些（列举）", "全方位": "覆盖了哪些（列举）", "多维度": "哪几个维度（列举）",
    "智能化": "自动做了什么（写动作）", "不断完善": "改了什么（写事实）", "不断发展": "发生了什么（写事实）",
    # 公文/汇报腔
    "扎实推进": "做了什么（写事实）", "稳步推进": "推进到哪（写进度）", "狠抓落实": "抓了什么（写事实）",
    "高度重视": "具体做了什么（写动作）", "决策部署": "哪个决定（写内容）",
}


def _compile(word: str) -> "re.Pattern[str]":
    """词库项编译：… 通配最多 8 个汉字，其余字符按字面量。"""
    return re.compile("[一-龥]{0,8}".join(re.escape(p) for p in word.split("…")))


WORD_PATTERNS = {k: _compile(k) for k in WORD_BANK}

# ── 句级结构模式 ──
SUMMARY_OPEN = re.compile(r"^(总之|综上|可见|因此|由此可以看出|总的来说)", re.M)
ABSTRACT_STACK = re.compile(r"[一-龥]{1,4}[性化度][一-龥]{0,2}[性化度][一-龥]{0,2}[性化度]")
NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def prose_view(text: str) -> str:
    """散文视图：剔除表格行 → 遮蔽引号内直接引语 → 遮蔽白名单词。
    密度与词级/句级检测统一用这个口径；数字冻结（numbers）不受影响，仍扫全文。"""
    t = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("|"))
    t = _QUOTE_RE.sub(lambda m: "◇" * len(m.group(0)), t)
    for w in WHITELIST:
        t = t.replace(w, "◇" * len(w))
    return t


def sentences(text: str) -> list:
    return [s.strip() for s in re.split(r"[。！？\n]", text) if len(s.strip()) >= 6]


def parallel_hits(text: str) -> list:
    """排比三连：同一句里 ≥3 个逗号/顿号分句且开头 2 字相同（AI 爱用的整齐排比）。"""
    hits = []
    for sent in sentences(text):
        parts = [p.strip() for p in re.split(r"[，,]", sent) if len(p.strip()) >= 4]
        if len(parts) >= 3:
            heads = [p[:2] for p in parts]
            if len(set(heads)) == 1 or len(set(heads)) <= len(parts) // 2:
                hits.append(sent)
    return hits


def abstract_hits(text: str) -> list:
    return [m.group(0) for m in ABSTRACT_STACK.finditer(text)]


def summary_hits(text: str) -> list:
    return [s for s in sentences(text) if SUMMARY_OPEN.match(s)]


def length_uniformity(text: str):
    """连续 ≥5 句的句长变异系数。<0.15 = AI 均匀句长特征；无命中返回 None。"""
    ss = sentences(text)
    for i in range(len(ss) - 4):
        window = [len(s) for s in ss[i:i + 5]]
        mean = sum(window) / 5
        if mean == 0:
            continue
        var = sum((x - mean) ** 2 for x in window) / 5
        cv = (var ** 0.5) / mean
        if cv < 0.15:
            return round(cv, 3)
    return None


def word_hits(text: str) -> list:
    """词级命中 [(词, 次数, 改写方向)]，按次数降序。"""
    t = prose_view(text)
    hits = []
    for w, pat in WORD_PATTERNS.items():
        n = len(pat.findall(t))
        if n:
            hits.append((w, n, WORD_BANK[w]))
    hits.sort(key=lambda kv: -kv[1])
    return hits


def density(text: str) -> float:
    """AI 味密度 =（词级命中 + 排比×2 + 总结腔×2 + 抽象堆叠×2）÷ 千字（散文口径）。"""
    t = prose_view(text)
    kilo = max(len(re.sub(r"\s", "", t)), 1) / 1000
    word_score = sum(n for _, n, _ in word_hits(text))
    struct_score = len(parallel_hits(t)) * 2 + len(summary_hits(t)) * 2 + len(abstract_hits(t)) * 2
    return (word_score + struct_score) / kilo


def level(d: float) -> str:
    return "干净" if d < LEVEL_CLEAN else "轻度" if d < LEVEL_LIGHT else "中度" if d < LEVEL_MEDIUM else "重度"


# ── 稿件专用闸 ──

def numbers(text: str) -> set:
    """全部数字 token（含表格行——数字冻结覆盖全稿，表格数字更不许动）。"""
    return set(NUM_RE.findall(text))


def evidence_counts(text: str) -> dict:
    return {t: text.count(t) for t in EVIDENCE_TAGS}


def _num_key(s: str):
    try:
        return (0, float(s), "")
    except ValueError:
        return (1, 0.0, s)


def verify_gates(old: str, new: str, allow_length: bool = False):
    """改写验收。返回 (ok, 失败原因列表, 摘要行列表)。

    三条通用线（lls-aiwei）：密度降 ≥50%、字数 ±20%、残留 ≤3；
    三条稿件专用线：数字冻结（双向）、禁语、证据标注不减少。
    原文密度已 <3（干净）时密度线视为达标——原文不是 AI 写的，不做无意义改写。
    """
    reasons, summary = [], []

    d_old, d_new = density(old), density(new)
    drop = (d_old - d_new) / d_old * 100 if d_old else 0.0
    clean_old = d_old < LEVEL_CLEAN
    summary.append(f"AI 味密度：{d_old:.1f} → {d_new:.1f}/千字（下降 {drop:.0f}%）"
                   + ("；原文密度已达标，无需为密度重改" if clean_old else ""))
    if drop < VERIFY_DROP and not clean_old:
        reasons.append(f"密度下降不足 {VERIFY_DROP:.0f}%（实际 {drop:.0f}%）")

    n_old = len(re.sub(r"\s", "", old))
    n_new = len(re.sub(r"\s", "", new))
    len_delta = (n_new - n_old) / n_old * 100 if n_old else 0.0
    summary.append(f"字数（含表格）：{n_old} → {n_new}（{len_delta:+.0f}%，合格线 ±{VERIFY_LEN_BAND:.0f}%）")
    if abs(len_delta) > VERIFY_LEN_BAND and not allow_length:
        reasons.append(f"字数变化超 ±{VERIFY_LEN_BAND:.0f}%（实际 {len_delta:+.0f}%）——疑似改丢内容或过度发挥；"
                       "重度去味文本自然缩水属正常，确认无丢失后可加 --allow-length 放行")

    residue = [(w, n) for w, n, _ in word_hits(new)]
    summary.append("残留黑名单词：" + ("、".join(f"{w}×{n}" for w, n in residue[:6])
                                     + (f" 等 {len(residue)} 种" if len(residue) > 6 else "")
                                     if residue else "无"))
    if len(residue) > VERIFY_RESIDUE:
        reasons.append(f"残留黑名单词 {len(residue)} 种（合格线 ≤{VERIFY_RESIDUE}）")

    miss = sorted(numbers(old) - numbers(new), key=_num_key)
    added = sorted(numbers(new) - numbers(old), key=_num_key)
    if miss:
        reasons.append("改丢数字：" + "、".join(miss[:10]) + ("…" if len(miss) > 10 else "")
                       + "——原文的数字必须原样保留（含表格）")
    if added:
        reasons.append("新增数字：" + "、".join(added[:10]) + ("…" if len(added) > 10 else "")
                       + "——稿件层不产生新数字，数字只来自底稿")

    hit = [w for w in BANNED if w in new]
    if hit:
        reasons.append("禁语（不荐股/无预期差）：" + "、".join(hit))

    ev_old, ev_new = evidence_counts(old), evidence_counts(new)
    lost = [f"{t} {ev_old[t]}→{ev_new[t]}" for t in EVIDENCE_TAGS if ev_new[t] < ev_old[t]]
    if lost:
        reasons.append("证据标注减少：" + "、".join(lost) + "——【披露】【计算】【推断】必须保留")

    return (not reasons), reasons, summary
