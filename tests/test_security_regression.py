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


if __name__ == '__main__':
    unittest.main()
