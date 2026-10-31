#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_report.py — 交付前校验 HTML 财务分析报告。

检查项：
  1. 内联 <script> 语法（抽出后交给 node --check）
  2. HTML 标签平衡（div/table/tr/td/section/span 等）
  3. 文档收尾结构（</body></html> 是否唯一且在末尾）
  4. ECharts 容器 id：getElementById 引用的 id 是否存在、是否重复
  5. ECharts 数据序列长度：列出所有 data:[...] 的元素个数，用于人工核对
     xAxis 类目数与各 series 长度是否一致（不一致会导致图形错位）
  6. CSS 变量引用：var(--x) 是否都已在 :root 定义

用法：
  python check_report.py 报告.html
  python check_report.py 报告.html --node C:/path/to/node.exe
退出码：0=通过（可含警告），1=存在必须修复的错误
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DEFAULT_NODE = r"C:\Users\Administrator\.workbuddy\binaries\node\versions\22.22.2-3\node.exe"
VOID = {"br", "hr", "img", "input", "meta", "link", "source", "col", "area", "base", "wbr"}


def find_node(user_node=None):
    for c in [user_node, DEFAULT_NODE, "node", "node.exe"]:
        if not c:
            continue
        try:
            r = subprocess.run([c, "--version"], capture_output=True, text=True, timeout=20)
            if r.returncode == 0:
                return c
        except Exception:  # noqa: BLE001
            continue
    return None


def extract_inline_scripts(html):
    out = []
    for m in re.finditer(r"<script(?![^>]*\ssrc=)[^>]*>(.*?)</script>", html, re.S | re.I):
        out.append(m.group(1))
    return out


def match_array(text, start):
    """从 start 处的 '[' 开始做括号匹配，返回数组内部文本"""
    depth = 0
    i = start
    in_s = None
    while i < len(text):
        ch = text[i]
        if in_s:
            if ch == "\\":
                i += 2
                continue
            if ch == in_s:
                in_s = None
        else:
            if ch in "'\"`":
                in_s = ch
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return text[start + 1:i]
        i += 1
    return None


def count_elements(inner):
    if inner is None:
        return None
    depth = 0
    n = 1
    has = False
    in_s = None
    for ch in inner:
        if in_s:
            if ch == in_s:
                in_s = None
            continue
        if ch in "'\"`":
            in_s = ch
        elif ch in "[({":
            depth += 1
        elif ch in "])}":
            depth -= 1
        elif ch == "," and depth == 0:
            n += 1
    for ch in inner.strip():
        if ch not in ", \t\r\n":
            has = True
            break
    return 0 if not has else n


def check_tags(html):
    errs = []
    for tag in ["div", "table", "tr", "td", "th", "thead", "tbody", "section", "span", "p", "ul", "li", "script", "style"]:
        if tag in VOID:
            continue
        opens = len(re.findall(r"<" + tag + r"(?=[\s>])", html, re.I))
        closes = len(re.findall(r"</" + tag + r"\s*>", html, re.I))
        if opens != closes:
            errs.append(f"标签不平衡 <{tag}>: 开 {opens} / 闭 {closes}")
    return errs


def check_tail(html):
    errs = []
    nb = len(re.findall(r"</body>", html, re.I))
    nh = len(re.findall(r"</html>", html, re.I))
    if nb != 1:
        errs.append(f"</body> 出现 {nb} 次（应为 1，分段写入易产生重复收尾）")
    if nh != 1:
        errs.append(f"</html> 出现 {nh} 次（应为 1）")
    tail = html[-200:].strip().lower()
    if not tail.endswith("</html>"):
        errs.append("文档末尾不是 </html>，可能在 </script> 之后残留了重复片段")
    return errs


def strip_js_comments(text):
    """去掉 JS 注释，避免注释里的示例 id 被当成真实引用。

    真实案例：骨架里写了一句注释 "check_report.py 依赖 getElementById('chartN')"，
    结果被判成 [ERR] 引用了不存在的容器 id。注释中的示例代码必须忽略。
    用等长空格替换以保持偏移（序列长度核对依赖位置）；用 (?<!:) 保护 https:// 这类 URL。
    """
    text = re.sub(r"/\*.*?\*/", lambda m: " " * len(m.group(0)), text, flags=re.S)
    text = re.sub(r"(?<!:)//[^\n]*", lambda m: " " * len(m.group(0)), text)
    return text


