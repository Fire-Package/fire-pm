import os
import sys
import tempfile
import urllib.parse
from unittest.mock import MagicMock

# Add app directory to sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))

from fire_ssh import FireSSHServerHandler, HTML_TEMPLATE


class TestImagePreviewEndpoint:
    def test_preview_serves_inline_image_headers(self):
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

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_img:
            # Minimal 1x1 PNG bytes
            tmp_img.write(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4')
            tmp_path = tmp_img.name

        try:
            # 1. GET /api/preview
            handler.path = f"/api/preview?file={urllib.parse.quote(tmp_path)}"
            handler.do_GET()

            handler.send_response.assert_called_with(200)
            headers_sent = [call[0] for call in handler.send_header.call_args_list]
            content_type = next(h[1] for h in headers_sent if h[0] == "Content-Type")
            content_disp = next(h[1] for h in headers_sent if h[0] == "Content-Disposition")
            assert content_type == "image/png"
            assert content_disp.startswith("inline;")
            assert f'{os.path.basename(tmp_path)}"' in content_disp

            # 2. HEAD /api/preview
            handler.send_response.reset_mock()
            handler.send_header.reset_mock()
            handler.do_HEAD()

            handler.send_response.assert_called_with(200)
            head_headers = [call[0] for call in handler.send_header.call_args_list]
            head_type = next(h[1] for h in head_headers if h[0] == "Content-Type")
            head_disp = next(h[1] for h in head_headers if h[0] == "Content-Disposition")
            assert head_type == "image/png"
            assert head_disp.startswith("inline;")

            # 3. GET /api/download?file=...&inline=1
            handler.send_response.reset_mock()
            handler.send_header.reset_mock()
            handler.path = f"/api/download?file={urllib.parse.quote(tmp_path)}&inline=1"
            handler.do_GET()

            handler.send_response.assert_called_with(200)
            dl_headers = [call[0] for call in handler.send_header.call_args_list]
            dl_disp = next(h[1] for h in dl_headers if h[0] == "Content-Disposition")
            assert dl_disp.startswith("inline;")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_preview_nonexistent_returns_404(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.headers = {}
        handler.is_authenticated = MagicMock(return_value=True)
        handler.get_auth_token = MagicMock(return_value="valid-token")
        handler.send_json = MagicMock()
        handler.server = MagicMock()
        handler.server.terminals.get.return_value = None

        handler.path = "/api/preview?file=/nonexistent/path/image.png"
        handler.do_GET()
        handler.send_json.assert_called_once_with({"success": False, "error": "Path not found: /nonexistent/path/image.png"}, status=404)

    def test_preview_unauthorized_returns_401(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.headers = {}
        handler.is_authenticated = MagicMock(return_value=False)
        handler.send_json = MagicMock()

        handler.path = "/api/preview?file=/some/image.png"
        handler.do_GET()
        handler.send_json.assert_called_once_with({"success": False, "error": "Unauthorized session"}, status=401)


class TestImagePreviewFrontendIntegration:
    def test_html_template_contains_image_preview_components(self):
        assert 'id="image-preview-modal"' in HTML_TEMPLATE
        assert 'id="image-hover-card"' in HTML_TEMPLATE
        assert 'id="image-output-chip"' in HTML_TEMPLATE
        assert 'registerImageLinkProvider' in HTML_TEMPLATE
        assert 'openImagePreviewModal' in HTML_TEMPLATE
        assert 'detectImageOutputInChunk' in HTML_TEMPLATE
        assert 'setupImageViewerInteractions' in HTML_TEMPLATE
