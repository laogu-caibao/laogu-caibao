"""从定期报告 PDF 中提取合并三表与“主要会计数据”。

只认合并报表（跳过母公司报表），只取能精确匹配规范标签的行。
解析不到就留空并记录原因，绝不猜。
"""
import re
from .fields import BY_KEY, FIELDS

HEADERS = {
    "合并资产负债表": ("bs", True), "母公司资产负债表": ("bs", False),
    "合并利润表": ("is", True), "母公司利润表": ("is", False),
    "合并现金流量表": ("cf", True), "母公司现金流量表": ("cf", False),
}
# 部分公司写“合并资产负债表(未经审计)”等，统一按前缀识别
# 兼容：“合并资产负债表(未经审计)”“2026 年半年度合并及公司利润表”“合并及母公司现金流量表”
HDR_RE = re.compile(r"^(?:[（(]?[一二三四五六七八九十\d]{1,2}[)）、.．])?(?:未经审计的?|经审计的?)?"
                    r"(?:\d{4}年(?:半年度|第[一三]季度|年度|1-\d+月)?)?"
                    r"(合并及公司|合并及母公司|合并|母公司|公司)"
                    r"(年初到报告期末|年初至报告期末|第[一二三四]季度|本报告期|本期)?"
                    r"(资产负债表|利润表|现金流量表)(?:[（(].*[)）])?(?:[（(]续[)）])?$")


def _hdr(m):
    """HDR_RE 匹配 → (报表, 是否采用)。只采用合并口径的累计报表；单季度报表（第X季度）不采用。"""
    kind = {"资产负债表": "bs", "利润表": "is", "现金流量表": "cf"}[m.group(3)]
    use = m.group(1).startswith("合并") and not (m.group(2) or "").startswith("第")
    return kind, use
UNIT_RE = re.compile(r"单位(?:为|均以|均为|是)?[:：]?\s*(人民币)?\s*(百万元|千元|万元|亿元|元)")
UNIT_RE2 = re.compile(r"[（(]\s*(?:货币)?(?:单位[:：])?\s*人民币\s*(百万元|千元|万元|亿元)")
UNIT_LINE_RE = re.compile(r"^\s*[（(]?(?:金额)?(?:单位[:：])?人民币\s*(百万元|千元|万元|亿元|元)[)）]?\s*$", re.M)
LABEL_UNIT_RE = re.compile(r"[（(](?:人民币)?(元|千元|万元|百万元|亿元)[)）]")
UNIT = {"元": 1, "千元": 1e3, "万元": 1e4, "百万元": 1e6, "亿元": 1e8}
NUM_RE = re.compile(r"^[（(]?-?[\d,]+(\.\d+)?[)）]?$")

_ALIAS = {}
for f in FIELDS:
    for a in f[6]:
        _ALIAS.setdefault(None, None)


def _canon(s):
    """主体称谓统一：本行/本公司/本集团/母公司/上市公司 股东|所有者 → 母公司股东；所有者权益 → 股东权益。"""
    s = re.sub(r"(归属于)?(本行|本公司|本集团|母公司|上市公司)(普通)?(股东|所有者)(的)?", "归属于母公司股东", s)
    s = s.replace("所有者权益", "股东权益").replace("少数股东的净利润", "少数股东损益")
    return s


def norm_label(s):
    s = (s or "").replace("\n", "").replace(" ", "").replace("\u3000", "")
    prev = None
    while prev != s:                                    # 去括号说明（含嵌套）：（净亏损以“()”号填列）
        prev, s = s, re.sub(r"[（(][^（()）]*[)）]", "", s)
    s = re.sub(r"[“”\"']", "", s)
    s = re.sub(r"^[一二三四五六七八九十]+、", "", s)
    s = re.sub(r"^[（(][一二三四五六七八九十\d]+[)）]", "", s)
    s = re.sub(r"^(其中|减|加)[:：]", "", s)
    s = re.sub(r"^\d+[.、]", "", s)
    s = s.rstrip(":：")
    return _canon(s)


