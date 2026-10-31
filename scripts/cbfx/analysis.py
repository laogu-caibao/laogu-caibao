"""分析层：只读底稿（usable 的值），按规则手册计算分型、指标、红旗、估值位置。

输出的每个数都带 inputs（科目、报告期、取值），可回溯到底稿单元格；底稿缺数则结论为“未获取”，不估算。
"""
import datetime as dt
import json, os, statistics
from . import rules as R
from .synthesis import Synth
from .sources import market

FIN = {"bank": "BANK", "insurance": "INSURANCE", "securities": "SECURITIES"}


def _shift(p, years=-1):
    return f"{int(p[:4]) + years}{p[4:]}"


def _prev_q(p):
    y, md = int(p[:4]), p[5:]
    seq = ["03-31", "06-30", "09-30", "12-31"]
    i = seq.index(md)
    return f"{y}-{seq[i - 1]}" if i else f"{y - 1}-12-31"


def _div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def _yoy(cur, prev):
    if cur is None or prev is None or prev == 0:
        return None
    return (cur - prev) / abs(prev)


class Analyzer:
    def __init__(self, doc, out_dir, log=print, track=True, valuation=True, persist_archetype=True):
        self.d, self.out_dir, self.log = doc, out_dir, log
        self.track, self.do_val, self.persist_arch = track, valuation, persist_archetype
        self.m = doc["meta"]
        self.t = self.m["target_period"]
        self.periods = sorted(doc["periods"])
        self.sqd = doc["derived"]["single_quarter"]
        self.ttmd = doc["derived"]["ttm"]
        self.debt = doc["derived"]["interest_bearing_debt"]["values"]
        self.notes, self.metrics = [], {}

    # ---------- 取数（只取可用值） ----------
    def v(self, k, p):
        c = self.d["fields"].get(k, {}).get("values", {}).get(p)
        return c["value"] if c and c["usable"] else None

    def sq(self, k, p):
        return self.sqd.get(k, {}).get(p)

    def ttm(self, k, p):
        return self.ttmd.get(k, {}).get(p)

    def avg_bs(self, k, p):
        a, b = self.v(k, p), self.v(k, _shift(p))
        return (a + b) / 2 if a is not None and b is not None else a

    def fy_list(self):
        return sorted(p for p in self.periods if p.endswith("12-31") and self.v("rev", p) is not None)

    def put(self, key, name, value, unit, formula, inputs, verdict=None, th=None, note=None):
        self.metrics[key] = {"name": name, "value": value, "unit": unit, "formula": formula,
                             "inputs": [{"field": f, "period": p, "basis": b, "value": val} for f, p, b, val in inputs],
                             "verdict": verdict if value is not None else "未获取", "threshold": th, "note": note}
        return value

    # ---------- 1. 分型 ----------
    def classify(self):
        t, ct = self.t, self.m["company_type"]
        path = os.path.join(os.path.dirname(self.out_dir), "分型.json")
        try:
            self.industry = market.industry({"code": self.m["code"], "market": self.m["market"]})
        except Exception as e:
            self.industry = {"em": None, "csrc": None}
            self.notes.append(f"行业分类获取失败：{e}")
        ind = (self.industry.get("em") or "") + "|" + (self.industry.get("csrc") or "")
        basis = []
        rev_g = _yoy(self.ttm("rev", t), self.ttm("rev", _shift(t)))
        cip_fixed = _div(self.v("cip", t), self.v("fixed", t))
        rd_ttm, rev_ttm, np_ttm = self.ttm("rd_exp", t), self.ttm("rev", t), self.ttm("np_parent", t)
        gms = {p: _div(self.v("rev", p) - self.v("cost", p), self.v("rev", p))
               for p in self.fy_list() if self.v("cost", p) is not None}
        swing = None
        if len(gms) >= R.CYCLE_MIN_YEARS and max(gms.values()) > 0:
            swing = (max(gms.values()) - min(gms.values())) / max(gms.values())
        cyc_kw = next((k for k in R.CYCLICAL_KW if k in ind), None)
        fys = self.fy_list()
        np_yoys = [_yoy(self.v("np_parent", b), self.v("np_parent", a)) for a, b in zip(fys, fys[1:])]
        np_yoys = [x for x in np_yoys if x is not None]
        worst = min(np_yoys) if np_yoys else None
        swing_hit = swing is not None and swing > R.CYCLE_GM_SWING and worst is not None and worst <= R.CYCLE_NP_DROP
        conf = "中"
        if ct in FIN:
            arch, conf = FIN[ct], "高"
            basis.append(f"底稿报表模板为{self.m['company_type_cn']}")
        elif any(k in ind for k in R.REALESTATE_KW):
            arch, conf = "RE", "高"
            basis.append(f"行业：{self.industry.get('em')}")
        elif rev_ttm is not None and rd_ttm is not None and rev_ttm > 0 and (rev_ttm < rd_ttm or (
                np_ttm is not None and np_ttm < 0 and rd_ttm / rev_ttm > R.D_RD_TO_REV)):
            arch = "D"
            basis.append(f"Q1：研发 TTM {rd_ttm / 1e8:.2f} 亿 vs 营收 TTM {rev_ttm / 1e8:.2f} 亿，归母 TTM {np_ttm / 1e8 if np_ttm else 0:.2f} 亿")
        elif cyc_kw or swing_hit:
            arch = "B"
            if cyc_kw:
                basis.append(f"Q2：行业“{self.industry.get('em')}”属强周期（关键词“{cyc_kw}”）")
            if swing is not None:
                basis.append(f"Q2：{len(gms)} 个年度毛利率峰谷差 ÷ 峰值 = {swing:.0%}（阈值 {R.CYCLE_GM_SWING:.0%}），"
                             f"期内归母最差年度同比 {worst:+.0%}（阈值 {R.CYCLE_NP_DROP:.0%}）" if worst is not None else
                             f"Q2：{len(gms)} 个年度毛利率峰谷差 ÷ 峰值 = {swing:.0%}（阈值 {R.CYCLE_GM_SWING:.0%}）")
            conf = "高" if (cyc_kw and swing_hit) else "中"
        elif (rev_g is not None and rev_g > R.GROWTH_REV_YOY) or (cip_fixed is not None and cip_fixed > R.GROWTH_CIP_FIXED):
            arch = "C"
            basis.append(f"Q3：营收 TTM 同比 {rev_g:.1%}" if rev_g is not None else "Q3：营收增速未获取")
            basis.append(f"Q3：在建工程 ÷ 固定资产 = {cip_fixed:.1%}" if cip_fixed is not None else "Q3：在建/固定未获取")
        else:
            arch = "A"
            basis.append(f"Q1 否；Q2 否（行业“{self.industry.get('em')}”非强周期"
                         + (f"，{len(gms)} 年毛利率峰谷差 {swing:.0%}"
                            + (f"、归母最差年度同比 {worst:+.0%}" if worst is not None else "")
                            + ("；毛利率变化大但利润未出现周期性大幅下滑，视为趋势性变化" if swing > R.CYCLE_GM_SWING else "")
                            if swing is not None else "，年度数据不足 5 年未做毛利率周期检验") + "）")
            basis.append(f"Q3 否：营收 TTM 同比 {rev_g:.1%}" if rev_g is not None else "Q3：营收增速未获取")
        if swing is None and arch in "ABC" and len(arch) == 1:
            conf = "低" if arch == "A" else conf
            self.notes.append("年度数据不足 5 年，周期性只能靠行业判断；建议跑年报深检（--mode deep）确认分型")
        prev = None
        if os.path.exists(path) and self.persist_arch:
            prev = json.load(open(path, encoding="utf-8"))
        cur = {"archetype": arch, "name": R.ARCHETYPE_CN[arch], "confidence": conf, "basis": basis,
               "industry": self.industry, "decided_at": t, "mode": self.m["mode"],
               "mixed": "混合体判定需要年报“主营业务构成”分部数据，v0 未自动化；新兴业务占比 10%–70% 时须人工拆分",
               "rules_version": R.VERSION}
        if self.m["mode"] == "quick" and prev and prev.get("mode") == "deep":
            cur_quick = cur
            cur = dict(prev, quick_recheck=cur_quick["archetype"])
            if cur_quick["archetype"] != prev["archetype"]:
                self.notes.append(f"快检按本期数据判为 {cur_quick['name']}，与深检结论 {prev['name']} 不同，沿用深检，建议复核")
        elif self.persist_arch and (self.m["mode"] == "deep" or not prev or prev.get("mode") != "deep"):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cur, f, ensure_ascii=False, indent=1)
        self.arch = cur["archetype"]
        self.archetype = cur
        self._recheck_triggers()
        return cur

    def _recheck_triggers(self):
        t, ly = self.t, _shift(self.t)
        trig = []
        g = _yoy(self.sq("rev", t), self.sq("rev", ly))
        if g is not None and abs(g) > R.RECHECK["rev_sq_yoy_abs"]:
            trig.append(f"单季营收同比 {g:+.0%}")
        gm, gm0 = self._gm_sq(t), self._gm_sq(ly)
        if gm is not None and gm0 is not None and abs(gm - gm0) * 100 > R.RECHECK["gm_sq_change_pp"]:
            trig.append(f"单季毛利率同比变动 {(gm - gm0) * 100:+.1f}pct")
        a, b = self.sq("np_parent", t), self.sq("np_parent", ly)
        if a is not None and b is not None and (a > 0) != (b > 0):
            trig.append("单季归母净利润盈亏反转")
        self.archetype["recheck_triggers"] = trig

    def _gm_sq(self, p):
        r, c = self.sq("rev", p), self.sq("cost", p)
        return _div(r - c, r) if r is not None and c is not None else None

    # ---------- 2. 本期发生了什么 ----------
    def changes(self):
        t, ly, pq = self.t, _shift(self.t), _prev_q(self.t)
        rows = []
        for k, name in (("rev", "营业收入"), ("np_parent", "归母净利润"), ("np_ded", "扣非归母净利润"), ("ocf", "经营现金流净额")):
            cur = self.sq(k, t)
            ytd, ytd0 = self.v(k, t), self.v(k, ly)
            streak = self._streak(k)
            rows.append({"key": k, "name": name, "single_q": cur, "single_q_ly": self.sq(k, ly), "single_q_pq": self.sq(k, pq),
                         "ytd_ly": ytd0, "single_q_yoy": _yoy(cur, self.sq(k, ly)),
                         "single_q_qoq": _yoy(cur, self.sq(k, pq)), "ytd": ytd, "ytd_yoy": _yoy(ytd, ytd0),
                         "streak": streak})
        gm, gm0, gmq = self._gm_sq(t), self._gm_sq(ly), self._gm_sq(pq)
        rows.append({"key": "gm", "name": "毛利率（单季）", "single_q": gm, "pp_yoy": (gm - gm0) * 100 if None not in (gm, gm0) else None,
                     "pp_qoq": (gm - gmq) * 100 if None not in (gm, gmq) else None})
        self.change_rows = rows
        return rows

    def _streak(self, k):
        """从最近一季往前数：单季同比同号连续期数（FRA：≥3 期 = 趋势确立）。"""
        qs = [p for p in sorted(self.periods, reverse=True) if p <= self.t]
        n, sign = 0, None
        for p in qs:
            g = _yoy(self.sq(k, p), self.sq(k, _shift(p)))
            if g is None:
                break
            s = g > 0
            if sign is None:
                sign = s
            if s != sign:
                break
            n += 1
        if sign is None:
            return None
        return {"direction": "增长" if sign else "下滑", "quarters": n, "confirmed": n >= R.TREND_CONFIRM_N}

    # ---------- 3. 核心指标 ----------
    def indicators(self):
        t, a = self.t, self.arch
        fin = a in ("BANK", "INSURANCE", "SECURITIES")
        npp, eqa = self.ttm("np_parent", t), self.avg_bs("eq_parent", t)
        th = R.TH["roe"]
        roe = _div(npp, eqa)
        self.put("roe", "ROE（TTM，归母口径）", roe, "%", "归母净利润 TTM ÷ 平均归母权益（期初期末）",
                 [("np_parent", t, "TTM", npp), ("eq_parent", t, "期末", self.v("eq_parent", t)),
                  ("eq_parent", _shift(t), "上年同期末", self.v("eq_parent", _shift(t)))],
                 self._grade(roe, th["good"], th["warn"]) if a in ("A", "BANK", "INSURANCE", "SECURITIES") else "参考",
                 f"健康 ≥{th['good']:.0%}，预警 <{th['warn']:.0%}（{th['src']}）" + ("；B 型看跨周期均值、C 型看趋势、D 型弃用" if a in "BCD" else ""))
        fy = self.fy_list()
        roes = {}
        for p in fy:
            e = self.avg_bs("eq_parent", p)
            if self.v("np_parent", p) is not None and e:
                roes[p[:4]] = self.v("np_parent", p) / e
        if len(roes) >= 3:
            mean = statistics.mean(roes.values())
            self.put("roe_avg", f"ROE 年度均值（{len(roes)} 年）", mean, "%", "各年 归母净利润 ÷ 平均归母权益 的算术平均",
                     [("np_parent", f"{y}-12-31", "年度", None) for y in roes],
                     None, "A 型：5 年均值 >15% 且近 3 年无一年 <10%；B 型：跨周期均值 <8% 且 PB 高分位 → 排除线",
                     "；".join(f"{y} {v:.1%}" for y, v in roes.items()))
            self.roe_years = roes
        else:
            self.roe_years = roes
        if not fin:
            nd = self.ttm("np_ded", t)
            r = _div(nd, npp) if npp and npp > 0 else None
            th = R.TH["np_ded_ratio"]
            self.put("np_ded_ratio", "扣非 ÷ 归母（TTM）", r, "%", "扣非归母净利润 TTM ÷ 归母净利润 TTM",
                     [("np_ded", t, "TTM", nd), ("np_parent", t, "TTM", npp)], self._grade(r, th["good"], th["warn"]),
                     f"≥{th['good']:.0%} 佳，<{th['warn']:.0%} 预警（{th['src']}）", "归母为负时不计算" if npp is not None and npp <= 0 else None)
            ocf, n = self.ttm("ocf", t), self.ttm("np", t)
            r = _div(ocf, n) if n and n > 0 else None
            th = R.TH["ocf_np"]
            good = th["good_A"] if a == "A" else th["good"]
            self.put("ocf_np", "净现比（TTM）", r, "倍", "经营现金流净额 TTM ÷ 净利润 TTM",
                     [("ocf", t, "TTM", ocf), ("np", t, "TTM", n)],
                     "不适用" if a == "D" else self._grade(r, good, th["warn"]),
                     f"健康 ≥{good}，预警 <{th['warn']}（{th['src']}）；B 型看全周期累计，C 型允许 <1 但须解释缺口")
            sc, rv = self.ttm("sales_cash", t), self.ttm("rev", t)
            r = _div(sc, rv)
            th = R.TH["cash_rev"]
            self.put("cash_rev", "收现比（TTM）", r, "倍", "销售商品、提供劳务收到的现金 TTM ÷ 营业收入 TTM",
                     [("sales_cash", t, "TTM", sc), ("rev", t, "TTM", rv)], self._grade(r, th["good"], th["warn"]),
                     f"≥{th['good']} 健康，<{th['warn']} 预警（含增值税，>1 正常）")
            parts = {k: self.ttm(k, t) for k in ("rev", "cost", "tax_surcharge", "sell_exp", "admin_exp", "rd_exp", "int_exp")}
            core = None
            if all(parts[k] is not None for k in ("rev", "cost", "tax_surcharge", "sell_exp", "admin_exp")):
                core = parts["rev"] - sum(parts[k] or 0 for k in parts if k != "rev")
            opp = self.ttm("op_profit", t)
            r = _div(core, opp) if opp and opp > 0 else None
            th = R.TH["core_op"]
            self.put("core_profit", "核心利润（TTM）", core, "亿", "营收−营业成本−税金及附加−销售−管理−研发−利息费用",
                     [(k, t, "TTM", v) for k, v in parts.items()], None, None,
                     "研发或利息费用未获取时按 0 计" if core is not None and (parts["rd_exp"] is None or parts["int_exp"] is None) else None)
            pb = {k: self.ttm(k, t) for k in ("fin_exp",)}
            core_b = core + (parts["int_exp"] or 0) - (pb["fin_exp"] or 0) if core is not None else None
            self.put("core_profit_b", "核心利润·口径二（TTM）", core_b, "亿", "营收−营业成本−税金及附加−销售−管理−研发−财务费用（全额，含利息收入与汇兑）",
                 [("fin_exp", t, "TTM", pb["fin_exp"])], None, None,
                 "张新民两种口径并列：口径一只扣利息费用（看经营本身），口径二扣财务费用全额（含利息收入与汇兑）；两者差距大说明资金收益或汇兑影响大")
            self.put("core_op", "核心利润 ÷ 营业利润（TTM）", r, "%", "核心利润 ÷ 营业利润",
                     [("op_profit", t, "TTM", opp)], self._grade(r, th["good"], th["warn"]),
                     f"≥{th['good']:.0%} 优秀，<{th['warn']:.0%} 需警惕“在玩不在干”（{th['src']}）")
            oi = self.ttm("other_inc", t) or 0
            r = _div(ocf, core + oi) if core is not None and core + oi > 0 else None
            th = R.TH["core_cash"]
            self.put("core_cash", "核心利润获现率（TTM）", r, "倍", "经营现金流净额 ÷（核心利润 + 其他收益）",
                     [("ocf", t, "TTM", ocf), ("other_inc", t, "TTM", oi)], self._grade(r, th["good"], th["warn"]),
                     f"1.2–1.5 理想，<{th['warn']} 预警（{th['src']}）")
            d_, ta = self.debt.get(t), self.v("ta", t)
            r = _div(d_, ta)
            th = R.TH["ibd_ta"]
            self.put("ibd_ta", "有息负债率（近似）", r, "%", "（短借+一年内到期非流动负债+长借+应付债券+租赁负债）÷ 总资产",
                     [("interest_bearing_debt", t, "期末", d_), ("ta", t, "期末", ta)], self._grade(r, th["good"], th["warn"], lower=True),
                     f"<{th['good']:.0%} 优，≥{th['warn']:.0%} 关注（{th['src']}）", "一年内到期非流动负债全额计入，偏保守")
            tl = self.v("tl", t)
            r = _div(tl, ta)
            th = R.TH["debt_ratio"]
            self.put("debt_ratio", "资产负债率", r, "%", "负债合计 ÷ 资产总计", [("tl", t, "期末", tl), ("ta", t, "期末", ta)],
                     "参考" if a == "RE" else self._grade(r, th["good"], th["warn"], lower=True), f"制造业 <{th['good']:.0%}，>{th['warn']:.0%} 预警（{th['src']}）")
            cx = self.ttm("capex", t)
            fcf = ocf - cx if ocf is not None and cx is not None else None
            self.put("fcf", "自由现金流（TTM）", fcf, "亿", "经营现金流净额 − 购建长期资产支付的现金",
                     [("ocf", t, "TTM", ocf), ("capex", t, "TTM", cx)], ("健康" if fcf and fcf > 0 else "关注") if fcf is not None else None,
                     ">0 且稳定；C 型扩张期为负需解释")
            gw, eq = self.v("goodwill", t), self.v("eq_parent", t)
            r = _div(gw or 0, eq) if eq else None
            th = R.TH["goodwill_eq"]
            self.put("goodwill_eq", "商誉 ÷ 归母权益", r, "%", "商誉 ÷ 归母所有者权益", [("goodwill", t, "期末", gw), ("eq_parent", t, "期末", eq)],
                     self._grade(r, th["good"], th["warn"], lower=True), f"<{th['good']:.0%} 低，>{th['warn']:.0%} 预警")
            gm, gm0 = self._gm_ytd(t), self._gm_ytd(_shift(t))
            ch = (gm - gm0) * 100 if None not in (gm, gm0) else None
            self.put("gm", "毛利率（年初至今）", gm, "%", "（营收−营业成本）÷ 营收", [("rev", t, "累计", self.v("rev", t)), ("cost", t, "累计", self.v("cost", t))],
                     ("预警" if ch is not None and ch < R.TH["gm_yoy_pp"]["warn"] else "中性") if a != "D" else "不适用",
                     f"同比下滑 >{-R.TH['gm_yoy_pp']['warn']:.0f}pct 预警；B 型只做同期同业比", f"同比 {ch:+.1f}pct" if ch is not None else None)
            self.gm_change = ch
            # 应收、存货增速差
            rec = self._sum(("ar", "notes_rec", "rec_fin"), t)
            rec0 = self._sum(("ar", "notes_rec", "rec_fin"), _shift(t))
            rg = _yoy(self.v("rev", t), self.v("rev", _shift(t)))
            gap = (_yoy(rec, rec0) - rg) * 100 if None not in (_yoy(rec, rec0), rg) else None
            self.put("ar_gap", "应收增速 − 营收增速", gap, "pct", "（应收账款+应收票据+应收款项融资）同比 − 营收（年初至今）同比",
                     [("ar+notes_rec+rec_fin", t, "期末", rec), ("ar+notes_rec+rec_fin", _shift(t), "上年同期末", rec0)],
                     ("预警" if gap > R.TH["ar_gap_pp"]["warn"] else "正常") if gap is not None else None, f">{R.TH['ar_gap_pp']['warn']:.0f}pct 预警")
            iv, iv0 = self.v("inv", t), self.v("inv", _shift(t))
            gap2 = (_yoy(iv, iv0) - rg) * 100 if None not in (_yoy(iv, iv0), rg) else None
            self.put("inv_gap", "存货增速 − 营收增速", gap2, "pct", "存货同比 − 营收（年初至今）同比",
                     [("inv", t, "期末", iv), ("inv", _shift(t), "上年同期末", iv0)],
                     ("预警" if gap2 > R.TH["inv_gap_pp"]["warn"] else "正常") if gap2 is not None else None, f">{R.TH['inv_gap_pp']['warn']:.0f}pct 预警")
        if a == "D" or (self.ttm("ocf", t) is not None and self.ttm("ocf", t) < 0 and a != "RE" and not fin):
            cash, ocf = self.v("cash", t), self.ttm("ocf", t)
            burn = -ocf / 12 if ocf is not None and ocf < 0 else None
            r = _div(cash, burn)
            th = R.TH["runway_m"]
            self.put("runway", "现金续航（月）", r, "月", "货币资金 ÷ 月均经营现金净流出（TTM/12）",
                     [("cash", t, "期末", cash), ("ocf", t, "TTM", ocf)],
                     ("红色" if r < th["red"] else "黄色" if r < th["yellow"] else "通过") if r is not None else ("通过" if ocf and ocf >= 0 else None),
                     f"<{th['red']} 月红色，{th['red']}–{th['yellow']} 黄色（{th['src']}）", "未计交易性金融资产（字段未接入），偏保守")
        if a == "RE":
            tl, ta = self.v("tl", t), self.v("ta", t)
            adv = (self.v("contract_liab", t) or 0) + (self.v("adv_rec", t) or 0)
            r1 = _div(tl - adv, ta - adv) if tl is not None and ta is not None else None
            self.put("re_debt_ex_adv", "剔除预收款的资产负债率", r1, "%", "（负债−合同负债−预收款项）÷（资产−合同负债−预收款项）",
                     [("tl", t, "期末", tl), ("ta", t, "期末", ta), ("contract_liab+adv_rec", t, "期末", adv)],
                     self._grade(r1, R.TH["re_debt_ex_adv"]["warn"], R.TH["re_debt_ex_adv"]["warn"], lower=True), "<70%（三道红线）")
            d_, cash, eqt = self.debt.get(t), self.v("cash", t), self.v("eq_total", t)
            r2 = _div(d_ - cash, eqt) if None not in (d_, cash) else None
            self.put("re_net_gearing", "净负债率", r2, "%", "（有息负债−货币资金）÷ 所有者权益",
                     [("interest_bearing_debt", t, "期末", d_), ("cash", t, "期末", cash), ("eq_total", t, "期末", eqt)],
                     self._grade(r2, 1.0, 1.0, lower=True), "<100%（三道红线）", "货币资金含受限资金，偏乐观")
            sd = (self.v("st_loan", t) or 0) + (self.v("ncl_1y", t) or 0)
            r3 = _div(cash, sd)
            self.put("re_cash_short", "现金短债比", r3, "倍", "货币资金 ÷（短期借款+一年内到期的非流动负债）",
                     [("cash", t, "期末", cash), ("st_loan+ncl_1y", t, "期末", sd)], self._grade(r3, 1.0, 1.0), ">1（三道红线）", "货币资金含受限资金，偏乐观")
        if fin:
            ta = self.avg_bs("ta", t)
            roa = _div(self.ttm("np", t), ta)
            self.put("roa", "ROA（TTM）", roa, "%", "净利润 TTM ÷ 平均总资产", [("np", t, "TTM", self.ttm("np", t)), ("ta", t, "平均", ta)], "参考", None)
            lev = _div(self.v("ta", t), self.v("eq_total", t))
            self.put("leverage", "权益乘数", lev, "倍", "资产总计 ÷ 所有者权益", [("ta", t, "期末", self.v("ta", t)), ("eq_total", t, "期末", self.v("eq_total", t))], "参考", None)
            for k, n in {"BANK": ("净息差、不良率、拨备覆盖率、拨贷比、核心一级资本充足率"),
                         "INSURANCE": ("新业务价值 NBV、内含价值 EV、综合成本率、偿付能力充足率"),
                         "SECURITIES": ("业务收入结构、风控指标、杠杆率")}.items():
                if a == k:
                    self.notes.append(f"{R.ARCHETYPE_CN[a]}核心指标（{n}）尚未接入底稿，本报告不做资产质量/资本结论；需读原文“主要会计数据/补充财务资料”")
        return self.metrics

    def _gm_ytd(self, p):
        r, c = self.v("rev", p), self.v("cost", p)
        return _div(r - c, r) if r is not None and c is not None else None

    def _sum(self, ks, p):
        vals = [self.v(k, p) for k in ks]
        return None if all(x is None for x in vals) else sum(x or 0 for x in vals)

    @staticmethod
    def _grade(v, good, warn, lower=False):
        if v is None:
            return None
        if lower:
            return "健康" if v < good else ("预警" if v >= warn else "中性")
        return "健康" if v >= good else ("预警" if v < warn else "中性")

    # ---------- 4. 红旗 ----------
    def red_flags(self):
        t, a, out = self.t, self.arch, []
        if a in ("BANK", "INSURANCE", "SECURITIES"):
            self.flags = []
            return []
        typ = a if a in "ABCD" else "A"

        def add(no, hit, detail, inputs):
            f = R.FLAGS[no]
            if typ in f["types"]:
                level = "红"
            elif typ in f.get("yellow", ""):
                level = "黄"
            else:
                level = "不适用"
            out.append({"no": no, "name": f["name"], "hit": hit, "level": level if hit else ("不适用" if level == "不适用" else "未触发"),
                        "detail": detail, "inputs": inputs})

        cash, ta, d_ = self.v("cash", t), self.v("ta", t), self.debt.get(t)
        if None not in (cash, ta, d_):
            add(1, cash / ta > R.FLAGS[1]["cash_ta"] and d_ / ta > R.FLAGS[1]["ibd_ta"],
                f"货币资金/总资产 {cash / ta:.1%}，有息负债率 {d_ / ta:.1%}（均 >20% 触发）", ["cash", "interest_bearing_debt", "ta"])
        g = self.metrics.get("ar_gap", {}).get("value")
        if g is not None:
            add(2, g > R.FLAGS[2]["gap_pp"], f"应收增速 − 营收增速 = {g:+.1f}pct（>20pct 触发）", ["ar", "notes_rec", "rec_fin", "rev"])
        g2, gmc = self.metrics.get("inv_gap", {}).get("value"), getattr(self, "gm_change", None)
        if g2 is not None and gmc is not None:
            add(3, g2 > 0 and gmc > 0, f"存货增速 − 营收增速 = {g2:+.1f}pct，毛利率同比 {gmc:+.1f}pct（存货跑赢营收且毛利率上升触发）", ["inv", "rev", "cost"])
        cip, fx = self.v("cip", t), self.v("fixed", t)
        if cip is not None and fx:
            add(4, cip / fx > R.FLAGS[4]["cip_fixed"], f"在建工程 ÷ 固定资产 = {cip / fx:.1%}（>50% 触发；是否长期不转固需年报附注）", ["cip", "fixed"])
        orc = self.v("other_rec", t)
        if orc is not None and ta:
            add(5, orc / ta > R.FLAGS[5]["ratio"], f"其他应收款 ÷ 总资产 = {orc / ta:.1%}（>5% 触发）", ["other_rec", "ta"])
        gw, eq = self.v("goodwill", t), self.v("eq_parent", t)
        if eq:
            add(7, (gw or 0) / eq > R.FLAGS[7]["ratio"], f"商誉 ÷ 归母权益 = {(gw or 0) / eq:.1%}（>30% 触发）", ["goodwill", "eq_parent"])
        imp = [self.ttm(k, t) for k in ("asset_impair", "credit_impair")]
        npp = self.ttm("np_parent", t)
        if any(x is not None for x in imp) and npp and npp > 0:
            s = abs(sum(x or 0 for x in imp))
            add(10, s / npp > R.FLAGS[10]["ratio"], f"资产+信用减值 TTM {s / 1e8:.2f} 亿，占归母 TTM {s / npp:.1%}（>30% 触发）", ["asset_impair", "credit_impair", "np_parent"])
        n, ocf = self.ttm("np", t), self.ttm("ocf", t)
        if None not in (n, ocf):
            add(12, n > 0 and ocf < 0, f"净利润 TTM {n / 1e8:.2f} 亿，经营现金流 TTM {ocf / 1e8:.2f} 亿（净利为正而现金流为负触发）", ["np", "ocf"])
        self.flags = out
        return out

    # ---------- 5. 估值位置 ----------
    def valuation(self):
        t, a = self.t, self.arch
        org = {"code": self.m["code"], "market": self.m["market"]}
        res = {"method": None, "current": {}, "history": {}, "implied": [], "notes": []}
        try:
            kl = market.monthly_kline(org)
            sh = market.share_history(org)
        except Exception as e:
            res["notes"].append(f"历史行情/股本获取失败，跳过估值位置：{e}")
            self.val = res
            return res
        snap = next(iter(self.d.get("quote", {}).get("snapshots") or []), None)
        price = snap["price"] if snap else kl[-1]["close"]
        shares = sh[-1]["total_shares"]
        mcap = price * shares
        res["current"] = {"price": price, "price_source": snap["source"] if snap else "腾讯月K线收盘",
                          "total_shares": shares, "mcap": mcap, "quote_time": snap.get("time") if snap else kl[-1]["date"]}
        if snap and snap.get("mcap_yi") and abs(snap["mcap_yi"] * 1e8 / mcap - 1) > 0.02:
            res["notes"].append(f"自算市值 {mcap / 1e8:.0f} 亿与行情软件 {snap['mcap_yi']:.0f} 亿差异 >2%（股本口径差），以自算为准")
        npp, eq, rev = self.ttm("np_parent", t), self.v("eq_parent", t), self.ttm("rev", t)
        cur = {"pe_ttm": mcap / npp if npp and npp > 0 else None, "pb": mcap / eq if eq else None,
               "ps_ttm": mcap / rev if rev else None}
        res["current"].update(cur)
        if snap and snap.get("pe_ttm") and cur["pe_ttm"] and abs(snap["pe_ttm"] / cur["pe_ttm"] - 1) > 0.05:
            res["notes"].append(f"自算 PE(TTM) {cur['pe_ttm']:.2f} 与{snap['source']} {snap['pe_ttm']:.2f} 差 >5%（多因 TTM 期次或股本口径不同）")
        # 历史：每月末用“当时已披露”的最近一期财务数据
        hist = []
        avail = sorted(p for p in self.periods if self.v("eq_parent", p) is not None)
        for k in kl:
            m_ = k["date"]
            ps = [p for p in avail if self._published(p) <= m_]
            if not ps:
                continue
            p = ps[-1]
            s_ = next((x["total_shares"] for x in reversed(sh) if x["date"] <= m_), sh[0]["total_shares"])
            mc = k["close"] * s_
            n_ = self.ttm("np_parent", p)
            hist.append({"month": m_[:7], "period": p, "pe": mc / n_ if n_ and n_ > 0 else None, "pb": mc / self.v("eq_parent", p)})
        res["history"] = {"months": len(hist), "from": hist[0]["month"] if hist else None, "to": hist[-1]["month"] if hist else None}
        for key in ("pe", "pb"):
            xs = [h[key] for h in hist if h[key] is not None]
            c = cur["pe_ttm" if key == "pe" else "pb"]
            if len(xs) >= 24 and c is not None:
                res["history"][key] = {"n": len(xs), "median": statistics.median(xs), "min": min(xs), "max": max(xs),
                                       "pct": sum(1 for x in xs if x <= c) / len(xs)}
        if len(hist) < 36:
            res["notes"].append(f"历史估值样本仅 {len(hist)} 个月（快检只有约 4 年财务数据），分位参考性有限；深检可覆盖 10 年 PB")
        # 分型对应方法
        H = res["history"]
        if a == "B":
            res["method"] = "PB 历史分位 + 跨周期平均利润倍数；禁用当期 PE（周期顶部 PE 最低、最危险）"
            fy_np = [self.v("np_parent", p) for p in self.fy_list()]
            fy_np = [x for x in fy_np if x is not None]
            if len(fy_np) >= 3:
                avg = statistics.mean(fy_np)
                res["current"]["pe_on_avg_profit"] = mcap / avg if avg > 0 else None
                res["implied"].append(f"当前市值是近 {len(fy_np)} 个年度平均归母利润（{avg / 1e8:.1f} 亿）的 "
                                      f"{mcap / avg:.1f} 倍；当期 PE(TTM) {cur['pe_ttm']:.1f} 倍" if avg > 0 and cur["pe_ttm"] else "年度平均利润为负，跨周期倍数不可用")
        elif a == "D":
            res["method"] = "期权思维；PE/PB 不适用，只列市销率供参考"
            if cur["ps_ttm"]:
                res["implied"].append(f"当前市值是营收 TTM 的 {cur['ps_ttm']:.1f} 倍，价格主要反映对技术里程碑的预期，财务数据无法验证")
        elif a == "RE":
            res["method"] = "PB 历史分位；亏损或利润大幅波动时 PE 不可用（地产需结合存货减值风险看 PB 含金量）"
        elif a in ("BANK", "INSURANCE", "SECURITIES"):
            res["method"] = "PB 历史分位为主，结合 ROE（PB ≈ ROE × 合理 PE）"
            res["notes"].append("PB 分母为归母所有者权益，含永续债等其他权益工具，可能低于行情软件 PB（行情软件多扣除）")
            roe = self.metrics.get("roe", {}).get("value")
            if roe and cur["pb"]:
                res["implied"].append(f"PB {cur['pb']:.2f} 倍、ROE {roe:.1%}：相当于为每 1 元年利润支付 {cur['pb'] / roe:.1f} 元")
        else:
            res["method"] = "PE 历史分位 + PB 交叉" + ("；C 型配合增速看 PEG（历史增速，非预测）" if a == "C" else "")
            if cur["pe_ttm"]:
                res["implied"].append(f"利润不增长时，按当前市值需 {cur['pe_ttm']:.1f} 年归母利润才能“回本”")
                if H.get("pe"):
                    need = cur["pe_ttm"] / H["pe"]["median"] - 1
                    res["implied"].append(f"价格不变时，估值回到近 {H['pe']['n'] // 12} 年 PE 中位数（{H['pe']['median']:.1f} 倍）需要 TTM 归母利润"
                                          f"{'增长' if need >= 0 else '下降'} {abs(need):.0%}")
            if a == "C":
                g = _yoy(npp, self.ttm("np_parent", _shift(t)))
                if g and g > 0 and cur["pe_ttm"]:
                    res["current"]["peg_hist"] = cur["pe_ttm"] / (g * 100)
                    res["implied"].append(f"PEG（用过去一年归母 TTM 增速 {g:.0%}）= {cur['pe_ttm'] / (g * 100):.2f}；未来增速需另行交叉验证")
        for key in ("pe", "pb"):
            h = H.get(key)
            if h:
                pos = "偏低区" if h["pct"] < R.PCT_LOW else "偏高区" if h["pct"] > R.PCT_HIGH else "中间区"
                h["position"] = pos
        if a == "B" and H.get("pe"):
            H["pe"]["note"] = "B 型不以 PE 分位判断（周期顶部 PE 最低）"
        self.val = res
        return res

    def _published(self, p):
        md = R.PUB_LAG[p[5:]]
        y = int(p[:4]) + (1 if p.endswith("12-31") else 0)
        return f"{y}-{md}"

    # ---------- 6. 汇总 ----------
    def headline(self):
        t = self.t
        c = {r["key"]: r for r in self.change_rows}
        bits = []
        for k in ("rev", "np_parent", "np_ded"):
            r = c.get(k)
            if r and r["single_q"] is not None and r["single_q_yoy"] is not None:
                a_, b_ = r["single_q"], r["single_q_ly"]
                if a_ < 0 or b_ < 0:
                    g = "扭亏" if b_ < 0 <= a_ else "转亏" if b_ >= 0 > a_ else ("亏损收窄" if a_ > b_ else "亏损扩大")
                    g = f"上年同期 {b_ / 1e8:.2f} 亿，{g}"
                else:
                    g = f"同比 {r['single_q_yoy']:+.1%}"
                bits.append(f"单季{r['name']} {a_ / 1e8:.2f} 亿（{g}）")
        ocf = self.metrics.get("ocf_np", {}).get("value")
        if ocf is not None:
            bits.append(f"净现比 TTM {ocf:.2f}")
        reds = [f for f in self.flags if f["hit"] and f["level"] == "红"]
        yel = [f for f in self.flags if f["hit"] and f["level"] == "黄"]
        # 应收/存货增速差已由红旗 #2/#3 表达，不重复计数
        warn_m = [m["name"] for k, m in self.metrics.items() if m["verdict"] in ("预警", "红色") and k not in ("ar_gap", "inv_gap")]
        errs, hist_errs = self.split_errors()
        if errs:
            tail = f"近期数据存在 {len(errs)} 项冲突，结论待人工核对"
        elif reds or warn_m:
            tail = f"存在 {len(reds) + len(warn_m)} 项待解释风险（{'、'.join([f['name'] for f in reds] + warn_m)}）"
        elif yel:
            tail = f"{len(yel)} 项黄色信号需结合明细判断"
        elif self.arch in ("BANK", "INSURANCE", "SECURITIES"):
            tail = "金融类行业核心指标（资产质量、资本、负债成本等）尚未接入，本报告不做健康度结论"
        else:
            tail = "本期底稿可算的红旗与预警指标均未触发"
        if hist_errs:
            tail += f"（另有 {len(hist_errs)} 项较早年份数据冲突，只影响长期均值类指标，不影响本期结论）"
        return f"{self.m['name']} {t}：" + "；".join(bits) + f"。{tail}。"

    def split_errors(self):
        """近期（本期结论用到的约两年内）冲突 vs 历史期冲突。历史期冲突只影响长期均值，不阻断本期结论。"""
        y = int(self.m["target_period"][:4])
        cutoff = f"{y - 2}-12-31"
        near, hist = [], []
        for i in self.d["issues"]:
            if i["level"] != "error":
                continue
            (hist if i.get("period") and i["period"] < cutoff else near).append(i)
        return near, hist

    def run(self):
        self.classify()
        self.changes()
        self.indicators()
        self.red_flags()
        if self.do_val:
            self.valuation()
        else:
            self.val = {"method": None, "current": {}, "history": {}, "implied": [], "notes": ["回放模式：不做估值"]}
        syn = Synth(self, track=self.track).run()
        out = {"schema": "cbfx.analysis/0.3", "rules_version": R.VERSION,
               "meta": {k: self.m[k] for k in ("code", "name", "target_period", "report_type", "mode", "company_type")},
               "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
               "data_quality": {"coverage": self.d["coverage_target"],
                                "errors": [i["msg"] for i in self.split_errors()[0]],
                                "historical_errors": [i["msg"] for i in self.split_errors()[1]],
                                "warnings": [i["msg"] for i in self.d["issues"] if i["level"] == "warn"],
                                "filings": [{k: f.get(k) for k in ("title", "publish_date", "url", "audit_opinion")} for f in self.d["filings"]]},
               "archetype": self.archetype, "changes": self.change_rows, "metrics": self.metrics,
               "red_flags": self.flags, "valuation": self.val, "notes": self.notes}
        out.update(syn)
        with open(os.path.join(self.out_dir, "分析.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        return out
