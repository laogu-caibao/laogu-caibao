"""行情快照：腾讯行情 + 东方财富，两源互相兜底与核对。"""
import time
from ..net import fetch, fetch_json, FetchError


def tencent(org):
    text, _ = fetch(f"http://qt.gtimg.cn/q={org['market']}{org['code']}", ttl=300)
    s = text.split('"')[1].split("~")
    return {"source": "腾讯行情", "price": float(s[3]), "time": s[30], "pe_ttm": _f(s[39]),
            "mcap_yi": _f(s[45]), "float_mcap_yi": _f(s[44]), "pb": _f(s[46])}


def eastmoney(org):
    secid = ("1." if org["market"] == "sh" else "0.") + org["code"]
    d, _ = fetch_json("https://push2.eastmoney.com/api/qt/stock/get", ttl=300, params={
        "ut": "fa5fd1943c7b386f172d6893dbfba10b", "fltt": 2, "invt": 2, "secid": secid,
        "fields": "f43,f57,f58,f84,f116,f162,f167"})
    x = d.get("data") or {}
    if not x:
        raise FetchError("东方财富行情空响应")
    return {"source": "东方财富行情", "price": _f(x.get("f43")), "time": time.strftime("%Y%m%d"),
            "pe_ttm": _f(x.get("f162")), "mcap_yi": _f(x.get("f116")) / 1e8 if _f(x.get("f116")) else None,
            "pb": _f(x.get("f167")), "total_shares": _f(x.get("f84"))}


def snapshot(org):
    res, errs = [], []
    for fn in (tencent, eastmoney):
        try:
            res.append(fn(org))
        except Exception as e:  # 行情不是核心数据，失败只记录
            errs.append(f"{fn.__name__}: {e}")
    return res, errs


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
