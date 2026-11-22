#!/usr/bin/env python3
"""Diagnostic for exact repeated paragraphs and near-duplicate n-gram shingles (not a literary quality score)."""
from __future__ import annotations
import argparse
from collections import defaultdict
from pathlib import Path
import re
import sys


def shingles(text: str, n: int) -> set[str]:
    compact = ''.join(ch for ch in text if not ch.isspace())
    if len(compact) < n: return {compact} if compact else set()
    return {compact[i:i+n] for i in range(len(compact) - n + 1)}


def inspect(text: str, n: int = 8, threshold: float = 0.8) -> tuple[list[tuple[int, int, float]], list[tuple[int, int]]]:
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    exact: dict[str, list[int]] = defaultdict(list)
    for i, paragraph in enumerate(paragraphs, 1): exact[''.join(paragraph.split())].append(i)
    exact_pairs = [(indices[a], indices[b]) for indices in exact.values() if len(indices) > 1 for a in range(len(indices)) for b in range(a+1, len(indices))]
    near: list[tuple[int, int, float]] = []
    sets = [shingles(p, n) for p in paragraphs]
    for i in range(len(sets)):
        for j in range(i+1, len(sets)):
            union = sets[i] | sets[j]
            score = len(sets[i] & sets[j]) / len(union) if union else 1.0
            if score >= threshold:
                near.append((i+1, j+1, score))
    return near, exact_pairs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('chapter', type=Path)
    ap.add_argument('--ngram', type=int, default=8)
    ap.add_argument('--threshold', type=float, default=0.8, help='Jaccard threshold; diagnostic only')
    args = ap.parse_args()
    if args.ngram < 2 or not 0 < args.threshold <= 1:
        print('FAIL: ngram must be >=2 and threshold must be in (0,1]', file=sys.stderr); return 2
    try: text = args.chapter.read_text(encoding='utf-8')
    except OSError as exc: print(f'FAIL: {exc}', file=sys.stderr); return 2
    near, exact = inspect(text, args.ngram, args.threshold)
    print(f'paragraphs_checked; exact_duplicate_pairs={len(exact)}; near_duplicate_pairs={len(near)}; ngram={args.ngram}; threshold={args.threshold}')
    for a, b in exact: print(f'EXACT paragraph {a} == {b}')
    for a, b, score in near: print(f'NEAR paragraph {a} / {b} Jaccard={score:.3f}')
    print('This diagnostic is not a semantic padding detector and does not establish plagiarism or AI authorship.')
    return 1 if exact or near else 0

if __name__ == '__main__': raise SystemExit(main())
