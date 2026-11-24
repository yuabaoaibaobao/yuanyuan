#!/usr/bin/env python3
"""Validate the package's declared JSON-Schema subset and project release gates."""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / '项目运行模板' / 'state.schema.json'
STAGES = {'立项', '检索', '设定', '章节卡', '正文', '润色', '审计', '返修', '定稿', '周期审计', '暂停'}
STATUSES = {'草稿', '待确认', '已锁', '审计通过', '返修中', '定稿', '归档', 'stale', '阻断'}
GATE_VALUES = {'待检查', '通过', '阻断', '不适用'}
SCHEMA_KEYWORDS = {
    '$schema', '$id', '$ref', '$defs', 'title', 'description', 'type', 'const', 'enum',
    'additionalProperties', 'required', 'properties', 'items', 'uniqueItems', 'minLength',
    'pattern', 'minimum', 'format'
}


def load_schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding='utf-8'))


def unsupported_schema_keywords(schema: Optional[dict] = None) -> list[str]:
    """Return unsupported schema keywords; maintenance fails closed rather than ignoring them."""
    schema = schema or load_schema()
    bad: set[str] = set()
    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key not in SCHEMA_KEYWORDS: bad.add(key)
                if key == 'format' and value != 'date-time': bad.add(f'format:{value}')
                if key in {'properties', '$defs'} and isinstance(value, dict):
                    for child in value.values(): walk(child)
                elif key in {'items', 'additionalProperties'} and isinstance(value, dict): walk(value)
        elif isinstance(node, list):
            for child in node: walk(child)
    walk(schema)
    return sorted(bad)


def validate_schema(data: object, schema: dict, root_schema: Optional[dict] = None, path: str = '$') -> list[str]:
    """Validate the supported subset declared in SCHEMA_KEYWORDS (stdlib-only)."""
    root_schema = root_schema or schema
    errors: list[str] = []
    if '$ref' in schema:
        ref = schema['$ref']
        if not ref.startswith('#/$defs/'):
            return [f'{path}: unsupported schema reference {ref}']
        target = root_schema.get('$defs', {}).get(ref.rsplit('/', 1)[-1])
        return [f'{path}: unresolved schema reference {ref}'] if target is None else validate_schema(data, target, root_schema, path)
    if 'const' in schema and data != schema['const']: errors.append(f'{path}: must equal {schema["const"]!r}')
    if 'enum' in schema and data not in schema['enum']: errors.append(f'{path}: must be one of {schema["enum"]!r}')
    expected = schema.get('type')
    valid_type = True
    if expected == 'object': valid_type = isinstance(data, dict)
    elif expected == 'array': valid_type = isinstance(data, list)
    elif expected == 'string': valid_type = isinstance(data, str)
    elif expected == 'integer': valid_type = isinstance(data, int) and not isinstance(data, bool)
    elif expected == 'number': valid_type = isinstance(data, (int, float)) and not isinstance(data, bool)
    elif expected == 'boolean': valid_type = isinstance(data, bool)
    if expected and not valid_type:
        errors.append(f'{path}: expected {expected}')
        return errors
    if isinstance(data, str):
        if schema.get('format') == 'date-time':
            try: datetime.fromisoformat(data.replace('Z', '+00:00'))
            except ValueError: errors.append(f'{path}: expected ISO 8601 date-time with timezone')
        if len(data) < schema.get('minLength', 0): errors.append(f'{path}: shorter than minLength {schema["minLength"]}')
        if 'pattern' in schema and not re.search(schema['pattern'], data): errors.append(f'{path}: does not match pattern {schema["pattern"]!r}')
    if isinstance(data, int) and 'minimum' in schema and data < schema['minimum']: errors.append(f'{path}: below minimum {schema["minimum"]}')
    if isinstance(data, list):
        if schema.get('uniqueItems'):
            encoded = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in data]
            if len(encoded) != len(set(encoded)): errors.append(f'{path}: array items must be unique')
        if 'items' in schema:
            for i, item in enumerate(data): errors.extend(validate_schema(item, schema['items'], root_schema, f'{path}[{i}]'))
    if isinstance(data, dict):
        for key in schema.get('required', []):
            if key not in data: errors.append(f'{path}: missing required property {key!r}')
        properties = schema.get('properties', {})
        for key, value in data.items():
            if key in properties: errors.extend(validate_schema(value, properties[key], root_schema, f'{path}.{key}'))
            elif schema.get('additionalProperties') is False: errors.append(f'{path}: unexpected property {key!r}')
            elif isinstance(schema.get('additionalProperties'), dict): errors.extend(validate_schema(value, schema['additionalProperties'], root_schema, f'{path}.{key}'))
    return errors


