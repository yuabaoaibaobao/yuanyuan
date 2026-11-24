#!/usr/bin/env python3
"""Check rolling-summary structure and chapter coverage; semantic accuracy remains human-reviewed."""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

REQUIRED_LABELS = ('项目/摘要版本/生效时间', '覆盖章号闭区间', '相关定稿版本/哈希清单', '最近校验者/校验报告版本', '## 窗口共识', '## 更新与完整性')

def parse_range(value: str) -> set[int]:
    if '-' in value:
        a, b = map(int, value.split('-', 1))
        if a < 1 or b < a: raise ValueError('chapter range must be positive and ascending')
        return set(range(a, b + 1))
    return {int(x) for x in value.split(',') if x.strip()}

def validate(text: str, expected: set[int] | None = None) -> list[str]:
    errors = [f'missing required summary field/section: {label}' for label in REQUIRED_LABELS if label not in text]
    rows: dict[int, tuple[str, ...]] = {}
    for line in text.splitlines():
        if not line.lstrip().startswith('|'): continue
        cells = tuple(cell.strip() for cell in line.strip().strip('|').split('|'))
        if len(cells) < 7 or not re.match(r'^\d{1,4}\s*/', cells[0]): continue
        chapter = int(re.match(r'^(\d+)', cells[0]).group(1))
        if chapter in rows: errors.append(f'duplicate summary row for chapter {chapter}')
        rows[chapter] = cells
        if not cells[1] or not cells[2] or not cells[3] or not cells[4] or not cells[5] or not cells[6]:
            errors.append(f'chapter {chapter}: summary row has an empty required cell')
    if expected is not None:
        missing = expected - rows.keys()
        extra = rows.keys() - expected
        if missing: errors.append('missing chapter rows: ' + ', '.join(map(str, sorted(missing))))
        if extra: errors.append('unexpected chapter rows: ' + ', '.join(map(str, sorted(extra))))
    return errors

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('summary', type=Path)
    ap.add_argument('--chapters', help='expected coverage, e.g. 1-15 or 1,3,5')
    args = ap.parse_args()
    try:
        text = args.summary.read_text(encoding='utf-8')
        expected = parse_range(args.chapters) if args.chapters else None
    except (OSError, ValueError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr); return 1
    errors = validate(text, expected)
    if errors:
        for error in errors: print('FAIL: ' + error, file=sys.stderr)
        return 1
    print('PASS: summary structure and requested chapter coverage verified; semantic accuracy is not established.')
    return 0
if __name__ == '__main__': raise SystemExit(main())
