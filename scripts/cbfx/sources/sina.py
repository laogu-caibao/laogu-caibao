"""新浪财经三表接口（与东方财富相互独立的第二来源，用于交叉核对）。"""
from ..net import fetch_json

API = "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022"
SRC = {"bs": "fzb", "is": "lrb", "cf": "llb"}


def statements(org, stmt, n=20):
    """返回 {报告期: {字段: 值}}，以及 {报告期: 元信息（审计意见、披露日等）}。"""
    out, meta = {}, {}
    page = 1
    while len(out) < n and page <= n // 20 + 2:
        d, _ = fetch_json(API, params={"paperCode": org["market"] + org["code"], "source": SRC[stmt],
                                       "type": 0, "page": page, "num": 20})
        rl = (((d.get("result") or {}).get("data") or {}).get("report_list")) or {}
        if not rl:
            break
        for k, r in rl.items():
            p = f"{k[:4]}-{k[4:6]}-{k[6:]}"
            if p in out:
                continue
            row = {}
            for it in r.get("data") or []:
                f, v = it.get("item_field"), it.get("item_value")
                if f and v not in (None, ""):
                    try:
                        row[f] = float(v)
                    except ValueError:
                        pass
            out[p] = row
            meta[p] = {x: r.get(x) for x in ("rType", "data_source", "is_audit", "audit_opinion", "publish_date")}
        page += 1
    return out, meta
