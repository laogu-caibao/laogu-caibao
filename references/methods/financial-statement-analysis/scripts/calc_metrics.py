#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calc_metrics.py — 由 fetch_statements.py 的输出计算全套财务指标（十年序列）。

解决的问题：SKILL 第 3 步要求"保留十年序列"的指标，过去每次分析都要临时手写计算脚本
（格力 / 科大国创 / 兴业银行各写一份），既慢又容易算错、口径不一致。本脚本把它固化。

输入：<dir>/<code>_income.json | _balance.json | _cashflow.json（fetch_statements.py 产出，单位亿元）
输出：<dir>/<code>_metrics.md   （指标 × 报告期 表格，可直接粘进报告的"可切换数据表"）
      <dir>/<code>_metrics.json（结构化，供 ECharts 序列直接取用）

用法：
  python calc_metrics.py --dir ./data --code 000651
  python calc_metrics.py --dir ./data --code 601166 --bank        # 银行口径
  python calc_metrics.py --dir ./data --code 000651 --periods all # 保留季报/中报期
  python calc_metrics.py --dir ./data --code 000651 --check       # 只打印缺失科目诊断

口径说明（写入报告时必须注明）：
  核心利润口径A = 营收 − 营业成本 − 税金及附加 − 销售 − 管理 − 研发 − 财务费用
  核心利润口径B = 同上但不减财务费用（剥离利息净收入，更严格）
  获现率口径A = 经营现金流 ÷ (核心利润A + 其他收益)；口径B = 经营现金流 ÷ 核心利润A
