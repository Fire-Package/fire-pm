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


class TestMediaPreviewEndpoint:
    def test_mp4_preview_serves_inline_headers_and_accept_ranges(self):
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

        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp_vid:
            tmp_vid.write(b'fake-mp4-video-stream-content-bytes-for-preview-testing')
            tmp_path = tmp_vid.name

        try:
            # 1. GET /api/preview
            handler.path = f"/api/preview?file={urllib.parse.quote(tmp_path)}"
            handler.do_GET()

            handler.send_response.assert_called_with(200)
            headers_sent = [call[0] for call in handler.send_header.call_args_list]
            content_type = next(h[1] for h in headers_sent if h[0] == "Content-Type")
            content_disp = next(h[1] for h in headers_sent if h[0] == "Content-Disposition")
            accept_ranges = next(h[1] for h in headers_sent if h[0] == "Accept-Ranges")
            assert content_type == "video/mp4"
            assert content_disp.startswith("inline;")
            assert accept_ranges == "bytes"
            assert f'{os.path.basename(tmp_path)}"' in content_disp

            # 2. HEAD /api/preview
            handler.send_response.reset_mock()
            handler.send_header.reset_mock()
            handler.do_HEAD()

            handler.send_response.assert_called_with(200)
            head_headers = [call[0] for call in handler.send_header.call_args_list]
            head_type = next(h[1] for h in head_headers if h[0] == "Content-Type")
            head_disp = next(h[1] for h in head_headers if h[0] == "Content-Disposition")
            head_ranges = next(h[1] for h in head_headers if h[0] == "Accept-Ranges")
            assert head_type == "video/mp4"
            assert head_disp.startswith("inline;")
            assert head_ranges == "bytes"
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_mp4_range_request_partial_content_206(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.is_authenticated = MagicMock(return_value=True)
        handler.get_auth_token = MagicMock(return_value="valid-token")
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler.server = MagicMock()
        handler.server.terminals.get.return_value = None

        dummy_bytes = b'0123456789' * 10  # 100 bytes total
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp_vid:
            tmp_vid.write(dummy_bytes)
            tmp_path = tmp_vid.name

        try:
            # Range: bytes=0-49 (first 50 bytes)
            handler.headers = {'Range': 'bytes=0-49'}
            handler.path = f"/api/preview?file={urllib.parse.quote(tmp_path)}"
            handler.do_GET()

            handler.send_response.assert_called_with(206)
            headers_sent = [call[0] for call in handler.send_header.call_args_list]
            content_range = next(h[1] for h in headers_sent if h[0] == "Content-Range")
            content_len = next(h[1] for h in headers_sent if h[0] == "Content-Length")
            assert content_range == "bytes 0-49/100"
            assert content_len == "50"

            written_bytes = b''.join(call[0][0] for call in handler.wfile.write.call_args_list)
            assert written_bytes == dummy_bytes[0:50]

            # Range: bytes=-20 (suffix range: last 20 bytes)
            handler.send_response.reset_mock()
            handler.send_header.reset_mock()
            handler.wfile.reset_mock()
            handler.headers = {'Range': 'bytes=-20'}
            handler.do_GET()

            handler.send_response.assert_called_with(206)
            headers_sent_suffix = [call[0] for call in handler.send_header.call_args_list]
            suffix_range = next(h[1] for h in headers_sent_suffix if h[0] == "Content-Range")
            assert suffix_range == "bytes 80-99/100"
            written_suffix = b''.join(call[0][0] for call in handler.wfile.write.call_args_list)
            assert written_suffix == dummy_bytes[80:100]
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_mp4_range_request_out_of_bounds_returns_416(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.is_authenticated = MagicMock(return_value=True)
        handler.get_auth_token = MagicMock(return_value="valid-token")
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler.server = MagicMock()
        handler.server.terminals.get.return_value = None

        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp_vid:
            tmp_vid.write(b'short')
            tmp_path = tmp_vid.name

        try:
            handler.headers = {'Range': 'bytes=50-100'}
            handler.path = f"/api/preview?file={urllib.parse.quote(tmp_path)}"
            handler.do_GET()

            handler.send_response.assert_called_with(416)
            headers_sent = [call[0] for call in handler.send_header.call_args_list]
            content_range = next(h[1] for h in headers_sent if h[0] == "Content-Range")
            assert content_range == "bytes */5"
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


    def test_audio_preview_serves_inline_headers_and_accept_ranges(self):
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

        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_audio:
            tmp_audio.write(b'fake-mp3-audio-bytes-for-preview-testing')
            tmp_path = tmp_audio.name

        try:
            handler.path = f"/api/preview?file={urllib.parse.quote(tmp_path)}"
            handler.do_GET()

            handler.send_response.assert_called_with(200)
            headers_sent = [call[0] for call in handler.send_header.call_args_list]
            content_type = next(h[1] for h in headers_sent if h[0] == "Content-Type")
            content_disp = next(h[1] for h in headers_sent if h[0] == "Content-Disposition")
            accept_ranges = next(h[1] for h in headers_sent if h[0] == "Accept-Ranges")
            assert "audio" in content_type
            assert content_disp.startswith("inline;")
            assert accept_ranges == "bytes"
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


class TestMediaPreviewFrontendIntegration:
    def test_html_template_contains_video_preview_components(self):
        assert 'id="image-modal-video"' in HTML_TEMPLATE
        assert 'VIDEO_EXTENSIONS' in HTML_TEMPLATE
        assert 'Preview Video' in HTML_TEMPLATE
        assert 'formatDuration' in HTML_TEMPLATE
        assert 'isVideo' in HTML_TEMPLATE
        assert 'Space to play/pause' in HTML_TEMPLATE
        assert 'id="image-modal-zoom-group"' in HTML_TEMPLATE
        assert 'id="image-modal-pip-btn"' in HTML_TEMPLATE
        assert 'toggleModalPictureInPicture' in HTML_TEMPLATE

    def test_html_template_contains_audio_preview_components(self):
        assert 'id="image-modal-audio-box"' in HTML_TEMPLATE
        assert 'id="image-modal-audio"' in HTML_TEMPLATE
        assert 'AUDIO_EXTENSIONS' in HTML_TEMPLATE
        assert 'Play Audio' in HTML_TEMPLATE
        assert 'isAudio' in HTML_TEMPLATE

    def test_html_template_contains_listener_leak_and_race_prevention(self):
        assert 'activePreviewSeq' in HTML_TEMPLATE
        assert 'resetMediaModalState' in HTML_TEMPLATE
        assert 'img.onload = null;' in HTML_TEMPLATE
        assert 'img.onerror = null;' in HTML_TEMPLATE
        assert 'img.removeAttribute(\'src\');' in HTML_TEMPLATE
        assert 'videoEl.removeAttribute(\'src\');' in HTML_TEMPLATE
        assert 'reqId !== activePreviewSeq' in HTML_TEMPLATE
