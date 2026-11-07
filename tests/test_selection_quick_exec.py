import os
import sys
import json
import io
from unittest.mock import MagicMock, patch

# Add app directory to sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))

from fire_ssh import FireSSHServerHandler, HTML_TEMPLATE


class TestSelectionQuickExecFrontend:
    def test_html_template_contains_selection_menu(self):
        assert 'id="terminal-selection-menu"' in HTML_TEMPLATE
        assert 'id="term-sel-btn-run"' in HTML_TEMPLATE
        assert 'id="term-sel-btn-copy"' in HTML_TEMPLATE
        assert 'runSelectionCommand' in HTML_TEMPLATE
        assert 'copySelectionText' in HTML_TEMPLATE
        assert 'showTerminalSelectionMenu' in HTML_TEMPLATE
        assert 'hideTerminalSelectionMenu' in HTML_TEMPLATE

    def test_html_template_contains_quick_exec_modal(self):
        assert 'id="quick-exec-modal"' in HTML_TEMPLATE
        assert 'id="quick-exec-input"' in HTML_TEMPLATE
        assert 'id="quick-exec-output"' in HTML_TEMPLATE
        assert 'id="quick-exec-badge"' in HTML_TEMPLATE
        assert 'id="quick-exec-kill-btn"' in HTML_TEMPLATE
        assert 'openQuickExecModal' in HTML_TEMPLATE
        assert 'closeQuickExecModal' in HTML_TEMPLATE
        assert 'rerunQuickExec' in HTML_TEMPLATE
        assert 'executeQuickCommand' in HTML_TEMPLATE
        assert 'killQuickExec' in HTML_TEMPLATE


class TestQuickExecBackendAPI:
    def test_quick_exec_requires_authentication(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.headers = {'Content-Length': '0'}
        handler.is_authenticated = MagicMock(return_value=False)
        handler.send_json = MagicMock()
        handler.path = "/api/quick-exec"

        handler.do_POST()

        handler.send_json.assert_called_once()
        args, kwargs = handler.send_json.call_args
        assert kwargs.get("status") == 401
        assert "Unauthorized" in args[0]["error"]

    def test_quick_exec_runs_command_and_streams_chunked_output(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.is_authenticated = MagicMock(return_value=True)
        handler.get_auth_token = MagicMock(return_value="valid-token")
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = io.BytesIO()
        handler.server = MagicMock()
        handler.server.quick_procs = {}
        handler.server.quick_procs_lock = None
        handler.server.terminals.get.return_value = None

        payload = json.dumps({"command": "echo 'quick_runner_test_string'", "tab": "default"}).encode('utf-8')
        handler.headers = {'Content-Length': str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        handler.path = "/api/quick-exec"

        handler.do_POST()

        handler.send_response.assert_called_with(200)
        headers_sent = [call[0] for call in handler.send_header.call_args_list]
        content_type = next(h[1] for h in headers_sent if h[0] == "Content-Type")
        transfer_enc = next(h[1] for h in headers_sent if h[0] == "Transfer-Encoding")
        assert content_type == "text/plain; charset=utf-8"
        assert transfer_enc == "chunked"

        raw_output = handler.wfile.getvalue().decode('utf-8', errors='ignore')
        assert "quick_runner_test_string" in raw_output
        assert "Process completed: exit code 0" in raw_output

    def test_quick_exec_kill_endpoint(self):
        import signal
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.is_authenticated = MagicMock(return_value=True)
        handler.get_auth_token = MagicMock(return_value="valid-token")
        handler.send_json = MagicMock()
        handler.server = MagicMock()

        # Mock a running process with valid integer PID > 1
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 54321
        handler.server.quick_procs = {"test_exec_id": mock_proc}
        handler.server.quick_procs_lock = None

        payload = json.dumps({"id": "test_exec_id"}).encode('utf-8')
        handler.headers = {'Content-Length': str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        handler.path = "/api/quick-exec/kill"

        with patch('os.getpgid', return_value=54321), patch('os.killpg') as mock_killpg:
            handler.do_POST()
            mock_killpg.assert_called_once_with(54321, signal.SIGTERM)

        handler.send_json.assert_called_once()
        args, kwargs = handler.send_json.call_args
        assert args[0]["success"] is True

    def test_quick_exec_kill_endpoint_safe_fallback_on_invalid_pid(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.is_authenticated = MagicMock(return_value=True)
        handler.get_auth_token = MagicMock(return_value="valid-token")
        handler.send_json = MagicMock()
        handler.server = MagicMock()

        # Mock a process with non-int / invalid pid (e.g. MagicMock or 1)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 1  # init / systemd must never be signaled via killpg
        handler.server.quick_procs = {"test_exec_id": mock_proc}
        handler.server.quick_procs_lock = None

        payload = json.dumps({"id": "test_exec_id"}).encode('utf-8')
        handler.headers = {'Content-Length': str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        handler.path = "/api/quick-exec/kill"

        with patch('os.killpg') as mock_killpg:
            handler.do_POST()
            mock_killpg.assert_not_called()
            mock_proc.terminate.assert_called_once()

        handler.send_json.assert_called_once()
        args, kwargs = handler.send_json.call_args
        assert args[0]["success"] is True
