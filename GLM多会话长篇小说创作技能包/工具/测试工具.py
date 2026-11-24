#!/usr/bin/env python3
"""Hermetic regression tests for character counting, state/summary gates and ZIP tooling."""
from __future__ import annotations
from pathlib import Path
import hashlib
import io
import json
import os
import runpy
import tempfile
import zipfile
from contextlib import redirect_stderr
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
    def test_inline_html_comment_preserves_following_prose(self):
        text = '正文甲<!-- 隐藏批注 -->乙丙丁'
        self.assertEqual(counter.count_chars(counter.prose_text(text)), 6)
        crossline, warnings = counter.prose_text_with_warnings('正文甲<!-- 跨行\n隐藏批注 -->乙')
        self.assertEqual(counter.count_chars(crossline), 4)
        self.assertEqual(warnings, [])
    def test_unclosed_html_comment_is_retained_and_cli_refuses_gate_count(self):
        text, warnings = counter.prose_text_with_warnings('正文甲<!-- 未闭合批注')
        self.assertEqual(text, '正文甲<!-- 未闭合批注')
        self.assertEqual(len(warnings), 1)
        import subprocess, sys
        result = subprocess.run([sys.executable, str(TOOLS / '字数统计.py'), '--text', '正文甲<!-- 未闭合批注', '--chapter-range'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('未闭合HTML注释', result.stderr)
        self.assertNotIn('码点', result.stdout)
    def test_text_and_file_count_use_same_prose_normalization(self):
        import subprocess, sys
        sample = '# 标题\n正文甲\n<!-- 注释 -->\n'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'chapter.md'
            path.write_text(sample, encoding='utf-8')
            file_result = subprocess.run([sys.executable, str(TOOLS / '字数统计.py'), str(path)], capture_output=True, text=True)
            text_result = subprocess.run([sys.executable, str(TOOLS / '字数统计.py'), '--text', sample], capture_output=True, text=True)
        self.assertEqual(file_result.returncode, 0, file_result.stderr)
        self.assertEqual(text_result.returncode, 0, text_result.stderr)
        self.assertEqual(file_result.stdout.splitlines()[0].split(': ')[1], text_result.stdout.splitlines()[0].split(': ')[1])
        self.assertIn('manifest全文件码点指标不同', text_result.stdout)
    def test_manifest_count_contract_uses_synthetic_markdown_fixture(self):
        sample = '# Heading\nBody\n'
        raw_count = bundle.count_chars(sample)
        prose_count = counter.count_chars(counter.prose_text(sample))
        self.assertEqual(raw_count, 12)
        self.assertEqual(prose_count, 4)
        self.assertNotEqual(raw_count, prose_count)

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
    def test_unknown_hash_report_does_not_claim_it_was_checked(self):
        import subprocess, sys
        data = json.loads((ROOT / '项目运行模板/project_state.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            payload = base / 'note.md'
            payload.write_text('已登记文件', encoding='utf-8')
            data['files'] = [{'logical_path': 'note.md', 'platform_name': 'note.md', 'version': 'v1',
                'status': '草稿', 'artifact_kind': 'other', 'sole_writer': data['owner'],
                'sha256': '未知', 'read_receipts': []}]
            state_file = base / 'state.json'
            state_file.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            result = subprocess.run([sys.executable, str(TOOLS / 'validate_state.py'), str(state_file), '--root', str(base)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('registered paths checked: 1', result.stdout)
        self.assertIn('known SHA-256 values matched: 0', result.stdout)
        self.assertIn('unknown hashes not checked: 1', result.stdout)
    def test_release_gate_requires_root_and_checks_registered_hashes(self):
        import hashlib
        data = json.loads((ROOT / '项目运行模板/project_state.json').read_text(encoding='utf-8'))
        data['gates'].update({'dependencies_read': '通过', 'chapter_complete': '通过', 'audit_07': '通过', 'window_08': '不适用', 'release_09': '通过'})
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            payload = base / 'chapter.md'
            payload.write_text('定稿正文', encoding='utf-8')
            data['files'] = [{'logical_path': 'chapter.md', 'platform_name': 'chapter.md', 'version': 'v1',
                'status': '定稿', 'artifact_kind': 'other', 'sole_writer': data['owner'],
                'sha256': hashlib.sha256(payload.read_bytes()).hexdigest(), 'read_receipts': []}]
            self.assertTrue(any('--root' in error for error in state.validate(data)))
            self.assertEqual(state.validate(data, base), [])
            data['files'][0]['sha256'] = '0' * 64
            self.assertTrue(any('does not match file bytes' in error for error in state.validate(data, base)))
            data['files'][0]['sha256'] = '未知'
            data['files'][0]['sole_writer'] = '任意会话'
            self.assertTrue(any('sole_writer must be' in error for error in state.validate(data, base)))
            data['files'][0]['sole_writer'] = data['owner']
            data['files'][0]['logical_path'] = '../outside.md'
            self.assertTrue(any('safe relative POSIX path' in error for error in state.validate(data, base)))
    def test_repeated_paragraphs_are_advisory_with_sample_count(self):
        count, near, exact = repetition.inspect('重复段落甲乙丙。\n\n另一段内容。\n\n重复段落甲乙丙。')
        self.assertEqual(count, 3)
        self.assertTrue(exact)
    def test_markdown_heading_and_frontmatter_do_not_count_as_prose(self):
        text = '---\ntitle: chapter\n---\n# 第001章\n正文。\n<!-- note -->'
        self.assertEqual(counter.count_chars(counter.prose_text(text)), 3)
    def test_inline_count_command_input(self):
        self.assertEqual(counter.count_chars('甲，乙'), 3)
        import subprocess, sys
        script = str(TOOLS / '字数统计.py')
        result = subprocess.run([sys.executable, script, '--text', '甲，乙'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('3 个Unicode非空白码点', result.stdout)
        chapter_gate = subprocess.run([sys.executable, script, '--text', '甲，乙', '--chapter-range'], capture_output=True, text=True)
        self.assertEqual(chapter_gate.returncode, 1)
    def test_workspace_files_are_not_package_sources(self):
        self.assertTrue(bundle.is_workspace_path(Path('项目状态索引.json')))
        self.assertTrue(bundle.is_workspace_path(Path('项目工作区/chapter-001.md')))
        self.assertFalse(bundle.is_workspace_path(Path('作者05/会话指令.md')))
    def test_empty_summary_template_structural_check_passes_without_chapter_range(self):
        text = (ROOT / '项目运行模板/滚动摘要.md').read_text(encoding='utf-8')
        self.assertEqual(summary.validate(text), [])
        self.assertTrue(any('missing chapter rows' in e for e in summary.validate(text, set(range(1, 16)))))
    def test_summary_coverage_pass_and_gap_fail(self):
        text = '''# 摘要\n- 项目/摘要版本/生效时间：x\n- 覆盖章号闭区间：1-2\n- 相关定稿版本/哈希清单：x\n- 最近校验者/校验报告版本：x\n| 章号/定稿版本 | 关键事件与因果 | 人物状态 | 伏笔 | 道具/地点/时间/规则 | 回查路径 | 状态 |\n|---|---|---|---|---|---|---|\n| 1 / v1 | x | x | x | x | x | 已确认 |\n| 2 / v1 | x | x | x | x | x | 已确认 |\n## 窗口共识\nx\n## 更新与完整性\nx\n'''
        self.assertEqual(summary.validate(text, {1, 2}), [])
        self.assertTrue(any('missing chapter rows' in e for e in summary.validate(text, {1, 2, 3})))

class BundleTests(unittest.TestCase):
    def test_source_manifest_and_zip_integrity(self):
        if not bundle.ZIP_PATH.is_file():
            self.skipTest('adjacent ZIP absent; archive CRC/inventory not checked in this extracted-source run')
        self.assertTrue(bundle.verify())
    def test_explicit_source_only_mode_when_archive_is_absent(self):
        with redirect_stderr(io.StringIO()):
            self.assertTrue(bundle.verify(source_only=True))
    def test_current_document_version_lint_rejects_mixed_versions(self):
        check = bundle._current_doc_version_errors
        self.assertEqual(check('Release 1.1.2', '1.1.2'), [])
        self.assertTrue(any('mixed package release versions' in e for e in check('Old 1.1.1; current 1.1.2', '1.1.2')))
        self.assertTrue(any('does not mention' in e for e in check('Only 1.1.1', '1.1.2')))
    def test_lint_rejects_mixed_versions_in_real_current_docs(self):
        import shutil, subprocess, sys
        with tempfile.TemporaryDirectory() as tmp:
            clone = Path(tmp) / 'kit'
            shutil.copytree(ROOT, clone, ignore=shutil.ignore_patterns('__pycache__', '项目工作区'))
            readme = clone / 'README.md'
            # 版本号取自release.json，避免升版时本测试硬编码失效。
            current = bundle.VERSION
            text = readme.read_text(encoding='utf-8').replace(f'版本 {current}', f'版本 1.1.1 与 {current}', 1)
            readme.write_text(text, encoding='utf-8')
            result = subprocess.run([sys.executable, str(clone / '工具/构建与校验.py'), 'lint'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('README.md: contains mixed package release versions: 1.1.1', result.stderr)
    def test_directory_index_uses_exact_filename_tokens(self):
        mention = bundle._exact_index_mentions
        self.assertEqual(mention('README.md.bak', 'README.md'), 0)
        self.assertEqual(mention('README.md README.md', 'README.md'), 2)
        self.assertEqual(mention('README.md / CHANGELOG.md', 'README.md'), 1)
    def test_embedded_zip_manifest_must_match_selected_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source_zip, manifest_path, corrupted = tmp / 'source.zip', tmp / 'manifest.json', tmp / 'corrupted.zip'
            bundle.build(source_zip, manifest_path)
            with zipfile.ZipFile(source_zip) as source, zipfile.ZipFile(corrupted, 'w') as target:
                for info in source.infolist():
                    payload = b'{}' if info.filename == 'manifest.json' else source.read(info.filename)
                    target.writestr(info, payload)
            with redirect_stderr(io.StringIO()):
                self.assertFalse(bundle.verify(corrupted, manifest_path))
    def test_semantic_lint(self):
        self.assertTrue(bundle.lint())
    def test_reproducible_build_is_hermetic(self):
        source_manifest = (ROOT / 'manifest.json').read_bytes()
        source_zip = bundle.ZIP_PATH.read_bytes() if bundle.ZIP_PATH.exists() else None
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            zip_path, manifest_path = tmp / 'kit.zip', tmp / 'manifest.json'
            bundle.build(zip_path, manifest_path)
            first = hashlib.sha256(zip_path.read_bytes()).hexdigest()
            bundle.build(zip_path, manifest_path, overwrite=True)
            second = hashlib.sha256(zip_path.read_bytes()).hexdigest()
            self.assertEqual(first, second)
            self.assertTrue(bundle.verify(zip_path, manifest_path))
        self.assertEqual(source_manifest, (ROOT / 'manifest.json').read_bytes())
        if source_zip is not None: self.assertEqual(source_zip, bundle.ZIP_PATH.read_bytes())
    def test_custom_extraction_directory_finds_sibling_package_zip(self):
        import shutil, subprocess, sys
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            clone = base / 'arbitrary-extraction-name'
            shutil.copytree(ROOT, clone, ignore=shutil.ignore_patterns('__pycache__', '项目工作区'))
            package_name = json.loads((clone / 'manifest.json').read_text(encoding='utf-8'))['package']
            archive = base / f'{package_name}.zip'
            built_manifest = base / 'built-manifest.json'
            bundle.build(archive, built_manifest)
            internal_archive = clone / f'{package_name}.zip'
            shutil.copyfile(archive, internal_archive)
            result = subprocess.run([sys.executable, str(clone / '工具/构建与校验.py'), 'verify'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('2 ZIP archive(s) verified', result.stdout)
            self.assertIn(str(archive), result.stdout)
            self.assertIn(str(internal_archive), result.stdout)
    def test_source_verify_in_custom_directory_without_zip(self):
        if os.environ.get('KIT_NO_CLONE_TEST'): self.skipTest('nested clone test disabled')
        import shutil, subprocess, sys
        with tempfile.TemporaryDirectory() as tmp:
            clone = Path(tmp) / 'newpack'
            shutil.copytree(ROOT, clone, ignore=shutil.ignore_patterns('__pycache__', '项目工作区'))
            result = subprocess.run([sys.executable, str(clone / '工具/构建与校验.py'), 'verify'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn('ZIP archive not found', result.stderr)
            result = subprocess.run([sys.executable, str(clone / '工具/构建与校验.py'), 'verify', '--source-only'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('PASS (SOURCE ONLY)', result.stdout)
            child_env = dict(os.environ, KIT_NO_CLONE_TEST='1')
            result_tests = subprocess.run([sys.executable, str(clone / '工具/测试工具.py')], capture_output=True, text=True, env=child_env)
            self.assertEqual(result_tests.returncode, 0, result_tests.stderr)
            self.assertIn('Ran ', result_tests.stderr)
            self.assertNotIn('ERROR', result_tests.stderr)
            self.assertNotIn('FAILED', result_tests.stderr)
            self.assertIn('skipped', result_tests.stderr)
            (clone / '随手笔记.md').write_text('not part of the manifest', encoding='utf-8')
            (clone / 'README.md.bak').write_text('a legitimate top-level filename token', encoding='utf-8')
            index_lint = subprocess.run([sys.executable, str(clone / '工具/构建与校验.py'), 'lint'], capture_output=True, text=True)
            self.assertEqual(index_lint.returncode, 1)
            self.assertIn('directory index omits: README.md.bak', index_lint.stderr)
            self.assertIn('随手笔记.md', index_lint.stderr)
            readme = clone / 'README.md'
            text = readme.read_text(encoding='utf-8')
            text = text.replace('README.md / 部署与运行手册.md', 'README.md README.md.bak / 部署与运行手册.md')
            text = text.replace('反模式库.md / manifest.json', '反模式库.md / manifest.json / 随手笔记.md')
            readme.write_text(text, encoding='utf-8')
            exact_lint = subprocess.run([sys.executable, str(clone / '工具/构建与校验.py'), 'lint'], capture_output=True, text=True)
            self.assertEqual(exact_lint.returncode, 0, exact_lint.stderr)
            extra = subprocess.run([sys.executable, str(clone / '工具/构建与校验.py'), 'verify', '--source-only'], capture_output=True, text=True)
            self.assertEqual(extra.returncode, 1)
            self.assertIn('manifest/source inventory mismatch', extra.stderr)

if __name__ == '__main__':
    unittest.main(verbosity=2)
