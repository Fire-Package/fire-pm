import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import urllib.parse
from unittest.mock import MagicMock

import pytest

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "tui"))

from fire_ssh import FireSSHServerHandler, HTML_TEMPLATE, TerminalSessionManager
import fire_tui


def _make_handler(is_auth=True):
    handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
    handler.client_address = ("127.0.0.1", 12345)
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


class TestFireSSHHardening:
    def test_large_file_allows_line_window_and_offset_tail_but_rejects_full_view(self):
        handler = _make_handler(is_auth=True)
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".log", delete=False) as tmp:
            # Create a ~5.3 MB text log file
            line = b"2026-11-24 INFO sample log line for testing windowing and tailing\n"
            tmp.write(line * 85000)
            log_path = tmp.name

        try:
            # Unwindowed /api/view still returns 413 FILE_TOO_LARGE
            handler.path = f"/api/view?file={urllib.parse.quote(log_path)}"
            handler.do_GET()
            assert handler.send_json.call_args[1]["status"] == 413

            # Line-windowed /api/view succeeds on >5MB file
            handler.send_json.reset_mock()
            handler.send_response.reset_mock()
            handler.send_header.reset_mock()
            handler.wfile.reset_mock()
            handler.path = f"/api/view?file={urllib.parse.quote(log_path)}&start_line=10&end_line=20"
            handler.do_GET()
            handler.send_response.assert_called_with(200)
            hdrs = {c[0][0]: c[0][1] for c in handler.send_header.call_args_list}
            assert hdrs.get("X-Start-Line") == "10"
            assert hdrs.get("X-End-Line") == "20"

            # Offset tailing succeeds on >5MB file
            handler.send_response.reset_mock()
            handler.send_header.reset_mock()
            handler.wfile.reset_mock()
            size = os.path.getsize(log_path)
            handler.path = f"/api/view?file={urllib.parse.quote(log_path)}&offset={size - len(line)}"
            handler.do_GET()
            handler.send_response.assert_called_with(200)
            written = b"".join(c[0][0] for c in handler.wfile.write.call_args_list)
            assert written == line
        finally:
            if os.path.exists(log_path):
                os.remove(log_path)

    def test_stream_multipart_upload_writes_files_and_cleans_up_errors(self):
        handler = _make_handler(is_auth=True)
        boundary = "----FirePMTestBoundary123"
        payload = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="hello.txt"\r\n'
            f"Content-Type: text/plain\r\n\r\n"
            f"hello world\n"
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file2"; filename="../escape.bin"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
            f"BIN\x00DATA"
            f"\r\n--{boundary}--\r\n"
        ).encode("latin-1")

        with tempfile.TemporaryDirectory() as tmpdir:
            handler.path = f"/api/upload?dest={urllib.parse.quote(tmpdir)}"
            handler.headers = {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(payload)),
            }
            handler.rfile = io.BytesIO(payload)
            handler.do_POST()

            resp = handler.send_json.call_args[0][0]
            assert resp["success"] is True
            assert len(resp["files"]) == 2
            assert open(os.path.join(tmpdir, "hello.txt"), "rb").read() == b"hello world\n"
            assert open(os.path.join(tmpdir, "escape.bin"), "rb").read() == b"BIN\x00DATA"

    def test_negative_and_invalid_content_length_rejected(self):
        for bad_len in ["-5", "not-a-number"]:
            handler = _make_handler(is_auth=True)
            handler.path = "/api/file-op"
            handler.headers = {"Content-Length": bad_len}
            handler.rfile = io.BytesIO(b"{}")
            handler.do_POST()
            assert handler.send_json.call_args[1]["status"] == 400

    def test_file_op_symlink_delete_and_rename_do_not_destroy_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = os.path.join(tmpdir, "real-folder")
            os.makedirs(target_dir)
            secret_file = os.path.join(target_dir, "keep.txt")
            with open(secret_file, "w") as f:
                f.write("important")

            link_path = os.path.join(tmpdir, "folder-link")
            os.symlink(target_dir, link_path)

            # Rename symlink itself
            handler = _make_handler(is_auth=True)
            handler.path = "/api/file-op"
            body = json.dumps({"op": "rename", "path": link_path, "new_name": "renamed-link"}).encode("utf-8")
            handler.headers = {"Content-Length": str(len(body))}
            handler.rfile = io.BytesIO(body)
            handler.do_POST()
            assert handler.send_json.call_args[0][0]["success"] is True
            renamed_link = os.path.join(tmpdir, "renamed-link")
            assert os.path.islink(renamed_link)
            assert os.path.isdir(target_dir)

            # Delete symlink removes link without removing target directory contents
            handler.send_json.reset_mock()
            body = json.dumps({"op": "delete", "path": renamed_link}).encode("utf-8")
            handler.headers = {"Content-Length": str(len(body))}
            handler.rfile = io.BytesIO(body)
            handler.do_POST()
            assert handler.send_json.call_args[0][0]["success"] is True
            assert not os.path.lexists(renamed_link)
            assert os.path.exists(secret_file)

            # Protected critical system subdirs blocked
            for protected in ["/etc/systemd", "/usr/bin"]:
                handler.send_json.reset_mock()
                body = json.dumps({"op": "delete", "path": protected}).encode("utf-8")
                handler.headers = {"Content-Length": str(len(body))}
                handler.rfile = io.BytesIO(body)
                handler.do_POST()
                assert handler.send_json.call_args[1]["status"] == 403

    def test_sqlite_tables_handles_double_quotes_in_table_name(self):
        handler = _make_handler(is_auth=True)
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            conn = sqlite3.connect(db_path)
            conn.execute('CREATE TABLE "weird""table" (id INTEGER PRIMARY KEY, name TEXT);')
            conn.execute('INSERT INTO "weird""table" (name) VALUES ("ok");')
            conn.commit()
            conn.close()

            handler.path = f"/api/db/tables?file={urllib.parse.quote(db_path)}"
            handler.do_GET()
            resp = handler.send_json.call_args[0][0]
            assert resp["success"] is True
            assert resp["tables"][0]["name"] == 'weird"table'
            assert resp["tables"][0]["count"] == 1
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_reaper_loop_stops_and_handles_mock_sessions(self):
        mgr = TerminalSessionManager()
        mock_sess = MagicMock()
        mock_sess.is_alive.return_value = True
        mock_sess.interactive_socks = set()
        mock_sess.readonly_socks = set()
        with mgr.lock:
            mgr.sessions["tab-1"] = mock_sess
        mgr.stop()
        mgr.reaper_thread.join(timeout=6)
        assert not mgr.reaper_thread.is_alive()

    def test_handle_websocket_exits_when_session_invalidated(self):
        handler = _make_handler(is_auth=True)
        sock = MagicMock()
        handler.connection = sock
        mock_session = MagicMock()
        mock_session.is_alive.return_value = True
        handler.server.terminals.get_or_create.return_value = mock_session
        handler.server.sessions.is_valid.return_value = False

        handler.handle_websocket("revoked-token", "tab-1")
        mock_session.detach_socket.assert_called_once_with(sock)
        assert sock.sendall.called

    def test_html_template_markdown_sanitizer_and_no_nested_buttons(self):
        assert "function sanitizeMarkdownHtml(" in HTML_TEMPLATE
        assert "return sanitizeMarkdownHtml(parseGitHubAlerts(rendered));" in HTML_TEMPLATE
        # Grid cards use div[role="button"] instead of nested <button> inside <button>
        m = re.search(r"function renderDirListing\(items, dirPath\)([\s\S]*?)function renderBinaryModalCard", HTML_TEMPLATE)
        assert m is not None
        assert "const card = document.createElement('div');" in m.group(1)
        assert "card.setAttribute('role', 'button');" in m.group(1)


