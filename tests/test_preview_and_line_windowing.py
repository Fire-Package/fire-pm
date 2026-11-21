import json
import os
import re
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


class TestTrailingSlashAndRegexMatching:
    """Test regex link provider matching with trailing slashes and line numbers."""

    def test_regex_pattern_matches_trailing_slash_folders(self):
        # Extract rawRegex from HTML_TEMPLATE
        m = re.search(r'const rawRegex = (/(?:[^\n/]|\\/)+/[a-z]*);', HTML_TEMPLATE)
        assert m is not None, "rawRegex should be defined in HTML_TEMPLATE"
        regex_str = m.group(1)

        # Regex flags and pattern
        pattern = r'(?:^|[\s"\'`(\[<])((?:file:\/\/(?:localhost)?\/|[~.A-Za-z0-9_-]*\/)?(?:[A-Za-z0-9_.~%+-]+\/)*[A-Za-z0-9_.~%+-]+(?:\.[A-Za-z0-9_+-]+)?\/?(?::\d+(?::\d+)?)?)(?=[\s"\'`()\[\]<>{},;:!?.#]|$)'
        regex = re.compile(pattern)

        test_cases = [
            ("/root/fire-package-pm/tests/", "/root/fire-package-pm/tests/"),
            ("/root/fire-package-pm/app/", "/root/fire-package-pm/app/"),
            ("./tests/", "./tests/"),
            ("app/fire_ssh.py:4338", "app/fire_ssh.py:4338"),
            ("/root/fire_ssh.py:100:5", "/root/fire_ssh.py:100:5"),
            ("tests/test_image_preview.py", "tests/test_image_preview.py"),
            ("Check directory /root/fire-package-pm/tests/ for details", "/root/fire-package-pm/tests/"),
            ("Error at app/fire_ssh.py:4338 in handler", "app/fire_ssh.py:4338"),
        ]

        for text, expected in test_cases:
            matches = [found.group(1) for found in regex.finditer(text)]
            assert expected in matches, f"Expected {expected} in matches from '{text}', got {matches}"

    def test_parse_candidate_path_logic(self):
        """Verify helper functions parseCandidatePath and cleanCandidatePath in template."""
        assert "function parseCandidatePath(p)" in HTML_TEMPLATE
        assert "function cleanCandidatePath(p)" in HTML_TEMPLATE
        assert "s.replace(/\\/+$/, '')" in HTML_TEMPLATE or "s.replace(/\\/$/, '')" in HTML_TEMPLATE

    def test_html_template_javascript_has_no_syntax_errors(self):
        """Validate that all inline JavaScript in HTML_TEMPLATE compiles without syntax errors."""
        scripts = re.findall(r'<script(?:\s+[^>]*)?>(.*?)</script>', HTML_TEMPLATE, re.DOTALL)
        main_script = next((s for s in scripts if 'function checkAuth' in s), None)
        assert main_script is not None, "Main terminal script must be present in HTML_TEMPLATE"

        import subprocess
        proc = subprocess.run(
            ['node', '--check'],
            input=main_script,
            text=True,
            capture_output=True
        )
        assert proc.returncode == 0, f"JavaScript syntax error in HTML_TEMPLATE:\n{proc.stderr}"


