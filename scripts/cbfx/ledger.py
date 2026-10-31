"""组装统一底稿：多源取数 → 逐字段核对 → 单季差分/TTM → 内部勾稽 → 问题清单。

核对规则（见 references/底稿规范.md）：
  参照值 = 公告原文 > 东方财富 > 新浪
  相对差 ≤0.1% 一致；≤1% 偏差；>1% 冲突；只有一个来源 = 单一来源；都没有 = 未获取
  冲突字段 usable=False，分析层不得使用。
"""
import datetime as dt
import json, os
from . import __version__
from .fields import FIELDS, BY_KEY, STMT_KEYS, COMPANY_TYPES, COMPANY_TYPE_CN
from .sources import cninfo, eastmoney, sina, quote
from . import pdfparse

TOL_OK, TOL_WARN = 0.001, 0.01
SRC_ORDER = ("pdf", "eastmoney", "sina")
SRC_CN = {"pdf": "公告原文", "pdf_comparative": "公告原文(比较期)", "eastmoney": "东方财富", "sina": "新浪财经"}


def _rel(a, b):
    d = max(abs(a), abs(b))
    return 0.0 if d < 1 else abs(a - b) / d


# 天然非负的科目：各来源符号习惯不同（新浪对部分公司的利息费用记负），统一取绝对值再比对
NONNEG = {"cost", "tax_surcharge", "sell_exp", "admin_exp", "rd_exp", "int_exp", "capex", "div_int_paid", "sales_cash"}


def reconcile(vals, key=None):
    """vals: {来源: 值}。返回单元格字典。"""
    vals = {k: (abs(v) if key in NONNEG else v) for k, v in vals.items() if v is not None}
    cell = {"value": None, "status": "未获取", "chosen_from": None, "sources": vals, "usable": False}
    if not vals:
        return cell
    ref_src = next((s for s in ("pdf", "pdf_comparative", "eastmoney", "sina") if s in vals), None)
    ref = vals[ref_src]
    cell.update(value=ref, chosen_from=ref_src)
    if len(vals) == 1:
        cell.update(status="单一来源", usable=True)
        return cell
    worst = max(_rel(ref, v) for v in vals.values())
    cell["max_rel_diff"] = round(worst, 6)
    if worst <= TOL_OK:
        cell.update(status="一致", usable=True)
    elif worst <= TOL_WARN:
        cell.update(status="偏差", usable=True)
    elif ref_src == "pdf_comparative":
        # 本期报告里的比较期数 ≠ 接口存的当年原始数：多为追溯调整（同一控制下合并、会计政策变更、差错更正）。
        # 趋势比较应使用调整后的口径，故以原文比较期数为准，但必须显式标注。
        cell.update(status="追溯调整", usable=True)
    else:
        cell.update(status="冲突", usable=False)
    return cell


# 金融类公司两家接口对这些科目的口径不同（如银行把发债利息并入/拆出），比对无意义，跳过
FIN_SKIP = {"div_int_paid"}


def _next_period(p):
    seq = ["03-31", "06-30", "09-30", "12-31"]
    i = seq.index(p[5:])
    return f"{p[:4]}-{seq[i + 1]}" if i < 3 else f"{int(p[:4]) + 1}-03-31"


def _prev_same_year(p, periods):
    cands = [x for x in periods if x[:4] == p[:4] and x < p]
    return max(cands) if cands else None


def _shift_year(p, n=-1):
    return f"{int(p[:4]) + n}{p[4:]}"


