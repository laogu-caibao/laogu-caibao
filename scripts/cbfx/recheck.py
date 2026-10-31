# -*- coding: utf-8 -*-
"""稿件数据反问卷：脚本出题与机器预填，执行本 skill 的默认大模型作答，脚本封卷验收。

在去AI味（polish）之前执行。机器关（三源交叉/勾稽/门禁/数字冻结/禁语）拦得住「数字对不上」，
拦不住语义错误——单位错位、单季/累计混用、归母/扣非混淆、结论互斥、量级异常无人质疑。
本模块出 8 道反问题并预填机器事实；大模型逐题判定（通过/存疑/不通过 + 依据）；
recheck.py --seal 解析封卷：任一不通过 → 阻断发布；存疑 → 可进入去AI味但稿件必须披露存疑项。

作答纪律（见 references/规则手册.md §11）：不改数、不自行解释掉冲突、依据必须指到
科目+报告期+原文页码或底稿单元格、不为了过关放水、存疑要如实写。
"""
from __future__ import annotations

import re

from cbfx import aiwei, reaction

SCHEMA = "cbfx.recheck/0.1"
VERDICTS = ("通过", "存疑", "不通过")
KEY_FIELDS = ("rev", "np_parent", "np_ded", "ocf", "ta", "tl", "eq_parent")

_Q4_KW = re.compile(r"同比|环比|单季|TTM|年化|归母|扣非|累计|毛利率")


def _num_key(s):
    try:
        return (0, float(s), "")
    except ValueError:
        return (1, 0.0, s)


def _cells(ledger, key, n=3):
    """某科目最近 n 期可用单元格 [(period, value, status)]。"""
    vals = ((ledger.get("fields") or {}).get(key) or {}).get("values") or {}
    out = []
    for p in sorted(vals, reverse=True):
        c = vals.get(p) or {}
        if c.get("usable") and c.get("value") is not None:
            out.append((p, c["value"], c.get("status") or "—"))
        if len(out) >= n:
            break
    return out


def _fmt_cells(ledger, key, n=3):
    cells = _cells(ledger, key, n)
    if not cells:
        return f"{key}：底稿无可用值"
    return f"{k2cn(key)}（{key}）：" + "；".join(f"{p}={v:,.0f} 元（{s}）" for p, v, s in cells)


def k2cn(key):
    return {"rev": "营业收入", "np_parent": "归母净利润", "np_ded": "扣非归母", "ocf": "经营现金流",
            "ta": "总资产", "tl": "总负债", "eq_parent": "归母权益"}.get(key, key)


