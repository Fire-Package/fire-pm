import unittest
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from app.fire_ssh import TerminalSessionManager, TerminalSession


class MockSocket:
    def __init__(self):
        self.sent_data = []
        self.closed = False

    def sendall(self, data):
        if self.closed:
            raise OSError("Socket closed")
        self.sent_data.append(data)

    def close(self):
        self.closed = True


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

    def test_multi_socket_broadcast_and_detachment(self):
        """Verify multiple client sockets can attach concurrently and receive broadcast frames."""
        sess = self.mgr.get_or_create(self.token, "tab-1", shell="/bin/sh")
        sock1 = MockSocket()
        sock2 = MockSocket()

        sess.attach_socket(sock1)
        sess.attach_socket(sock2)

        self.assertEqual(len(sess.interactive_socks), 2)

        count1_before = len(sock1.sent_data)
        count2_before = len(sock2.sent_data)

        sess.send_ws_json({"type": "test_broadcast", "data": "hello"})

        self.assertEqual(len(sock1.sent_data), count1_before + 1)
        self.assertEqual(len(sock2.sent_data), count2_before + 1)

        # Detach sock1: sock2 must remain attached and continue receiving frames
        sess.detach_socket(sock1)
        self.assertEqual(len(sess.interactive_socks), 1)
        self.assertIn(sock2, sess.interactive_socks)

        sess.send_ws_json({"type": "test_broadcast", "data": "world"})
        self.assertEqual(len(sock1.sent_data), count1_before + 1)  # No change
        self.assertEqual(len(sock2.sent_data), count2_before + 2)  # Incremented

        sess.detach_socket(sock2)
        self.assertEqual(len(sess.interactive_socks), 0)

    def test_multi_device_shared_session_and_tabs(self):
        """Verify multiple devices attach to the exact same session instance for identical tab IDs."""
        device_a_token = "token_desktop_device_a"
        device_b_token = "token_mobile_device_b"

        # Device A creates tab-1 and tab-2
        sess_a1 = self.mgr.get_or_create(device_a_token, "tab-1", shell="/bin/sh")
        sess_a2 = self.mgr.get_or_create(device_a_token, "tab-2", shell="/bin/sh")

        # Device B accesses tab-1 and tab-2: should retrieve the exact same sessions
        sess_b1 = self.mgr.get_or_create(device_b_token, "tab-1", shell="/bin/sh")
        sess_b2 = self.mgr.get(device_b_token, "tab-2")

        self.assertIs(sess_a1, sess_b1)
        self.assertIs(sess_a2, sess_b2)

        # Tabs list for Device B reflects both tabs
        tabs_b = self.mgr.list_tabs(device_b_token)
        tab_ids_b = [t["id"] for t in tabs_b]
        self.assertEqual(tab_ids_b, ["tab-1", "tab-2"])


if __name__ == '__main__':
    unittest.main()
