#!/usr/bin/env python3
"""
Unit tests for bridge/host_exec_daemon.py
"""

import os
import sys
import tempfile
import unittest

# Add bridge directory to sys.path
REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_DIR, "bridge"))

from host_exec_daemon import resolve_cwd


class TestResolveCwd(unittest.TestCase):
    def test_resolve_valid_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(resolve_cwd(tmpdir), tmpdir)

    def test_resolve_nonexistent_directory(self):
        nonexistent = "/path/that/does/not/exist/for/sure_12345"
        self.assertEqual(resolve_cwd(nonexistent), os.path.expanduser("~"))

    def test_resolve_none_or_empty(self):
        self.assertEqual(resolve_cwd(None), os.path.expanduser("~"))
        self.assertEqual(resolve_cwd(""), os.path.expanduser("~"))


if __name__ == "__main__":
    unittest.main()