for f in FIELDS:
    for a in f[6]:
        _ALIAS.setdefault(norm_label(a), f[0])
_ALIAS.pop(None, None)


def to_num(s):
    s = (s or "").replace("\n", "").replace(" ", "")
    if not s or not NUM_RE.match(s):
        return None
    neg = s.startswith(("(", "（")) or s.startswith("-")
    v = float(s.strip("()（）-").replace(",", ""))
    return -v if neg else v


def _lines(text):
    return [l.strip() for l in (text or "").splitlines()]


def parse(path, report_type, max_pages_scan=None):
    """返回 {"statements": {key: {"cur": v, "prev": v, "page": n}}, "main": {...}, "unit": .., "notes": [..]}"""
    import pdfplumber
    res = {"statements": {}, "main": {}, "notes": [], "audit_opinion": None, "pages": 0}
    with pdfplumber.open(path) as pdf:
        pages = pdf.pages if not max_pages_scan else pdf.pages[:max_pages_scan]
        res["pages"] = len(pdf.pages)
        texts = page_texts(path, len(pages))
        res["blank_pages"] = [i + 1 for i, t in enumerate(texts) if len((t or "").strip()) < 20]
        # 1) 定位报表页与主要会计数据页
        sec_by_page, cur, unit_by_page, unit, last_hdr = [], None, [], 1, -99
        stmt_pages, main_pages = set(), set()
        for i, t in enumerate(texts):
            hdrs = []
            for l in _lines(t):
                m = HDR_RE.match(l.replace(" ", ""))
                if m:
                    hdrs.append(_hdr(m))   # “合并及公司”表：前两列数字为合并口径
            um = UNIT_RE.search(t)
            um2 = UNIT_RE2.search(t) or UNIT_LINE_RE.search(t)
            page_unit = UNIT[um.group(2)] if um else (UNIT[um2.group(1)] if um2 else None)
            if hdrs and any(h[1] for h in hdrs):
                # 报表页单位只认本页声明，不继承前文（前文多为“万元”的经营讨论）
                if page_unit is None:
                    res["notes"].append(f"第{i + 1}页报表未找到单位声明，暂按元；请以接口量级校验")
                unit = page_unit or 1
            elif page_unit:
                unit = page_unit
            if i - last_hdr > 3:      # 一张报表最多续 3 页，之后是附注，不再当报表页
                cur = None
            start = cur
            if hdrs:
                cur = hdrs[-1]
                last_hdr = i
            sec_by_page.append((start, hdrs))
            unit_by_page.append(unit)
            if hdrs or (start and start[1]):
                stmt_pages.add(i)
            if ("主要会计数据" in t or "主要财务数据" in t) and i < 40:
                main_pages.add(i)
                main_pages.add(i + 1)
        # 2) 只对候选页抽表
        for i in sorted(stmt_pages | main_pages):
            if i >= len(pages):
                continue
            page = pages[i]
            start, hdrs = sec_by_page[i]
            hdr_tops = []
            for m in page.search(r"(合并及母公司|合并及公司|合并|母公司|公司)(年初到报告期末|年初至报告期末|第[一二三四]季度|本报告期|本期)?(资产负债表|利润表|现金流量表)", regex=True):
                mm = HDR_RE.match(m["text"].replace(" ", ""))
                if mm:
                    hdr_tops.append((m["top"], _hdr(mm)))
            hdr_tops.sort()
            tables = page.find_tables()
            for tb in tables:
                top = tb.bbox[1]
                sec = start
                for t0, s_ in hdr_tops:
                    if t0 <= top:
                        sec = s_
                rows = tb.extract()
                if i in main_pages:
                    _main_rows(rows, report_type, res, unit_by_page[i], i)
                if i in stmt_pages and sec and sec[1]:
                    _stmt_rows(rows, sec[0], res, unit_by_page[i], i)
            if True:   # 再按文本行补漏（无框线表格：银行、券商常见）；只填表格没取到的科目
                sec = start
                rows_by_sec = []
                for l in (page.extract_text() or "").splitlines():
                    m = HDR_RE.match(l.replace(" ", ""))
                    if m:
                        sec = _hdr(m)
                        continue
                    row = _text_row(l)
                    if row:
                        rows_by_sec.append((sec, row))
                if i in main_pages:
                    _main_rows([r for _, r in rows_by_sec], report_type, res, unit_by_page[i], i, from_text=True)
                if i in stmt_pages:
                    for sec2 in {s2 for s2, _ in rows_by_sec if s2 and s2[1]}:
                        _stmt_rows([r for s2, r in rows_by_sec if s2 == sec2], sec2[0], res, unit_by_page[i], i)
        _fix_signs(res)
        res.pop("_fin_seen", None)
        res.pop("_note_col", None)
        res["audit_opinion"] = _audit(texts) if report_type == "FY" else "季报/半年报一般未经审计"
    return res