def validate(data: object, root_dir: Optional[Path] = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict): return ['root must be a JSON object']
    try:
        schema = load_schema()
        unsupported = unsupported_schema_keywords(schema)
        if unsupported: errors.append('schema uses unsupported keywords: ' + ', '.join(unsupported))
        errors.extend(validate_schema(data, schema))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f'cannot load state schema: {exc}')
    required = {'schema_version','project','state_version','updated_at','owner','stage','next_action','next_owner','model','rule_versions','gates','files','open_issue_ids','stale_candidates'}
    missing = required - data.keys()
    if missing: errors.append(f'missing required fields: {", ".join(sorted(missing))}')
    if data.get('schema_version') != '1.0': errors.append('schema_version must be "1.0"')
    for k in ('project','state_version','updated_at','owner','next_action','next_owner'):
        if not isinstance(data.get(k), str) or not data[k].strip(): errors.append(f'{k} must be a non-empty string')
    if data.get('stage') not in STAGES: errors.append(f'stage must be one of: {", ".join(sorted(STAGES))}')
    if data.get('project_mode', '待选择') not in {'10会话','人工合并会话','待选择'}: errors.append('project_mode has an invalid enum value')
    model = data.get('model')
    if not isinstance(model, dict): errors.append('model must be an object')
    else:
        for k in ('display_name','entry','context_window','observed_at'):
            if not isinstance(model.get(k), str) or not model[k].strip(): errors.append(f'model.{k} must be a non-empty string')
    rules = data.get('rule_versions')
    if not isinstance(rules, dict) or not {'01','02','05','audit'} <= rules.keys(): errors.append('rule_versions must include 01, 02, 05, audit')
    gates = data.get('gates')
    gate_names = {'user_confirmation','dependencies_read','chapter_complete','audit_07','window_08','release_09'}
    if not isinstance(gates, dict): errors.append('gates must be an object')
    else:
        if not gate_names <= gates.keys(): errors.append('gates must include: ' + ', '.join(sorted(gate_names)))
        for name, value in gates.items():
            if value not in GATE_VALUES: errors.append(f'gates.{name} has invalid value {value!r}')
    for key in ('files','open_issue_ids','stale_candidates','injection_receipts','chapter_batch','handoff_receipts'):
        if key in data and not isinstance(data[key], list): errors.append(f'{key} must be an array')
    files = data.get('files', []) if isinstance(data.get('files', []), list) else []
    logical_paths = []
    for i, item in enumerate(files):
        if not isinstance(item, dict): errors.append(f'files[{i}] must be an object'); continue
        for f in ('logical_path','platform_name','version','status','artifact_kind','sole_writer','sha256'):
            if not isinstance(item.get(f), str) or not item[f].strip(): errors.append(f'files[{i}].{f} must be a non-empty string')
        rel = item.get('logical_path')
        if isinstance(rel, str) and rel.strip():
            posix = PurePosixPath(rel)
            if posix.is_absolute() or '..' in posix.parts or str(posix) in {'', '.'} or '\\' in rel:
                errors.append(f'files[{i}].logical_path must be a safe relative POSIX path')
            logical_paths.append(rel)
        if item.get('status') not in STATUSES: errors.append(f'files[{i}].status has invalid enum value')
        expected_writer = {
            'project_state': data.get('owner'), 'canon': '作者03', 'chapter_card': '作者04',
            'draft': '作者05', 'polished': '作者06', 'audit': '作者07', 'window_report': '作者08',
            'final': '作者09', 'quality_ledger': '作者10', 'rolling_summary': '项目所有者',
            'other': data.get('owner')
        }.get(item.get('artifact_kind'))
        if expected_writer and item.get('sole_writer') != expected_writer:
            errors.append(f'files[{i}].sole_writer must be {expected_writer!r} for artifact_kind {item.get("artifact_kind")!r}')
        if isinstance(item.get('sha256'), str) and item['sha256'] != '未知' and not re.fullmatch(r'[a-fA-F0-9]{64}', item['sha256']): errors.append(f'files[{i}].sha256 must be 64 hex characters or 未知')
    if len(logical_paths) != len(set(logical_paths)):
        errors.append('files.logical_path values must be unique')
    for key in ('open_issue_ids','stale_candidates'):
        values = data.get(key, [])
        if isinstance(values, list) and (not all(isinstance(x, str) and x for x in values) or len(values) != len(set(values))): errors.append(f'{key} must contain unique non-empty strings')
    for i, item in enumerate(data.get('chapter_batch', []) if isinstance(data.get('chapter_batch', []), list) else []):
        if not isinstance(item, dict): errors.append(f'chapter_batch[{i}] must be an object'); continue
        if not isinstance(item.get('chapter'), int) or item['chapter'] < 1: errors.append(f'chapter_batch[{i}].chapter must be a positive integer')
        if item.get('candidate_status') not in {'候选','生成中','stale','审计通过','定稿','阻断'}: errors.append(f'chapter_batch[{i}].candidate_status has invalid enum value')
        if 'depends_on_canon_versions' not in item or not isinstance(item['depends_on_canon_versions'], dict): errors.append(f'chapter_batch[{i}].depends_on_canon_versions must be an object')
    stale = set(data.get('stale_candidates', [])) if isinstance(data.get('stale_candidates', []), list) else set()
    if isinstance(gates, dict) and gates.get('release_09') == '通过':
        if stale: errors.append('release_09 cannot pass while stale_candidates is non-empty')
        if data.get('open_issue_ids'): errors.append('release_09 cannot pass while open_issue_ids is non-empty')
        if any(isinstance(ch, dict) and ch.get('candidate_status') in {'stale','生成中','阻断'} for ch in data.get('chapter_batch', []) if isinstance(data.get('chapter_batch', []), list)):
            errors.append('release_09 cannot pass with stale, generating, or blocked chapter candidates')
        for gate in ('dependencies_read','chapter_complete','audit_07'):
            if gates.get(gate) != '通过': errors.append(f'release_09 requires {gate}=通过')
        if gates.get('window_08') not in {'通过','不适用'}: errors.append('release_09 requires window_08=通过 or 不适用')
        if not files: errors.append('release_09 requires at least one registered file')
        if root_dir is None: errors.append('release_09=通过 requires --root to verify registered file paths and hashes')
    if root_dir is not None:
        base = root_dir.resolve()
        for i, item in enumerate(files):
            if not isinstance(item, dict): continue
            rel = item.get('logical_path')
            if not isinstance(rel, str): continue
            target = (base / rel).resolve()
            try: target.relative_to(base)
            except ValueError: errors.append(f'files[{i}].logical_path escapes --root'); continue
            if not target.is_file(): errors.append(f'files[{i}].logical_path does not exist under --root: {rel}'); continue
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if item.get('sha256') == '未知':
                if isinstance(gates, dict) and gates.get('release_09') == '通过':
                    errors.append(f'files[{i}].sha256 must be recorded before release: {rel}')
            elif item.get('sha256') != digest:
                errors.append(f'files[{i}].sha256 does not match file bytes: {rel}')
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('state', nargs='?', default=str(ROOT / '项目运行模板' / 'project_state.json'))
    ap.add_argument('--root', type=Path, help='project workspace root; required to pass a release gate')
    args = ap.parse_args()
    try: data = json.loads(Path(args.state).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr); return 1
    errors = validate(data, args.root)
    if errors:
        for error in errors: print('FAIL: ' + error, file=sys.stderr)
        return 1
    print(f'PASS: declared JSON-Schema subset and structural/gate rules validated ({args.state}).')
    if args.root is not None:
        registered = data.get('files', []) if isinstance(data.get('files', []), list) else []
        known = sum(isinstance(item, dict) and item.get('sha256') != '未知' for item in registered)
        unknown = sum(isinstance(item, dict) and item.get('sha256') == '未知' for item in registered)
        print(f'PASS: registered paths checked: {len(registered)}; known SHA-256 values matched: {known}; unknown hashes not checked: {unknown} (root: {args.root}).')
    else:
        print('NOTE: registered file paths and hashes were not checked; pass --root <project-workspace> to check them.')
    return 0

if __name__ == '__main__': raise SystemExit(main())
