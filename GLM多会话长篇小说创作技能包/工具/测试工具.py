#!/usr/bin/env python3
"""Small stdlib regression tests for the included counting and bundle tools."""
from __future__ import annotations
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest

TOOLS = Path(__file__).resolve().parent

def load(path: Path):
    # runpy compiles in-memory; importing sibling scripts can create __pycache__
    # inside the package and contaminate the manifest being tested.
    return SimpleNamespace(**runpy.run_path(str(path), run_name='package_test_module'))

counter = load(TOOLS / '字数统计.py')
bundle = load(TOOLS / '构建与校验.py')

class CountTests(unittest.TestCase):
    def test_whitespace_excluded_punctuation_included(self):
        self.assertEqual(counter.count_chars('甲，乙\n'), 3)
    def test_chapter_boundaries(self):
        self.assertFalse(2500 <= counter.count_chars('甲' * 2499) <= 4000)
        self.assertTrue(2500 <= counter.count_chars('甲' * 2500) <= 4000)
        self.assertTrue(2500 <= counter.count_chars('甲' * 4000) <= 4000)
        self.assertFalse(2500 <= counter.count_chars('甲' * 4001) <= 4000)

class BundleTests(unittest.TestCase):
    def test_source_manifest_and_zip(self):
        self.assertTrue(bundle.verify())

if __name__ == '__main__':
    unittest.main(verbosity=2)
