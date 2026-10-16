import unittest
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from app.fire_ssh import TerminalSessionManager, TerminalSession


class TerminalSessionManagerTests(unittest.TestCase):

    def setUp(self):
        self.mgr = TerminalSessionManager()
        self.token = "test_token_abc123"

    def tearDown(self):
        # Clean up any opened sessions
        self.mgr.remove(self.token)

    def test_session_lifecycle_and_tab_removal(self):
        """Verify tab creation, tab listing, and clean removal without resurrecting tabs."""
        # Create tab-1 and tab-2
        sess1 = self.mgr.get_or_create(self.token, "tab-1", shell="/bin/sh")
        sess2 = self.mgr.get_or_create(self.token, "tab-2", shell="/bin/sh")

        self.assertTrue(sess1.is_alive())
        self.assertTrue(sess2.is_alive())

        tabs = self.mgr.list_tabs(self.token)
        tab_ids = [t["id"] for t in tabs]
        self.assertIn("tab-1", tab_ids)
        self.assertIn("tab-2", tab_ids)
        self.assertEqual(len(tab_ids), 2)

        # Remove tab-2
        self.mgr.remove(self.token, "tab-2")
        self.assertFalse(sess2.is_alive())

        remaining_tabs = self.mgr.list_tabs(self.token)
        remaining_ids = [t["id"] for t in remaining_tabs]
        self.assertIn("tab-1", remaining_ids)
        self.assertNotIn("tab-2", remaining_ids)
        self.assertEqual(len(remaining_ids), 1)

    def test_tab_1_fallback_removal(self):
        """Verify tab-1 is cleaned up even if created under root token key without explicit tab-1 suffix."""
        sess_legacy = self.mgr.get_or_create(self.token, None, shell="/bin/sh")
        self.assertTrue(sess_legacy.is_alive())

        # list_tabs identifies root token as tab-1
        tabs = self.mgr.list_tabs(self.token)
        tab_ids = [t["id"] for t in tabs]
        self.assertEqual(tab_ids, ["tab-1"])

        # Removing with tab-1 should find and remove it
        self.mgr.remove(self.token, "tab-1")
        self.assertFalse(sess_legacy.is_alive())

        tabs_after = self.mgr.list_tabs(self.token)
        self.assertEqual(tabs_after, [])


if __name__ == '__main__':
    unittest.main()
