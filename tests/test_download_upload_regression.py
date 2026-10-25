import os
import sys
import tempfile
import urllib.parse
from unittest.mock import MagicMock

# Add app directory to sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))

from fire_ssh import resolve_fs_path, TerminalSessionManager, FireSSHServerHandler


class TestPathResolution:
    def test_resolve_empty_and_none(self):
        cwd = "/tmp/test-project"
        assert resolve_fs_path(cwd, "") == os.path.realpath(cwd)
        assert resolve_fs_path(cwd, None) == os.path.realpath(cwd)
        assert resolve_fs_path(cwd, "   ") == os.path.realpath(cwd)

    def test_resolve_absolute_paths(self):
        cwd = "/tmp/test-project"
        assert resolve_fs_path(cwd, "/etc/nginx") == "/etc/nginx"
        assert resolve_fs_path(cwd, "/var/log/syslog") == "/var/log/syslog"

    def test_resolve_relative_paths(self):
        cwd = "/tmp/test-project"
        assert resolve_fs_path(cwd, "file.txt") == os.path.join(cwd, "file.txt")
        assert resolve_fs_path(cwd, "subdir/nested.py") == os.path.join(cwd, "subdir", "nested.py")
        assert resolve_fs_path(cwd, "./file.txt") == os.path.join(cwd, "file.txt")

    def test_resolve_tilde_expansion(self):
        cwd = "/tmp/test-project"
        home = os.path.expanduser("~")
        assert resolve_fs_path(cwd, "~") == home
        assert resolve_fs_path(cwd, "~/downloads") == os.path.join(home, "downloads")
        assert resolve_fs_path(cwd, "~/.bashrc") == os.path.join(home, ".bashrc")
        # Ensure ~ is never appended as literal directory to cwd
        assert "/~/" not in resolve_fs_path(cwd, "~/file.txt")

    def test_resolve_parent_traversal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, "nested")
            os.makedirs(subdir)
            assert resolve_fs_path(subdir, "..") == os.path.realpath(tmpdir)
            assert resolve_fs_path(subdir, "../other.txt") == os.path.join(os.path.realpath(tmpdir), "other.txt")


class TestTerminalSessionManagerFallback:
    def test_tab_fallback_to_alive_session(self):
        mgr = TerminalSessionManager()
        # Mock an active session
        mock_sess = MagicMock()
        mock_sess.is_alive.return_value = True
        mock_sess.get_cwd.return_value = "/tmp/mock-dir"

        with mgr.lock:
            mgr.sessions["tab-1"] = mock_sess

        # Looking up existing tab returns it
        assert mgr.get("token1", "tab-1") is mock_sess
        # Looking up unknown or undefined tab falls back to the alive session
        assert mgr.get("token1", "undefined") is mock_sess
        assert mgr.get("token1", "tab-999") is mock_sess
        assert mgr.get("token1", None) is mock_sess


class TestEndpointsAndTokens:
    def test_do_head_unmatched_path_returns_404(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.path = "/api/unknown-endpoint"
        handler.headers = {}
        handler.send_error = MagicMock()
        handler.send_response = MagicMock()

        handler.do_HEAD()
        handler.send_error.assert_called_once_with(404, "Not Found")

    def test_do_head_trailing_slash_api_download_recognized(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.path = "/api/download/?file=nonexistent.txt"
        handler.headers = {}
        handler.is_authenticated = MagicMock(return_value=True)
        handler.get_auth_token = MagicMock(return_value="valid-token")
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.server = MagicMock()
        handler.server.terminals.get.return_value = None

        handler.do_HEAD()
        # Should return 404 JSON for non-existent file, not fall through to 200 text/html!
        handler.send_response.assert_called_once_with(404)
        handler.send_header.assert_called_with("Content-Type", "application/json")

    def test_auth_token_from_query_parameter(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.headers = {}
        handler.path = "/api/download?file=test.txt&token=my_secret_token_123"

        token = handler.get_auth_token()
        assert token == "my_secret_token_123"

    def test_unauthorized_download_returns_json_not_html(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.headers = {}
        handler.path = "/api/download?file=test.txt"
        handler.is_authenticated = MagicMock(return_value=False)
        handler.send_json = MagicMock()

        handler.do_GET()
        handler.send_json.assert_called_once_with({"success": False, "error": "Unauthorized session"}, status=401)

    def test_unauthorized_upload_returns_json_not_html(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.headers = {}
        handler.path = "/api/upload?name=test.txt"
        handler.is_authenticated = MagicMock(return_value=False)
        handler.send_json = MagicMock()

        handler.do_POST()
        handler.send_json.assert_called_once_with({"success": False, "error": "Unauthorized session"}, status=401)
