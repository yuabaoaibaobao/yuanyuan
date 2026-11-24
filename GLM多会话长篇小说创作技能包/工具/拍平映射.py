#!/usr/bin/env python3
"""Generate or check the platform-flattened filename mapping (Python 3.9+, stdlib only).

Implements the flattening convention from 部署与运行手册.md: when the platform file
area only supports flat names, files are saved as ``作者NN__子目录__原文件名`` style
names. This tool derives the whole mapping from the current package tree so users
never hand-transcribe it, and can later verify a saved list still matches the tree.

The generated list is a user-workspace artifact: by default it must be written
OUTSIDE the package directory, and it never replaces the package's own structure.
"""
from __future__ import annotations
import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIX_OVERRIDES = {'项目运行模板': '运行模板'}
ROOT_FILE_PREFIX = '根'


def relative_parts(path: Path) -> tuple[str, ...]:
    return path.relative_to(ROOT).parts


def flat_name(rel: tuple[str, ...]) -> str:
    parts = [PREFIX_OVERRIDES.get(p, p) for p in rel]
    if len(parts) == 1:
        return f'{ROOT_FILE_PREFIX}__{parts[0]}'
    return '__'.join(parts)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(65536), b''):
            digest.update(block)
    return digest.hexdigest()


def inventory() -> dict[str, Path]:
    files: dict[tuple[str, ...], Path] = {}
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file():
            continue
        rel = relative_parts(path)
        if any(part in {'.git', '__pycache__'} for part in rel):
            continue
        files[rel] = path
    names: dict[str, tuple[str, ...]] = {}
    for rel in files:
        name = flat_name(rel)
        if name in names:
            raise SystemExit(f'FAIL: 拍平名冲突：{name} 同时对应 {names[name]} 与 {rel}')
        names[name] = rel
    return {flat_name(rel): files[rel] for rel in files}


def generate(output: Path, overwrite: bool, allow_inside: bool) -> int:
    resolved = output.resolve()
    if not allow_inside and resolved.is_relative_to(ROOT.resolve()):
        print('FAIL: 输出路径位于技能包目录内部；清单属于项目工作区文件。'
              '请输出到包外，或显式使用 --allow-inside。', file=sys.stderr)
        return 1
    if resolved.exists() and not overwrite:
        print(f'FAIL: {output} 已存在；确认覆盖请加 --overwrite。', file=sys.stderr)
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    entries = inventory()
    lines = [
        '# 拍平映射清单（自动生成）',
        '',
        f'> 由`工具/拍平映射.py`依据`部署与运行手册.md`拍平约定从包目录树生成；'
        f'生成于技能包目录{ROOT.name}。不要手改本文件；包升级后重新生成并复核。',
        '> 用途：平台文件区仅支持平面文件名时，按"建议拍平文件名"保存；'
        '并在`项目状态索引.md`的活跃文件登记表中引用本清单，不得凭标题猜来源。',
        '',
        '| 逻辑相对路径 | 建议拍平文件名 | 字节 | SHA-256 |',
        '|---|---|---:|---|',
    ]
    for name in sorted(entries):
        path = entries[name]
        lines.append(f'| {"/".join(relative_parts(path))} | {name} '
                     f'| {path.stat().st_size} | {sha256_of(path)} |')
    lines.append('')
    output.write_text('\n'.join(lines), encoding='utf-8')
    print(f'OK: 写出 {len(entries)} 条映射到 {output}')
    print('提醒：清单是生成快照；包升级或本地改动后请重新生成并 --check 校验。')
    return 0


def check(list_file: Path) -> int:
    entries = inventory()
    text = list_file.read_text(encoding='utf-8')
    ok = True
    seen: set[str] = set()
    for line in text.splitlines():
        if not line.startswith('| ') or line.startswith('| 逻辑'):
            continue
        cells = [cell.strip() for cell in line.strip('|').split('|')]
        if len(cells) < 4:
            continue
        logical, flat, size, digest = cells[0], cells[1], cells[2], cells[3]
        seen.add(flat)
        path = entries.get(flat)
        if path is None:
            print(f'FAIL: 清单含未知拍平名 {flat}（逻辑路径 {logical}）')
            ok = False
            continue
        rel = '/'.join(relative_parts(path))
        if rel != logical:
            print(f'FAIL: {flat} 逻辑路径不一致：清单 {logical} vs 现树 {rel}')
            ok = False
        if size != str(path.stat().st_size) or digest != sha256_of(path):
            print(f'FAIL: {flat} 内容与清单不符（包已升级或文件被改动）；请重新生成')
            ok = False
    missing = sorted(set(entries) - seen)
    if missing:
        print('FAIL: 现树存在清单未登记的文件（清单过期）：')
        for name in missing[:20]:
            print(f'  {name}')
        if len(missing) > 20:
            print(f'  ……共 {len(missing)} 条')
        ok = False
    if ok:
        print(f'OK: 清单与现树一致，共 {len(entries)} 条映射')
        return 0
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    default_out = ROOT.parent / '项目工作区' / '拍平映射清单.md'
    sub = parser.add_subparsers(dest='action', required=True)
    gen = sub.add_parser('generate', help='生成拍平映射清单（默认输出到包外项目工作区）')
    gen.add_argument('--output', type=Path, default=default_out)
    gen.add_argument('--overwrite', action='store_true')
    gen.add_argument('--allow-inside', action='store_true',
                     help='显式允许写入包内（不推荐；清单不进运行ZIP）')
    chk = sub.add_parser('check', help='校验既有清单与当前包目录树一致')
    chk.add_argument('list_file', type=Path)
    args = parser.parse_args()
    if args.action == 'generate':
        return generate(args.output, args.overwrite, args.allow_inside)
    return check(args.list_file)


if __name__ == '__main__':
    raise SystemExit(main())
