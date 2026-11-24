#!/usr/bin/env python3
"""Build and verify the kit package (Python 3.9+, stdlib only).

The command-line builder requires explicit output paths and never overwrites an
existing file unless --overwrite is supplied. `verify` requires an archive unless
source-only verification is explicitly selected with --source-only.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
RELEASE_FILE = ROOT / 'release.json'
RELEASE = json.loads(RELEASE_FILE.read_text(encoding='utf-8'))
VERSION = RELEASE['version']
BUILD_DATE = RELEASE['build_date_utc']
try:
    PACKAGE_NAME = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8')).get('package', ROOT.name)
except (OSError, json.JSONDecodeError):
    PACKAGE_NAME = ROOT.name
ZIP_PATH = ROOT.parent / f'{PACKAGE_NAME}.zip'  # convenience for local regression tests only
EXTERNAL = ['用户使用指导/使用教程.md', '用户使用指导/导入检查单.md', '用户使用指导/故障排查表.md']
FIRST = ['01_自定义指令.md', '02_长期记忆.md']
WORKSPACE_DIRS = {'项目工作区'}
WORKSPACE_FILES = {'项目状态索引.json'}


def count_chars(text: str) -> int:
    return sum(not ch.isspace() for ch in text)


def _current_doc_version_errors(text: str, current_version: str) -> list[str]:
    """Current README/P6 may cite only one package release version, not old/new mixtures."""
    versions = set(re.findall(r'(?<![\w.])\d+\.\d+\.\d+(?![\w.])', text))
    if current_version not in versions:
        return [f'does not mention release version {current_version}']
    stale = sorted(versions - {current_version})
    return [f'contains mixed package release versions: {", ".join(stale)}'] if stale else []


def _exact_index_mentions(text: str, name: str) -> int:
    """Count filename tokens, not substrings embedded in names such as README.md.bak."""
    pattern = rf'(?<![\w.-]){re.escape(name)}(?![\w.-])'
    return len(re.findall(pattern, text))


def is_workspace_path(path: Path) -> bool:
    return any(part in WORKSPACE_DIRS for part in path.parts) or path.name in WORKSPACE_FILES


def included_file(path: Path) -> bool:
    canonical_archive = path.name == f'{PACKAGE_NAME}.zip'
    return (path.is_file() and path.name != 'manifest.json' and not canonical_archive and not is_workspace_path(path)
            and '__pycache__' not in path.parts and path.suffix not in {'.pyc', '.pyo'}
            and path.name != '.DS_Store')


def files_in_order() -> list[Path]:
    # First two bootstrap files, then author01-10 at ZIP root, then other kit docs/tools.
    files = [ROOT / p for p in FIRST]
    for i in range(1, 11):
        folder = ROOT / f'作者{i:02d}'
        files.extend(sorted(p for p in folder.rglob('*') if included_file(p)))
    files.extend(sorted(p for p in ROOT.rglob('*') if included_file(p) and p not in files))
    return files


def record(path: Path) -> dict:
    raw = path.read_bytes()
    text = raw.decode('utf-8')
    rel = path.relative_to(ROOT).as_posix()
    return {'path': rel, 'version': VERSION, 'encoding': 'UTF-8', 'bytes': len(raw),
            'unicode_non_whitespace_file_code_points': count_chars(text), 'sha256': hashlib.sha256(raw).hexdigest()}


def _write_manifest(manifest_path: Path, manifest: dict, overwrite: bool) -> None:
    if manifest_path.exists() and not overwrite:
        raise FileExistsError(f'manifest already exists (pass overwrite=True explicitly): {manifest_path}')
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def build(zip_path: Path, manifest_path: Path, overwrite: bool = False) -> None:
    if zip_path.exists() and not overwrite:
        raise FileExistsError(f'ZIP already exists (pass overwrite=True explicitly): {zip_path}')
    if manifest_path.exists() and not overwrite:
        raise FileExistsError(f'manifest already exists (pass overwrite=True explicitly): {manifest_path}')
    paths = files_in_order()
    entries = [record(p) for p in paths]
    manifest = {'package': PACKAGE_NAME, 'version': VERSION, 'generated_date_utc': BUILD_DATE,
        'encoding': 'UTF-8 without BOM',
        'file_code_point_count_method': 'Full UTF-8 file text; Unicode non-whitespace code points; punctuation and Markdown framing count. Not chapter prose count.',
        'inventory_excludes': 'manifest.json itself (self-referential hash excluded); project workspace paths; canonical package ZIP if stored inside source folder',
        'file_count_excluding_manifest': len(entries),
        'total_unicode_non_whitespace_file_code_points_excluding_manifest': sum(e['unicode_non_whitespace_file_code_points'] for e in entries),
        'root_files': {p: next(e['unicode_non_whitespace_file_code_points'] for e in entries if e['path'] == p) for p in FIRST},
        'external_guides_not_in_zip': EXTERNAL, 'files': entries}
    _write_manifest(manifest_path, manifest, overwrite)

    def add_file(zf: zipfile.ZipFile, path: Path, arcname: str) -> None:
        info = zipfile.ZipInfo(arcname, date_time=(2026, 11, 22, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        zf.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in paths:
            add_file(zf, p, p.relative_to(ROOT).as_posix())
        add_file(zf, manifest_path, 'manifest.json')
    print(f'Built {zip_path}: {len(entries)} source files + manifest; '
          f'{manifest["total_unicode_non_whitespace_file_code_points_excluding_manifest"]:,} non-whitespace code points')


def _resolve_zips(explicit: Optional[Path], package_name: str) -> list[Path]:
    """Resolve an explicit archive or all canonical ZIPs inside/beside extracted source."""
    if explicit is not None:
        return [explicit]
    if not package_name or Path(package_name).name != package_name:
        return []
    candidates = [ROOT / f'{package_name}.zip', ROOT.parent / f'{package_name}.zip']
    return list(dict.fromkeys(p for p in candidates if p.is_file()))


def verify(zip_path: Optional[Path] = None, manifest_path: Path = ROOT / 'manifest.json', source_only: bool = False) -> bool:
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        print(f'FAIL: cannot read manifest: {exc}', file=sys.stderr)
        return False
    expected = {e['path']: e for e in manifest['files']}
    errors = []
    release = json.loads(RELEASE_FILE.read_text(encoding='utf-8'))
    if manifest.get('version') != release['version']: errors.append('manifest version differs from release.json')
    if manifest.get('generated_date_utc') != release['build_date_utc']: errors.append('manifest build date differs from release.json')
    if manifest.get('version') != VERSION: errors.append('manifest version does not match package release metadata')
    for i in range(1, 11):
        required = [f'作者{i:02d}/README.md', f'作者{i:02d}/会话指令.md', f'作者{i:02d}/输入输出契约.md',
                    f'作者{i:02d}/规范/执行规范.md', f'作者{i:02d}/自检清单.md', f'作者{i:02d}/变更记录.md']
        for rel in required:
            if not (ROOT / rel).is_file(): errors.append(f'required author file missing: {rel}')
    for rel in FIRST:
        if rel in expected and expected[rel]['unicode_non_whitespace_file_code_points'] > 2000:
            errors.append(f'{rel}: exceeds 2000-code-point project limit')
    actual_paths = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if included_file(p)}
    missing, extra = set(expected) - actual_paths, actual_paths - set(expected)
    if missing or extra:
        errors.append(f'manifest/source inventory mismatch: missing={sorted(missing)}, extra={sorted(extra)}')
    for rel, item in expected.items():
        p = ROOT / rel
        if not p.exists(): continue
        try:
            raw = p.read_bytes()
            text = raw.decode('utf-8')
        except (OSError, UnicodeError) as exc:
            errors.append(f'{rel}: cannot read as UTF-8: {exc}'); continue
        if raw.startswith(b'\xef\xbb\xbf'): errors.append(f'{rel}: UTF-8 BOM')
        if (len(raw) != item['bytes'] or hashlib.sha256(raw).hexdigest() != item['sha256']
                or count_chars(text) != item['unicode_non_whitespace_file_code_points']):
            errors.append(f'{rel}: manifest metadata mismatch')

    package_name = manifest.get('package', ROOT.name)
    archives = _resolve_zips(zip_path, package_name)
    archive_checked = False
    if source_only and zip_path is not None:
        errors.append('--source-only cannot be combined with --zip')
    if not archives and not source_only:
        errors.append('ZIP archive not found; pass --zip <archive> or place <package>.zip beside the source directory; explicitly choose --source-only to skip ZIP checks')
    if archives and not source_only:
        archive_checked = True
        for archive in archives:
            if not archive.is_file():
                errors.append(f'ZIP missing: {archive}')
                continue
            try:
                with zipfile.ZipFile(archive) as zf:
                    bad = zf.testzip()
                    if bad: errors.append(f'{archive}: CRC failure: {bad}')
                    names = zf.namelist()
                    if names[:2] != FIRST: errors.append(f'{archive}: ZIP must begin with {FIRST}')
                    if len(names) < 12 or not names[2].startswith('作者01/'): errors.append(f'{archive}: author folders must follow the first two root files')
                    groups = [n.split('/', 1)[0] for n in names if n.startswith('作者') and '/' in n]
                    if list(dict.fromkeys(groups)) != [f'作者{i:02d}' for i in range(1, 11)]: errors.append(f'{archive}: author folders must be grouped in 作者01–作者10 order')
                    if not names or names[-1] != 'manifest.json': errors.append(f'{archive}: manifest.json must be last')
                    if set(names) != set(expected) | {'manifest.json'}: errors.append(f'{archive}: ZIP/source inventory mismatch')
                    if 'manifest.json' in names and zf.read('manifest.json') != manifest_path.read_bytes():
                        errors.append(f'{archive}: embedded ZIP manifest differs from selected manifest')
                    if any(n in names for n in EXTERNAL): errors.append(f'{archive}: external user guides found inside ZIP')
                    for rel, item in expected.items():
                        if rel in names and hashlib.sha256(zf.read(rel)).hexdigest() != item['sha256']:
                            errors.append(f'{archive}: ZIP hash mismatch: {rel}')
            except (OSError, zipfile.BadZipFile) as exc:
                errors.append(f'cannot read ZIP {archive}: {exc}')
    if errors:
        for error in errors: print('FAIL: ' + error, file=sys.stderr)
        return False
    if archive_checked:
        verified = ', '.join(str(p) for p in archives)
        print(f'PASS: {len(expected)} source files; {len(archives)} ZIP archive(s) verified [{verified}]; CRC/inventory/order/hashes and manifest metadata verified.')
    else:
        print(f'PASS (SOURCE ONLY): {len(expected)} source files and manifest verified; ZIP was NOT checked.')
    return True


def lint() -> bool:
    """Run only the named, targeted cross-file checks; not a general semantic analyzer."""
    errors = []
    for i in range(1, 11):
        p = ROOT / f'作者{i:02d}' / 'README.md'
        text = p.read_text(encoding='utf-8')
        if '冒烟测试确认' not in text or '读不到即阻断' not in text:
            errors.append(f'{p.relative_to(ROOT)}: missing conditional file-access fallback')
        if '文件区共享；' in text:
            errors.append(f'{p.relative_to(ROOT)}: unqualified cross-session sharing claim')

    audit_files = [ROOT / '作者07/README.md', ROOT / '作者07/会话指令.md',
                   ROOT / '作者07/规范/执行规范.md', ROOT / '作者07/输入输出契约.md']
    for p in audit_files:
        text = p.read_text(encoding='utf-8')
        if '两轨都通过且无待确认才进入09。' in text:
            errors.append(f'{p.relative_to(ROOT)}: stale subjective style-gate wording')
        for marker in ('同模型', '仅', '建议'):
            if marker not in text: errors.append(f'{p.relative_to(ROOT)}: missing review-scope marker {marker!r}')

    owner_files = [ROOT / '作者09/README.md', ROOT / '作者09/会话指令.md', ROOT / '作者09/输入输出契约.md']
    for p in owner_files:
        text = p.read_text(encoding='utf-8')
        if '作者03账本变更；质量账本事件' in text or '直接编辑其台账' in text:
            errors.append(f'{p.relative_to(ROOT)}: author09 ledger ownership conflict')

    top_level = {p.name for p in ROOT.iterdir() if p.is_file() and included_file(p)}
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    section = re.search(r'(?ms)^## 9\. 目录索引\s*\n(.*?)(?=^## |\Z)', readme)
    index_blocks = re.findall(r'```[^\n]*\n(.*?)```', section.group(1), re.S) if section else []
    if not index_blocks:
        errors.append('package README: cannot find fenced directory index under section 9')
    else:
        index_text = '\n'.join(index_blocks)
        missing_index = sorted(name for name in top_level if _exact_index_mentions(index_text, name) == 0)
        duplicate_index = sorted(name for name in top_level if _exact_index_mentions(index_text, name) > 1)
        if missing_index: errors.append('package README directory index omits: ' + ', '.join(missing_index))
        if duplicate_index: errors.append('package README directory index duplicates: ' + ', '.join(duplicate_index))

    current_version = json.loads(RELEASE_FILE.read_text(encoding='utf-8'))['version']
    for rel in ('README.md', 'P6验收报告.md'):
        text = (ROOT / rel).read_text(encoding='utf-8')
        errors.extend(f'{rel}: {message}' for message in _current_doc_version_errors(text, current_version))
    changelog = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
    latest = re.search(r'(?m)^##\s+(\d+\.\d+\.\d+)\b', changelog)
    if not latest or latest.group(1) != current_version:
        errors.append(f'CHANGELOG.md: first release heading must be {current_version}')

    # Validate the checked-in state sample and fail closed if schema adds unsupported keywords.
    state_module = __import__('runpy').run_path(str(ROOT / '工具/validate_state.py'), run_name='targeted_lint_state')
    state_data = json.loads((ROOT / '项目运行模板/project_state.json').read_text(encoding='utf-8'))
    errors.extend('project_state.json: ' + e for e in state_module['validate'](state_data))
    unsupported = state_module['unsupported_schema_keywords']()
    if unsupported: errors.append('state schema uses unsupported keywords: ' + ', '.join(unsupported))

    if errors:
        print('TARGETED LINT FAIL:')
        for error in errors: print('FAIL: ' + error, file=sys.stderr)
        return False
    print('TARGETED LINT PASS: named README fallbacks, author07 review scope, author09 ledger boundary, exact filename-token index, non-mixed current release mentions, and state sample/schema subset.')
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    b = sub.add_parser('build')
    b.add_argument('--output', required=True, type=Path, help='new ZIP output path')
    b.add_argument('--manifest-output', required=True, type=Path, help='new manifest output path')
    b.add_argument('--overwrite', action='store_true', help='explicitly allow replacing either existing output')
    v = sub.add_parser('verify')
    group = v.add_mutually_exclusive_group()
    group.add_argument('--zip', type=Path, help='archive to verify; omitted checks all canonical package ZIPs beside/inside the source folder')
    group.add_argument('--source-only', action='store_true', help='explicitly skip ZIP verification and verify only source files/manifest')
    v.add_argument('--manifest', type=Path, default=ROOT / 'manifest.json')
    sub.add_parser('lint')
    args = parser.parse_args()
    if args.action == 'build':
        try: build(args.output, args.manifest_output, args.overwrite)
        except (OSError, zipfile.BadZipFile) as exc:
            print(f'FAIL: {exc}', file=sys.stderr); return 1
        return 0
    if args.action == 'verify': return 0 if verify(args.zip, args.manifest, args.source_only) else 1
    return 0 if lint() else 1

if __name__ == '__main__': raise SystemExit(main())
