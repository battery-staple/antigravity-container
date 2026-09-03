#!/usr/bin/env python3
"""
Unit tests for bridge/host_exec_daemon.py
"""

import hashlib
import hmac
import json
import os
import shutil
import sys
import tempfile
import unittest

# Add bridge directory to sys.path
REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_DIR, "bridge"))

from host_exec_daemon import (
    format_log_prefix,
    get_command_description,
    get_or_create_secret,
    resolve_cwd,
    verify_token,
)


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


class TestVerifyToken(unittest.TestCase):
    def setUp(self):
        self.secret = "test-secret-key-1234567890abcdef"

    def _compute_token(self, cmd, args, cwd):
        payload = {"command": cmd, "args": args, "cwd": cwd}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hmac.new(self.secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()

    def test_valid_token(self):
        req = {"command": "sw_vers", "args": ["-productVersion"], "cwd": "/tmp"}
        token = self._compute_token("sw_vers", ["-productVersion"], "/tmp")
        self.assertTrue(verify_token(req, token, self.secret))

    def test_extra_metadata_does_not_break_hmac(self):
        # request_id and trajectory_id should not affect HMAC verification
        token = self._compute_token("sw_vers", ["-productVersion"], "/tmp")
        req = {
            "command": "sw_vers",
            "args": ["-productVersion"],
            "cwd": "/tmp",
            "request_id": "req-9988aabb",
            "trajectory_id": "traj-11223344",
        }
        self.assertTrue(verify_token(req, token, self.secret))

    def test_tampered_command_fails(self):
        token = self._compute_token("sw_vers", [], "/tmp")
        req = {"command": "rm", "args": ["-rf", "/"], "cwd": "/tmp"}
        self.assertFalse(verify_token(req, token, self.secret))

    def test_tampered_args_fails(self):
        token = self._compute_token("sw_vers", ["-productVersion"], "/tmp")
        req = {"command": "sw_vers", "args": ["-buildVersion"], "cwd": "/tmp"}
        self.assertFalse(verify_token(req, token, self.secret))

    def test_tampered_cwd_fails(self):
        token = self._compute_token("sw_vers", [], "/tmp")
        req = {"command": "sw_vers", "args": [], "cwd": "/var/root"}
        self.assertFalse(verify_token(req, token, self.secret))

    def test_empty_or_invalid_token(self):
        req = {"command": "sw_vers", "args": [], "cwd": "/tmp"}
        self.assertFalse(verify_token(req, "", self.secret))
        self.assertFalse(verify_token(req, "invalid-token", self.secret))


class TestCommandDescription(unittest.TestCase):
    def test_explicit_description(self):
        policy = {"description": "Custom tool description", "binary_path": "/bin/echo"}
        self.assertEqual(get_command_description("echo", policy), "Custom tool description")

    def test_fallback_description_with_alias(self):
        policy = {"binary_path": "/usr/bin/open", "allowed_args_regex": "^-a Simulator$"}
        desc = get_command_description("simulator", policy)
        self.assertIn("Run '/usr/bin/open' via alias 'simulator'", desc)
        self.assertIn("-a Simulator", desc)


class TestSecretLifecycle(unittest.TestCase):
    def test_get_or_create_secret_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_ipc = os.environ.get("ANTIGRAVITY_STATE_DIR")
            try:
                os.environ["ANTIGRAVITY_STATE_DIR"] = tmpdir
                # Re-import or run with patched path
                secret = get_or_create_secret()
                self.assertTrue(len(secret) >= 32)
                # Second call returns same secret
                secret2 = get_or_create_secret()
                self.assertEqual(secret, secret2)
            finally:
                if orig_ipc:
                    os.environ["ANTIGRAVITY_STATE_DIR"] = orig_ipc
                else:
                    os.environ.pop("ANTIGRAVITY_STATE_DIR", None)


class TestFormatLogPrefix(unittest.TestCase):
    def test_format_prefix(self):
        prefix = format_log_prefix("req-12345678", "traj-abcdefgh", "sw_vers")
        self.assertIn("req-123456", prefix)
        self.assertIn("traj-abc", prefix)
        self.assertIn("sw_vers", prefix)

    def test_format_prefix_empty(self):
        prefix = format_log_prefix("", "")
        self.assertIn("req-init", prefix)
        self.assertIn("manual", prefix)


if __name__ == "__main__":
    unittest.main()
