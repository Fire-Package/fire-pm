import json
import os
import re
import subprocess
import sys
import pytest

# Add app directory to sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))

from fire_ssh import HTML_TEMPLATE


class TestFileHoverComponents:
    """Verify HTML template structure and UI component presence for file hover quick actions."""

    def test_hover_menu_dom_structure(self):
        # Container
        assert 'id="file-hover-menu"' in HTML_TEMPLATE

        # Header info
        assert 'id="file-hover-icon-box"' in HTML_TEMPLATE
        assert 'id="file-hover-icon"' in HTML_TEMPLATE
        assert 'id="file-hover-thumb"' in HTML_TEMPLATE
        assert 'id="file-hover-name"' in HTML_TEMPLATE
        assert 'id="file-hover-path"' in HTML_TEMPLATE
        assert 'id="file-hover-badge"' in HTML_TEMPLATE

        # 4 Required Action buttons (+ View Image for images)
        assert 'id="file-hover-btn-cat"' in HTML_TEMPLATE
        assert 'id="file-hover-btn-edit"' in HTML_TEMPLATE
        assert 'id="file-hover-btn-img"' in HTML_TEMPLATE
        assert 'id="file-hover-btn-copy"' in HTML_TEMPLATE
        assert 'id="file-hover-btn-dl"' in HTML_TEMPLATE

    def test_hover_menu_javascript_functions(self):
        assert 'function registerFileLinkProvider(' in HTML_TEMPLATE
        assert 'function getFileCategory(' in HTML_TEMPLATE
        assert 'function isPathValidCandidate(' in HTML_TEMPLATE
        assert 'function quoteShellArg(' in HTML_TEMPLATE
        assert 'function openTabWithCommand(' in HTML_TEMPLATE
        assert 'function showFileHoverMenu(' in HTML_TEMPLATE
        assert 'function hideFileHoverMenu(' in HTML_TEMPLATE