def check_chart_ids(html, js_text=""):
    errs, warns = [], []
    html_ids = re.findall(r"\sid\s*=\s*[\"']([^\"']+)[\"']", html)
    dup = {i for i in html_ids if html_ids.count(i) > 1}
    if dup:
        errs.append("HTML 中 id 重复（ECharts 只会挂载第一个）：" + ", ".join(sorted(dup)))
    refs = set()
    src = js_text if js_text.strip() else html
    for m in re.finditer(r"getElementById\(\s*[\"']([^\"']+)[\"']", src):
        refs.add(m.group(1))
    for m in re.finditer(r"querySelector\(\s*[\"']#([^\"']+)[\"']", src):
        refs.add(m.group(1))
    missing = sorted(r for r in refs if r not in html_ids)
    if missing:
        errs.append("JS 引用了不存在的容器 id：" + ", ".join(missing))
    elif refs:
        warns.append(f"图表容器 id 检查通过（{len(refs)} 个图表）")
    return errs, warns


def match_braces(text, start):
    """从 start 处的 '{' 做花括号匹配，返回内部文本；失败返回 None"""
    depth = 0
    i = start
    in_s = None
    while i < len(text):
        ch = text[i]
        if in_s:
            if ch == "\\":
                i += 2
                continue
            if ch == in_s:
                in_s = None
        else:
            if ch in "'\"`":
                in_s = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start + 1:i]
        i += 1
    return None


def arrays_after(text, pattern):
    """从 pattern 匹配位置之后的第一个 '[' 提取所有顶层数组长度"""
    res = []
    for m in re.finditer(pattern, text):
        inner = match_array(text, m.end() - 1)
        n = count_elements(inner)
        if n is not None:
            res.append(n)
    return res


def check_chart_series(js):
    """按图表逐项核对：xAxis 类目数 vs 各 series data 长度。
    只统计 series:[...] 块内的 data，避免把 legend.data 误当序列。"""
    problems, info = [], []
    marks = [(m.start(), m.group(1)) for m in re.finditer(r"getElementById\(\s*[\"']([^\"']+)[\"']", js)]
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(js)
        seg = js[pos:end]
        # xAxis 类目数（支持 data:[...] 与 data:VAR 两种写法）
        def data_len(scope_text, container):
            """在 container 片段内解析 data 长度；变量引用则回溯到 var 定义"""
            m = re.search(r"data\s*:\s*\[", container)
            if m:
                return count_elements(match_array(container, m.end() - 1))
            m2 = re.search(r"data\s*:\s*([A-Za-z_$][\w$]*)", container)
            if m2:
                mv = re.search(r"var\s+" + re.escape(m2.group(1)) + r"\s*=\s*\[", scope_text)
                if mv:
                    return count_elements(match_array(scope_text, mv.end() - 1))
            return None

        xlen = None
        mx = re.search(r"xAxis\s*:\s*\{", seg)
        if mx:
            inner = match_braces(seg, mx.end() - 1)
            if inner:
                xlen = data_len(js, inner)
        if xlen is None:
            mv = re.search(r"xAxis\s*:\s*([A-Za-z_$][\w$]*)", seg)
            if mv:
                vd = re.search(r"var\s+" + re.escape(mv.group(1)) + r"\s*=\s*\{", js)
                if vd:
                    inner = match_braces(js, vd.end() - 1)
                    if inner:
                        xlen = data_len(js, inner)
        # series 长度
        slens = []
        ms = re.search(r"series\s*:\s*\[", seg)
        if ms:
            inner = match_array(seg, ms.end() - 1)
            if inner:
                # 移除 markLine / markPoint / markArea 子块（用等长空格替换以保持偏移），
                # 它们内部的 data 是标注线而非数据序列。样式块（itemStyle 等）不含 data，不处理。
                for key in ("markLine", "markPoint", "markArea"):
                    for mk in re.finditer(key + r"\s*:\s*\{", inner):
                        blk = match_braces(inner, mk.end() - 1)
                        if blk is not None:
                            s0, s1 = mk.end() - 1, mk.end() + len(blk) + 1
                            inner = inner[:s0] + " " * (s1 - s0) + inner[s1:]
                for m in re.finditer(r"data\s*:\s*(\[|[A-Za-z_$][\w$]*)", inner):
                    if m.group(1) == "[":
                        n = count_elements(match_array(inner, m.end() - 1))
                    else:
                        mv = re.search(r"var\s+" + re.escape(m.group(1)) + r"\s*=\s*\[", js)
                        n = count_elements(match_array(js, mv.end() - 1)) if mv else None
                    if n is not None:
                        slens.append(n)
        if xlen is None or not slens:
            info.append(f"{name}: 未识别 xAxis/series（雷达图等特殊图表可忽略）")
            continue
        bad = [n for n in slens if n != xlen]
        if bad:
            problems.append(f"{name}: xAxis 类目 {xlen} 个，但 series 长度 {slens} 存在不一致")
        else:
            info.append(f"{name}: xAxis {xlen} × {len(slens)} 条序列，长度一致")
    return problems, info