EXP_KEYS = ("cost", "tax_surcharge", "sell_exp", "admin_exp", "rd_exp", "fin_exp", "int_exp", "income_tax")
OUT_KEYS = ("capex", "div_int_paid")


def _fix_signs(res):
    """部分公司（如美的）把费用、现金流出用括号列示为负数；统一成接口口径（正数）。"""
    st = res["statements"]
    paren_exp = ("cost" in st and (st["cost"]["cur"] or 0) < 0) or (
        "cost" not in st and "income_tax" in st and (st["income_tax"]["cur"] or 0) < 0
        and "total_profit" in st and "np" in st and st["total_profit"]["cur"] > st["np"]["cur"])
    paren_out = "capex" in st and (st["capex"]["cur"] or 0) < 0
    for probe, keys, hit in (("cost", EXP_KEYS, paren_exp), ("capex", OUT_KEYS, paren_out)):
        if hit:
            for k in keys:
                if k in st:
                    for p in ("cur", "prev"):
                        if st[k].get(p) is not None:
                            st[k][p] = -st[k][p]
            res["notes"].append(f"原文以括号列示{'费用' if probe == 'cost' else '现金流出'}，已统一为正数")


def page_texts(path, n=None):
    """快速取各页文本用于定位：PyMuPDF 优先（快 20 倍），失败再退回 pdfplumber。"""
    try:
        import pymupdf
        with pymupdf.open(path) as d:
            return [d[i].get_text() for i in range(n or len(d))]
    except Exception:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return [p.extract_text() or "" for p in pdf.pages[:n]]


DASH = {"-", "—", "–", "－", "--"}


def _nums(cells):
    """按列顺序取数；“-”记为 0（报表中表示无发生额），附注列等非数字跳过。"""
    out = []
    for c in cells:
        c2 = (c or "").replace("\n", "").replace(" ", "")
        if c2 in DASH:
            out.append(0.0)
            continue
        v = to_num(c2)
        if v is not None:
            out.append(v)
    return out


TOK_RE = re.compile(r"^[（(]?-?[\d,]+(\.\d+)?[)）]?$|^[-—–－]$")
NOTE_RE = re.compile(r"^(\d{1,2}|[一二三四五六七八九十]+)(\([a-z0-9一二三四五六七八九十]+\))*$|^[四五六七八九十]+\(|^附注")


def _text_row(line):
    """把“贷款和垫款 9 7,194,263 7,004,238”拆成 [科目, 数1, 数2]；附注编号剔除。"""
    toks = line.strip().split()
    if len(toks) < 2:
        return None
    nums = []
    while toks and TOK_RE.match(toks[-1]):
        nums.insert(0, toks.pop())
    if not nums or not toks:
        return None
    # 末尾的附注编号（如“9”“49(f)”“四(1)”）
    if len(toks) > 1 and NOTE_RE.match(toks[-1]):
        toks.pop()
    # 附注是纯数字时会被当成第一个数：数字个数为奇数且第一个是 1–2 位无逗号整数，则视为附注
    if len(nums) % 2 == 1 and len(nums) >= 3 and re.match(r"^\d{1,2}$", nums[0]):
        nums.pop(0)
    return ["".join(toks)] + nums


