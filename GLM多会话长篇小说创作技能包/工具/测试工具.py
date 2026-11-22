#!/usr/bin/env python3
"""Hermetic regression tests for character counting, state/summary gates and ZIP tooling."""
from __future__ import annotations
from pathlib import Path
import hashlib
import json
import runpy
import tempfile
from types import SimpleNamespace
import unittest

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent

def load(path: Path):
    return SimpleNamespace(**runpy.run_path(str(path), run_name='package_test_module'))

counter = load(TOOLS / '字数统计.py')
bundle = load(TOOLS / '构建与校验.py')
state = load(TOOLS / 'validate_state.py')
summary = load(TOOLS / '校验摘要.py')
repetition = load(TOOLS / '重复检测.py')

class CountTests(unittest.TestCase):
    def test_whitespace_excluded_punctuation_included(self):
        self.assertEqual(counter.count_chars('甲，乙\n'), 3)
    def test_chapter_boundaries(self):
        self.assertFalse(2500 <= counter.count_chars('甲' * 2499) <= 4000)
        self.assertTrue(2500 <= counter.count_chars('甲' * 2500) <= 4000)
        self.assertTrue(2500 <= counter.count_chars('甲' * 4000) <= 4000)
        self.assertFalse(2500 <= counter.count_chars('甲' * 4001) <= 4000)
    def test_demo_pair_meets_chapter_length(self):
        root = ROOT / '示例项目'
        for name in ['第001章_演示正文.md', '第002章_演示正文.md']:
            text = (root / name).read_text(encoding='utf-8')
            self.assertTrue(2500 <= counter.count_chars(text) <= 4000, name)

class StateAndSummaryTests(unittest.TestCase):
    def test_state_template_passes(self):
        data = json.loads((ROOT / '项目运行模板/project_state.json').read_text(encoding='utf-8'))
        self.assertEqual(state.validate(data), [])
    def test_invalid_state_gate_and_enum_fail(self):
        data = json.loads((ROOT / '项目运行模板/project_state.json').read_text(encoding='utf-8'))
        data['stage'] = '定槁'
        data['stale_candidates'] = ['第016章_v0']
        data['gates']['release_09'] = '通过'
        errors = state.validate(data)
        self.assertTrue(any('stage' in e for e in errors))
        self.assertTrue(any('stale_candidates' in e for e in errors))
    def test_repeated_paragraphs_are_flagged(self):
        near, exact = repetition.inspect('重复段落甲乙丙。\n\n另一段内容。\n\n重复段落甲乙丙。')
        self.assertTrue(exact)
    def test_summary_coverage_pass_and_gap_fail(self):
        text = '''# 摘要\n- 项目/摘要版本/生效时间：x\n- 覆盖章号闭区间：1-2\n- 相关定稿版本/哈希清单：x\n- 最近校验者/校验报告版本：x\n| 章号/定稿版本 | 关键事件与因果 | 人物状态 | 伏笔 | 道具/地点/时间/规则 | 回查路径 | 状态 |\n|---|---|---|---|---|---|---|\n| 1 / v1 | x | x | x | x | x | 已确认 |\n| 2 / v1 | x | x | x | x | x | 已确认 |\n## 窗口共识\nx\n## 更新与完整性\nx\n'''
        self.assertEqual(summary.validate(text, {1, 2}), [])
        self.assertTrue(any('missing chapter rows' in e for e in summary.validate(text, {1, 2, 3})))

class BundleTests(unittest.TestCase):
    def test_source_manifest_and_zip_integrity(self):
        self.assertTrue(bundle.verify())
    def test_semantic_lint(self):
        self.assertTrue(bundle.lint())
    def test_reproducible_build_is_hermetic(self):
        source_manifest = (ROOT / 'manifest.json').read_bytes()
        source_zip = bundle.ZIP_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            zip_path, manifest_path = tmp / 'kit.zip', tmp / 'manifest.json'
            bundle.build(zip_path, manifest_path)
            first = hashlib.sha256(zip_path.read_bytes()).hexdigest()
            bundle.build(zip_path, manifest_path)
            second = hashlib.sha256(zip_path.read_bytes()).hexdigest()
            self.assertEqual(first, second)
            self.assertTrue(bundle.verify(zip_path, manifest_path))
        self.assertEqual(source_manifest, (ROOT / 'manifest.json').read_bytes())
        self.assertEqual(source_zip, bundle.ZIP_PATH.read_bytes())

if __name__ == '__main__':
    unittest.main(verbosity=2)
