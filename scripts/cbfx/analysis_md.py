"""把 分析.json 写成《财报快检/深检报告》（v0.3：核心结论→门禁→分型→结果→驱动→指标→风险→估值→跟踪）。每个数字后注明口径。"""
import os

SRC = {"pdf": "原文", "pdf_comparative": "原文比较期", "eastmoney": "东财", "sina": "新浪"}


def yi(v):
    return "—" if v is None else f"{v / 1e8:,.2f}"


def growth(cur, prev, g, cash=False):
    """负值参与比较时，百分比没有直观含义，改用文字。"""
    if cur is None or prev is None:
        return "—"
    if prev < 0 or cur < 0:
        w = ("由负转正", "由正转负", "净流出收窄", "净流出扩大") if cash else ("扭亏", "转亏", "亏损收窄", "亏损扩大")
        if prev < 0 <= cur:
            return w[0]
        if prev >= 0 > cur:
            return w[1]
        return w[2] if cur > prev else w[3]
    return pct(g, True)


def pct(v, sign=False):
    return "—" if v is None else (f"{v:+.1%}" if sign else f"{v:.1%}")


def _pp(x):
    return "—" if x is None else f"{x:+.1f}pct"


def fmt(m):
    v, u = m["value"], m["unit"]
    if v is None:
        return "未获取"
    return {"%": f"{v:.1%}", "倍": f"{v:.2f}", "亿": f"{v / 1e8:,.2f} 亿", "pct": f"{v:+.1f}pct", "月": f"{v:.1f}"}.get(u, str(v))


ICON = {"健康": "🟢", "通过": "🟢", "正常": "🟢", "中性": "⚪", "参考": "⚪", "关注": "🟡", "黄色": "🟡",
        "预警": "🔴", "红色": "🔴", "不适用": "—", "未获取": "❔", None: ""}


SEV = {"high": "🔴 高", "medium": "🟡 中", "low": "⚪ 低"}
STATE = {"风险解除": "🟢", "有所缓解": "🟢", "延续": "🟡", "风险加重": "🔴", "无法验证": "❔"}
REC = {"pass": "🟢 通过", "warn": "🟡 存疑", "fail": "🔴 不通过", "na": "— 不适用"}


def tag(t):
    return f"【{t}】" if t else ""


