#!/usr/bin/env python3
"""Count a UTF-8 text file using this kit's explicit chapter-length convention."""
from __future__ import annotations
import argparse
from pathlib import Path


def count_chars(text: str) -> int:
    # Count Unicode code points except whitespace. Punctuation counts; this is
    # intentionally not claimed to match any platform's billing/editor count.
    return sum(not ch.isspace() for ch in text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path, help='UTF-8 plain-text chapter prose')
    parser.add_argument('--chapter-range', action='store_true', help='require 2500–4000 non-whitespace code points')
    args = parser.parse_args()
    try:
        text = args.file.read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError) as exc:
        parser.error(str(exc))
    count = count_chars(text)
    print(f'{args.file}: {count} 个Unicode非空白码点（含标点）')
    if args.chapter_range and not 2500 <= count <= 4000:
        print('不通过：每章目标为2500–4000。请先核实统计范围；禁止用重复/注水文本补数。')
        return 1
    if args.chapter_range:
        print('通过字数区间检查；这不代表内容质量或审计通过。')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