class TestCLIFlagsAndTUIHelpers:
    def test_cli_parse_args_supports_watch_reload_memory_cpu(self):
        with open(os.path.join(PROJECT_ROOT, "app", "fire"), "r", encoding="utf-8") as f:
            cli_src = f.read()

        match = re.search(r'(NAME_OPT=""[\s\S]*?\nparse_args\(\)\s*\{[\s\S]*?\n\})', cli_src)
        assert match is not None
        fn_code = match.group(1)

        script = f"""
        set -e
        CMD="start"
        {fn_code}
        parse_args app.py --name api --memory 512M --cpu 75% --watch --reload
        [[ "$NAME_OPT" == "api" ]]
        [[ "$MEM_OPT" == "512M" ]]
        [[ "$CPU_OPT" == "75%" ]]
        [[ "$WATCH_OPT" == "always" ]]
        [[ "$RELOAD_OPT" == "1" ]]

        WATCH_OPT=""; RELOAD_OPT=0; MEM_OPT=""; CPU_OPT=""; ARGS=()
        parse_args app.py --no-watch --mem=1G --cpu=50%
        [[ "$WATCH_OPT" == "no" ]]
        [[ "$MEM_OPT" == "1G" ]]
        [[ "$CPU_OPT" == "50%" ]]
        """
        proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr

    def test_cli_ssh_port_boundary_and_password_env(self):
        with open(os.path.join(PROJECT_ROOT, "app", "fire"), "r", encoding="utf-8") as f:
            cli_src = f.read()
        assert '--port ${port}([[:space:]]|$)' in cli_src
        assert 'FIRE_SSH_PASSWORD' in cli_src

    def test_tui_parse_mem_bytes_units(self):
        assert fire_tui._parse_mem_bytes("512KB") == 512 * 1024
        assert fire_tui._parse_mem_bytes("10.0MB") == 10 * 1024 * 1024
        assert fire_tui._parse_mem_bytes("1.5GB") == int(1.5 * 1024 ** 3)
        assert fire_tui._parse_mem_bytes("invalid") == 0
