"""巨潮资讯：证监会指定披露平台。定位公司、列公告、下载 PDF。这是“标准答案”的来源。"""
import hashlib, os, re, time
from ..net import fetch, fetch_json, FetchError

BASE = "http://www.cninfo.com.cn"
PDF_BASE = "http://static.cninfo.com.cn/"
CATEGORY = {"Q1": "category_yjdbg_szsh", "H1": "category_bndbg_szsh",
            "Q3": "category_sjdbg_szsh", "FY": "category_ndbg_szsh"}
REPORT_NAME = {"Q1": "第一季度报告", "H1": "半年度报告", "Q3": "第三季度报告", "FY": "年度报告"}
# 标题写法不统一：“第三季度报告”“三季度报告”“第3季度报告”“半年度报告全文”
REPORT_RE = {"Q1": re.compile(r"(第?[一1]季度|一季)报告"), "H1": re.compile(r"(半年度|中期)报告"),
             "Q3": re.compile(r"(第?[三3]季度|三季)报告"), "FY": re.compile(r"年度报告")}
EXCLUDE = ("摘要", "英文", "已取消", "取消", "H股", "公告", "提示", "更正公告", "补充公告", "专项", "鉴证")


def market_of(code):
    if code.startswith(("6", "9")) and not code.startswith("92"):
        return "sh"
    if code.startswith(("0", "2", "3")):
        return "sz"
    return "bj"


def search(code):
    d, _ = fetch_json(f"{BASE}/new/information/topSearch/query", data={"keyWord": code, "maxNum": 10}, ttl=7 * 86400)
    for x in d:
        if x.get("code") == code and x.get("category") == "A股":
            return {"code": code, "name": x["zwjc"], "orgId": x["orgId"], "market": market_of(code)}
    raise FetchError(f"巨潮未找到 A 股代码 {code}")


def report_type(period):
    return {"03-31": "Q1", "06-30": "H1", "09-30": "Q3", "12-31": "FY"}[period[5:]]


def list_reports(org, period):
    """列出某报告期的定期报告正文（剔除摘要/英文版），按披露时间新到旧。"""
    rt = report_type(period)
    y = int(period[:4])
    start, end = f"{y}-{period[5:7]}-01", f"{y + 1}-12-31"
    col = {"sh": "sse", "sz": "szse", "bj": "szse"}[org["market"]]
    d, _ = fetch_json(f"{BASE}/new/hisAnnouncement/query", ttl=1800, data={
        "pageNum": 1, "pageSize": 30, "column": col, "tabName": "fulltext", "plate": "",
        "stock": f"{org['code']},{org['orgId']}", "searchkey": "", "secid": "",
        "category": CATEGORY[rt] + ";", "trade": "", "seDate": f"{start}~{end}",
        "sortName": "", "sortType": "", "isHLtitle": "true"})
    out = []
    want_year = f"{y}年"
    for a in d.get("announcements") or []:
        title = a["announcementTitle"].replace("<em>", "").replace("</em>", "")
        if want_year not in title or not REPORT_RE[rt].search(title):
            continue
        if rt == "FY" and "半年度" in title:
            continue
        if any(k in title for k in EXCLUDE) and "更正后" not in title and "修订" not in title:
            continue
        out.append({"period": period, "type": rt, "title": title,
                    "url": PDF_BASE + a["adjunctUrl"],
                    "publish_date": time.strftime("%Y-%m-%d", time.gmtime(a["announcementTime"] / 1000 + 8 * 3600)),
                    "announcement_id": a.get("announcementId")})
    out.sort(key=lambda x: x["publish_date"], reverse=True)
    return out


def download(rep, dest_dir):
    raw, meta = fetch(rep["url"], ttl=None, binary=True, timeout=90)
    if not raw.startswith(b"%PDF"):
        raise FetchError(f"下载内容不是 PDF：{rep['url']}")
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, f"{rep['period']}_{rep['type']}_{rep['publish_date']}.pdf")
    with open(path, "wb") as f:
        f.write(raw)
    rep = dict(rep, local_path=path, sha1=hashlib.sha1(raw).hexdigest(), size=len(raw))
    return rep
