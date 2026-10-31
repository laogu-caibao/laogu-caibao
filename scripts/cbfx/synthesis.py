"""综合判断层：门禁、趋势降档、跳变检测、利润桥、持续性、杜邦、同源风险归并、结构化风险与跟踪验证。

输入：Analyzer（已算完分型/变化/指标/红旗）；输出写回 Analyzer 的属性，并进入 分析.json。
每条叙述带证据类型：披露（原文/接口原值）、计算（脚本由原值算出）、推断（基于规则的解释，需验证）。
"""
import json, os, statistics
from . import rules as R

FIN = ("BANK", "INSURANCE", "SECURITIES")
SEQ = ["03-31", "06-30", "09-30", "12-31"]


def _shift(p, years=-1):
    return f"{int(p[:4]) + years}{p[4:]}"


def _prev_q(p):
    y, md = int(p[:4]), p[5:]
    i = SEQ.index(md)
    return f"{y}-{SEQ[i - 1]}" if i else f"{y - 1}-12-31"


def _next_q(p):
    y, md = int(p[:4]), p[5:]
    i = SEQ.index(md)
    return f"{y}-{SEQ[i + 1]}" if i < 3 else f"{y + 1}-03-31"


def _div(a, b):
    return None if a is None or b is None or b == 0 else a / b


def _yi(x):
    return f"{x / 1e8:+,.2f} 亿"


