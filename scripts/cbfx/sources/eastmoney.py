"""东方财富 F10 三表接口。支持一般企业/银行/保险/证券四种报表模板。"""
from ..net import fetch_json, FetchError

F10 = "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis"
EP = {"bs": "zcfzb", "is": "lrb", "cf": "xjllb"}


def _code(org):
    return ("SH" if org["market"] == "sh" else "BJ" if org["market"] == "bj" else "SZ") + org["code"]


def detect_company_type(org):
    """返回 (东方财富 companyType, 可用报告期列表)。依次尝试 一般/银行/保险/证券。"""
    for ct in (4, 3, 2, 1):
        try:
            d, _ = fetch_json(f"{F10}/zcfzbDateAjaxNew", ttl=6 * 3600,
                              params={"companyType": ct, "reportDateType": 0, "code": _code(org)})
        except FetchError:
            continue
        rows = d.get("data") or []
        if rows:
            return ct, [r["REPORT_DATE"][:10] for r in rows]
    raise FetchError("东方财富未返回任何报表模板的数据")


def dates(org, ct, stmt="bs"):
    """完整的报告期列表（接口每页有限，翻页直到取完）。"""
    out, page = [], 1
    while page < 20:
        d, _ = fetch_json(f"{F10}/{EP[stmt]}DateAjaxNew", ttl=6 * 3600,
                          params={"companyType": ct, "reportDateType": 0, "code": _code(org), "pageIndex": page})
        rows = d.get("data") or []
        new = [r["REPORT_DATE"][:10] for r in rows if r["REPORT_DATE"][:10] not in out]
        if not new:
            break
        out += new
        page += 1
    return out


def statements(org, ct, stmt, periods):
    """取指定报告期的原始行（字段名为东方财富原名）。接口一次最多 5 个日期。"""
    res = {}
    for i in range(0, len(periods), 5):
        chunk = periods[i:i + 5]
        d, meta = fetch_json(f"{F10}/{EP[stmt]}AjaxNew", params={
            "companyType": ct, "reportDateType": 0, "reportType": 1,
            "dates": ",".join(chunk), "code": _code(org)})
        for r in d.get("data") or []:
            res[r["REPORT_DATE"][:10]] = r
    return res
