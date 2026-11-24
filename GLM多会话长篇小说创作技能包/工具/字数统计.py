#!/usr/bin/env python3
"""Count chapter prose from UTF-8 text or inline text using the kit's code-point convention."""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import sys


def strip_html_comments(text: str) -> tuple[str, bool]:
    """Remove closed HTML comments; retain an unclosed comment-like tail and flag it."""
    chunks = []
    cursor = 0
    unclosed = False
    while True:
        start = text.find('<!--', cursor)
        if start < 0:
            chunks.append(text[cursor:])
            break
        chunks.append(text[cursor:start])
        end = text.find('-->', start + 4)
        if end < 0:
            # Do not silently discard the rest of a chapter on a malformed delimiter.
            chunks.append(text[start:])
            unclosed = True
            break
        cursor = end + 3
    return ''.join(chunks), unclosed


def prose_text_with_warnings(text: str) -> tuple[str, list[str]]:
    """Remove recognizable Markdown framing and return actionable input warnings."""
    text = text.lstrip('\ufeff')
    text, unclosed_comment = strip_html_comments(text)
    warnings = ['检测到未闭合HTML注释起始符；注释样式文本已保留，请核对输入后再使用计数'] if unclosed_comment else []
    lines = text.splitlines()
    if lines and lines[0].strip() == '---':
        for i in range(1, len(lines)):
            if lines[i].strip() == '---':
                lines = lines[i + 1:]
                break
    return '\n'.join(line for line in lines if not re.match(r'^#{1,6}\s+', line)), warnings


def prose_text(text: str) -> str:
    """Remove recognizable Markdown framing; preserve prose around inline comments."""
    return prose_text_with_warnings(text)[0]


def count_chars(text: str) -> int:
    # Unicode code points except whitespace. Punctuation counts.
    return sum(not ch.isspace() for ch in text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', nargs='?', type=Path, help='UTF-8 chapter text file')
    parser.add_argument('--text', help='count literal text with the same prose normalization used for files')
    parser.add_argument('--chapter-range', action='store_true', help='require 2500–4000 non-whitespace code points')
    parser.add_argument('--raw', action='store_true', help='count all file contents including Markdown headings/front matter/comments')
    args = parser.parse_args()
    if (args.file is None) == (args.text is None): parser.error('provide exactly one file path or --text')
    if args.raw and args.text is not None: parser.error('--raw applies only to a file')
    try:
        text = args.text if args.text is not None else args.file.read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError) as exc:
        parser.error(str(exc))
    if not args.raw:
        text, warnings = prose_text_with_warnings(text)
        if warnings:
            for warning in warnings: print(f'警告：{warning}', file=sys.stderr)
            print('不输出可用于章节门禁的计数；请先修复或确认输入。', file=sys.stderr)
            return 2
    count = count_chars(text)
    label = str(args.file) if args.file is not None else '--text'
    print(f'{label}: {count} 个Unicode非空白码点（含标点）')
    if args.raw:
        print('计数模式：原始全文件文本；不剥离YAML front matter、Markdown标题或HTML注释。')
    else:
        print('计数模式：正文规范化；已去除YAML front matter、Markdown标题行和闭合HTML注释。与manifest全文件码点指标不同。')
    if args.chapter_range and not 2500 <= count <= 4000:
        print('不通过：每章目标为2500–4000。请核实统计范围；禁止用重复/注水文本补数。')
        return 1
    if args.chapter_range: print('通过字数区间检查；这不代表内容质量或审计通过。')
    return 0

if __name__ == '__main__': raise SystemExit(main())