def build(ledger, ana, draft_text, trace_texts):
    """出 8 道反问题并预填机器事实。trace_texts: [(标签, 文本)]——用于 Q1 出处追溯的脚本产出全文。"""
    meta = ledger.get("meta") or {}

    # Q1 出处完备
    corpus = "\n".join(t for _, t in trace_texts)
    missing = sorted(aiwei.numbers(draft_text) - aiwei.numbers(corpus), key=_num_key)
    q1_facts = ["追溯语料：" + "、".join(label for label, _ in trace_texts)]
    q1_facts.append("待解释数字（语料中均未出现，须给出底稿单元格出处或判不通过）："
                    + ("、".join(missing[:15]) + ("…" if len(missing) > 15 else "") if missing else "无"))
    # 机器行：parse 靠它做「逐个给出处」硬闸；无待解释数字时值为「无」
    q1_facts.append("【待解释数字】" + ("、".join(missing) if missing else "无"))

    # Q2 量级与单位
    q2_facts = [_fmt_cells(ledger, k) for k in KEY_FIELDS]
    q2_facts.append("底稿单位一律为元；稿件若写亿/万，自行换算核量级。")

    # Q3 结论自洽
    q3_facts = ["headline：" + str(ana.get("headline") or "（无）")]
    br = ana.get("bridge") or {}
    if br:
        q3_facts.append(f"利润桥：status={br.get('status')}；{br.get('text') or ''}")
        gs = br.get("gross_split") or {}
        if gs:
            q3_facts.append(f"毛利拆分：规模 {gs.get('scale', 0)/1e8:+.2f} 亿、毛利率 {gs.get('margin', 0)/1e8:+.2f} 亿")
    risks = ana.get("risks") or []
    if risks:
        r0 = risks[0]
        q3_facts.append(f"首要风险组：{r0.get('title') or r0.get('id') or '—'}（{r0.get('severity') or '—'}）")

    # Q4 口径正确
    sents = [s for s in aiwei.sentences(aiwei.prose_view(draft_text)) if _Q4_KW.search(s)]
    q4_facts = ["稿件中含口径关键词的句子（逐句核：单季还是累计？归母还是扣非？同比还是环比？）："]
    q4_facts += [f"- {s[:60]}" for s in sents[:12]] or ["- 无"]

    # Q5 冲突漏用
    issues = ledger.get("issues") or []
    errs = [f"{i.get('field')}@{i.get('period')}：{i.get('msg')}" for i in issues if i.get("level") == "error"]
    warns = [f"{i.get('field')}@{i.get('period')}：{i.get('msg')}" for i in issues if i.get("level") == "warn"]
    bad_status = []
    for k, f in (ledger.get("fields") or {}).items():
        for p, c in (f.get("values") or {}).items():
            st = (c or {}).get("status")
            if st in ("冲突", "单一来源"):
                bad_status.append(f"{k}@{p}={st}")
    q5_facts = [f"error 级问题 {len(errs)} 项"] + [f"- {x}" for x in errs[:8]]
    q5_facts += [f"warn 级问题 {len(warns)} 项"] + [f"- {x}" for x in warns[:5]]
    q5_facts += [f"冲突/单一来源单元格 {len(bad_status)} 个"] + [f"- {x}" for x in bad_status[:8]]
    q5_facts.append("冲突项对应科目不得出现在稿件结论里；单一来源不得作为关键结论唯一支撑。")

    # Q6 门禁与勾稽
    g = ana.get("gate") or {}
    recs = [r for r in (ledger.get("reconciliations") or []) if r.get("status") not in ("pass", "na")]
    q6_facts = [f"门禁：status={g.get('status') or '—'}"
                + ("；原因：" + "；".join(g.get("reasons") or []) if g.get("reasons") else "")]
    q6_facts += [f"勾稽非 pass {len(recs)} 项"] + [f"- {r.get('label')}@{r.get('period')}={r.get('status')}（{r.get('note') or ''}）"
                                                  for r in recs[:8]]
    q6_facts.append("门禁非 pass 时报告标「草稿」，稿件必须原样转述，不得洗掉草稿字样。")

    # Q7 行情与估值越界
    q7_facts = []
    snap = next(iter(((ledger.get("quote") or {}).get("snapshots") or [])), None)
    if snap:
        q7_facts.append(f"行情快照：{snap.get('source') or '—'} @ {snap.get('as_of') or snap.get('time') or '时间未注'}，"
                        f"价 {snap.get('price') or '—'}")
    try:
        rx = reaction.judge(ledger, ana)
        q7_facts.append(f"反应判定：verdict={rx.get('verdict')}，3日={rx.get('move_3d')}，5日={rx.get('move_5d')}，"
                        f"强度={rx.get('strength') or '—'}")
    except Exception as e:  # 行情数据缺失不阻断出卷
        q7_facts.append(f"反应判定：无法计算（{e}）")
    val = ana.get("valuation") or {}
    hist = val.get("history") or {}
    if hist:
        q7_facts.append(f"估值历史样本：{hist.get('months') or '—'} 个月（{hist.get('from') or '—'} ~ {hist.get('to') or '—'}）；"
                        "样本 <24 个月只报数值不报分位。")
    q7_facts.append("估值只能写「历史位置/价格隐含了什么」，写成贵/便宜/该不该买即不通过。")

    # Q8 反例挑战
    q8_facts = ["无——本题由模型自行构造。对稿件前 3 组矛盾点逐一设想：若关键科目被追溯调整/口径变化/单位错位，结论还成立吗？"
                "写出至少 1 个具体反例及当前证据为何仍支持（或推翻）结论。"]

    questions = [
        {"id": "Q1", "title": "出处完备", "ask": "稿件里每个数字都能落到脚本产出（底稿/分析/报告）吗？", "facts": q1_facts},
        {"id": "Q2", "title": "量级与单位", "ask": "关键科目数值与近 3 期是否同量级？有没有元/亿/万错位？", "facts": q2_facts},
        {"id": "Q3", "title": "结论自洽", "ask": "headline、利润桥、首要风险组、稿件叙述的方向是否互斥？", "facts": q3_facts},
        {"id": "Q4", "title": "口径正确", "ask": "单季/累计/TTM、归母/扣非、同比/环比有没有用错？", "facts": q4_facts},
        {"id": "Q5", "title": "冲突漏用", "ask": "问题清单里的冲突项/单一来源科目有没有漏进稿件？", "facts": q5_facts},
        {"id": "Q6", "title": "门禁与勾稽", "ask": "门禁与勾稽状态是否被稿件忽略或洗白？", "facts": q6_facts},
        {"id": "Q7", "title": "行情与估值越界", "ask": "反应窗口与估值样本足以支撑表述吗？有没有把「位置」说成「贵便宜」？", "facts": q7_facts},
        {"id": "Q8", "title": "反例挑战", "ask": "若关键科目被追溯调整/口径变化，结论还成立吗？", "facts": q8_facts},
    ]
    return questions