"""

import argparse
import json
import os
import re
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------- 数据装载

def norm(s):
    """科目名归一化：去掉章节序号、空格、冒号、括号内容差异不影响匹配"""
    s = re.sub(r"^[一二三四五六七八九十]+、", "", (s or "").strip())
    s = re.sub(r"[\s\u3000\xa0]", "", s)
    s = s.replace("：", ":").replace("（", "(").replace("）", ")")
    return s


class Sheet:
    """一张报表：按科目名（归一化后）模糊取值"""

    def __init__(self, path):
        self.path = path
        self.periods = []
        self.rows = {}          # norm名 -> {期: float}
        self.raw = {}
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        self.periods = obj.get("periods", [])
        for k, v in (obj.get("data") or {}).items():
            nk = norm(k)
            vals = {}
            for p, raw in v.items():
                try:
                    vals[p] = float(raw) / 10000.0 if raw not in ("", None) else None
                except (TypeError, ValueError):
                    vals[p] = None
            if any(x is not None for x in vals.values()):
                self.rows[nk] = vals
                self.raw[nk] = k

    def get(self, *cands):
        """取值：精确匹配 → 行名包含候选名（取最短行名）→ 兜底（行名是候选名子串，且行名≥6字）

        注意：`k in n` 方向极易误命中。真实案例：兴业的归母净利科目名是「归属于母公司的净利润」，
        候选名写的是「归属于母公司所有者的净利润」，精确与包含都失败，兜底被「五、净利润」命中
        （"净利润" in "归属于母公司所有者的净利润"），结果取成了含少数股东的净利润，虚增 3.85 亿。
        因此兜底必须限制行名长度，且候选名要覆盖各公司的实际写法。
        """
        for c in cands:
            n = norm(c)
            if n in self.rows:
                return dict(self.rows[n])
        for c in cands:
            n = norm(c)
            hits = [k for k in self.rows if n in k]
            if hits:
                return dict(self.rows[min(hits, key=len)])
        for c in cands:
            n = norm(c)
            hits = [k for k in self.rows if len(k) >= 6 and k in n]
            if hits:
                return dict(self.rows[min(hits, key=len)])
        return {}

    def v(self, period, *cands):
        """取单期值，缺失返回 None"""
        d = self.get(*cands)
        return d.get(period)

    def has(self, *cands):
        return bool(self.get(*cands))


def num(x, nd=2):
    return None if x is None else round(x + 0.0, nd)


def div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def pct(a, b):
    r = div(a, b)
    return None if r is None else round(r * 100, 2)


def chg(cur, prev):
    """同比增速 %"""
    if cur is None or prev in (None, 0):
        return None
    return round((cur / abs(prev) - 1) * 100, 2)


def cagr(a, b, n):
    if a is None or b is None or n <= 0 or b <= 0 or a <= 0:
        return None
    return round(((a / b) ** (1.0 / n) - 1) * 100, 2)


def series(fn, periods):
    return [fn(p) for p in periods]


def prev_of(periods, i, d):
    """取上一期值（按期字符串顺序）"""
    if i <= 0:
        return None
    return d.get(periods[i - 1])


def avg(d, periods, i):
    cur, prev = d.get(periods[i]), prev_of(periods, i, d)
    if cur is None:
        return None
    if prev is None:
        return cur
    return (cur + prev) / 2.0


# ---------------------------------------------------------------- 制造业/通用口径

INC = {
    "rev": ("营业总收入", "营业收入", "一、营业收入"),
    "cogs": ("营业成本",),
    "tax": ("营业税金及附加", "税金及附加"),
    "sell": ("销售费用",),
    "admin": ("管理费用",),
    "rd": ("研发费用",),
    "fin": ("财务费用",),
    "op_profit": ("三、营业利润", "营业利润"),
    "tot_profit": ("四、利润总额", "利润总额"),
    "np": ("五、净利润", "净利润"),
    "np_parent": ("归属于母公司所有者的净利润", "归属于母公司股东的净利润",
                  "归属于母公司的净利润", "归属母公司股东的净利润", "归属于母公司股东权益的净利润"),
    "other_income": ("其他收益", "其他收益(损失以\"-\"号填列)"),
    "invest": ("投资收益", "投资净收益"),
    "fv": ("公允价值变动收益", "公允价值变动净收益"),
    "fx": ("汇兑收益",),
    "disposal": ("资产处置收益",),
    "impair_credit": ("信用减值损失",),
    "impair_asset": ("资产减值损失",),
    "nonop_in": ("加:营业外收入", "营业外收入"),
    "nonop_out": ("减：营业外支出", "营业外支出"),
}

BAL = {
    "cash": ("货币资金",),
    "cce": ("现金及现金等价物期末余额", "期末现金及现金等价物余额"),
    "inv": ("存货",),
    "ar": ("应收账款",),
    "ar_note": ("应收票据",),
    "ar_bill": ("应收票据及应收账款",),
    "ap": ("应付账款",),
    "ap_note": ("应付票据",),
    "ap_bill": ("应付票据及应付账款",),
    "fa": ("固定资产",),
    "cip": ("在建工程",),
    "intang": ("无形资产",),
    "gw": ("商誉",),
    "lt_eq": ("长期股权投资", "长期股权投"),
    "trad": ("交易性金融资产",),
    "st_loan": ("短期借款",),
    "lt_loan": ("长期借款",),
    "bond": ("应付债券",),
    "ncl_1y": ("一年内到期的非流动负债",),
    "ca": ("流动资产合计", "流动资产总计"),
    "cl": ("流动负债合计", "流动负债总计"),
    "ta": ("资产总计", "总资产"),
    "tl": ("负债合计", "负债总计"),
    "eq_parent": ("归属于母公司股东权益合计", "归属于母公司所有者权益合计", "归属母公司股东权益合计"),
    "eq_all": ("所有者权益合计", "股东权益合计"),
    "retained": ("未分配利润",),
    "surplus": ("盈余公积",),
    "capital_res": ("资本公积",),
    "capital": ("实收资本(或股本)", "股本", "实收资本"),
    "gen_risk": ("一般风险准备",),
    "loan": ("发放贷款及垫款", "发放贷款和垫款"),
    "deposit": ("客户存款(吸收存款)", "吸收存款", "客户存款"),
}

CFS = {
    "ocf": ("经营活动产生的现金流量净额", "经营活动产生现金流量净额"),
    "capex": ("购建固定资产、无形资产和其他长期资产所支付的现金",
              "购建固定资产、无形资产和其他长期资产支付的现金"),
    "inv_pay": ("投资所支付的现金", "投资支付的现金"),
    "borrow": ("取得借款收到的现金", "取得借款所收到的现金"),
    "repay": ("偿还债务支付的现金", "偿还债务所支付的现金"),
    "div_pay": ("分配股利、利润或偿付利息所支付的现金", "分配股利、利润或偿付利息支付的现金"),
    "dep": ("固定资产折旧、油气资产折耗、生产性物资折旧", "固定资产折旧"),
    "amort_int": ("无形资产摊销",),
    "amort_lt": ("长期待摊费用摊销",),
    "sale_cash": ("销售商品、提供劳务收到的现金",),
    "provision": ("计提的资产减值准备", "资产减值准备"),
}


def pick(sheet, key_map, key):
    return sheet.get(*key_map[key])


def compute_general(inc, bal, cf, periods):
    """制造业 / 一般工商企业口径"""
    M = {}
    n = len(periods)

    def add(name, fn, unit=""):
        M[name] = {"unit": unit, "values": series(lambda p: fn(p, periods.index(p)), periods)}

    g_rev = pick(inc, INC, "rev")
    g_np = pick(inc, INC, "np_parent")
    g_np_all = pick(inc, INC, "np")
    g_cogs = pick(inc, INC, "cogs")
    g_op = pick(inc, INC, "op_profit")
    g_ocf = pick(cf, CFS, "ocf")

    # ---- 规模与成长
    add("营业收入", lambda p, i: num(g_rev.get(p)), "亿元")
    add("营收同比", lambda p, i: chg(g_rev.get(p), prev_of(periods, i, g_rev)), "%")
    add("归母净利润", lambda p, i: num(g_np.get(p)), "亿元")
    add("净利同比", lambda p, i: chg(g_np.get(p), prev_of(periods, i, g_np)), "%")
    add("超额增速(净利-营收)", lambda p, i: (
        None if chg(g_np.get(p), prev_of(periods, i, g_np)) is None
        or chg(g_rev.get(p), prev_of(periods, i, g_rev)) is None
        else round(chg(g_np.get(p), prev_of(periods, i, g_np))
                   - chg(g_rev.get(p), prev_of(periods, i, g_rev)), 2)), "pp")
    add("净利润(含少数股东)", lambda p, i: num(g_np_all.get(p)), "亿元")

    # ---- 盈利结构
    g_tax = pick(inc, INC, "tax")
    g_sell = pick(inc, INC, "sell")
    g_admin = pick(inc, INC, "admin")
    g_rd = pick(inc, INC, "rd")
    g_fin = pick(inc, INC, "fin")

    def core_a(p):
        parts = [g_rev.get(p), g_cogs.get(p), g_tax.get(p), g_sell.get(p),
                 g_admin.get(p), g_rd.get(p), g_fin.get(p)]
        if parts[0] is None:
            return None
        return parts[0] - sum(x or 0 for x in parts[1:])

    def core_b(p):
        parts = [g_rev.get(p), g_cogs.get(p), g_tax.get(p), g_sell.get(p),
                 g_admin.get(p), g_rd.get(p)]
        if parts[0] is None:
            return None
        return parts[0] - sum(x or 0 for x in parts[1:])

    add("毛利", lambda p, i: (None if g_rev.get(p) is None or g_cogs.get(p) is None
                              else num(g_rev.get(p) - g_cogs.get(p))), "亿元")
    add("毛利率", lambda p, i: pct(None if g_rev.get(p) is None or g_cogs.get(p) is None
                                   else g_rev.get(p) - g_cogs.get(p), g_rev.get(p)), "%")
    add("净利率", lambda p, i: pct(g_np.get(p), g_rev.get(p)), "%")
    add("营业利润", lambda p, i: num(g_op.get(p)), "亿元")
    add("核心利润(口径A-含财务费用)", lambda p, i: num(core_a(p)), "亿元")
    add("核心利润(口径B-剥离财务费用)", lambda p, i: num(core_b(p)), "亿元")
    add("核心利润率(口径A)", lambda p, i: pct(core_a(p), g_rev.get(p)), "%")
    add("核心利润率(口径B)", lambda p, i: pct(core_b(p), g_rev.get(p)), "%")
    add("核心利润/营业利润(口径A)", lambda p, i: pct(core_a(p), g_op.get(p)), "%")
    add("核心利润/营业利润(口径B)", lambda p, i: pct(core_b(p), g_op.get(p)), "%")

    # 三支柱两搅局
    g_other = pick(inc, INC, "other_income")
    g_invest = pick(inc, INC, "invest")
    g_fv = pick(inc, INC, "fv")
    g_fx = pick(inc, INC, "fx")
    g_disp = pick(inc, INC, "disposal")
    g_imp_c = pick(inc, INC, "impair_credit")
    g_imp_a = pick(inc, INC, "impair_asset")

    def misc(p):
        vals = [g_invest.get(p), g_fv.get(p), g_fx.get(p), g_disp.get(p)]
        if all(v is None for v in vals):
            return None
        return sum(v or 0 for v in vals)

    def impair(p):
        vals = [g_imp_c.get(p), g_imp_a.get(p)]
        if all(v is None for v in vals):
            return None
        return sum(v or 0 for v in vals)

    add("支柱2:其他收益", lambda p, i: num(g_other.get(p)), "亿元")
    add("支柱3:杂项收益(投资+公允+汇兑+处置)", lambda p, i: num(misc(p)), "亿元")
    add("搅局:减值损失合计", lambda p, i: num(impair(p)), "亿元")
    add("三支柱两搅局校验差", lambda p, i: (
        None if g_op.get(p) is None or core_a(p) is None
        else num(g_op.get(p) - (core_a(p) + (g_other.get(p) or 0)
                                + (misc(p) or 0) - (impair(p) or 0)))), "亿元")

    # ---- 现金流
    g_capex = pick(cf, CFS, "capex")
    g_dep = pick(cf, CFS, "dep")
    g_am_i = pick(cf, CFS, "amort_int")
    g_am_l = pick(cf, CFS, "amort_lt")
    g_sale = pick(cf, CFS, "sale_cash")

    def dep_am(p):
        vals = [g_dep.get(p), g_am_i.get(p), g_am_l.get(p)]
        if all(v is None for v in vals):
            return None
        return sum(v or 0 for v in vals)

    add("经营现金流净额", lambda p, i: num(g_ocf.get(p)), "亿元")
    add("资本支出", lambda p, i: num(g_capex.get(p)), "亿元")
    add("折旧摊销", lambda p, i: num(dep_am(p)), "亿元")
    add("自由现金流", lambda p, i: (None if g_ocf.get(p) is None or g_capex.get(p) is None
                                    else num(g_ocf.get(p) - g_capex.get(p))), "亿元")
    add("资本支出/折旧摊销", lambda p, i: (None if dep_am(p) in (None, 0)
                                          else round(g_capex.get(p) / dep_am(p), 2)
                                          if g_capex.get(p) is not None else None), "倍")
    add("获现率(口径A-含其他收益)", lambda p, i: (
        None if not core_a(p) else round(g_ocf.get(p) / (core_a(p) + (g_other.get(p) or 0)), 2)
        if g_ocf.get(p) is not None else None), "倍")
    add("获现率(口径B-核心利润)", lambda p, i: (
        None if not core_a(p) else round(g_ocf.get(p) / core_a(p), 2)
        if g_ocf.get(p) is not None else None), "倍")
    add("净利润现金含量", lambda p, i: (None if not g_np.get(p) else round(g_ocf.get(p) / g_np.get(p), 2)
                                       if g_ocf.get(p) is not None else None), "倍")
    add("收现比", lambda p, i: (None if not g_rev.get(p) else round(g_sale.get(p) / g_rev.get(p), 3)
                                if g_sale.get(p) is not None else None), "倍")

    # ---- 资产负债表
    g_ta = pick(bal, BAL, "ta")
    g_tl = pick(bal, BAL, "tl")
    g_ca = pick(bal, BAL, "ca")
    g_cl = pick(bal, BAL, "cl")
    g_eqp = pick(bal, BAL, "eq_parent")
    g_cash = pick(bal, BAL, "cash")
    g_cce = pick(bal, BAL, "cce")
    g_inv = pick(bal, BAL, "inv")

    add("总资产", lambda p, i: num(g_ta.get(p)), "亿元")
    add("总资产增速", lambda p, i: chg(g_ta.get(p), prev_of(periods, i, g_ta)), "%")
    add("资产负债率", lambda p, i: pct(g_tl.get(p), g_ta.get(p)), "%")
    add("流动比率", lambda p, i: (None if not g_cl.get(p) else round(g_ca.get(p) / g_cl.get(p), 2)
                                  if g_ca.get(p) is not None else None), "倍")
    add("速动比率", lambda p, i: (
        None if not g_cl.get(p) or g_ca.get(p) is None else
        round((g_ca.get(p) - (g_inv.get(p) or 0)) / g_cl.get(p), 2)), "倍")

    g_st = pick(bal, BAL, "st_loan")
    g_lt = pick(bal, BAL, "lt_loan")
    g_bd = pick(bal, BAL, "bond")
    g_1y = pick(bal, BAL, "ncl_1y")

    def ibd(p):
        return sum(x or 0 for x in (g_st.get(p), g_lt.get(p), g_bd.get(p), g_1y.get(p)))

    add("有息负债", lambda p, i: num(ibd(p)), "亿元")
    add("资产有息负债率", lambda p, i: pct(ibd(p), g_ta.get(p)), "%")
    add("货币资金", lambda p, i: num(g_cash.get(p)), "亿元")
    add("现金及现金等价物", lambda p, i: num(g_cce.get(p)), "亿元")
    add("楔子(货币资金-现金等价物)", lambda p, i: (
        None if g_cash.get(p) is None or g_cce.get(p) is None
        else num(g_cash.get(p) - g_cce.get(p))), "亿元")
    add("可动用口径净现金", lambda p, i: (
        None if g_cce.get(p) is None else num(g_cce.get(p) - ibd(p))), "亿元")
    add("账面口径净现金", lambda p, i: (
        None if g_cash.get(p) is None else num(g_cash.get(p) - ibd(p))), "亿元")

    # ---- 营运效率
    g_ar = pick(bal, BAL, "ar")
    g_arn = pick(bal, BAL, "ar_note")
    g_ap = pick(bal, BAL, "ap")
    g_apn = pick(bal, BAL, "ap_note")

    g_arb = pick(bal, BAL, "ar_bill")
    g_apb = pick(bal, BAL, "ap_bill")

    def arv(p):
        """合并列优先，避免在只有「应收票据及应收账款」时把同一行重复加两次"""
        if g_arb.get(p) is not None:
            return g_arb.get(p)
        vals = [g_ar.get(p), g_arn.get(p)]
        return None if all(v is None for v in vals) else sum(v or 0 for v in vals)

    def apv(p):
        if g_apb.get(p) is not None:
            return g_apb.get(p)
        vals = [g_ap.get(p), g_apn.get(p)]
        return None if all(v is None for v in vals) else sum(v or 0 for v in vals)

    def days(bal_d, flow_d, i, use_cogs=True):
        """周转天数 = 平均余额 / 期间发生额 × 365"""
        av = avg(bal_d, periods, i)
        fl = (g_cogs if use_cogs else g_rev).get(periods[i])
        if not av or not fl:
            return None
        return round(av / fl * 365, 1)

    add("存货周转天数", lambda p, i: days(g_inv, g_cogs, i, True), "天")
    add("应收周转天数", lambda p, i: days(arv_dict(arv, periods), g_rev, i, False), "天")
    add("应付周转天数", lambda p, i: days(apv_dict(apv, periods), g_cogs, i, True), "天")
    add("现金周期", lambda p, i: (
        None if days(g_inv, g_cogs, i, True) is None
        or days(arv_dict(arv, periods), g_rev, i, False) is None
        or days(apv_dict(apv, periods), g_cogs, i, True) is None
        else round(days(g_inv, g_cogs, i, True)
                   + days(arv_dict(arv, periods), g_rev, i, False)
                   - days(apv_dict(apv, periods), g_cogs, i, True), 1)), "天")

    # ---- 资产结构
    g_fa = pick(bal, BAL, "fa")
    g_cip = pick(bal, BAL, "cip")
    g_int = pick(bal, BAL, "intang")
    g_lte = pick(bal, BAL, "lt_eq")
    g_trad = pick(bal, BAL, "trad")
    g_gw = pick(bal, BAL, "gw")

    def op_asset(p):
        return sum(x or 0 for x in (g_fa.get(p), g_cip.get(p), g_int.get(p),
                                    g_inv.get(p), arv(p)))

    def inv_asset(p):
        vals = [g_lte.get(p), g_trad.get(p)]
        return None if all(v is None for v in vals) else sum(v or 0 for v in vals)

    add("经营资产", lambda p, i: num(op_asset(p)), "亿元")
    add("投资资产", lambda p, i: num(inv_asset(p)), "亿元")
    add("投资/经营比", lambda p, i: pct(inv_asset(p), op_asset(p) if op_asset(p) else None), "%")
    add("(固定资产+在建)/总资产", lambda p, i: (
        None if not g_ta.get(p) else round(((g_fa.get(p) or 0) + (g_cip.get(p) or 0))
                                           / g_ta.get(p) * 100, 2)), "%")
    add("(固定资产+在建)/经营资产", lambda p, i: (
        None if not op_asset(p) else round(((g_fa.get(p) or 0) + (g_cip.get(p) or 0))
                                           / op_asset(p) * 100, 2)), "%")
    add("商誉", lambda p, i: num(g_gw.get(p)), "亿元")

    # ---- 权益与积累
    g_ret = pick(bal, BAL, "retained")
    g_sur = pick(bal, BAL, "surplus")
    g_capres = pick(bal, BAL, "capital_res")
    g_cap = pick(bal, BAL, "capital")

    def accum(p):
        return sum(x or 0 for x in (g_ret.get(p), g_sur.get(p)))

    def paidin(p):
        return sum(x or 0 for x in (g_cap.get(p), g_capres.get(p)))

    add("归母权益", lambda p, i: num(g_eqp.get(p)), "亿元")
    add("利润积累(盈余公积+未分配)", lambda p, i: num(accum(p)), "亿元")
    add("股东入资(股本+资本公积)", lambda p, i: num(paidin(p)), "亿元")
    add("利润积累占比", lambda p, i: pct(accum(p), g_eqp.get(p)), "%")
    add("自我造血倍数", lambda p, i: (None if not paidin(p) else round(accum(p) / paidin(p), 2)), "倍")
    add("ROE", lambda p, i: (
        None if g_np.get(p) is None or not avg(g_eqp, periods, i)
        else round(g_np.get(p) / avg(g_eqp, periods, i) * 100, 2)), "%")

    # ---- 勾稽
    add("未分配利润勾稽缺口", lambda p, i: (
        None if i == 0 or g_ret.get(p) is None or g_np.get(p) is None
        else num(g_ret.get(periods[i - 1]) + g_np.get(p) - g_ret.get(p))), "亿元")
    add("平衡验证(资产-负债-权益)", lambda p, i: (
        None if g_ta.get(p) is None or g_tl.get(p) is None or g_eqp.get(p) is None
        else num(g_ta.get(p) - g_tl.get(p) - g_eqp.get(p))), "亿元")

    M["_CAGR"] = {
        "营收CAGR": cagr(g_rev.get(periods[-1]), g_rev.get(periods[0]), n - 1),
        "净利CAGR": (cagr(g_np.get(periods[-1]), g_np.get(periods[0]), n - 1)
                     if (g_np.get(periods[-1]) or 0) > 0 and (g_np.get(periods[0]) or 0) > 0 else None),
        "总资产CAGR": cagr(g_ta.get(periods[-1]), g_ta.get(periods[0]), n - 1),
    }
    return M


def arv_dict(fn, periods):
    return {p: fn(p) for p in periods}


def apv_dict(fn, periods):
    return {p: fn(p) for p in periods}


# ---------------------------------------------------------------- 银行口径

BANK_INC = {
    "rev": ("一、营业收入", "营业收入"),
    "nii": ("利息净收入",),
    "fee": ("手续费及佣金净收入", "手续费及佣金净收入"),
    "invest": ("投资净收益", "投资收益"),
    "fv": ("公允价值变动净收益", "公允价值变动收益"),
    "fx": ("汇兑收益", "汇兑净收益"),
    "other_bus": ("其他业务收入",),
    "op_exp": ("二、营业支出", "营业支出"),
    "tax": ("营业税金及附加", "税金及附加"),
    "admin": ("业务及管理费用", "业务及管理费"),
    "other_bus_exp": ("其他业务支出", "其他业务成本"),
    "impair": ("信用减值损失", "资产减值损失"),
    "op_profit": ("三、营业利润", "营业利润"),
    "np_parent": ("归属于母公司所有者的净利润", "归属于母公司股东的净利润",
                  "归属于母公司的净利润", "归属母公司股东的净利润"),
}


def compute_bank(inc, bal, cf, periods):
    M = {}
    n = len(periods)

    def add(name, fn, unit=""):
        M[name] = {"unit": unit, "values": series(lambda p: fn(p, periods.index(p)), periods)}

    g_rev = inc.get(*BANK_INC["rev"])
    g_nii = inc.get(*BANK_INC["nii"])
    g_fee = inc.get(*BANK_INC["fee"])
    g_tax = inc.get(*BANK_INC["tax"])
    g_adm = inc.get(*BANK_INC["admin"])
    g_obe = inc.get(*BANK_INC["other_bus_exp"])
    g_imp = inc.get(*BANK_INC["impair"])
    g_op = inc.get(*BANK_INC["op_profit"])
    g_np = inc.get(*BANK_INC["np_parent"])
    g_inv = inc.get(*BANK_INC["invest"])
    g_fv = inc.get(*BANK_INC["fv"])
    g_fx = inc.get(*BANK_INC["fx"])

    def ppop(p):
        """拨备前利润 = 营收 − 税金 − 管理费 − 其他业务支出"""
        if g_rev.get(p) is None:
            return None
        return g_rev.get(p) - sum(x or 0 for x in (g_tax.get(p), g_adm.get(p), g_obe.get(p)))

    def impair_calc(p):
        """减值倒算 = 营业支出 − 税金 − 管理费 − 其他业务支出（2019后新浪该行为空，必须倒算）"""
        ope = inc.get(*BANK_INC["op_exp"]).get(p)
        if ope is None:
            return g_imp.get(p)
        return ope - sum(x or 0 for x in (g_tax.get(p), g_adm.get(p), g_obe.get(p)))

    def core_bank(p):
        """银行版核心利润 = 利息净收入 + 中收 − 管理费 − 税金 − 其他业务支出"""
        if g_nii.get(p) is None:
            return None
        return g_nii.get(p) + (g_fee.get(p) or 0) - sum(
            x or 0 for x in (g_adm.get(p), g_tax.get(p), g_obe.get(p)))

    def misc(p):
        vals = [g_inv.get(p), g_fv.get(p), g_fx.get(p)]
        return None if all(v is None for v in vals) else sum(v or 0 for v in vals)

    add("营业收入", lambda p, i: num(g_rev.get(p)), "亿元")
    add("营收同比", lambda p, i: chg(g_rev.get(p), prev_of(periods, i, g_rev)), "%")
    add("拨备前利润", lambda p, i: num(ppop(p)), "亿元")
    add("拨备前利润同比", lambda p, i: chg(ppop(p), prev_of(periods, i,
                                                           {q: ppop(q) for q in periods})), "%")
    add("归母净利润", lambda p, i: num(g_np.get(p)), "亿元")
    add("净利同比", lambda p, i: chg(g_np.get(p), prev_of(periods, i, g_np)), "%")
    add("利息净收入", lambda p, i: num(g_nii.get(p)), "亿元")
    add("手续费及佣金净收入", lambda p, i: num(g_fee.get(p)), "亿元")
    add("支柱3:投资+公允+汇兑", lambda p, i: num(misc(p)), "亿元")
    add("利息净收入占比", lambda p, i: pct(g_nii.get(p), g_rev.get(p)), "%")
    add("中收占比", lambda p, i: pct(g_fee.get(p), g_rev.get(p)), "%")
    add("投资+公允占比", lambda p, i: pct(misc(p), g_rev.get(p)), "%")
    add("银行版核心利润", lambda p, i: num(core_bank(p)), "亿元")
    add("核心利润/拨备前利润", lambda p, i: pct(core_bank(p), ppop(p)), "%")
    add("信用减值损失(倒算)", lambda p, i: num(impair_calc(p)), "亿元")
    add("减值/拨备前利润", lambda p, i: pct(impair_calc(p), ppop(p)), "%")
    add("成本收入比", lambda p, i: pct(g_adm.get(p), g_rev.get(p)), "%")

    g_ta = bal.get(*BAL["ta"])
    g_loan = bal.get(*BAL["loan"])
    g_dep = bal.get(*BAL["deposit"])
    g_eqp = bal.get(*BAL["eq_parent"])
    g_tl = bal.get(*BAL["tl"])

    add("总资产", lambda p, i: num(g_ta.get(p)), "亿元")
    add("总资产增速", lambda p, i: chg(g_ta.get(p), prev_of(periods, i, g_ta)), "%")
    add("发放贷款及垫款", lambda p, i: num(g_loan.get(p)), "亿元")
    add("吸收存款", lambda p, i: num(g_dep.get(p)), "亿元")
    add("存贷比", lambda p, i: pct(g_loan.get(p), g_dep.get(p)), "%")
    add("存贷差", lambda p, i: (None if g_dep.get(p) is None or g_loan.get(p) is None
                                else num(g_dep.get(p) - g_loan.get(p))), "亿元")
    add("贷款增速", lambda p, i: chg(g_loan.get(p), prev_of(periods, i, g_loan)), "%")
    add("存款增速", lambda p, i: chg(g_dep.get(p), prev_of(periods, i, g_dep)), "%")
    add("存贷增速差", lambda p, i: (
        None if chg(g_loan.get(p), prev_of(periods, i, g_loan)) is None
        or chg(g_dep.get(p), prev_of(periods, i, g_dep)) is None
        else round(chg(g_dep.get(p), prev_of(periods, i, g_dep))
                   - chg(g_loan.get(p), prev_of(periods, i, g_loan)), 2)), "pp")
    add("简化净息差", lambda p, i: (
        None if g_nii.get(p) is None or not avg(g_ta, periods, i)
        else round(g_nii.get(p) / avg(g_ta, periods, i) * 100, 2)), "%")
    add("资产负债率(行业属性)", lambda p, i: pct(g_tl.get(p), g_ta.get(p)), "%")
    add("权益乘数(总资产/归母权益)", lambda p, i: (
        None if not g_eqp.get(p) else round(g_ta.get(p) / g_eqp.get(p), 2)
        if g_ta.get(p) else None), "倍")
    add("归母权益", lambda p, i: num(g_eqp.get(p)), "亿元")
    add("ROE", lambda p, i: (
        None if g_np.get(p) is None or not avg(g_eqp, periods, i)
        else round(g_np.get(p) / avg(g_eqp, periods, i) * 100, 2)), "%")

    g_ret = bal.get(*BAL["retained"])
    g_sur = bal.get(*BAL["surplus"])
    g_gr = bal.get(*BAL["gen_risk"])
    g_cap = bal.get(*BAL["capital"])
    g_capres = bal.get(*BAL["capital_res"])

    def accum(p):
        return sum(x or 0 for x in (g_ret.get(p), g_sur.get(p), g_gr.get(p)))

    add("利润积累(含一般风险准备)", lambda p, i: num(accum(p)), "亿元")
    add("利润积累占比", lambda p, i: pct(accum(p), g_eqp.get(p)), "%")
    add("未分配利润勾稽缺口", lambda p, i: (
        None if i == 0 or g_ret.get(p) is None or g_np.get(p) is None
        else num(g_ret.get(periods[i - 1]) + g_np.get(p) - g_ret.get(p))), "亿元")

    # 减值倒算 vs 间接法计提（银行最强勾稽）
    g_prov = cf.get(*CFS["provision"])
    add("间接法:计提的资产减值准备", lambda p, i: num(g_prov.get(p)), "亿元")
    add("减值倒算校验差", lambda p, i: (
        None if impair_calc(p) is None or g_prov.get(p) is None
        else num(impair_calc(p) - g_prov.get(p))), "亿元")

    M["_CAGR"] = {
        "营收CAGR": cagr(g_rev.get(periods[-1]), g_rev.get(periods[0]), n - 1),
        "净利CAGR": cagr(g_np.get(periods[-1]), g_np.get(periods[0]), n - 1),
        "总资产CAGR": cagr(g_ta.get(periods[-1]), g_ta.get(periods[0]), n - 1),
    }
    return M


# ---------------------------------------------------------------- 输出

def write_md(path, code, periods, M, bank):
    lines = [f"# {code} 财务指标序列（{'银行口径' if bank else '通用口径'}，单位见各行）", ""]
    head = ["指标", "单位"] + periods
    lines.append("| " + " | ".join(head) + " |")
    lines.append("|" + "|".join(["---"] * len(head)) + "|")
    for name, obj in M.items():
        if name.startswith("_"):
            continue
        cells = []
        for v in obj["values"]:
            cells.append("" if v is None else f"{v}")
        lines.append(f"| {name} | {obj['unit']} | " + " | ".join(cells) + " |")
    if "_CAGR" in M:
        lines.append("")
        lines.append("**区间复合增速（首期→末期）**")
        for k, v in M["_CAGR"].items():
            lines.append(f"- {k}：{'' if v is None else str(v) + '%'}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def diagnose(inc, bal, cf, bank):
    """打印没抓到的关键科目，提示补数方向"""
    miss = []
    groups = (BANK_INC if bank else INC)
    for key, cands in groups.items():
        if not inc.has(*cands):
            miss.append(f"[利润表] {key} <- {cands[0]}")
    for key in ("ta", "tl", "eq_parent", "retained", "cash", "cce", "inv",
                "fa", "cip", "st_loan", "lt_loan", "capital", "capital_res"):
        if not bal.has(*BAL[key]):
            miss.append(f"[资产负债表] {key} <- {BAL[key][0]}")
    for key in ("ocf", "capex", "dep", "provision"):
        if not cf.has(*CFS[key]):
            miss.append(f"[现金流] {key} <- {CFS[key][0]}")
    return miss


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="fetch_statements.py 的输出目录")
    ap.add_argument("--code", required=True, help="6 位股票代码")
    ap.add_argument("--bank", action="store_true", help="银行口径")
    ap.add_argument("--periods", default="annual", choices=["annual", "all"],
                    help="annual=只保留 12-31 年报；all=全部")
    ap.add_argument("--extra", default="", help="额外保留的报告期，逗号分隔")
    ap.add_argument("--check", action="store_true", help="只做缺失科目诊断")
    args = ap.parse_args()

    inc = Sheet(os.path.join(args.dir, f"{args.code}_income.json"))
    bal = Sheet(os.path.join(args.dir, f"{args.code}_balance.json"))
    cf = Sheet(os.path.join(args.dir, f"{args.code}_cashflow.json"))
    if not inc.periods and not bal.periods:
        print(f"[ERR] {args.dir} 下未找到 {args.code}_*.json，请先跑 fetch_statements.py")
        sys.exit(1)

    periods = sorted(set(inc.periods) | set(bal.periods) | set(cf.periods))
    if args.periods == "annual":
        extra = {x.strip() for x in args.extra.split(",") if x.strip()}
        periods = [p for p in periods if p.endswith("-12-31") or p in extra]
    if not periods:
        print("[ERR] 过滤后无报告期，检查 --periods / --extra")
        sys.exit(1)

    miss = diagnose(inc, bal, cf, args.bank)
    print(f"报告期 {len(periods)} 期：{periods[0]} ~ {periods[-1]}")
    if miss:
        print(f"[WARN] 缺失 {len(miss)} 个关键科目（对应指标会留空）：")
        for m in miss:
            print("   " + m)
    else:
        print("[OK] 关键科目齐全")
    if args.check:
        return

    M = compute_bank(inc, bal, cf, periods) if args.bank else compute_general(inc, bal, cf, periods)
    out_md = os.path.join(args.dir, f"{args.code}_metrics.md")
    out_json = os.path.join(args.dir, f"{args.code}_metrics.json")
    write_md(out_md, args.code, periods, M, args.bank)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({"periods": periods, "bank": args.bank, "metrics": M}, f,
                  ensure_ascii=False, indent=1)
    real = [k for k in M if not k.startswith("_")]
    empties = [k for k in real if all(v is None for v in M[k]["values"])]
    print(f"[OK] 计算 {len(real)} 项指标 -> {out_md}")
    if empties:
        print(f"[WARN] 其中 {len(empties)} 项全为空（多为该公司不适用或无该科目）：{', '.join(empties[:12])}")


if __name__ == "__main__":
    main()