class Synth:
    def __init__(self, an, track=True):
        self.a, self.t, self.track = an, an.t, track
        self.arch = an.arch

    # ---------- 门禁 ----------
    def gate(self):
        a, t, reasons = self.a, self.t, []
        fil = {f["period"] for f in a.d["filings"]}
        if t not in fil:
            reasons.append("本期正式报告原文未读取")
        if not t.endswith("12-31") and f"{int(t[:4]) - 1}-12-31" not in fil:
            reasons.append("季报/半年报未同时读取上一份年报")
        near, _ = a.split_errors()
        key_conf = [i for i in near if i.get("field") in R.GATE_KEY_FIELDS and i.get("period") in (t, _shift(t), _prev_q(t))]
        if key_conf:
            reasons.append(f"关键科目近期冲突 {len(key_conf)} 项")
        recs = a.d.get("reconciliations", [])
        fails = [r for r in recs if r["status"] == "fail"]
        if fails:
            reasons.append("勾稽未通过：" + "、".join(r["label"] for r in fails))
        self.gate_res = {"status": "pass" if not reasons else "draft", "reasons": reasons, "reconciliations": recs}
        return self.gate_res

    def cell_ok(self, k, p):
        c = self.a.d["fields"].get(k, {}).get("values", {}).get(p)
        return bool(c and c["usable"] and c["status"] in R.HEADLINE_OK_STATUS)

    def sq_verified(self, k, p):
        return bool(self.a.d["derived"].get("sq_verified", {}).get(k, {}).get(p)) or self.sq_ok(k, p)

    def sq_ok(self, k, p):
        """单季值可进结论：本期累计与上期累计（一季度除外）都须为“一致/原文自洽”。"""
        if not self.cell_ok(k, p):
            return False
        return p.endswith("03-31") or self.cell_ok(k, _prev_q(p))

    # ---------- 指标时间序列（趋势降档用） ----------
    def metric_at(self, key, p):
        a = self.a
        if key == "ocf_np":
            n = a.ttm("np", p)
            return _div(a.ttm("ocf", p), n) if n and n > 0 else None
        if key == "cash_rev":
            return _div(a.ttm("sales_cash", p), a.ttm("rev", p))
        if key == "np_ded_ratio":
            n = a.ttm("np_parent", p)
            return _div(a.ttm("np_ded", p), n) if n and n > 0 else None
        if key == "debt_ratio":
            return _div(a.v("tl", p), a.v("ta", p))
        if key == "ibd_ta":
            return _div(a.debt.get(p), a.v("ta", p))
        if key == "roe":
            return _div(a.ttm("np_parent", p), a.avg_bs("eq_parent", p))
        if key in ("core_op", "core_cash"):
            core = self.core_ttm(p)
            if core is None:
                return None
            if key == "core_op":
                op = a.ttm("op_profit", p)
                return _div(core, op) if op and op > 0 else None
            base = core + (a.ttm("other_inc", p) or 0)
            return _div(a.ttm("ocf", p), base) if base > 0 else None
        return None

    def core_ttm(self, p, fin_exp_full=False):
        a = self.a
        ks = ("rev", "cost", "tax_surcharge", "sell_exp", "admin_exp", "rd_exp", "fin_exp" if fin_exp_full else "int_exp")
        parts = {k: a.ttm(k, p) for k in ks}
        if any(parts[k] is None for k in ("rev", "cost", "tax_surcharge", "sell_exp", "admin_exp")):
            return None
        return parts["rev"] - sum(parts[k] or 0 for k in ks if k != "rev")

    def trend_downgrade(self):
        tiers = ["健康", "中性", "预警"]
        for key, m in self.a.metrics.items():
            d = R.METRIC_DIR.get(key)
            if d is None or m.get("verdict") not in ("健康", "中性"):
                continue
            ps, p = [], self.t
            for _ in range(R.TREND_DOWNGRADE_N + 1):
                ps.append(p)
                p = _prev_q(p)
            ser = [self.metric_at(key, p) for p in ps]
            if any(x is None for x in ser):
                continue
            ser = ser[::-1]
            worse = all((ser[i + 1] - ser[i]) * d < -1e-9 for i in range(len(ser) - 1))
            m["trend"] = {"periods": ps[::-1], "values": ser, "worsening": worse}
            if worse:
                m["verdict_raw"] = m["verdict"]
                m["verdict"] = tiers[tiers.index(m["verdict"]) + 1]
                m["downgrade"] = f"连续 {R.TREND_DOWNGRADE_N} 期变差，由“{m['verdict_raw']}”降为“{m['verdict']}”"

    # ---------- 跳变检测 ----------
    def jumps(self):
        a, out = self.a, []
        ratios = {
            "毛利率": lambda p: _div((a.sq("rev", p) or 0) - (a.sq("cost", p) or 0), a.sq("rev", p)) if a.sq("cost", p) is not None else None,
            "销售费用率": lambda p: _div(a.sq("sell_exp", p), a.sq("rev", p)),
            "管理费用率": lambda p: _div(a.sq("admin_exp", p), a.sq("rev", p)),
            "研发费用率": lambda p: _div(a.sq("rd_exp", p), a.sq("rev", p)),
            "财务费用率": lambda p: _div(a.sq("fin_exp", p), a.sq("rev", p)),
            "投资收益/营业收入": lambda p: _div(a.sq("invest_inc", p), a.sq("rev", p)),
            "减值损失/营业收入": lambda p: _div(-((a.sq("asset_impair", p) or 0) + (a.sq("credit_impair", p) or 0)), a.sq("rev", p))
            if a.sq("asset_impair", p) is not None or a.sq("credit_impair", p) is not None else None,
            "非经常性损益/营业收入": lambda p: _div((a.sq("np_parent", p) or 0) - a.sq("np_ded", p), a.sq("rev", p)) if a.sq("np_ded", p) is not None else None,
        }
        hist_ps = [p for p in sorted(a.periods) if p < self.t][-12:]
        for name, f in ratios.items():
            cur = f(self.t)
            hist = [x for x in (f(p) for p in hist_ps) if x is not None]
            if cur is None or len(hist) < R.JUMP_MIN_N:
                continue
            mu, sd = statistics.mean(hist), max(statistics.pstdev(hist), R.JUMP_STD_FLOOR)
            z = (cur - mu) / sd
            if abs(z) > R.JUMP_Z:
                out.append({"name": name, "value": cur, "mean": mu, "std": sd, "z": z, "n": len(hist),
                            "text": f"单季{name} {cur:.1%}，过去 {len(hist)} 季均值 {mu:.1%}，偏离 {z:+.1f}σ"})
        self.jump_list = out
        return out

    # ---------- 利润桥（驱动，报表口径） ----------
    def bridge(self):
        a, t, ly = self.a, self.t, _shift(self.t)
        if self.arch in FIN:
            self.bridge_res = {"status": "INSUFFICIENT", "reason": "金融类利润表结构不同，利润桥未接入"}
            return self.bridge_res
        v = lambda k, p: a.v(k, p)
        need = ("rev", "cost", "op_profit")
        if any(v(k, t) is None or v(k, ly) is None for k in need):
            self.bridge_res = {"status": "INSUFFICIENT", "reason": "营收/营业成本/营业利润缺少可用的本期或上年同期值"}
            return self.bridge_res
        d = lambda k, sign=1: sign * ((v(k, t) or 0) - (v(k, ly) or 0))
        items = [("毛利", (v("rev", t) - v("cost", t)) - (v("rev", ly) - v("cost", ly))),
                 ("税金及附加", d("tax_surcharge", -1)), ("销售费用", d("sell_exp", -1)), ("管理费用", d("admin_exp", -1)),
                 ("研发费用", d("rd_exp", -1)), ("财务费用", d("fin_exp", -1)), ("其他收益", d("other_inc")),
                 ("投资收益", d("invest_inc")), ("公允价值变动", d("fv_chg")), ("信用减值", d("credit_impair")),
                 ("资产减值", d("asset_impair"))]
        dop = v("op_profit", t) - v("op_profit", ly)
        resid = dop - sum(x for _, x in items)
        items.append(("其他（资产处置等）", resid))
        r0, r1 = v("rev", ly), v("rev", t)
        gm0, gm1 = (r0 - v("cost", ly)) / r0, (r1 - v("cost", t)) / r1
        scale, margin = (r1 - r0) * gm0, r1 * (gm1 - gm0)
        main = sorted([x for x in items if abs(x[1]) > 0], key=lambda x: -abs(x[1]))
        pos = [f"{n} {_yi(x)}" for n, x in main if x > 0][:3]
        neg = [f"{n} {_yi(x)}" for n, x in main if x < 0][:3]
        text = f"营业利润（年初至今）同比 {_yi(dop)}" + (f"；主要拉动：{'、'.join(pos)}" if pos else "") + (f"；主要拖累：{'、'.join(neg)}" if neg else "")
        gtext = f"毛利变化 {_yi(items[0][1])} = 规模效应 {_yi(scale)}（营收 {(r1 / r0 - 1):+.1%} × 上年毛利率 {gm0:.1%}）+ 毛利率效应 {_yi(margin)}（毛利率 {(gm1 - gm0) * 100:+.1f}pct）"
        self.bridge_res = {"status": "ok", "delta_op": dop, "items": [{"name": n, "delta": x} for n, x in items],
                           "gross_split": {"scale": scale, "margin": margin}, "text": text, "gross_text": gtext,
                           "volume_price": "INSUFFICIENT：量、价拆分需主营构成与销量数据，尚未接入"}
        return self.bridge_res

    # ---------- 持续性 ----------
    def persistence(self):
        a, t, ly, out = self.a, self.t, _shift(self.t), []
        n1, n0, d1, d0 = a.v("np_parent", t), a.v("np_parent", ly), a.v("np_ded", t), a.v("np_ded", ly)
        if None not in (n1, n0, d1, d0):
            one1, one0 = n1 - d1, n0 - d0
            dn, done = n1 - n0, one1 - one0
            share = abs(done) / abs(dn) if dn else 0
            txt = f"归母净利润（年初至今）同比 {_yi(dn)}，其中扣非部分 {_yi(d1 - d0)}、非经常性损益 {_yi(done)}"
            if dn and share > R.ONE_OFF_SHARE:
                out.append({"kind": "一次性", "type": "计算", "text": txt + f"；非经常性损益贡献了变化的 {share:.0%}，利润变化以一次性因素为主，不宜外推"})
            else:
                out.append({"kind": "经营性", "type": "计算", "text": txt + "；变化主要来自扣非口径（经营性）"})
        if self.arch == "B" and getattr(a, "gm_change", None) is not None and abs(a.gm_change) >= R.PRICE_UP_GM_PP:
            out.append({"kind": "周期性", "type": "推断", "text": f"周期型公司毛利率同比 {a.gm_change:+.1f}pct，利润弹性可能主要来自产品价格，价格回落时会反向；需结合产品价格验证"})
        for j in getattr(self, "jump_list", []):
            out.append({"kind": "待判定", "type": "计算", "text": j["text"] + "，可能是一次性事项或口径变化，需附注确认"})
        adj = [i for i in a.d["issues"] if "追溯调整" in i["msg"] and i.get("period") in (t, ly)]
        if adj:
            out.append({"kind": "口径性", "type": "披露", "text": f"本期或同期存在 {len(adj)} 项追溯调整，同比基数已变"})
        self.persist = out
        return out

    # ---------- 杜邦 ----------
    def dupont(self):
        a, t = self.a, self.t
        def f(p):
            npp, rev, ta, eq = a.ttm("np_parent", p), a.ttm("rev", p), a.avg_bs("ta", p), a.avg_bs("eq_parent", p)
            if None in (npp, rev, ta, eq) or not rev or not ta or not eq:
                return None
            return {"margin": npp / rev, "turnover": rev / ta, "multiplier": ta / eq, "roe": npp / eq}
        cur, prev = f(t), f(_shift(t))
        self.dup = {"current": cur, "prev": prev}
        if cur and prev and cur["roe"] > 0 and prev["roe"] > 0:
            import math
            c = {k: math.log(cur[k] / prev[k]) for k in ("margin", "turnover", "multiplier") if cur[k] > 0 and prev[k] > 0}
            names = {"margin": "归母净利率", "turnover": "总资产周转率", "multiplier": "权益乘数"}
            if c:
                k = max(c, key=lambda x: abs(c[x]))
                self.dup["driver"] = names[k]
                self.dup["text"] = (f"ROE(TTM) {prev['roe']:.1%} → {cur['roe']:.1%}：净利率 {prev['margin']:.1%}→{cur['margin']:.1%}，"
                                    f"周转 {prev['turnover']:.2f}→{cur['turnover']:.2f}，权益乘数 {prev['multiplier']:.2f}→{cur['multiplier']:.2f}；"
                                    f"变化主要来自{names[k]}")
            else:
                self.dup["driver"] = None
                self.dup["text"] = (f"ROE(TTM) {prev['roe']:.1%} → {cur['roe']:.1%}：净利率 {prev['margin']:.1%}→{cur['margin']:.1%}，"
                                    f"周转 {prev['turnover']:.2f}→{cur['turnover']:.2f}，权益乘数 {prev['multiplier']:.2f}→{cur['multiplier']:.2f}；"
                                    f"亏损期不做主因归属（对数分解要求各项为正）")
        return self.dup

    # ---------- 同源风险归并 ----------
    def signals(self):
        sig = {}
        for k, m in self.a.metrics.items():
            if m.get("verdict") in ("预警", "红色"):
                sig[k] = {"key": k, "name": m["name"], "level": "red" if m["verdict"] in ("红色",) else "warn",
                          "text": f"{m['name']} {self._fmt(m)}（{m['verdict']}{'，' + m['downgrade'] if m.get('downgrade') else ''}）"}
        for fl in self.a.flags:
            if fl["hit"] and fl["level"] in ("红", "黄"):
                sig[f"flag{fl['no']}"] = {"key": f"flag{fl['no']}", "name": f"#{fl['no']} {fl['name']}",
                                          "level": "red" if fl["level"] == "红" else "yellow", "text": f"红旗 #{fl['no']} {fl['name']}：{fl['detail']}"}
        # 同一件事的指标与红旗（应收增速差 ↔ #2、存货增速差 ↔ #3）只保留红旗
        # 存贷双高：货币资金与有息负债同时占总资产高位（资金真实性存疑的经典信号，康美/康得新类）
        a, t = self.a, self.t
        cash, ta = a.v("cash", t), a.v("ta", t)
        ibd = (a.metrics.get("ibd_ta") or {}).get("value")
        if a.d["meta"]["company_type"] == "general" and cash and ta and ibd is not None:
            cr = cash / ta
            if cr >= R.CASH_DEBT_BOTH and ibd >= R.CASH_DEBT_BOTH:
                sig["cash_debt"] = {"key": "cash_debt", "name": "存贷双高", "level": "red",
                                    "text": f"存贷双高：货币资金/总资产 {cr:.1%}、有息负债/总资产 {ibd:.1%}（均 ≥{R.CASH_DEBT_BOTH:.0%}），需核对利息收入与资金受限情况"}
        for mk, fk in (("ar_gap", "flag2"), ("inv_gap", "flag3"), ("goodwill_eq", "flag7")):
            if mk in sig and fk in sig:
                sig.pop(mk)
        return sig

    @staticmethod
    def _severity(mem):
        """按证据强度定级：红=2 分，预警=1 分，黄=0.5 分；≥4 分且含红 → 高；≥2 分或含红 → 中；否则低。"""
        reds = sum(m["level"] == "red" for m in mem)
        score = sum({"red": 2, "warn": 1, "yellow": 0.5}.get(m["level"], 0) for m in mem)
        if reds and score >= R.SEV_HIGH_SCORE:
            return "high"
        if reds or score >= R.SEV_MEDIUM_SCORE:
            return "medium"
        return "low"

    @staticmethod
    def _fmt(m):
        v, u = m["value"], m["unit"]
        if v is None:
            return "未获取"
        return f"{v:.1%}" if u == "%" else f"{v / 1e8:,.2f} 亿" if u == "亿" else f"{v:+.1f}pct" if u == "pct" else f"{v:.2f}{'' if u == '倍' else u}"

    def group_cond(self, gid):
        a = self.a
        if gid == "price_up":
            rg = next((r.get("ytd_yoy") for r in a.change_rows if r["key"] == "rev"), None)
            gmc = getattr(a, "gm_change", None)
            ok = gmc is not None and gmc >= R.PRICE_UP_GM_PP and rg is not None and rg > 0
            return ok, (f"毛利率同比 {gmc:+.1f}pct、营收（年初至今）同比 {rg:+.1%}" if ok else None)
        if gid == "expansion":
            cip, fx = a.v("cip", self.t), a.v("fixed", self.t)
            cx, ocf = a.ttm("capex", self.t), a.ttm("ocf", self.t)
            r = _div(cip, fx)
            ok = self.arch == "C" or (r is not None and r > R.GROWTH_CIP_FIXED) or (cx is not None and ocf is not None and cx > ocf)
            return ok, ("成长扩张型" if self.arch == "C" else f"在建工程/固定资产 {r:.0%}" if r is not None and r > R.GROWTH_CIP_FIXED else "资本开支 TTM 超过经营现金流") if ok else None
        return True, None

    def group_risks(self):
        sig, groups, used = self.signals(), [], set()
        for g in R.RISK_GROUPS:
            mem = [k for k in g["members"] if k in sig and k not in used]
            if not mem:
                continue
            ok, why = self.group_cond(g["id"])
            if not ok:
                continue
            used.update(mem)
            sev = "low" if g["id"] == "price_up" else self._severity([sig[k] for k in mem])
            expl = None
            if g["id"] == "price_up":
                expl = f"{why}；以下预警可能同源于产品价格或销量上升带来的应收、存货与在途资金占用，不是多个独立风险"
            elif g["id"] == "expansion":
                expl = f"{why}；以下信号可能同源于扩张期的产能与备货投入"
            elif g["id"] == "collection":
                expl = "应收增长快于收入且现金回笼偏弱，未见量价上行可解释，属需优先解释的风险"
            groups.append({"id": g["id"], "title": g["name"], "severity": sev, "direction": "negative",
                           "members": [sig[k] for k in mem], "explain": expl, "explain_type": "推断" if expl else None,
                           "next_metric": g["next"]})
        for k, s in sig.items():
            if k not in used:
                groups.append({"id": k, "title": s["name"], "severity": self._severity([s]),
                               "direction": "negative", "members": [s], "explain": None, "explain_type": None,
                               "next_metric": {"metric": k if not k.startswith("flag") else None, "flag": k if k.startswith("flag") else None,
                                               "text": f"{s['name']} 是否延续"}})
        # 多组共振：≥2 个风险组（量价上行组除外）各含红色信号 → 这些组升为高
        red_groups = [g for g in groups if g["id"] != "price_up" and any(m["level"] == "red" for m in g["members"])]
        if len(red_groups) >= R.RESONANCE_GROUPS:
            for g in red_groups:
                if g["severity"] != "high":
                    g["severity"] = "high"
                    g["escalated"] = f"多组共振：{len(red_groups)} 个风险组同时出现红色信号"
        order = {"high": 0, "medium": 1, "low": 2}
        groups.sort(key=lambda g: order[g["severity"]])
        self.risks = groups
        return groups

    # ---------- 跟踪：写入本期待验证命题，验证上期命题 ----------
    def tracking(self):
        path = os.path.join(os.path.dirname(self.a.out_dir), "跟踪.json")
        try:
            tr = json.load(open(path, encoding="utf-8"))
        except Exception:
            tr = {"items": []}
        review = []
        for it in tr["items"]:
            if it["status"] != "open" or it["due_period"] > self.t or it["created_period"] >= self.t:
                continue
            res = self._evaluate(it)
            if res:
                review.append(res)
                if self.track:
                    it.update(status=res["state"], evaluated_period=self.t, result_value=res.get("value"))
        new = []
        for g in self.risks:
            nm = g["next_metric"]
            key = nm.get("metric") or nm.get("flag")
            base = self.a.metrics.get(nm["metric"], {}).get("value") if nm.get("metric") else None
            new.append({"id": f"{self.t}:{g['id']}", "created_period": self.t, "due_period": _next_q(self.t),
                        "risk": g["title"], "severity": g["severity"], "metric": nm.get("metric"), "flag": nm.get("flag"),
                        "op": nm.get("op"), "value": nm.get("value"), "baseline": base, "text": nm["text"],
                        "proposition": f"风险“{g['title']}”在 {_next_q(self.t)} 仍将存在（可证伪条件：{nm['text']}）",
                        "status": "open" if key else "manual"})
        if self.track:
            tr["items"] = [i for i in tr["items"] if i["created_period"] != self.t] + new
            with open(path, "w", encoding="utf-8") as f:
                json.dump(tr, f, ensure_ascii=False, indent=1)
        self.review, self.new_items = review, new
        return review

    def _evaluate(self, it):
        a = self.a
        if it.get("metric"):
            m = a.metrics.get(it["metric"])
            if not m or m.get("value") is None:
                return {"item": it, "state": "无法验证", "detail": "本期该指标未获取"}
            v, d = m["value"], R.METRIC_DIR.get(it["metric"], 1)
            met = None
            if it.get("op") and it.get("value") is not None:
                met = v >= it["value"] if it["op"] == ">=" else v <= it["value"]
            b = it.get("baseline")
            if met:
                state = "风险解除"
            elif b is not None and (v - b) * d < 0:
                state = "风险加重"
            elif b is not None and (v - b) * d > 0:
                state = "有所缓解"
            else:
                state = "延续"
            return {"item": it, "state": state, "value": v,
                    "detail": f"{m['name']}：上期 {self._fmt({**m, 'value': b}) if b is not None else '—'} → 本期 {self._fmt(m)}；条件“{it['text']}”{'已满足' if met else '未满足'}"}
        if it.get("flag"):
            no = int(it["flag"][4:])
            fl = next((f for f in a.flags if f["no"] == no), None)
            if not fl:
                return {"item": it, "state": "无法验证", "detail": "本期该红旗未计算"}
            return {"item": it, "state": "延续" if fl["hit"] else "风险解除", "detail": fl["detail"]}
        return None

    # ---------- 一句话结论 ----------
    def headline(self):
        a, t = self.a, self.t
        c = {r["key"]: r for r in a.change_rows}
        bits, skipped = [], []
        for k in ("rev", "np_parent", "np_ded"):
            r = c.get(k)
            if not (r and r["single_q"] is not None and r["single_q_yoy"] is not None):
                continue
            base_note = ""
            if self.sq_verified(k, t) and not self.sq_ok(k, _shift(t)):
                base_note = "，同比基数为东财单源" if self.cell_ok(k, t) or self.sq_verified(k, t) else ""
            if base_note:
                pass
            elif not (self.sq_verified(k, t) and self.sq_ok(k, _shift(t))):
                # 单季差分用到了单一来源的上期累计 → 退回年初至今口径（本期与同期累计均已核对）
                if self.cell_ok(k, t) and self.cell_ok(k, _shift(t)) and r.get("ytd_yoy") is not None and r["ytd"] > 0 and r["ytd_ly"] > 0:
                    bits.append(f"年初至今{r['name']} {r['ytd'] / 1e8:.2f} 亿（同比 {r['ytd_yoy']:+.1%}）")
                else:
                    skipped.append(r["name"])
                continue
            a_, b_ = r["single_q"], r["single_q_ly"]
            if a_ < 0 or b_ < 0:
                g = "扭亏" if b_ < 0 <= a_ else "转亏" if b_ >= 0 > a_ else ("亏损收窄" if a_ > b_ else "亏损扩大")
                g = f"上年同期 {b_ / 1e8:.2f} 亿，{g}"
            else:
                g = f"同比 {r['single_q_yoy']:+.1%}"
            bits.append(f"单季{r['name']} {a_ / 1e8:.2f} 亿（{g}{base_note}）")
        ocf = a.metrics.get("ocf_np", {}).get("value")
        if ocf is not None:
            bits.append(f"净现比 TTM {ocf:.2f}")
        errs, hist = a.split_errors()
        hi = [g for g in self.risks if g["severity"] == "high"]
        if errs:
            tail = f"近期数据存在 {len(errs)} 项冲突，结论待人工核对"
        elif self.arch in FIN:
            tail = "金融类行业核心指标（资产质量、资本、负债成本等）尚未接入，本报告不做健康度结论"
            if self.risks:
                tail += f"；通用指标另有 {sum(len(g['members']) for g in self.risks)} 个预警（见风险表，仅供参考）"
        elif self.risks:
            sigs = sum(len(g["members"]) for g in self.risks)
            tail = f"{sigs} 个预警信号归并为 {len(self.risks)} 组待解释风险（" + "；".join(
                g["title"] + ("·高" if g["severity"] == "high" else "·待验证" if g["id"] == "price_up" else "·弱信号" if g["severity"] == "low" else "") for g in self.risks) + "）"
        else:
            tail = "本期底稿可算的红旗与预警指标均未触发"
        if hist:
            tail += f"（另有 {len(hist)} 项较早年份数据冲突，只影响长期均值类指标）"
        if skipped:
            tail += f"（{'、'.join(skipped)}含单一来源数据，待核验，未写入本句）"
        pre = "【草稿：" + "；".join(self.gate_res["reasons"]) + "】" if self.gate_res["status"] != "pass" else ""
        return pre + f"{a.m['name']} {t}：" + "；".join(bits) + f"。{tail}。"

    def run(self):
        self.gate()
        self.trend_downgrade()
        self.jumps()
        self.bridge()
        self.persistence()
        self.dupont()
        self.group_risks()
        self.tracking()
        return {"gate": self.gate_res, "jumps": self.jump_list, "bridge": self.bridge_res, "persistence": self.persist,
                "dupont": self.dup, "risks": self.risks, "tracking_review": [{k: v for k, v in r.items() if k != "item"} | {
                    "risk": r["item"]["risk"], "created_period": r["item"]["created_period"], "text": r["item"]["text"]} for r in self.review],
                "tracking_new": self.new_items, "headline": self.headline()}
