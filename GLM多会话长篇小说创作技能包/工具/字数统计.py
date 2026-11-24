#!/usr/bin/env python3
"""Count chapter prose from UTF-8 text or inline text using the kit's code-point convention."""
from __future__ import annotations
import argparse
from pathlib import Path
import re


def prose_text(text: str) -> str:
    """Remove recognizable Markdown framing; preserve prose around inline comments."""
    text = text.lstrip('\ufeff')
    # Remove closed inline/block comments without discarding prose after a same-line close.
    # An unclosed comment is treated as extending to EOF, per HTML comment syntax.
    text = re.sub(r'<!--.*?(?:-->|\Z)', '', text, flags=re.S)
    lines = text.splitlines()
    if lines and lines[0].strip() == '---':
        for i in range(1, len(lines)):
            if lines[i].strip() == '---':
                lines = lines[i + 1:]
                break
    return '\n'.join(line for line in lines if not re.match(r'^#{1,6}\s+', line))


def count_chars(text: str) -> int:
    # Unicode code points except whitespace. Punctuation counts.
    return sum(not ch.isspace() for ch in text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', nargs='?', type=Path, help='UTF-8 chapter text file')
    parser.add_argument('--text', help='count this literal text instead of reading a file')
    parser.add_argument('--chapter-range', action='store_true', help='require 2500–4000 non-whitespace code points')
    parser.add_argument('--raw', action='store_true', help='count all file contents including Markdown headings/front matter/comments')
    args = parser.parse_args()
    if (args.file is None) == (args.text is None): parser.error('provide exactly one file path or --text')
    if args.raw and args.text is not None: parser.error('--raw applies only to a file')
    try:
        text = args.text if args.text is not None else args.file.read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError) as exc:
        parser.error(str(exc))
    if args.file is not None and not args.raw: text = prose_text(text)
    count = count_chars(text)
    label = str(args.file) if args.file is not None else '--text'
    print(f'{label}: {count} 个Unicode非空白码点（含标点）')
    if args.file is not None and not args.raw:
        print('计数模式：已去除YAML front matter、Markdown标题行和HTML注释；其他内容仍按纯正文输入契约处理。')
    if args.chapter_range and not 2500 <= count <= 4000:
        print('不通过：每章目标为2500–4000。请核实统计范围；禁止用重复/注水文本补数。')
        return 1
    if args.chapter_range: print('通过字数区间检查；这不代表内容质量或审计通过。')
    return 0

if __name__ == '__main__': raise SystemExit(main())