def _label(r, nxt=None):
    """取首个非空文本单元格为科目名；若下一行只有续写的科目名（无数字），拼接起来。"""
    idx = next((j for j, c in enumerate(r) if c and str(c).strip() and to_num(c) is None and c.strip() not in DASH), None)
    if idx is None:
        return None, 0
    lab = r[idx].replace("\n", "")
    if nxt:
        j2 = next((j for j, c in enumerate(nxt) if c and str(c).strip()), None)
        if j2 is not None and not _nums(nxt[j2 + 1:]) and to_num(nxt[j2]) is None:
            lab2 = lab + nxt[j2].replace("\n", "")
            if _ALIAS.get(norm_label(lab2)) and not _ALIAS.get(norm_label(lab)):
                lab = lab2
    return lab, idx


def _strip_note_col(rows, res):
    """去掉“附注”列（茅台等公司附注列是纯数字“44”，会被误当成本期数）。
    表头没有“附注”的续页表格，沿用前一张同宽度表格识别到的附注列位置。"""
    width = max((len(r) for r in rows if r), default=0)
    note = None
    for r in rows[:4]:
        for j, c in enumerate(r or []):
            if c and c.replace("\n", "").replace(" ", "") in ("附注", "附注七", "附注五", "注释", "附注号"):
                note = j
    if note is None and res.get("_note_col", (None, None))[0] == width:
        note = res["_note_col"][1]
    if note is None:
        return rows
    res["_note_col"] = (width, note)
    return [[c if j != note else "" for j, c in enumerate(r)] if r else r for r in rows]


def _stmt_rows(rows, stmt, res, unit, page_no):
    rows = _strip_note_col(rows, res)
    for k, r in enumerate(rows):
        if not r:
            continue
        lab, idx = _label(r, rows[k + 1] if k + 1 < len(rows) else None)
        if not lab:
            continue
        key = _ALIAS.get(norm_label(lab))
        if key == "fin_exp":
            res["_fin_seen"] = True
        if not key or BY_KEY[key]["stmt"] != stmt or key in res["statements"]:
            continue
        # 利息费用/利息收入只认“财务费用”下的明细行（金融子公司的“利息收入”营收行不算）
        if key in ("int_exp", "int_inc") and not res.get("_fin_seen"):
            continue
        cells = [c for c in r[idx + 1:] if c not in (None, "")]
        # 兜底：数字个数为奇数且第一个是 1–3 位无逗号整数 → 视为附注编号
        if len(cells) >= 3 and len(cells) % 2 == 1 and re.match(r"^\d{1,3}$", (cells[0] or "").strip()):
            cells = cells[1:]
        ns = _nums(cells)
        if not ns:
            continue
        res["statements"][key] = {"cur": ns[0] * unit, "prev": ns[1] * unit if len(ns) > 1 else None,
                                  "page": page_no + 1, "label": lab}


MAIN_KEYS = ("rev", "np_parent", "np_ded", "ocf", "ta", "eq_parent")


def _col_roles(header_rows, width):
    """根据表头判定列：q=本报告期(单季)、ytd=年初至报告期末/本期累计；剔除上年同期、增减幅度列。"""
    heads = [""] * width
    for ri, r in enumerate(header_rows):
        last = ""
        for j in range(width):
            c = r[j] if j < len(r) else None
            if c is None:
                # 横向合并单元格只在首行表头沿用左侧标题（如“上年同期”横跨调整前/调整后两列）；
                # 下层表头的 None 多是纵向合并，不能沿用左侧
                c = last if ri == 0 else ""
            else:
                last = c
            heads[j] += (c or "").replace("\n", "").replace(" ", "")
    years = [int(y) for h in heads for y in re.findall(r"(20\d{2})年", h)]
    ymax = max(years) if years else None
    roles = {}
    for j, h in enumerate(heads):
        if not h or re.search(r"增减|变动|%|调整前", h):
            continue
        ys = [int(y) for y in re.findall(r"(20\d{2})年", h)]
        if (ys and ymax and max(ys) < ymax) or ("上年" in h and "年初至" not in h.replace("上年同期", "")):
            continue
        if "上年同期" in h:
            continue
        if "年初至" in h or re.search(r"1[-－至~]9月|1[-－至~]6月|1[-－至~]3月|年度|1[-－至~]12月", h):
            roles.setdefault("ytd", j)
        elif "本报告期" in h or re.search(r"[47][-－至~](6|9|12)月|10[-－至~]12月", h):
            roles.setdefault("q", j)
    return roles


