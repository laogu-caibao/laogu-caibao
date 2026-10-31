#!/usr/bin/env python3
"""环境自检：Python 版本、依赖包、各免费数据源连通性。任何 agent 首次使用前先跑一次。

用法：python3 scripts/doctor.py        退出码 0=可用，1=有阻断项
"""
import importlib, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OK, BAD, WARN = "✅", "❌", "⚠️"
blocking = []


def line(flag, name, msg=""):
    print(f"{flag} {name}{('：' + msg) if msg else ''}")


def main():
    print("== 运行环境")
    v = sys.version_info
    if v < (3, 9):
        line(BAD, "Python", f"{v.major}.{v.minor}，需要 ≥3.9"); blocking.append("python")
    else:
        line(OK, "Python", f"{v.major}.{v.minor}.{v.micro}")
    for pkg, need, hint in (("pdfplumber", True, "pip install pdfplumber（解析公告 PDF 必需）"),
                            ("pymupdf", False, "pip install pymupdf（可选，PDF 定位快 20 倍）"),
                            ("pypdf", False, "pip install pypdf（可选，备用文本提取）")):
        try:
            m = importlib.import_module(pkg)
            line(OK, pkg, getattr(m, "__version__", getattr(m, "VersionBind", "")) or "已安装")
        except Exception:
            line(BAD if need else WARN, pkg, "未安装，" + hint)
            if need:
                blocking.append(pkg)

    print("\n== 数据源连通性（以贵州茅台 600519 试取）")
    from cbfx.sources import cninfo, eastmoney, sina, quote
    org = None
    checks = []

    def t_cninfo():
        nonlocal org
        org = cninfo.search("600519")
        reps = cninfo.list_reports(org, f"{time.localtime().tm_year - 1}-12-31") or cninfo.list_reports(org, f"{time.localtime().tm_year - 2}-12-31")
        return f"orgId={org['orgId']}，最近年报：{reps[0]['title'] if reps else '未找到'}"

    def t_em():
        ct, _ = eastmoney.detect_company_type(org)
        ds = eastmoney.dates(org, ct)
        return f"公司类型={ct}，最新报告期 {ds[0] if ds else '无'}"

    def t_sina():
        rows, meta = sina.statements(org, "is", n=4)
        return f"利润表 {len(rows)} 期，最新 {max(rows) if rows else '无'}"

    def t_quote():
        res, errs = quote.snapshot(org)
        if not res:
            raise RuntimeError("；".join(errs))
        return "；".join(f"{q.get('source')} 价格 {q.get('price')}" for q in res) + (f"（{len(errs)} 个源失败，不影响）" if errs else "")

    for name, fn, need in (("巨潮资讯（公告原文，标准答案）", t_cninfo, True),
                           ("东方财富 F10（结构化三表）", t_em, False),
                           ("新浪财经（结构化三表，第二来源）", t_sina, False),
                           ("行情（腾讯/东财）", t_quote, False)):
        try:
            line(OK, name, fn())
            checks.append(True)
        except Exception as e:
            line(BAD if need else WARN, name, str(e)[:160])
            checks.append(False)
            if need:
                blocking.append(name)
                break
    if len(checks) >= 3 and not checks[1] and not checks[2]:
        line(BAD, "结构化接口", "东财与新浪均不可用，只能做原文单源，不满足双源核对")
        blocking.append("structured")

    print()
    if blocking:
        print(f"{BAD} 有阻断项：{', '.join(blocking)}。先修复再运行 collect.py")
        return 1
    print(f"{OK} 环境可用。下一步：python3 scripts/collect.py <代码> --mode quick")
    return 0


if __name__ == "__main__":
    sys.exit(main())
