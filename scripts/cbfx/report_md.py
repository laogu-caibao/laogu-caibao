"""把底稿写成人能快速看懂的《数据核对报告》。"""
import os

KEY_ROWS = ["rev", "cost", "np_parent", "np_ded", "ocf", "sales_cash", "capex", "cash", "ar", "inv",
            "ta", "tl", "eq_parent", "st_loan", "ncl_1y", "lt_loan", "bonds", "goodwill", "contract_liab"]
SRC_CN = {"pdf": "原文", "pdf_comparative": "原文比较期", "eastmoney": "东财", "sina": "新浪"}


def yi(v):
    return "—" if v is None else f"{v / 1e8:,.2f}"


def write(doc, out_dir):
    m, t = doc["meta"], doc["meta"]["target_period"]
    L = [f"# {m['name']}（{m['code']}）{t} 数据核对报告", "",
         f"- 报告类型：{m['report_type']}　模式：{'季报快检' if m['mode'] == 'quick' else '年报深检'}　公司模板：{m['company_type_cn']}",
         f"- 生成时间：{m['generated_at']}　工具版本：{m['tool_version']}",
         f"- 数据源状态：" + "；".join(f"{k} {v}" for k, v in m["source_status"].items()), ""]
    L += ["## 原文", ""]
    if doc["filings"]:
        for f in doc["filings"]:
            L.append(f"- {f['title']}（{f.get('publish_date') or '本地文件'}）解析出 {f.get('parsed_fields')} 个科目；"
                     f"审计意见：{f.get('audit_opinion') or '—'}；地址：{f.get('url') or f.get('local_file')}")
    else:
        L.append("- 未取得原文，本期所有结论只能标为「草稿」。")
    cov = doc["coverage_target"]
    L += ["", "## 本期覆盖", "", "　".join(f"{k} {v}" for k, v in sorted(cov.items(), key=lambda x: -x[1])), ""]
    L += ["## 关键科目（单位：亿元，年初累计/期末口径）", "",
          "| 科目 | 采用值 | 状态 | 原文 | 东财 | 新浪 | 原文页 |", "|---|---:|---|---:|---:|---:|---:|"]
    for k in KEY_ROWS:
        f = doc["fields"][k]
        c = f["values"].get(t) or {"sources": {}, "status": "未获取", "value": None}
        s = c["sources"]
        L.append(f"| {f['name']} | {yi(c['value']) if c.get('usable') else '不可用'} | {c['status']} | "
                 f"{yi(s.get('pdf'))} | {yi(s.get('eastmoney'))} | {yi(s.get('sina'))} | {c.get('pdf_page') or ''} |")
    sq = doc["derived"]["single_quarter"]
    L += ["", "## 单季序列（亿元，最近 8 季）", ""]
    ps = sorted(doc["periods"])[-8:]
    L += ["| 科目 | " + " | ".join(ps) + " |", "|---|" + "---:|" * len(ps)]
    for k in ("rev", "np_parent", "np_ded", "ocf"):
        L.append(f"| {doc['fields'][k]['name']} | " + " | ".join(yi(sq.get(k, {}).get(p)) for p in ps) + " |")
    debt = doc["derived"]["interest_bearing_debt"]
    L += ["", f"有息负债（近似口径）本期：{yi(debt['values'].get(t))} 亿。{debt['口径']}", ""]
    q = doc["quote"]
    L += ["## 行情快照", ""]
    for s in q["snapshots"]:
        L.append(f"- {s['source']}：{s.get('price')} 元，总市值 {s.get('mcap_yi')} 亿，PE(TTM) {s.get('pe_ttm')}，PB {s.get('pb')}")
    for e in q["errors"]:
        L.append(f"- 失败：{e}")
    L += ["", "## 问题清单", ""]
    order = {"error": 0, "warn": 1, "info": 2}
    tag = {"error": "🔴 错误", "warn": "🟡 注意", "info": "⚪ 说明"}
    iss = sorted(doc["issues"], key=lambda x: (order[x["level"]], x.get("period") or ""), reverse=False)
    if not iss:
        L.append("- 无")
    for i in iss[:60]:
        L.append(f"- {tag[i['level']]}：{i['msg']}")
    if len(iss) > 60:
        L.append(f"- ……另有 {len(iss) - 60} 条，见 底稿.json")
    L += ["", "> 状态含义：一致 ≤0.1%｜偏差 0.1%–1%｜冲突 >1%（不可用）｜追溯调整＝本期报告比较期数与接口原始数不同，按调整后口径｜原文自洽＝财报当日仅有原文，报表与主要会计数据表互相印证｜单一来源＝只有一个来源，可用但置信度低。"]
    path = os.path.join(out_dir, "数据核对报告.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path