class TestFileHoverLogicWithNode:
    """Execute the exact JS helper functions extracted from HTML_TEMPLATE in Node.js to verify behavior."""

    @classmethod
    def setup_class(cls):
        # Extract JS helper functions from HTML_TEMPLATE
        match = re.search(r'(const BLOCKED_EXTENSIONS = new Set\(.*?\n\s*const registerImageLinkProvider = registerFileLinkProvider;)', HTML_TEMPLATE, re.DOTALL)
        assert match is not None, "Could not extract file hover JS block from HTML_TEMPLATE"
        cls.js_helpers = match.group(1)

    def _eval_js(self, js_expr: str):
        script = f"""
        {self.js_helpers}
        const result = ({js_expr});
        console.log(JSON.stringify(result));
        """
        proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
        return json.loads(proc.stdout.strip())

    def test_file_category_blocked_archives(self):
        archives = ["archive.zip", "bundle.tar", "data.tar.gz", "pkg.tgz", "archive.bz2", "rootfs.xz", "backup.7z", "disk.iso", "old.rar"]
        for fn in archives:
            res = self._eval_js(f"getFileCategory('{fn}')")
            assert res["badge"] == "ARCHIVE", f"{fn} should have ARCHIVE badge"
            assert res["canCat"] is False, f"{fn} must be blocked from cat"
            assert res["canEdit"] is False, f"{fn} must be blocked from nano"
            assert res["isImage"] is False

    def test_file_category_blocked_videos(self):
        videos = ["movie.mp4", "clip.mkv", "screencast.avi", "video.mov", "stream.webm", "recording.flv"]
        for fn in videos:
            res = self._eval_js(f"getFileCategory('{fn}')")
            assert res["badge"] == "VIDEO", f"{fn} should have VIDEO badge"
            assert res["canCat"] is False, f"{fn} must be blocked from cat"
            assert res["canEdit"] is False, f"{fn} must be blocked from nano"
            assert res["isImage"] is False

    def test_file_category_blocked_audio(self):
        audio_files = ["song.mp3", "track.wav", "audio.ogg", "sample.flac", "podcast.m4a", "sound.aac"]
        for fn in audio_files:
            res = self._eval_js(f"getFileCategory('{fn}')")
            assert res["badge"] == "AUDIO", f"{fn} should have AUDIO badge"
            assert res["canCat"] is False, f"{fn} must be blocked from cat"
            assert res["canEdit"] is False, f"{fn} must be blocked from nano"

    def test_file_category_blocked_binaries_and_executables(self):
        binaries = ["program.exe", "library.so", "lib.dll", "module.dylib", "kernel.bin", "main.o", "libstatic.a", "compiled.pyc", "engine.wasm"]
        for fn in binaries:
            res = self._eval_js(f"getFileCategory('{fn}')")
            assert res["badge"] == "BINARY", f"{fn} should have BINARY badge"
            assert res["canCat"] is False, f"{fn} must be blocked from cat"
            assert res["canEdit"] is False, f"{fn} must be blocked from nano"

    def test_file_category_blocked_package_installers(self):
        pkgs = ["installer.dmg", "package.deb", "package.rpm", "app.apk", "setup.msi"]
        for fn in pkgs:
            res = self._eval_js(f"getFileCategory('{fn}')")
            assert res["badge"] == "ARCHIVE", f"{fn} should have ARCHIVE badge"
            assert res["canCat"] is False, f"{fn} must be blocked from cat"
            assert res["canEdit"] is False, f"{fn} must be blocked from nano"

    def test_file_category_images_allowed_for_lightbox(self):
        images = ["photo.png", "image.jpg", "pic.jpeg", "anim.gif", "icon.webp", "vector.svg", "graphic.bmp", "favicon.ico"]
        for fn in images:
            res = self._eval_js(f"getFileCategory('{fn}')")
            assert res["isImage"] is True, f"{fn} should be classified as image"
            assert res["canCat"] is False, f"{fn} image should not be dumped to terminal with cat"
            assert res["canEdit"] is False, f"{fn} image should not be opened with nano"

    def test_file_category_allowed_text_and_code(self):
        code_files = [
            "script.py", "index.js", "app.ts", "package.json", "README.md",
            "deploy.sh", "notes.txt", "styles.css", "page.html", "main.rs",
            "server.go", "native.c", "engine.cpp", "docker-compose.yml", "config.yaml"
        ]
        for fn in code_files:
            res = self._eval_js(f"getFileCategory('{fn}')")
            assert res["canCat"] is True, f"{fn} should allow cat"
            assert res["canEdit"] is True, f"{fn} should allow nano edit"
            assert res["isImage"] is False

    def test_file_category_dotfiles_and_special_files(self):
        special_files = [".bashrc", ".env", ".gitignore", "Dockerfile", "Makefile"]
        for fn in special_files:
            res = self._eval_js(f"getFileCategory('{fn}')")
            assert res["canCat"] is True, f"{fn} should allow cat"
            assert res["canEdit"] is True, f"{fn} should allow nano edit"

    def test_is_path_valid_candidate(self):
        # Valid candidates
        valid_paths = [
            "/root/fire-package-pm/app/fire_ssh.py",
            "./src/index.ts",
            "../config.json",
            "~/.bashrc",
            "Dockerfile",
            "Makefile",
            "/var/log/syslog",
            "data/users.csv"
        ]
        for p in valid_paths:
            assert self._eval_js(f"isPathValidCandidate({json.dumps(p)})") is True, f"{p} should be valid candidate"

        # Invalid candidates
        invalid_paths = [
            "https://example.com/index.html",
            "http://127.0.0.1:7683/api/download",
            "--port",
            "-la",
            "127.0.0.1",
            "192.0.2.1",
            "7683",
            "hello",
            "some-random-word"
        ]
        for p in invalid_paths:
            assert self._eval_js(f"isPathValidCandidate({json.dumps(p)})") is False, f"{p} should be rejected as path candidate"

    def test_quote_shell_arg(self):
        assert self._eval_js("quoteShellArg('simple.txt')") == '"simple.txt"'
        assert self._eval_js("quoteShellArg('file with spaces.txt')") == '"file with spaces.txt"'
        assert self._eval_js("quoteShellArg('~/projects/app.js')") == '~/"projects/app.js"'
        assert self._eval_js('quoteShellArg(\'foo"bar.txt\')') == '"foo\\"bar.txt"'