def write(a, doc, out_dir):
    m, t = a["meta"], a["meta"]["target_period"]
    mode = "季报快检" if m["mode"] == "quick" else "年报深检"
    g = a.get("gate") or {"status": "pass", "reasons": [], "reconciliations": []}
    draft = g["status"] != "pass"
    L = [f"# {m['name']}（{m['code']}）{t} {mode}" + ("（草稿）" if draft else ""), ""]
    if draft:
        L += ["> ⚠️ **草稿**：未通过数据门禁（" + "；".join(g["reasons"]) + "），结论仅供核对，不应引用。", ""]
    L += ["> 本报告只描述经营实况、风险与估值所处位置，不构成投资建议，不含买卖观点。", "",
          "证据标注：【披露】= 公告原文或接口原值；【计算】= 由披露数据按公式算出；【推断】= 基于计算的解释，需后续验证。", ""]
    core = [f"{a['headline']}【计算】"]
    br = a.get("bridge") or {}
    if br.get("status") == "ok":
        core.append(f"{br['text']}【计算】")
    elif (a.get("dupont") or {}).get("text"):
        core.append(f"{a['dupont']['text']}【计算】")
    risks = a.get("risks") or []
    if risks:
        r0 = risks[0]
        core.append(f"首要风险：{r0['title']}（{SEV[r0['severity']]}{'·待验证' if r0['id'] == 'price_up' else ''}）——{r0['explain']}{tag(r0.get('explain_type'))}")
    else:
        core.append("未发现成组风险信号【计算】")
    L += ["## 核心结论", ""] + [f"{i + 1}. {c}" for i, c in enumerate(core[:3])]
    dq = a["data_quality"]
    L += ["", "## 1. 数据可信度与门禁", "",
          f"- 门禁：{'🟢 通过' if not draft else '🔴 未通过 → 草稿'}" + ("" if not draft else "（" + "；".join(g["reasons"]) + "）")]
    for f in dq["filings"]:
        L.append(f"- 原文：{f['title']}（{f.get('publish_date') or '—'}），审计：{f.get('audit_opinion') or '—'}【披露】")
    L.append("- 目标期科目核对：" + "，".join(f"{k} {v}" for k, v in sorted(dq["coverage"].items(), key=lambda x: -x[1])))
    if dq["errors"]:
        L.append(f"- 🔴 **冲突 {len(dq['errors'])} 项（相关科目不进入结论）**：" + "；".join(dq["errors"][:5]))
    if dq.get("historical_errors"):
        L.append(f"- 🟡 较早年份冲突 {len(dq['historical_errors'])} 项（该科目该期不可用，只影响长期均值）：" + "；".join(dq["historical_errors"][:5]))
    for w in dq["warnings"][:6]:
        L.append(f"- 🟡 {w}")
    if not dq["filings"]:
        L.append("- 🔴 未取得公告原文：本报告为**草稿**，数字仅经接口互核")
    if g.get("reconciliations"):
        L += ["", "| 勾稽项 | 期间 | 结果 | 说明 |", "|---|---|---|---|"]
        for r in g["reconciliations"]:
            L.append(f"| {r['label']} | {r.get('period') or '—'} | {REC.get(r['status'], r['status'])} | {r.get('note') or ''} |")
    ar = a["archetype"]
    L += ["", "## 2. 企业分型", "", f"**{ar['name']}**（置信度：{ar['confidence']}；判定期 {ar['decided_at']}，{'深检' if ar['mode'] == 'deep' else '快检'}）", ""]
    L += [f"- {b}" for b in ar["basis"]]
    L.append(f"- 行业：{ar['industry'].get('em') or '—'}（东财）／{ar['industry'].get('csrc') or '—'}（证监会）")
    L.append(f"- 混合体：{ar['mixed']}")
    if ar.get("recheck_triggers"):
        L.append(f"- ⚠️ 触发分型复核条件：{'、'.join(ar['recheck_triggers'])} → 建议重做年报深检")
    L += ["", "## 3. 结果与差异（单季口径）【计算】", "", "| 指标 | 本季 | 同比 | 环比 | 年初至今 | 累计同比 | 连续趋势 |", "|---|---:|---:|---:|---:|---:|---|"]
    for r in a["changes"]:
        if r["key"] == "gm":
            L.append(f"| {r['name']} | {pct(r['single_q'])} | {_pp(r['pp_yoy'])} | {_pp(r['pp_qoq'])} | | | |")
            continue
        st = r["streak"]
        s = "—" if not st else f"同比{st['direction']}连续 {st['quarters']} 季" + ("（趋势确立）" if st["confirmed"] else "")
        L.append(f"| {r['name']}（亿） | {yi(r['single_q'])} | {growth(r['single_q'], r.get('single_q_ly'), r['single_q_yoy'], r['key'] == 'ocf')} | "
                 f"{growth(r['single_q'], r.get('single_q_pq'), r['single_q_qoq'], r['key'] == 'ocf')} | "
                 f"{yi(r['ytd'])} | {growth(r['ytd'], r.get('ytd_ly'), r['ytd_yoy'], r['key'] == 'ocf')} | {s} |")
    L += ["", "注：单季 = 本期累计 − 上期累计；同比基数采用本期报告中的比较期数（已含追溯调整）。"]
    J = a.get("jumps") or []
    L.append("- 单季比率跳变（偏离过去均值 2σ 以上）：" + ("无" if not J else ""))
    for j in J:
        L.append(f"  - ⚠️ {j['text']}【计算】→ 需附注确认是否一次性或口径变化")
    L += ["", "## 4. 驱动与持续性", ""]
    if br.get("status") == "ok":
        L.append(f"- 利润桥：{br['text']}【计算】")
        if br.get("gross_text"):
            L.append(f"- 毛利拆分：{br['gross_text']}【计算】")
    elif br:
        L.append(f"- 利润桥：{br.get('text') or br.get('status')}")
    if br.get("volume_price"):
        L.append(f"- 量价拆分：证据不足（{br['volume_price'].split('：', 1)[-1]}）")
    for x in a.get("persistence") or []:
        L.append(f"- 持续性·{x['kind']}：{x['text']}{tag(x.get('type'))}")
    if (a.get("dupont") or {}).get("text"):
        L.append(f"- 杜邦：{a['dupont']['text']}【计算】")
    L.append("- 业务层驱动（产品、客户、区域、管理层解释）：证据不足，需结合主营构成与管理层讨论补充。")
    L += ["", "## 5. 核心指标（按分型启用）【计算】", "", "| 指标 | 数值 | 判定 | 口径 | 阈值与来源 |", "|---|---:|---|---|---|"]
    for k, x in a["metrics"].items():
        note = f"；{x['note']}" if x.get("note") else ""
        dg = f"（{x['downgrade']}）" if x.get("downgrade") else ""
        L.append(f"| {x['name']} | {fmt(x)} | {ICON.get(x['verdict'], '')} {x['verdict'] or ''}{dg} | {x['formula']}{note} | {x['threshold'] or '—'} |")
    L += ["", "## 6. 风险（同源归并）", ""]
    if risks:
        L += ["| 风险组 | 严重度 | 组内信号 | 解释 | 下期验证条件 |", "|---|---|---|---|---|"]
        for r in risks:
            mem = "<br>".join(x["text"] for x in r["members"])
            nx = (r.get("next_metric") or {}).get("text") or "—"
            sv = SEV[r["severity"]] + ("（待验证）" if r["id"] == "price_up" else "") + (f"<br>{r['escalated']}" if r.get("escalated") else "")
            L.append(f"| {r['title']} | {sv} | {mem} | {r['explain']}{tag(r.get('explain_type'))} | {nx} |")
    else:
        L.append("- 未发现预警信号。")
    L += ["", "红旗清单（唐朝 12 条中底稿可算的 8 条）：", ""]
    if not a["red_flags"]:
        L.append("- 金融类不适用工商业红旗清单。")
    for f in a["red_flags"]:
        icon = {"红": "🔴", "黄": "🟡", "未触发": "🟢", "不适用": "—"}[f["level"]]
        L.append(f"- {icon} #{f['no']} {f['name']}：{('触发（' + f['level'] + '）') if f['hit'] else f['level']} — {f['detail']}")
    L.append("- #6 长期待摊、#8 毛利率异常、#9 费用率、#11 营业外收入需附注或同业数据，年报深检人工补充。")
    v = a["valuation"]
    L += ["", "## 7. 估值所处位置（不构成建议）", ""]
    c = v.get("current") or {}
    if c:
        L.append(f"- 方法（按分型）：{v['method']}")
        L.append(f"- 当前：股价 {c['price']}（{c['price_source']}，{c.get('quote_time')}），总股本 {c['total_shares'] / 1e8:.2f} 亿股，"
                 f"市值 {c['mcap'] / 1e8:,.0f} 亿；PE(TTM) {c['pe_ttm'] and round(c['pe_ttm'], 2) or '—'}，PB {c['pb'] and round(c['pb'], 2) or '—'}，"
                 f"PS(TTM) {c['ps_ttm'] and round(c['ps_ttm'], 2) or '—'}")
        H = v.get("history") or {}
        for key, n in (("pe", "PE(TTM)"), ("pb", "PB")):
            h = H.get(key)
            if h:
                L.append(f"- {n} 近 {h['n']} 个月：中位 {h['median']:.2f}，区间 {h['min']:.2f}–{h['max']:.2f}，当前处 {h['pct']:.0%} 分位（{h['position']}）"
                         + (f"；{h['note']}" if h.get("note") else ""))
        for s in v["implied"]:
            L.append(f"- 隐含：{s}")
        L.append("- 口径：历史市值 = 月末不复权收盘价 × 当时总股本；每月只用当时已到法定披露截止日的财务数据（防未来函数）。")
    for n in v.get("notes") or []:
        L.append(f"- 说明：{n}")
    L += ["", "## 8. 跟踪验证（可证伪）", ""]
    rv = a.get("tracking_review") or []
    if rv:
        L += ["上期命题回看：", "", "| 命题（提出期） | 结果 | 依据 |", "|---|---|---|"]
        for r in rv:
            L.append(f"| {r['risk']}（{r['created_period']}） | {STATE.get(r['state'], '')} {r['state']} | {r.get('detail') or ''} |")
        L.append("")
    else:
        L.append("- 上期无待验证命题（或首次分析）。")
    nw = a.get("tracking_new") or []
    if nw:
        L.append("本期新增命题（下期自动回看）：")
        L += [f"- [{x['due_period']}] {x['proposition']}" for x in nw]
    for n in a["notes"]:
        L.append(f"- 局限：{n}")
    L += ["", "---", f"规则版本 {a['rules_version']}｜分析 schema {a['schema']}｜底稿 schema {doc['schema']}｜生成 {a['generated_at']}"]
    path = os.path.join(out_dir, f"{'快检' if m['mode'] == 'quick' else '深检'}报告.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path