class TestLineWindowingBackend:
    """Test /api/view line windowing and slice headers."""

    def test_line_windowing_slices_file_and_emits_headers(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.headers = {}
        handler.is_authenticated = MagicMock(return_value=True)
        handler.get_auth_token = MagicMock(return_value="valid-token")
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler.server = MagicMock()
        handler.server.terminals.get.return_value = None

        # Create a temp file with 2,000 lines
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp:
            for i in range(1, 2001):
                tmp.write(f"Line {i}: dummy content for line {i}\n")
            tmp_path = tmp.name

        try:
            # Query line 1000 with window 500 (expect lines 500 to 1500)
            handler.path = f"/api/view?file={urllib.parse.quote(tmp_path)}&line=1000&window=500"
            handler.do_GET()

            handler.send_response.assert_called_with(200)
            headers_sent = dict(handler.send_header.call_args_list)
            # Reconstruct header dict from calls
            hdr_dict = {call[0][0]: call[0][1] for call in handler.send_header.call_args_list}

            assert hdr_dict.get("X-Total-Lines") == "2000"
            assert hdr_dict.get("X-Start-Line") == "500"
            assert hdr_dict.get("X-End-Line") == "1500"
            assert hdr_dict.get("X-Has-More-Before") == "1"
            assert hdr_dict.get("X-Has-More-After") == "1"

            # Check written bytes
            written_data = b"".join(call[0][0] for call in handler.wfile.write.call_args_list).decode('utf-8')
            assert "Line 500: dummy content for line 500" in written_data
            assert "Line 1000: dummy content for line 1000" in written_data
            assert "Line 1500: dummy content for line 1500" in written_data
            assert "Line 499:" not in written_data
            assert "Line 1501:" not in written_data
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_start_and_end_line_parameters(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.headers = {}
        handler.is_authenticated = MagicMock(return_value=True)
        handler.get_auth_token = MagicMock(return_value="valid-token")
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler.server = MagicMock()
        handler.server.terminals.get.return_value = None

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp:
            for i in range(1, 101):
                tmp.write(f"Record #{i}\n")
            tmp_path = tmp.name

        try:
            handler.path = f"/api/view?file={urllib.parse.quote(tmp_path)}&start_line=1&end_line=25"
            handler.do_GET()

            handler.send_response.assert_called_with(200)
            hdr_dict = {call[0][0]: call[0][1] for call in handler.send_header.call_args_list}
            assert hdr_dict.get("X-Total-Lines") == "100"
            assert hdr_dict.get("X-Start-Line") == "1"
            assert hdr_dict.get("X-End-Line") == "25"
            assert hdr_dict.get("X-Has-More-Before") == "0"
            assert hdr_dict.get("X-Has-More-After") == "1"

            written_data = b"".join(call[0][0] for call in handler.wfile.write.call_args_list).decode('utf-8')
            assert "Record #1\n" in written_data
            assert "Record #25\n" in written_data
            assert "Record #26\n" not in written_data
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


class TestFrontendLightboxAndLineWindowingUI:
    """Verify Lightbox gallery and line windowing UI components in HTML_TEMPLATE."""

    def test_image_lightbox_navigation_components(self):
        assert 'id="image-modal-counter"' in HTML_TEMPLATE
        assert 'id="image-modal-folder-badge"' in HTML_TEMPLATE
        assert 'id="image-modal-prev-btn"' in HTML_TEMPLATE
        assert 'id="image-modal-next-btn"' in HTML_TEMPLATE
        assert 'id="image-modal-meta-folder"' in HTML_TEMPLATE
        assert 'function fetchPreviewFolderMedia(' in HTML_TEMPLATE
        assert 'function navigateImagePreview(' in HTML_TEMPLATE
        assert 'currentPreviewFolderMediaList' in HTML_TEMPLATE
        assert 'currentPreviewMediaIndex' in HTML_TEMPLATE
        assert 'ArrowLeft' in HTML_TEMPLATE
        assert 'ArrowRight' in HTML_TEMPLATE

    def test_file_line_windowing_components(self):
        assert 'id="file-modal-target-line-badge"' in HTML_TEMPLATE
        assert 'id="file-modal-window-banner"' in HTML_TEMPLATE
        assert 'function loadEarlierFileLines(' in HTML_TEMPLATE
        assert 'function loadMoreFileLines(' in HTML_TEMPLATE
        assert 'function loadFullFileContent(' in HTML_TEMPLATE
        assert 'currentModalFileStartLine' in HTML_TEMPLATE
        assert 'currentModalFileEndLine' in HTML_TEMPLATE
        assert 'currentModalFileTotalLines' in HTML_TEMPLATE
        assert 'currentModalFileTargetLine' in HTML_TEMPLATE
