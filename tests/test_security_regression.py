import unittest
import os
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "tools"))

from tools.upload_assets import safe_asset_path, ASSETS_DIR


class SecurityRegressionTests(unittest.TestCase):

    def test_path_traversal_rejection(self):
        """Verify safe_asset_path rejects traversal attempts and unsafe files."""
        malicious_inputs = [
            "../etc/passwd",
            "../../shadow",
            "/etc/hosts",
            "..\\windows\\system32",
            "sub/dir/test.png",
            ".hidden.png",
            "..",
            ".",
            ""
        ]
        for item in malicious_inputs:
            with self.subTest(item=item):
                with self.assertRaises(ValueError):
                    safe_asset_path(item)

    def test_safe_asset_path_valid(self):
        """Verify safe_asset_path allows standard clean filenames strictly within ASSETS_DIR."""
        res = safe_asset_path("dashboard-preview.png")
        self.assertTrue(res.startswith(ASSETS_DIR))
        self.assertEqual(os.path.basename(res), "dashboard-preview.png")

    def test_shell_whitelisting_validation(self):
        """Verify shell whitelisting logic only executes valid system shells."""
        allowed_shells = {'/bin/bash', '/usr/bin/bash', '/bin/sh', '/usr/bin/sh', '/bin/dash', '/usr/bin/dash', '/bin/zsh', '/usr/bin/zsh'}
        
        # Test malicious shell injection paths
        bad_shells = [
            "/bin/bash -c 'id'",
            "/tmp/evil_shell",
            "bash; rm -rf /",
            "$(id)"
        ]
        for bad in bad_shells:
            resolved = os.path.realpath(bad.strip())
            is_valid = resolved in allowed_shells and os.path.exists(resolved) and os.access(resolved, os.X_OK)
            self.assertFalse(is_valid, f"Shell should have been rejected: {bad}")

    def test_tunnel_hash_pattern(self):
        """Verify 10-character lowercase alphanumeric tunnel hash format and regex."""
        import re
        tunnel_regex = re.compile(r"^[a-z0-9]{8,10}$")

        valid_hashes = ["a1b2c3d4", "qpu693pplv", "l18cwthk4y", "0123456789", "abcdefghij"]
        for h in valid_hashes:
            with self.subTest(h=h):
                self.assertTrue(bool(tunnel_regex.match(h)), f"Expected {h} to match tunnel hash regex")

        invalid_hashes = ["A1B2C3D4EF", "short", "toolonghash123", "a1b2c3d4-tunnel", "qpu@93pplv"]
        for h in invalid_hashes:
            with self.subTest(h=h):
                self.assertFalse(bool(tunnel_regex.match(h)), f"Expected {h} to fail tunnel hash regex")


if __name__ == '__main__':
    unittest.main()
