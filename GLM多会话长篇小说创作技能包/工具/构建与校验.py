#!/usr/bin/env python3
"""Build and verify the kit ZIP and its SHA-256 manifest (Python 3.9+, stdlib only)."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ZIP_PATH = ROOT.parent / f'{ROOT.name}.zip'
VERSION = '1.1.0'
BUILD_DATE = '2026-11-22'  # Fixed for deterministic rebuilds of this release.
EXTERNAL = ['用户使用指导/使用教程.md', '用户使用指导/导入检查单.md', '用户使用指导/故障排查表.md']
FIRST = ['01_自定义指令.md', '02_长期记忆.md']

def count_chars(text: str) -> int:
    return sum(not ch.isspace() for ch in text)

def included_file(path: Path) -> bool:
    return path.is_file() and path.name != 'manifest.json' and '__pycache__' not in path.parts and path.suffix != '.pyc' and path.name != '.DS_Store'

def files_in_order() -> list[Path]:
    # Required bootstrap files, then each self-contained author bundle in order,
    # then management docs/tools. Files only; no ZIP directory entries.
    files = [ROOT / p for p in FIRST]
    for i in range(1, 11):
        folder = ROOT / f'作者{i:02d}'
        files.extend(sorted(p for p in folder.rglob('*') if included_file(p)))
    rest = sorted(p for p in ROOT.rglob('*') if included_file(p) and p not in files)
    files.extend(rest)
    return files

def record(path: Path) -> dict:
    raw = path.read_bytes()
    text = raw.decode('utf-8')
    rel = path.relative_to(ROOT).as_posix()
    return {'path': rel, 'version': VERSION, 'encoding': 'UTF-8', 'bytes': len(raw),
            'unicode_non_whitespace_characters': count_chars(text), 'sha256': hashlib.sha256(raw).hexdigest()}

def build() -> None:
    paths = files_in_order()
    entries = [record(p) for p in paths]
    manifest = {'package': ROOT.name, 'version': VERSION, 'generated_date_utc': BUILD_DATE,
        'encoding': 'UTF-8 without BOM',
        'character_count_method': 'Unicode non-whitespace code points; punctuation counts; see 工具/字数统计.py',
        'inventory_excludes': 'manifest.json itself (self-referential hash excluded)',
        'file_count_excluding_manifest': len(entries),
        'total_unicode_non_whitespace_characters_excluding_manifest': sum(e['unicode_non_whitespace_characters'] for e in entries),
        'root_files': {p: next(e['unicode_non_whitespace_characters'] for e in entries if e['path'] == p) for p in FIRST},
        'external_guides_not_in_zip': EXTERNAL, 'files': entries}
    (ROOT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    def add_file(zf: zipfile.ZipFile, path: Path, arcname: str) -> None:
        # Freeze ZIP timestamps and permissions so rebuilding the same release
        # from unchanged sources yields identical archive bytes.
        info = zipfile.ZipInfo(arcname, date_time=(2026, 11, 22, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        zf.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    with zipfile.ZipFile(ZIP_PATH, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in paths:
            add_file(zf, p, p.relative_to(ROOT).as_posix())
        add_file(zf, ROOT / 'manifest.json', 'manifest.json')
    print(f'Built {ZIP_PATH.name}: {len(entries)} files + manifest; {manifest["total_unicode_non_whitespace_characters_excluding_manifest"]:,} non-whitespace code points')

def verify() -> bool:
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    expected = {e['path']: e for e in manifest['files']}
    errors = []
    if manifest.get('version') != '1.1.0': errors.append('manifest version is not 1.1.0')
    for i in range(1, 11):
        required = [f'作者{i:02d}/README.md', f'作者{i:02d}/会话指令.md', f'作者{i:02d}/输入输出契约.md', f'作者{i:02d}/规范/执行规范.md', f'作者{i:02d}/自检清单.md', f'作者{i:02d}/变更记录.md']
        for rel in required:
            if not (ROOT / rel).is_file(): errors.append(f'required author file missing: {rel}')
    for rel in FIRST:
        if rel in expected and expected[rel]['unicode_non_whitespace_characters'] > 2000:
            errors.append(f'{rel}: exceeds 2000-code-point project limit')
    actual_paths = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if included_file(p)}
    if actual_paths != set(expected):
        errors.append(f'manifest/source inventory mismatch: missing={sorted(set(expected)-actual_paths)}, extra={sorted(actual_paths-set(expected))}')
    for rel, item in expected.items():
        p = ROOT / rel
        if not p.exists():
            continue
        raw = p.read_bytes()
        try: text = raw.decode('utf-8')
        except UnicodeError: errors.append(f'{rel}: invalid UTF-8'); continue
        if raw.startswith(b'\xef\xbb\xbf'): errors.append(f'{rel}: UTF-8 BOM')
        if len(raw) != item['bytes'] or hashlib.sha256(raw).hexdigest() != item['sha256'] or count_chars(text) != item['unicode_non_whitespace_characters']:
            errors.append(f'{rel}: manifest metadata mismatch')
    if not ZIP_PATH.exists(): errors.append(f'ZIP missing: {ZIP_PATH}')
    else:
        with zipfile.ZipFile(ZIP_PATH) as zf:
            bad = zf.testzip()
            if bad: errors.append(f'CRC failure: {bad}')
            names = zf.namelist()
            if names[:2] != FIRST: errors.append(f'ZIP must begin with {FIRST}')
            if len(names) < 12 or not names[2].startswith('作者01/'): errors.append('author folders must follow the first two root files')
            author_groups = [name.split('/', 1)[0] for name in names if name.startswith('作者') and '/' in name]
            unique_groups = list(dict.fromkeys(author_groups))
            if unique_groups != [f'作者{i:02d}' for i in range(1, 11)]: errors.append('author folders must be grouped in 作者01–作者10 order')
            if names[-1] != 'manifest.json': errors.append('manifest.json must be last')
            if set(names) != set(expected) | {'manifest.json'}: errors.append('ZIP/source inventory mismatch')
            if any(name in names for name in EXTERNAL): errors.append('external user guides found inside ZIP')
            for rel, item in expected.items():
                if rel in names and hashlib.sha256(zf.read(rel)).hexdigest() != item['sha256']:
                    errors.append(f'ZIP hash mismatch: {rel}')
    if errors:
        print('\n'.join('FAIL: ' + e for e in errors), file=sys.stderr)
        return False
    print(f'PASS: {len(expected)} source files; ZIP CRC/inventory/order/hashes and manifest metadata verified.')
    return True

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'verify'])
    action = parser.parse_args().action
    if action == 'build': build()
    return 0 if action == 'build' or verify() else 1
if __name__ == '__main__': raise SystemExit(main())
