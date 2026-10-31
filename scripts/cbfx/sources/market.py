"""估值用的历史行情与股本、行业分类（全部免费接口）。

- 月 K 线：腾讯 fqkline（不复权，bfq）。复权价不能乘股本算市值：前复权会把历史分红从价格里减掉，越早越失真。
- 股本变动：东方财富 F10 股本结构 lngbbd（总股本，含 H 股，和行情软件的总市值口径一致）。
- 行业：东方财富 F10 公司概况（东财行业 EM2016 + 证监会行业）。
"""
from ..net import fetch_json, FetchError
from .eastmoney import _code

F10 = "https://emweb.securities.eastmoney.com/PC_HSF10"


def monthly_kline(org, n=130):
    sym = f"{org['market']}{org['code']}"
    d, _ = fetch_json("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get", ttl=12 * 3600,
                      params={"param": f"{sym},month,,,{n},bfq"})
    rows = ((d.get("data") or {}).get(sym) or {}).get("month") or []
    if not rows:
        raise FetchError("腾讯月 K 线为空")
    return [{"date": r[0], "close": float(r[2])} for r in rows]


def share_history(org):
    d, _ = fetch_json(f"{F10}/CapitalStockStructure/PageAjax", ttl=7 * 86400, params={"code": _code(org)})
    rows = d.get("lngbbd") or []
    out = sorted(({"date": r["END_DATE"][:10], "total_shares": float(r["TOTAL_SHARES"])}
                  for r in rows if r.get("TOTAL_SHARES")), key=lambda x: x["date"])
    if not out:
        raise FetchError("东方财富股本变动为空")
    return out


def industry(org):
    d, _ = fetch_json(f"{F10}/CompanySurvey/PageAjax", ttl=30 * 86400, params={"code": _code(org)})
    j = d.get("jbzl")
    j = j[0] if isinstance(j, list) and j else (j or {})
    return {"em": j.get("EM2016"), "csrc": j.get("INDUSTRYCSRC1")}