def check_series_lengths(js):
    """列出 xAxis 类目数与 series data 长度，供人工核对"""
    lens = []
    for m in re.finditer(r"data\s*:\s*\[", js):
        inner = match_array(js, m.end() - 1)
        n = count_elements(inner)
        if n is not None:
            lens.append(n)
    from collections import Counter
    return Counter(lens)


def check_css_vars(html):
    defined = set(re.findall(r"(--[a-zA-Z0-9\-]+)\s*:", html))
    used = set(re.findall(r"var\((--[a-zA-Z0-9\-]+)\)", html))
    return sorted(used - defined)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--node", default=None)
    args = ap.parse_args()

    if not os.path.exists(args.path):
        print("文件不存在：" + args.path)
        sys.exit(1)
    with open(args.path, "r", encoding="utf-8", errors="ignore") as f:
        html = f.read()

    errors, warns = [], []
    print(f"=== 校验 {os.path.basename(args.path)} （{len(html)} 字符 / {html.count(chr(10))+1} 行）===")

    # 1. JS 语法
    scripts = extract_inline_scripts(html)
    node = find_node(args.node)
    if not node:
        warns.append("未找到 node，跳过 JS 语法校验")
    else:
        tmp = os.path.join(tempfile.gettempdir(), "_skill_check_inline.js")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n;\n".join(scripts))
        r = subprocess.run([node, "--check", tmp], capture_output=True, text=True, encoding="utf-8", errors="ignore")
        if r.returncode == 0:
            print(f"[OK] 内联 JS 语法（{len(scripts)} 段，node={os.path.basename(node)}）")
        else:
            errors.append("内联 JS 语法错误：\n" + (r.stderr or "")[:1500])

    # 2/3 标签与收尾
    for e in check_tags(html):
        errors.append(e)
    for e in check_tail(html):
        errors.append(e)

    # 4 图表 id（用剥掉注释的 JS，避免注释里的示例 id 误报）
    js_clean = strip_js_comments("\n".join(scripts))
    e4, w4 = check_chart_ids(html, js_clean)
    errors += e4
    warns += w4

    # 5 序列长度（按图表逐项核对）
    js_all = js_clean
    if "echarts" in html.lower():
        probs, infos = check_chart_series(js_all)
        for t in infos:
            print("[INFO] " + t)
        errors += probs
        cnt = check_series_lengths(js_all)
        print("[INFO] 全局 data 数组长度分布：" + ", ".join(f"{k}×{v}" for k, v in cnt.most_common(8)))

    # 6 CSS 变量
    miss = check_css_vars(html)
    if miss:
        errors.append("引用了未定义的 CSS 变量：" + ", ".join(miss))

    print("-" * 50)
    for w in warns:
        print("[WARN] " + w)
    if errors:
        for e in errors:
            print("[ERR ] " + e)
        print(f"\n结果：{len(errors)} 项必须修复")
        sys.exit(1)
    print("结果：通过（" + (f"{len(warns)} 项提示" if warns else "无问题") + "）")


if __name__ == "__main__":
    main()
