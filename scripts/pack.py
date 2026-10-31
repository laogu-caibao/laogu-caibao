#!/usr/bin/env python3
"""打包 skill 分发包：仓库带 out/ 产物，发包时剥掉。

用法：
    python3 scripts/pack.py                # 打包到 dist/lhg-cbfx-v<version>.zip
    python3 scripts/pack.py --out /tmp/x.zip
    python3 scripts/pack.py --list         # 只列出会进包/被剥掉的文件，不写盘

规则：
- 只从根目录的白名单目录进包（SKILL.md / scripts / references / libs / examples / tests）
- out/ 是内容产物，进 git 但绝不进包；.git/.workbuddy/.zcode/__pycache__/dist 同理
- 打包后自检：SKILL.md 必须在 zip 根目录，且包内不得出现 out/
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 进包的顶层条目（相对仓库根）
INCLUDE_TOP = ["SKILL.md", "scripts", "references", "libs", "examples", "tests", "台账.md"]

# 任何层级命中即排除
EXCLUDE_DIRS = {"out", ".git", ".workbuddy", ".zcode", "dist", "__pycache__", ".idea", ".vscode"}
EXCLUDE_FILES = {".DS_Store", ".gitignore"}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".swp"}


def read_version() -> str:
    p = os.path.join(ROOT, "SKILL.md")
    with open(p, encoding="utf-8") as f:
        head = f.read(4000)
    m = re.search(r"^version:\s*(\S+)\s*$", head, re.M)
    return m.group(1) if m else "0.0.0"


def read_name() -> str:
    p = os.path.join(ROOT, "SKILL.md")
    with open(p, encoding="utf-8") as f:
        head = f.read(4000)
    m = re.search(r"^name:\s*(\S+)\s*$", head, re.M)
    return m.group(1) if m else "skill"


def walk():
    """产出 (绝对路径, 包内相对路径)。"""
    for top in INCLUDE_TOP:
        ap = os.path.join(ROOT, top)
        if not os.path.exists(ap):
            continue
        if os.path.isfile(ap):
            yield ap, top
            continue
        for dirpath, dirnames, filenames in os.walk(ap):
            dirnames[:] = sorted(
                d for d in dirnames if d not in EXCLUDE_DIRS and not d.startswith(".")
            )
            for fn in sorted(filenames):
                if fn in EXCLUDE_FILES or os.path.splitext(fn)[1] in EXCLUDE_SUFFIX:
                    continue
                full = os.path.join(dirpath, fn)
                yield full, os.path.relpath(full, ROOT)


def stripped():
    """被剥掉的东西，用于 --list 说明和自检。"""
    out = []
    for name in sorted(os.listdir(ROOT)):
        if name in EXCLUDE_DIRS or name in EXCLUDE_FILES or name.startswith("."):
            p = os.path.join(ROOT, name)
            if os.path.isdir(p):
                n = sum(len(fs) for _, _, fs in os.walk(p))
                out.append((name + "/", n))
            elif os.path.isfile(p):
                out.append((name, 1))
    return out


def main():
    ap = argparse.ArgumentParser(description="打包 lhg-cbfx skill 分发包")
    ap.add_argument("--out", help="输出 zip 路径，默认 dist/<name>-v<version>.zip")
    ap.add_argument("--list", action="store_true", help="只列清单，不写盘")
    args = ap.parse_args()

    name, ver = read_name(), read_version()
    items = list(walk())
    if not items:
        sys.exit("[ERR] 没有任何文件可打包，检查 INCLUDE_TOP")

    if args.list:
        print(f"进包 {len(items)} 个文件：")
        for _, rel in items:
            print("  +", rel)
        st = stripped()
        if st:
            print(f"\n剥离 {len(st)} 项（不进包）：")
            for n, c in st:
                print(f"  - {n}  ({c} 个文件)")
        return

    out = args.out or os.path.join(ROOT, "dist", f"{name}-v{ver}.zip")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for full, rel in items:
            z.write(full, rel)

    # ---- 自检：根有 SKILL.md，包内无 out/ ----
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    problems = []
    if "SKILL.md" not in names:
        problems.append("包根目录缺 SKILL.md")
    leaked = [n for n in names if n.startswith("out/") or "/out/" in n]
    if leaked:
        problems.append(f"包内混入 out/ 产物 {len(leaked)} 个：{leaked[:3]}")
    if any(n.startswith(("__MACOSX/", ".")) for n in names):
        problems.append("包内混入隐藏文件")

    size = os.path.getsize(out)
    print(f"打包完成：{out}")
    print(f"  文件 {len(names)} 个，{size / 1024:.0f} KB（原始 {sum(os.path.getsize(f) for f, _ in items) / 1024:.0f} KB）")
    print(f"  版本 {name} v{ver}")
    st = stripped()
    if st:
        print("  已剥离：" + "、".join(n for n, _ in st))

    if problems:
        print("\n[FAIL] 自检不通过：")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("  自检通过：SKILL.md 在根、无 out/ 产物")


if __name__ == "__main__":
    main()
