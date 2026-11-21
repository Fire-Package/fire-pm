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


class TestDirBrowserBackendStatsAndDepth:
    """Test /api/suggest directory scanning, recursive depth, and folder stats."""

    def test_suggest_returns_sub_counts_for_folders(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.headers = {}
        handler.is_authenticated = MagicMock(return_value=True)
        handler.get_auth_token = MagicMock(return_value="valid-token")
        handler.send_json = MagicMock()
        handler.server = MagicMock()
        handler.server.terminals.get.return_value = None

        with tempfile.TemporaryDirectory() as root_tmp:
            # Create subfolder 'photos' with 2 images and 1 txt file
            photos_dir = os.path.join(root_tmp, "photos")
            os.makedirs(photos_dir, exist_ok=True)
            with open(os.path.join(photos_dir, "img1.png"), "wb") as f:
                f.write(b"fake-png-1")
            with open(os.path.join(photos_dir, "img2.jpg"), "wb") as f:
                f.write(b"fake-jpg-2")
            with open(os.path.join(photos_dir, "notes.txt"), "w") as f:
                f.write("text notes")

            # Create an empty subfolder 'empty_dir'
            empty_dir = os.path.join(root_tmp, "empty_dir")
            os.makedirs(empty_dir, exist_ok=True)

            # Create a root file
            with open(os.path.join(root_tmp, "readme.md"), "w") as f:
                f.write("# Readme")

            # GET /api/suggest?dir=<root_tmp>
            handler.path = f"/api/suggest?dir={urllib.parse.quote(root_tmp)}"
            handler.do_GET()

            handler.send_json.assert_called_once()
            call_args = handler.send_json.call_args[0][0]
            assert call_args["success"] is True
            items = call_args["items"]

            photos_item = next(it for it in items if it["name"] == "photos")
            assert photos_item["is_dir"] is True
            assert photos_item["sub_dirs"] == 0
            assert photos_item["sub_files"] == 3
            assert photos_item["sub_imgs"] == 2

            empty_item = next(it for it in items if it["name"] == "empty_dir")
            assert empty_item["is_dir"] is True
            assert empty_item["sub_dirs"] == 0
            assert empty_item["sub_files"] == 0
            assert empty_item["sub_imgs"] == 0

            readme_item = next(it for it in items if it["name"] == "readme.md")
            assert readme_item["is_dir"] is False
            assert readme_item["size"] > 0
            assert "mtime" in readme_item

    def test_suggest_recursive_depth_3(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.headers = {}
        handler.is_authenticated = MagicMock(return_value=True)
        handler.get_auth_token = MagicMock(return_value="valid-token")
        handler.send_json = MagicMock()
        handler.server = MagicMock()
        handler.server.terminals.get.return_value = None

        with tempfile.TemporaryDirectory() as root_tmp:
            # Level 1: a/
            # Level 2: a/b/
            # Level 3: a/b/c.txt
            level2_dir = os.path.join(root_tmp, "a", "b")
            os.makedirs(level2_dir, exist_ok=True)
            with open(os.path.join(level2_dir, "deep.txt"), "w") as f:
                f.write("deep file")

            # 1. Depth 1 request should only return 'a'
            handler.path = f"/api/suggest?dir={urllib.parse.quote(root_tmp)}&depth=1"
            handler.do_GET()
            items_d1 = handler.send_json.call_args[0][0]["items"]
            assert len(items_d1) == 1
            assert items_d1[0]["name"] == "a"

            # 2. Depth 3 request should return 'a', 'b', and 'deep.txt'
            handler.send_json.reset_mock()
            handler.path = f"/api/suggest?dir={urllib.parse.quote(root_tmp)}&depth=3"
            handler.do_GET()
            items_d3 = handler.send_json.call_args[0][0]["items"]
            names = [it["name"] for it in items_d3]
            rel_paths = [it["rel_path"] for it in items_d3]
            assert "a" in names
            assert "b" in names
            assert "deep.txt" in names
            assert os.path.join("a", "b", "deep.txt") in rel_paths


class TestDirBrowserFrontendUI:
    """Verify Directory Browser Toolbar and Controls in HTML_TEMPLATE."""

    def test_directory_browser_dom_components(self):
        assert 'id="file-modal-dir-wrap"' in HTML_TEMPLATE
        assert 'id="file-modal-breadcrumb"' in HTML_TEMPLATE
        assert 'id="file-modal-dir-search"' in HTML_TEMPLATE
        assert 'id="file-modal-dir-search-clear"' in HTML_TEMPLATE
        assert 'id="file-modal-dir-depth-btn"' in HTML_TEMPLATE
        assert 'id="file-modal-dir-dotfiles-btn"' in HTML_TEMPLATE
        assert 'id="file-modal-dir-sort-select"' in HTML_TEMPLATE
        assert 'id="file-modal-dir-list"' in HTML_TEMPLATE
        assert 'id="file-modal-dir-empty"' in HTML_TEMPLATE

    def test_directory_browser_javascript_functions(self):
        assert 'function fuzzyMatch(' in HTML_TEMPLATE
        assert 'function toggleDirDotfiles(' in HTML_TEMPLATE
        assert 'function onDirSortChange(' in HTML_TEMPLATE
        assert 'function toggleDirSearchDepth(' in HTML_TEMPLATE
        assert 'function fetchDirDepthItems(' in HTML_TEMPLATE
        assert 'function applyDirFiltersAndRender(' in HTML_TEMPLATE
        assert 'function onDirSearchInput(' in HTML_TEMPLATE
        assert 'function clearDirSearch(' in HTML_TEMPLATE

    def test_javascript_clean_syntax(self):
        scripts = re.findall(r'<script(?:\s+[^>]*)?>(.*?)</script>', HTML_TEMPLATE, re.DOTALL)
        main_script = next((s for s in scripts if 'function checkAuth' in s), None)
        assert main_script is not None

        proc = subprocess.run(
            ['node', '--check'],
            input=main_script,
            text=True,
            capture_output=True
        )
        assert proc.returncode == 0, f"JavaScript syntax error in HTML_TEMPLATE:\n{proc.stderr}"