def render(questions, meta):
    """出卷：判定/依据行留空待作答（模板留空是为了 parse 不把占位符当答案）。"""
    L = [f"# 稿件数据反问卷：{meta.get('name') or ''} {meta.get('target_period') or ''}", "",
         "> 出卷：scripts/recheck.py（脚本出题+机器事实预填）｜作答：执行本 skill 的默认大模型｜封卷：--seal",
         "> 判定枚举：通过 / 存疑 / 不通过。非「通过」必须在「依据：」同一行写明出处"
         "（科目+报告期+原文页码，或底稿单元格）。",
         "> 作答纪律：不改数、不自行解释掉冲突、不为了过关放水；存疑要如实写。Q8 必须写出具体反例。",
         "",
         "审查模型：",
         "作答时间：",
         ""]
    for q in questions:
        L.append(f"## {q['id']} {q['title']}")
        L.append(f"【反问】{q['ask']}")
        L.append("【机器事实】")
        L += [f"- {f}" for f in q["facts"]]
        L += ["【作答】", "判定：", "依据：", ""]
    return "\n".join(L)


def parse(text):
    """解析作答。返回 (record, errors)。非通过必须带依据；Q8 依据 ≥20 字；署名与时间必填。"""
    errors = []
    m = re.search(r"^审查模型：[ \t]*(\S.*)$", text, re.M)
    model = m.group(1).strip() if m else ""
    if not model:
        errors.append("「审查模型：」未署名")
    t = re.search(r"^作答时间：[ \t]*(\S.*)$", text, re.M)
    answered_at = t.group(1).strip() if t else ""
    if not answered_at:
        errors.append("「作答时间：」未填")

    parts = re.split(r"^## (Q\d)\b", text, flags=re.M)
    bodies = {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}
    answers = []
    for q in QUESTIONS_DEF:
        qid = q["id"]
        body = bodies.get(qid)
        if body is None:
            errors.append(f"{qid} 缺作答段")
            continue
        vm = re.search(r"判定：\s*(通过|存疑|不通过)", body)
        if not vm:
            errors.append(f"{qid} 判定未填或不在枚举（通过/存疑/不通过）")
            continue
        verdict = vm.group(1)
        bm = re.search(r"依据：[ \t]*(\S.*)", body)
        basis = bm.group(1).strip() if bm else ""
        if verdict != "通过" and len(basis) < 6:
            errors.append(f"{qid} 判定「{verdict}」但依据缺失/过短（须指到科目+报告期+页码）")
        if qid == "Q1" and verdict != "不通过":
            # 机器闸：待解释数字必须逐个在依据中给出出处，否则封卷不通过（堵「初稿编数」的洞）
            mm = re.search(r"^- 【待解释数字】(.+)$", body, re.M)
            if mm:
                nums = [s.strip() for s in mm.group(1).strip().split("、")
                        if s.strip() and s.strip() != "无"]
                unaddressed = [n for n in nums if n not in basis]
                if unaddressed:
                    errors.append(f"Q1 待解释数字未逐个给出出处：{'、'.join(unaddressed)}"
                                  "——非「不通过」判定必须逐个写明来源（科目+报告期+页码，或底稿单元格）")
        if qid == "Q8" and len(basis) < 20:
            errors.append("Q8 必须写出具体反例与回应（依据 ≥20 字）")
        answers.append({"id": qid, "verdict": verdict, "basis": basis})
    return {"model": model, "answered_at": answered_at, "questions": answers}, errors


def overall(answers):
    """任一不通过 → fail；有存疑 → doubt；8 题全通过 → pass；题数不足 → incomplete。"""
    vs = [a["verdict"] for a in answers]
    if "不通过" in vs:
        return "fail"
    if "存疑" in vs:
        return "doubt"
    return "pass" if len(answers) == len(QUESTIONS_DEF) else "incomplete"


QUESTIONS_DEF = [
    {"id": "Q1", "title": "出处完备"},
    {"id": "Q2", "title": "量级与单位"},
    {"id": "Q3", "title": "结论自洽"},
    {"id": "Q4", "title": "口径正确"},
    {"id": "Q5", "title": "冲突漏用"},
    {"id": "Q6", "title": "门禁与勾稽"},
    {"id": "Q7", "title": "行情与估值越界"},
    {"id": "Q8", "title": "反例挑战"},
]