def _main_rows(rows, rt, res, unit, page_no, from_text=False):
    """主要会计数据：季报（Q3）给出“本报告期”(单季)与“年初至报告期末”；其他报告给本期累计。
    表格优先按表头定位列；文本行没有列信息，只接受数字个数能唯一解释的行。"""
    width = max((len(r) for r in rows if r), default=0)
    first_data = None
    for k, r in enumerate(rows):
        lab, _ = _label(r) if r else (None, 0)
        if lab and _ALIAS.get(norm_label(lab)) in MAIN_KEYS:
            first_data = k
            break
    roles = _col_roles(rows[:first_data], width) if (first_data and not from_text) else {}
    for k, r in enumerate(rows):
        if not r:
            continue
        lab, idx = _label(r, rows[k + 1] if k + 1 < len(rows) else None)
        if not lab:
            continue
        key = _ALIAS.get(norm_label(lab))
        if key not in MAIN_KEYS or key in res["main"]:
            continue
        u = unit
        nxt = rows[k + 1] if k + 1 < len(rows) else None
        nxt_txt = "".join(c for c in (nxt or []) if c and to_num(c) is None) if nxt and not _nums(nxt) else ""
        lu = LABEL_UNIT_RE.search(lab) or LABEL_UNIT_RE.search(nxt_txt)
        if lu:
            u = UNIT[lu.group(1)]
        ns = [v for v in (to_num(c) for c in r[idx + 1:]) if v is not None]
        if not ns:
            continue
        item = {"page": page_no + 1}
        cell = lambda j: to_num((r[j] or "").replace("\n", "")) if j is not None and j < len(r) and r[j] else None
        if key in ("ta", "eq_parent"):
            item["cur"] = ns[0] * u
            item["prev_year_end"] = ns[1] * u if len(ns) > 1 else None
        elif rt == "Q3":
            if roles.get("ytd") is not None:
                cur, q = cell(roles["ytd"]), cell(roles.get("q"))
                if cur is None:
                    continue
                item["cur"] = cur * u
                if q is not None:
                    item["quarter"] = q * u
            elif from_text and len(ns) == 4:      # 本期、增减%、年初至、增减%
                item["quarter"], item["cur"] = ns[0] * u, ns[2] * u
            elif from_text and len(ns) == 6:      # 本期、上年、增减%、年初至、上年、增减%
                item["quarter"], item["cur"] = ns[0] * u, ns[3] * u
            elif from_text and len(ns) <= 3 and key == "ocf":   # 现金流只披露年初至
                item["cur"] = ns[0] * u
            else:
                continue
        else:
            j = roles.get("ytd", roles.get("q"))
            cur = cell(j) if j is not None else ns[0]
            if cur is None:
                continue
            item["cur"] = cur * u
            if rt in ("H1", "FY") and j is None and len(ns) >= 2:
                item["prev"] = ns[1] * u
        res["main"][key] = item


def _audit(texts):
    joined = "\n".join(texts[:80])
    for k in ("无法表示意见", "否定意见", "带强调事项段的无保留意见", "保留意见", "标准无保留意见", "无保留意见"):
        if k in joined:
            if k == "保留意见" and "无保留意见" in joined and joined.count("保留意见") == joined.count("无保留意见"):
                continue
            return k
    return None
