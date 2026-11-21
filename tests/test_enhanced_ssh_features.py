import io
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
from unittest.mock import MagicMock
import pytest

# Add app directory to sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))

from fire_ssh import FireSSHServerHandler, HTML_TEMPLATE


class TestEnhancedSSHFeatures:
    """Tests for file operations, live log tailing, in-modal search, bookmarks, and terminal search."""

    def _create_mock_handler(self, is_auth=True):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.headers = {}
        handler.is_authenticated = MagicMock(return_value=is_auth)
        handler.get_auth_token = MagicMock(return_value="valid-token" if is_auth else None)
        handler.send_json = MagicMock()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler.server = MagicMock()
        handler.server.terminals.get.return_value = None
        return handler

    def test_file_op_requires_authentication(self):
        handler = self._create_mock_handler(is_auth=False)
        handler.path = "/api/file-op"
        handler.do_POST()
        handler.send_json.assert_called_once()
        status = handler.send_json.call_args[1].get('status')
        assert status == 401

    def test_file_op_touch_and_mkdir(self):
        handler = self._create_mock_handler(is_auth=True)
        handler.path = "/api/file-op"

        with tempfile.TemporaryDirectory() as tmp_dir:
            # 1. mkdir
            new_dir = os.path.join(tmp_dir, "my_new_folder")
            body = json.dumps({"op": "mkdir", "path": new_dir}).encode('utf-8')
            handler.headers = {'Content-Length': str(len(body))}
            handler.rfile = io.BytesIO(body)
            handler.do_POST()

            assert os.path.isdir(new_dir)
            call_args = handler.send_json.call_args[0][0]
            assert call_args["success"] is True
            assert call_args["op"] == "mkdir"

            # 2. touch
            handler.send_json.reset_mock()
            new_file = os.path.join(new_dir, "hello.txt")
            body = json.dumps({"op": "touch", "path": new_file}).encode('utf-8')
            handler.headers = {'Content-Length': str(len(body))}
            handler.rfile = io.BytesIO(body)
            handler.do_POST()

            assert os.path.isfile(new_file)
            call_args = handler.send_json.call_args[0][0]
            assert call_args["success"] is True
            assert call_args["op"] == "touch"

    def test_file_op_rename(self):
        handler = self._create_mock_handler(is_auth=True)
        handler.path = "/api/file-op"

        with tempfile.TemporaryDirectory() as tmp_dir:
            file1 = os.path.join(tmp_dir, "file1.txt")
            with open(file1, 'w') as f:
                f.write("content")

            body = json.dumps({"op": "rename", "path": file1, "new_name": "file2.txt"}).encode('utf-8')
            handler.headers = {'Content-Length': str(len(body))}
            handler.rfile = io.BytesIO(body)
            handler.do_POST()

            assert not os.path.exists(file1)
            assert os.path.exists(os.path.join(tmp_dir, "file2.txt"))
            call_args = handler.send_json.call_args[0][0]
            assert call_args["success"] is True
            assert call_args["op"] == "rename"

    def test_file_op_duplicate(self):
        handler = self._create_mock_handler(is_auth=True)
        handler.path = "/api/file-op"

        with tempfile.TemporaryDirectory() as tmp_dir:
            file1 = os.path.join(tmp_dir, "doc.md")
            with open(file1, 'w') as f:
                f.write("# Hello")

            # Duplicate doc.md -> doc-copy.md
            body = json.dumps({"op": "duplicate", "path": file1}).encode('utf-8')
            handler.headers = {'Content-Length': str(len(body))}
            handler.rfile = io.BytesIO(body)
            handler.do_POST()

            dup_file = os.path.join(tmp_dir, "doc-copy.md")
            assert os.path.exists(dup_file)
            with open(dup_file, 'r') as f:
                assert f.read() == "# Hello"

            # Duplicate again -> doc-copy-1.md
            handler.send_json.reset_mock()
            handler.rfile = io.BytesIO(body)
            handler.do_POST()
            assert os.path.exists(os.path.join(tmp_dir, "doc-copy-1.md"))

    def test_file_op_delete(self):
        handler = self._create_mock_handler(is_auth=True)
        handler.path = "/api/file-op"

        with tempfile.TemporaryDirectory() as tmp_dir:
            to_delete = os.path.join(tmp_dir, "trash.txt")
            with open(to_delete, 'w') as f:
                f.write("trash")

            body = json.dumps({"op": "delete", "path": to_delete}).encode('utf-8')
            handler.headers = {'Content-Length': str(len(body))}
            handler.rfile = io.BytesIO(body)
            handler.do_POST()

            assert not os.path.exists(to_delete)
            call_args = handler.send_json.call_args[0][0]
            assert call_args["success"] is True
            assert call_args["op"] == "delete"

    def test_file_op_security_protected_system_dirs(self):
        handler = self._create_mock_handler(is_auth=True)
        handler.path = "/api/file-op"

        # Attempting to delete /root or /etc must be forbidden
        for bad_path in ["/etc", "/root", "/var", "/"]:
            handler.send_json.reset_mock()
            body = json.dumps({"op": "delete", "path": bad_path}).encode('utf-8')
            handler.headers = {'Content-Length': str(len(body))}
            handler.rfile = io.BytesIO(body)
            handler.do_POST()

            status = handler.send_json.call_args[1].get('status')
            assert status == 403, f"Deleting {bad_path} should return HTTP 403"

    def test_api_view_offset_tail(self):
        handler = self._create_mock_handler(is_auth=True)

        with tempfile.NamedTemporaryFile('w', suffix='.log', delete=False) as f:
            f.write("Line 1\nLine 2\n")
            log_path = f.name

        try:
            # First read at offset 0
            handler.path = f"/api/view?file={urllib.parse.quote(log_path)}&offset=0"
            handler.do_GET()

            handler.send_response.assert_called_with(200)
            headers = {k: v for k, v in [call[0] for call in handler.send_header.call_args_list]}
            assert "X-File-Offset" in headers
            initial_offset = int(headers["X-File-Offset"])
            assert initial_offset > 0
            assert headers["X-Truncated"] == "0"

            # Now append more text to the log file
            with open(log_path, 'a') as f:
                f.write("Line 3 (Appended)\n")

            # Poll starting from previous offset
            handler.send_response.reset_mock()
            handler.send_header.reset_mock()
            handler.wfile.reset_mock()
            handler.path = f"/api/view?file={urllib.parse.quote(log_path)}&offset={initial_offset}"
            handler.do_GET()

            handler.send_response.assert_called_with(200)
            headers_2 = {k: v for k, v in [call[0] for call in handler.send_header.call_args_list]}
            new_offset = int(headers_2["X-File-Offset"])
            assert new_offset > initial_offset

            # Chunk written should be the appended text
            written_bytes = b"".join(call[0][0] for call in handler.wfile.write.call_args_list)
            assert b"Line 3 (Appended)" in written_bytes
        finally:
            if os.path.exists(log_path):
                os.remove(log_path)

    def test_html_template_contains_all_ui_elements(self):
        assert 'id="term-search-bar"' in HTML_TEMPLATE
        assert 'id="term-search-input"' in HTML_TEMPLATE
        assert 'id="file-modal-find-bar"' in HTML_TEMPLATE
        assert 'id="file-modal-find-input"' in HTML_TEMPLATE
        assert 'id="file-modal-find-btn"' in HTML_TEMPLATE
        assert 'id="file-modal-follow-btn"' in HTML_TEMPLATE
        assert 'id="file-modal-dir-view-btn"' in HTML_TEMPLATE
        assert 'id="file-modal-dir-bookmark-btn"' in HTML_TEMPLATE
        assert 'id="file-modal-dir-bookmarks-btn"' in HTML_TEMPLATE
        assert 'id="file-modal-dir-new-btn"' in HTML_TEMPLATE
        assert 'id="file-modal-dir-drop-overlay"' in HTML_TEMPLATE
        assert 'id="file-modal-prompt-dialog"' in HTML_TEMPLATE
        assert 'xterm-addon-search' in HTML_TEMPLATE