class Ledger:
    def __init__(self, code, period=None, mode="quick", out_dir="out", local_pdf=None, use_pdf=True, log=print):
        self.code, self.mode, self.log = code, mode, log
        self.req_period, self.local_pdf, self.use_pdf = period, local_pdf, use_pdf
        self.out_root = out_dir
        self.issues, self.filings, self.source_status = [], [], {}
        self.raw = {"eastmoney": {}, "sina": {}, "sina_meta": {}}

    def issue(self, level, msg, field=None, period=None):
        self.issues.append({"level": level, "field": field, "period": period, "msg": msg})

    # ---------- 1. 标的与报告期 ----------
    def resolve(self):
        self.org = cninfo.search(self.code)
        self.log(f"标的：{self.org['name']} {self.code}（{self.org['market'].upper()}）")
        try:
            ct, _ = eastmoney.detect_company_type(self.org)
            self.ctype = COMPANY_TYPES[ct]
            self.em_ct = ct
            self.em_dates = eastmoney.dates(self.org, ct)
            self.source_status["eastmoney"] = "ok"
        except Exception as e:
            self.ctype, self.em_ct, self.em_dates = "general", None, []
            self.source_status["eastmoney"] = f"失败：{e}"
            self.issue("warn", f"东方财富不可用，改用新浪+原文：{e}")
        if self.ctype != "general":
            self.issue("warn", f"{COMPANY_TYPE_CN[self.ctype]}报表模板：通用字段表只覆盖共有科目，"
                               "行业专属指标（如不良率、净息差、综合成本率）尚未接入，分析层须走行业适配口径")
        # 目标报告期：用户指定 > 东方财富最新 > 新浪最新（稍后补）
        self.target = self.req_period or (self.em_dates[0] if self.em_dates else None)
        # 财报当日：接口常滞后 1–3 天。若巨潮已披露下一期正文，以下一期为目标、原文为唯一来源。
        if not self.req_period and self.target and self.use_pdf:
            nxt = _next_period(self.target)
            if nxt <= dt.date.today().isoformat():
                try:
                    if cninfo.list_reports(self.org, nxt):
                        self.issue("info", f"巨潮已披露 {nxt} 报告但接口最新只到 {self.target}，目标期改为 {nxt}（以原文为准）")
                        self.target = nxt
                except Exception as e:
                    self.issue("warn", f"检查巨潮是否有更新一期报告失败：{e}")

    def _period_list(self):
        t = self.target
        q = []
        y, md = int(t[:4]), t[5:]
        seq = ["03-31", "06-30", "09-30", "12-31"]
        i = seq.index(md)
        n = 16 if self.mode == "quick" else 24
        while len(q) < n:
            q.append(f"{y}-{seq[i]}")
            i -= 1
            if i < 0:
                i, y = 3, y - 1
        if self.mode == "deep":
            last_fy = int(t[:4]) if md == "12-31" else int(t[:4]) - 1
            q += [f"{yy}-12-31" for yy in range(last_fy - 9, last_fy + 1)]
        return sorted(set(q), reverse=True)

    # ---------- 2. 结构化接口 ----------
    def fetch_structured(self):
        need = self.periods
        if self.em_ct:
            avail = [p for p in need if p in set(self.em_dates)]
            for st in ("bs", "is", "cf"):
                try:
                    self.raw["eastmoney"][st] = eastmoney.statements(self.org, self.em_ct, st, avail)
                except Exception as e:
                    self.raw["eastmoney"][st] = {}
                    self.issue("warn", f"东方财富{st}取数失败：{e}")
        n = 44 if self.mode == "deep" else 20
        if self.req_period:  # 历史期（回放评测）：新浪按最新期倒序翻页，需多取到目标期之前
            n += max(0, (dt.date.today().year - int(self.req_period[:4])) * 4)
        try:
            for st in ("bs", "is", "cf"):
                rows, meta = sina.statements(self.org, st, n=n)
                self.raw["sina"][st] = rows
                self.raw["sina_meta"].update(meta)
            self.source_status["sina"] = "ok"
        except Exception as e:
            self.source_status["sina"] = f"失败：{e}"
            self.issue("warn", f"新浪不可用：{e}")
        if not self.target:
            ds = sorted(self.raw["sina"].get("bs", {}), reverse=True)
            self.target = ds[0] if ds else None

    # ---------- 3. 公告原文 ----------
    def fetch_filing(self, period):
        rt = cninfo.report_type(period)
        fdir = os.path.join(self.out_dir, "filings")
        if self.local_pdf and period == self.target:
            rep = {"period": period, "type": rt, "title": os.path.basename(self.local_pdf),
                   "url": None, "publish_date": None, "local_path": self.local_pdf}
        else:
            reps = cninfo.list_reports(self.org, period)
            if not reps:
                self.issue("warn", f"巨潮未找到 {period} {rt} 报告正文（可能尚未披露）", period=period)
                return None
            rep = cninfo.download(reps[0], fdir)
            if len(reps) > 1:
                rep["other_versions"] = [r["title"] for r in reps[1:]]
        self.log(f"解析原文：{rep['title']}")
        try:
            parsed = pdfparse.parse(rep["local_path"], rt)
        except Exception as e:
            self.issue("error", f"PDF 解析失败：{e}", period=period)
            return None
        rep["parsed_fields"] = len(parsed["statements"])
        self.raw.setdefault("pdf", {})[period] = parsed
        rep["audit_opinion"] = parsed["audit_opinion"]
        self.filings.append({k: v for k, v in rep.items() if k != "local_path"} | {"local_file": os.path.relpath(rep["local_path"], self.out_dir) if rep.get("local_path", "").startswith(self.out_dir) else rep.get("local_path")})
        if rep["parsed_fields"] < (30 if self.ctype == "general" else 15):
            blank = parsed.get("blank_pages", [])
            if len(blank) >= 5 and rep["parsed_fields"] < 5:
                rep["scanned_pages"] = f"{blank[0]}-{blank[-1]}"
                self.issue("warn", f"原文报表页是扫描图片（无文字层，约第 {blank[0]}-{blank[-1]} 页共 {len(blank)} 页），"
                                   f"无法自动解析；该期以东财+新浪双源交叉为准，主要会计数据页解析出 {len(parsed.get('main', {}))} 项", period=period)
            else:
                self.issue("warn", f"原文只解析出 {rep['parsed_fields']} 个科目，版式可能特殊，需人工核对", period=period)
        return rep, parsed

    # ---------- 4. 组装 ----------
    def build(self):
        self.resolve()
        if not self.target:
            self.periods = []
        else:
            self.periods = self._period_list()
        self.out_dir = os.path.join(self.out_root, self.code, (self.target or "unknown") + ("-deep" if self.mode == "deep" else ""))
        os.makedirs(self.out_dir, exist_ok=True)
        self.fetch_structured()
        if not self.periods and self.target:
            self.periods = self._period_list()
        pdf_vals = {}   # (key, period) -> (value, src, page)
        pdf_main = {}
        targets = [self.target] if self.use_pdf else []
        if self.use_pdf and not self.target.endswith("12-31"):
            # 门禁（财报解读插件 source-gates）：季报/半年报必须同时读上一份年报
            targets.append(f"{int(self.target[:4]) - 1}-12-31")
        for p in targets:
            try:
                got = self.fetch_filing(p)
            except Exception as e:
                self.issue("warn", f"公告原文获取失败（{p}）：{e}", period=p)
                got = None
            if not got:
                continue
            rep, parsed = got
            st_ = parsed["statements"]
            # 金融类利润表只有“营业总收入/营业收入合计”，接口的营业收入即此口径
            if self.ctype != "general" and "rev" not in st_ and "rev_total" in st_:
                st_["rev"] = dict(st_["rev_total"])
            self._calibrate_units(parsed, p)
            prev_bs = f"{int(p[:4]) - 1}-12-31"
            prev_fl = _shift_year(p)
            for k, v in parsed["statements"].items():
                pdf_vals[(k, p)] = (v["cur"], "pdf", v["page"], rep)
                if v["prev"] is not None:
                    pp = prev_fl if BY_KEY[k]["flow"] else prev_bs
                    if k == "cce_end":
                        pp = prev_fl
                    pdf_vals.setdefault((k, pp), (v["prev"], "pdf_comparative", v["page"], rep))
            for k, v in parsed["main"].items():
                pdf_main[(k, p)] = v
                if k == "np_ded":
                    pdf_vals[(k, p)] = (v["cur"], "pdf", v["page"], rep)
        if self.target not in self.raw["eastmoney"].get("bs", {}) and self.target not in self.raw["sina"].get("bs", {}):
            self.issue("info", f"结构化接口尚未更新 {self.target}，本期数据以公告原文为唯一来源（财报当日常见）")

        # 逐字段核对
        fields = {}
        for key, name, st, flow, emk, sk, _ in FIELDS:
            if self.ctype != "general" and key in FIN_SKIP:
                continue
            cells = {}
            for p in self.periods:
                vals = {}
                em_row = self.raw["eastmoney"].get(st, {}).get(p)
                if em_row and emk and em_row.get(emk) is not None:
                    vals["eastmoney"] = float(em_row[emk])
                sn_row = self.raw["sina"].get(st, {}).get(p)
                if sn_row and sk and sn_row.get(sk) is not None:
                    vals["sina"] = sn_row[sk]
                pv = pdf_vals.get((key, p))
                if pv:
                    vals[pv[1]] = pv[0]
                c = reconcile(vals, key)
                if pv:
                    c["pdf_page"] = pv[2]
                if c["status"] != "未获取" or p == self.target:
                    cells[p] = c
                if c["status"] in ("冲突", "追溯调整"):
                    srcs = "，".join(f"{SRC_CN[s]} {v / 1e8:,.2f} 亿" for s, v in c["sources"].items())
                    if c["status"] == "追溯调整":
                        self.issue("warn", f"{name} {p}：本期报告的比较期数与接口原始数不一致，疑似追溯调整，已按调整后口径（{srcs}）", key, p)
                    else:
                        hint = ""
                        a, b = c["sources"].get("eastmoney"), c["sources"].get("sina")
                        if c["chosen_from"] == "pdf" and a is not None and b is not None and _rel(a, b) <= TOL_OK:
                            hint = "；两家接口互相一致，优先排查原文解析（错行/单位/符号）"
                        self.issue("error", f"{name} {p}：来源冲突（{srcs}），该值不可用{hint}", key, p)
            fields[key] = {"name": name, "statement": st, "flow": flow, "unit": "元", "values": cells}
        self.fields = fields
        self._derive()
        self._checks(pdf_main)
        self._quote()
        return self.export()

    def _api_value(self, key, p):
        st = BY_KEY[key]["stmt"]
        f = next(x for x in FIELDS if x[0] == key)
        vals = []
        em = self.raw["eastmoney"].get(st, {}).get(p)
        if em and f[4] and em.get(f[4]) is not None:
            vals.append(float(em[f[4]]))
        sn = self.raw["sina"].get(st, {}).get(p)
        if sn and f[5] and sn.get(f[5]) is not None:
            vals.append(float(sn[f[5]]))
        return vals[0] if vals else None

    def _calibrate_units(self, parsed, p):
        """单位识别兜底：原文值与接口值恰好差 10 的整数次方（千元/万元/百万元误判）时，按接口量级校正并告警。"""
        import math
        probes = {"bs": ("ta", "tl", "eq_total"), "is": ("rev", "np", "total_profit"), "cf": ("ocf", "icf", "cce_end")}
        st_map = parsed["statements"]
        for st, keys in probes.items():
            for k in keys:
                a, b = st_map.get(k, {}).get("cur"), self._api_value(k, p)
                if not a or not b:
                    continue
                r = b / a
                e = round(math.log10(abs(r))) if r > 0 else None
                if e and abs(r / 10 ** e - 1) < 0.001:
                    for kk, v in st_map.items():
                        if BY_KEY[kk]["stmt"] == st:
                            for f in ("cur", "prev"):
                                if v.get(f) is not None:
                                    v[f] *= 10 ** e
                    self.issue("warn", f"原文{ {'bs': '资产负债表', 'is': '利润表', 'cf': '现金流量表'}[st] }单位识别有误（与接口差 10^{e} 倍），已按接口量级校正，请抽查原文单位", period=p)
                break
        # 主要会计数据 vs 报表
        for k, v in parsed["main"].items():
            a, b = v.get("cur"), st_map.get(k, {}).get("cur")
            if a and b and b / a > 0:
                import math as _m
                e = round(_m.log10(b / a))
                if e and abs(b / a / 10 ** e - 1) < 0.001:
                    for f in ("cur", "quarter", "prev", "prev_year_end"):
                        if v.get(f) is not None:
                            v[f] *= 10 ** e

    def v(self, key, p):
        c = self.fields.get(key, {}).get("values", {}).get(p)
        return c["value"] if c and c["usable"] else None

    def _derive(self):
        sq, ttm = {}, {}
        ps = sorted(self.periods)
        for key, f in self.fields.items():
            if not f["flow"] or key == "cce_end":
                continue
            sq[key], ttm[key] = {}, {}
            for p in ps:
                cur = self.v(key, p)
                if cur is None:
                    continue
                if p.endswith("03-31"):
                    sq[key][p] = cur
                else:
                    prev = _prev_same_year(p, ps)
                    expect = {"06-30": "03-31", "09-30": "06-30", "12-31": "09-30"}[p[5:]]
                    if prev and prev.endswith(expect) and self.v(key, prev) is not None:
                        sq[key][p] = cur - self.v(key, prev)
                fy, ly = f"{int(p[:4]) - 1}-12-31", _shift_year(p)
                if p.endswith("12-31"):
                    ttm[key][p] = cur
                elif self.v(key, fy) is not None and self.v(key, ly) is not None:
                    ttm[key][p] = cur + self.v(key, fy) - self.v(key, ly)
        debt = {}
        for p in ps:
            parts = {k: self.v(k, p) for k in ("st_loan", "ncl_1y", "lt_loan", "bonds", "lease_liab")}
            if self.v("ta", p) is None:
                continue
            if all(parts[k] is None for k in ("st_loan", "lt_loan", "bonds")):
                continue
            debt[p] = sum(x for x in parts.values() if x is not None)
        self.derived = {
            "single_quarter": sq, "ttm": ttm,
            "interest_bearing_debt": {"values": debt, "口径": "短期借款+一年内到期的非流动负债+长期借款+应付债券+租赁负债；"
                                      "一年内到期的非流动负债全额计入，未剔除其中的非付息项，属近似口径；"
                                      "其他流动负债中的短期融资券未计入。年报深检时应以附注拆分校正。"},
        }

    def _checks(self, pdf_main):
        t = self.target
        for p in self.periods:
            ta, tl, eq = self.v("ta", p), self.v("tl", p), self.v("eq_total", p)
            if None not in (ta, tl, eq) and abs(ta - tl - eq) / ta > 0.001:
                self.issue("error", f"{p} 资产负债表不平：资产 {ta / 1e8:.2f} ≠ 负债 {tl / 1e8:.2f} + 权益 {eq / 1e8:.2f}（亿）", "ta", p)
            ep, me = self.v("eq_parent", p), self.v("minority_eq", p)
            if None not in (eq, ep, me) and abs(eq - ep - me) / max(abs(eq), 1) > 0.002:
                self.issue("warn", f"{p} 所有者权益 ≠ 归母 + 少数股东（可能含其他权益工具口径差）", "eq_total", p)
            n, npp, mi = self.v("np", p), self.v("np_parent", p), self.v("minority_pl", p)
            if None not in (n, npp, mi) and abs(n - npp - mi) / max(abs(n), 1) > 0.002:
                self.issue("warn", f"{p} 净利润 ≠ 归母 + 少数股东损益", "np", p)
        self._reconcile()
        for (k, p), m in pdf_main.items():
            st = self.v(k, p)
            cell = self.fields.get(k, {}).get("values", {}).get(p)
            if (st is not None and m.get("cur") is not None and _rel(st, m["cur"]) <= TOL_OK and cell
                    and cell["status"] == "单一来源" and cell["chosen_from"] == "pdf"):
                # 财报当日只有原文：报表数与“主要会计数据”表互相印证，可信度高于普通单一来源
                cell["status"] = "原文自洽"
                cell["sources"]["pdf_main"] = m["cur"]
            if st is not None and m.get("cur") is not None and _rel(st, m["cur"]) > TOL_OK:
                self.issue("error", f"原文内部不一致：{BY_KEY[k]['name']} 主要会计数据 {m['cur'] / 1e8:.2f} 亿 vs 报表 {st / 1e8:.2f} 亿", k, p)
            if "quarter" in m:
                d = self.derived["single_quarter"].get(k, {}).get(p)
                ver = self.derived.setdefault("sq_verified", {}).setdefault(k, {})
                if d is None or _rel(d, m["quarter"]) <= TOL_OK:
                    ver[p] = "原文本报告期"
                if d is not None and _rel(d, m["quarter"]) > TOL_OK:
                    self.issue("warn", f"{BY_KEY[k]['name']} 单季差分 {d / 1e8:.2f} 亿 ≠ 原文本报告期 {m['quarter'] / 1e8:.2f} 亿（前期数可能被追溯调整）", k, p)
                elif d is None:
                    self.derived["single_quarter"].setdefault(k, {})[p] = m["quarter"]
        # 覆盖情况
        cov = {}
        for k, f in self.fields.items():
            c = f["values"].get(t)
            cov[c["status"] if c else "未获取"] = cov.get(c["status"] if c else "未获取", 0) + 1
        self.coverage = cov
        miss_flow = [BY_KEY[k]["name"] for k in ("np_ded", "sales_cash", "int_exp")
                     if not (self.fields[k]["values"].get(t) or {}).get("usable")]
        if miss_flow:
            self.issue("info", f"本期缺：{'、'.join(miss_flow)}")
        sm = self.raw["sina_meta"].get(t) or {}
        self.audit = {"新浪": sm.get("audit_opinion") or sm.get("is_audit"),
                      "原文": next((f.get("audit_opinion") for f in self.filings if f["period"] == t), None)}

    def _reconcile(self):
        """交付前勾稽（财报解读插件勾稽门禁 + 全链路三表勾稽），结果写入 reconciliations。"""
        t, rec = self.target, []
        fy0 = f"{int(t[:4]) - 1}-12-31"
        ly = _shift_year(t)

        def src(k, p):
            c = self.fields.get(k, {}).get("values", {}).get(p) or {}
            return c.get("sources", {}), c.get("status")
        # 1) 利润表同比基数来自本期原文比较列
        ss, st = src("rev", ly)
        ok = "pdf_comparative" in ss
        rec.append({"name": "income_statement_comparative", "label": "同比基数来自本期原文比较列", "period": ly,
                    "status": "pass" if ok and st == "一致" else ("warn" if ok else "na"),
                    "note": f"营业收入上年同期：{st or '未获取'}；来源 {'、'.join(ss) or '无'}"})
        # 2) 资产负债表期初来自本期原文
        ss, st = src("ta", fy0)
        ok = "pdf_comparative" in ss or "pdf" in ss
        rec.append({"name": "balance_sheet_opening", "label": "期初数来自本期原文期初列", "period": fy0,
                    "status": "pass" if ok and st == "一致" else ("warn" if ok else "na"),
                    "note": f"资产总计期初：{st or '未获取'}；来源 {'、'.join(ss) or '无'}"})
        # 3) 现金流量表期末现金 ≤ 资产负债表货币资金（差额通常为受限资金）
        cce, cash = self.v("cce_end", t), self.v("cash", t)
        if None in (cce, cash) or self.ctype != "general":
            rec.append({"name": "cash_closing_balance", "label": "期末现金 vs 货币资金", "period": t, "status": "na",
                        "note": "金融类现金等价物含存放央行/同业，口径不同，不做此项" if self.ctype != "general" else "字段未获取"})
        else:
            diff = cash - cce
            if diff >= -0.02 * cash:
                stt, note = "pass", f"货币资金 {cash / 1e8:.2f} 亿 − 期末现金及等价物 {cce / 1e8:.2f} 亿 = {diff / 1e8:.2f} 亿（受限资金等，占 {diff / cash:.1%}）"
                if diff / cash > 0.3:
                    stt, note = "warn", note + "；受限或非等价物占比超过 30%，货币资金可动用部分需打折"
            else:
                stt, note = "warn", f"期末现金及等价物 {cce / 1e8:.2f} 亿 > 货币资金 {cash / 1e8:.2f} 亿，现金等价物含货币资金以外项目（如短期理财），需附注核对"
            rec.append({"name": "cash_closing_balance", "label": "期末现金 vs 货币资金", "period": t, "status": stt,
                        "left": cce, "right": cash, "note": note})
            if stt == "warn":
                self.issue("warn", f"勾稽：{note}", "cce_end", t)
        # 4) 未分配利润滚动：期末 − 期初 − 归母净利润（年初至今）≈ −（分红 + 提取盈余公积）
        u1, u0, npp = self.v("undist", t), self.v("undist", fy0), self.v("np_parent", t)
        if None in (u1, u0, npp):
            rec.append({"name": "retained_earnings_roll", "label": "未分配利润滚动", "period": t, "status": "na", "note": "字段未获取"})
        else:
            gap = (u1 - u0) - npp
            base = max(abs(npp), 1)
            if gap > 0.05 * base:
                stt, note = "warn", f"未分配利润增加 {(u1 - u0) / 1e8:.2f} 亿，超过归母净利润 {npp / 1e8:.2f} 亿 {gap / 1e8:.2f} 亿（可能有追溯调整、其他综合收益结转），需附注核对"
            elif npp > 0 and -gap > 1.5 * base:
                stt, note = "warn", f"未分配利润减少额异常：期末−期初−归母 = {gap / 1e8:.2f} 亿，超过归母净利润 1.5 倍（大额分红/转增/调整），需附注核对"
            else:
                stt, note = "pass", f"期末−期初−归母净利润 = {gap / 1e8:.2f} 亿（应约等于 −分红 −提取盈余公积）"
            rec.append({"name": "retained_earnings_roll", "label": "未分配利润滚动", "period": t, "status": stt, "note": note})
            if stt == "warn":
                self.issue("warn", f"勾稽：{note}", "undist", t)
        self.reconciliations = rec

    def _quote(self):
        snaps, errs = quote.snapshot(self.org)
        self.quote = {"snapshots": snaps, "errors": errs, "取数时间": dt.datetime.now().isoformat(timespec="seconds")}
        prices = [s["price"] for s in snaps if s.get("price")]
        if len(prices) == 2 and _rel(*prices) > 0.005:
            self.issue("warn", f"两家行情价格不一致：{prices}")
        if not snaps:
            self.issue("warn", "行情两源均失败，估值层将跳过")

    def export(self):
        doc = {
            "schema": "cbfx.ledger/0.1",
            "meta": {"code": self.code, "name": self.org["name"], "market": self.org["market"],
                     "company_type": self.ctype, "company_type_cn": COMPANY_TYPE_CN[self.ctype],
                     "target_period": self.target, "report_type": cninfo.report_type(self.target),
                     "mode": self.mode, "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
                     "tool_version": __version__, "source_status": self.source_status},
            "filings": self.filings, "periods": self.periods, "coverage_target": self.coverage,
            "audit": self.audit, "fields": self.fields, "derived": self.derived,
            "quote": self.quote, "issues": self.issues, "reconciliations": getattr(self, "reconciliations", []),
        }
        with open(os.path.join(self.out_dir, "底稿.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        raw_dir = os.path.join(self.out_dir, "raw")
        os.makedirs(raw_dir, exist_ok=True)
        for src in ("eastmoney", "sina", "pdf"):
            with open(os.path.join(raw_dir, f"{src}.json"), "w", encoding="utf-8") as f:
                json.dump(self.raw.get(src, {}), f, ensure_ascii=False)
        return doc
