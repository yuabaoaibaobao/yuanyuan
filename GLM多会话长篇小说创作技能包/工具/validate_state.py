#!/usr/bin/env python3
"""Validate a project_state.json checkpoint using Python stdlib only."""
from __future__ import annotations
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / '项目运行模板' / 'state.schema.json'
STAGES = {'立项', '检索', '设定', '章节卡', '正文', '润色', '审计', '返修', '定稿', '周期审计', '暂停'}
STATUSES = {'草稿', '待确认', '已锁', '审计通过', '返修中', '定稿', '归档', 'stale', '阻断'}
GATE_VALUES = {'待检查', '通过', '阻断', '不适用'}
RECEIPT_STATUSES = {'已读', '未读', '待确认'}


def validate_schema(data: object, schema: dict, root_schema: Optional[dict] = None, path: str = '$') -> list[str]:
    """Validate the schema keywords used by this package's JSON Schema (stdlib-only)."""
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

def validate(data: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict): return ['root must be a JSON object']
    try:
        schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
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
    for i, item in enumerate(data.get('files', []) if isinstance(data.get('files', []), list) else []):
        if not isinstance(item, dict): errors.append(f'files[{i}] must be an object'); continue
        fields = ('logical_path','platform_name','version','status','sole_writer','sha256','downstream_read_receipt')
        for f in fields:
            if not isinstance(item.get(f), str) or not item[f].strip(): errors.append(f'files[{i}].{f} must be a non-empty string')
        if item.get('status') not in STATUSES: errors.append(f'files[{i}].status has invalid enum value')
        if isinstance(item.get('sha256'), str) and item['sha256'] != '未知' and not re.fullmatch(r'[a-fA-F0-9]{64}', item['sha256']): errors.append(f'files[{i}].sha256 must be 64 hex characters or 未知')
    for key in ('open_issue_ids','stale_candidates'):
        values = data.get(key, [])
        if isinstance(values, list) and (not all(isinstance(x, str) and x for x in values) or len(values) != len(set(values))): errors.append(f'{key} must contain unique non-empty strings')
    for i, item in enumerate(data.get('chapter_batch', []) if isinstance(data.get('chapter_batch', []), list) else []):
        if not isinstance(item, dict): errors.append(f'chapter_batch[{i}] must be an object'); continue
        if not isinstance(item.get('chapter'), int) or item['chapter'] < 1: errors.append(f'chapter_batch[{i}].chapter must be a positive integer')
        if item.get('candidate_status') not in {'候选','生成中','stale','审计通过','定稿','阻断'}: errors.append(f'chapter_batch[{i}].candidate_status has invalid enum value')
        if 'depends_on_canon_versions' not in item or not isinstance(item['depends_on_canon_versions'], dict): errors.append(f'chapter_batch[{i}].depends_on_canon_versions must be an object')
    # A canon change invalidates explicitly listed dependent candidates until re-audited.
    stale = set(data.get('stale_candidates', [])) if isinstance(data.get('stale_candidates', []), list) else set()
    if isinstance(gates, dict) and gates.get('release_09') == '通过':
        if stale: errors.append('release_09 cannot pass while stale_candidates is non-empty')
        if data.get('open_issue_ids'): errors.append('release_09 cannot pass while open_issue_ids is non-empty')
        if any(isinstance(ch, dict) and ch.get('candidate_status') in {'stale','生成中','阻断'} for ch in data.get('chapter_batch', []) if isinstance(data.get('chapter_batch', []), list)):
            errors.append('release_09 cannot pass with stale, generating, or blocked chapter candidates')
        for gate in ('dependencies_read','chapter_complete','audit_07'):
            if gates.get(gate) != '通过': errors.append(f'release_09 requires {gate}=通过')
        if gates.get('window_08') not in {'通过','不适用'}: errors.append('release_09 requires window_08=通过 or 不适用')
    return errors

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('state', nargs='?', default=str(ROOT / '项目运行模板' / 'project_state.json'))
    args = ap.parse_args()
    try:
        json.loads(SCHEMA.read_text(encoding='utf-8'))
        data = json.loads(Path(args.state).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr); return 1
    errors = validate(data)
    if errors:
        for error in errors: print('FAIL: ' + error, file=sys.stderr)
        return 1
    print(f'PASS: state structure/enums/gates validated ({args.state}).')
    return 0
if __name__ == '__main__': raise SystemExit(main())
