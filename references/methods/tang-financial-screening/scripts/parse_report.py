#!/usr/bin/env python3
"""
财报PDF解析脚本
用法: python3 parse_report.py <pdf_path> [--keyword <keyword>] [--output <output_path>]
功能: 提取PDF全文文本，支持按关键词搜索，结果保存为txt文件
"""

import sys
import os
import argparse

try:
    import pdfplumber
except ImportError:
    print("ERROR: 请先安装 pdfplumber: pip install pdfplumber")
    sys.exit(1)


def extract_text(pdf_path: str) -> str:
    """提取PDF全部页面文本"""
    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        print(f"PDF总页数: {total_pages}")
        
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                full_text += f"\n{'='*60}\n第{i+1}页 / 共{total_pages}页\n{'='*60}\n"
                full_text += text + "\n"
                
    return full_text


def search_keyword(full_text: str, keywords: list[str]) -> dict[str, list[str]]:
    """按关键词搜索，返回匹配行及其上下文"""
    results = {}
    lines = full_text.split("\n")
    
    for keyword in keywords:
        results[keyword] = []
        for i, line in enumerate(lines):
            if keyword in line:
                start = max(0, i - 3)
                end = min(len(lines), i + 4)
                context = lines[start:end]
                results[keyword].append({
                    "page_line": f"第{i+1}行",
                    "match": line.strip(),
                    "context": [l.strip() for l in context]
                })
        print(f"关键词 '{keyword}': 找到 {len(results[keyword])} 处匹配")
    
    return results


def extract_tables(pdf_path: str) -> list[dict]:
    """提取PDF中的表格"""
    tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            page_tables = page.extract_tables()
            if page_tables:
                for j, table in enumerate(page_tables):
                    tables.append({
                        "page": i + 1,
                        "index": j + 1,
                        "rows": len(table),
                        "cols": len(table[0]) if table else 0,
                        "data": table
                    })
    print(f"提取到 {len(tables)} 个表格")
    return tables


def main():
    parser = argparse.ArgumentParser(description="财报PDF解析工具")
    parser.add_argument("pdf_path", help="PDF文件路径")
    parser.add_argument("--keyword", "-k", nargs="+", help="搜索关键词（可多个）")
    parser.add_argument("--output", "-o", help="输出文件路径（默认与PDF同名.txt）")
    parser.add_argument("--tables", "-t", action="store_true", help="同时提取表格")
    parser.add_argument("--pages", "-p", help="只提取指定页面（如 1-5,8,10-12）")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.pdf_path):
        print(f"ERROR: 文件不存在 {args.pdf_path}")
        sys.exit(1)
    
    # 确定输出路径
    if args.output:
        output_path = args.output
    else:
        base = os.path.splitext(args.pdf_path)[0]
        output_path = base + "_extracted.txt"
    
    # 提取文本
    print(f"正在解析: {args.pdf_path}")
    full_text = extract_text(args.pdf_path)
    
    # 页面过滤
    if args.pages:
        page_ranges = parse_page_ranges(args.pages)
        filtered_lines = []
        in_range = False
        for line in full_text.split("\n"):
            if "第" in line and "/ 共" in line and "页" in line:
                page_num = extract_page_num(line)
                if page_num in page_ranges:
                    in_range = True
                else:
                    in_range = False
            if in_range:
                filtered_lines.append(line)
        full_text = "\n".join(filtered_lines)
    
    # 关键词搜索
    if args.keyword:
        print(f"\n--- 关键词搜索 ---")
        results = search_keyword(full_text, args.keyword)
        for kw, matches in results.items():
            if matches:
                print(f"\n[{kw}] ({len(matches)} 处)")
                for m in matches[:10]:  # 最多显示10处
                    print(f"  >>> {m['match'][:120]}")
    
    # 表格提取
    if args.tables:
        print(f"\n--- 表格提取 ---")
        tables = extract_tables(args.pdf_path)
        for t in tables:
            print(f"  表格: 第{t['page']}页 表{t['index']} ({t['rows']}行 × {t['cols']}列)")
    
    # 保存结果
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_text)
    
    print(f"\n文本已保存: {output_path} ({os.path.getsize(output_path)/1024:.1f} KB)")


def parse_page_ranges(page_str: str) -> set[int]:
    """解析页面范围字符串，如 '1-5,8,10-12' -> {1,2,3,4,5,8,10,11,12}"""
    pages = set()
    for part in page_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-")
            pages.update(range(int(start), int(end) + 1))
        else:
            pages.add(int(part))
    return pages


def extract_page_num(line: str) -> int | None:
    """从页码行中提取页码数字"""
    import re
    match = re.search(r"第(\d+)页", line)
    return int(match.group(1)) if match else None


if __name__ == "__main__":
    main()
