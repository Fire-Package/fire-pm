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

from fire_ssh import FireSSHServerHandler, HTML_TEMPLATE, resolve_fs_path


class TestFileHoverComponents:
    """Verify HTML template structure and UI component presence for file hover quick actions and content modal."""

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

        # Action buttons (Cat, Edit, Directory Open in Tab, View Image, Copy, Download)
        assert 'id="file-hover-btn-cat"' in HTML_TEMPLATE
        assert 'id="file-hover-btn-edit"' in HTML_TEMPLATE
        assert 'id="file-hover-btn-dir"' in HTML_TEMPLATE
        assert 'id="file-hover-btn-img"' in HTML_TEMPLATE
        assert 'id="file-hover-btn-copy"' in HTML_TEMPLATE
        assert 'id="file-hover-btn-dl"' in HTML_TEMPLATE

    def test_file_content_modal_dom_structure(self):
        # In-tab file content modal dialog
        assert 'id="file-content-modal"' in HTML_TEMPLATE
        assert 'id="file-modal-icon"' in HTML_TEMPLATE
        assert 'id="file-modal-title"' in HTML_TEMPLATE
        assert 'id="file-modal-line-badge"' in HTML_TEMPLATE
        assert 'id="file-modal-size-badge"' in HTML_TEMPLATE
        assert 'id="file-modal-path"' in HTML_TEMPLATE

        # Modal action buttons
        assert 'id="file-modal-edit-btn"' in HTML_TEMPLATE
        assert 'id="file-modal-tab-btn"' not in HTML_TEMPLATE
        assert 'id="file-modal-copy-label"' in HTML_TEMPLATE

        # Viewport, line numbers, and pre code
        assert 'id="file-modal-viewport"' in HTML_TEMPLATE
        assert 'id="file-modal-spinner"' in HTML_TEMPLATE
        assert 'id="file-modal-error"' in HTML_TEMPLATE
        assert 'id="file-modal-line-numbers"' in HTML_TEMPLATE
        assert 'id="file-modal-code-text"' in HTML_TEMPLATE

    def test_file_content_modal_html_preview_components(self):
        assert 'id="file-modal-view-mode"' in HTML_TEMPLATE
        assert 'id="file-modal-btn-code"' in HTML_TEMPLATE
        assert 'id="file-modal-btn-preview"' in HTML_TEMPLATE
        assert 'id="file-modal-open-tab-btn"' in HTML_TEMPLATE
        assert 'id="file-modal-preview-wrap"' in HTML_TEMPLATE
        assert 'id="file-modal-preview-frame"' in HTML_TEMPLATE
        assert 'function setFileModalViewMode(' in HTML_TEMPLATE
        assert 'function openModalFileInBrowser(' in HTML_TEMPLATE

    def test_file_content_modal_markdown_preview_components(self):
        assert 'id="file-modal-markdown-wrap"' in HTML_TEMPLATE
        assert 'id="file-modal-markdown-body"' in HTML_TEMPLATE
        assert 'class="markdown-body"' in HTML_TEMPLATE
        assert 'github-markdown-dark.min.css' in HTML_TEMPLATE
        assert 'marked.min.js' in HTML_TEMPLATE
        assert 'function renderMarkdownContent(' in HTML_TEMPLATE
        assert 'function parseGitHubAlerts(' in HTML_TEMPLATE
        assert 'function renderMarkdownFallback(' in HTML_TEMPLATE

    def test_file_modal_dir_components(self):
        assert 'id="file-modal-dir-wrap"' in HTML_TEMPLATE
        assert 'id="file-modal-breadcrumb"' in HTML_TEMPLATE
        assert 'id="file-modal-dir-list"' in HTML_TEMPLATE
        assert 'id="file-modal-dir-empty"' in HTML_TEMPLATE
        assert 'id="file-modal-cd-btn"' in HTML_TEMPLATE
        assert 'id="file-modal-copy-btn"' in HTML_TEMPLATE
        assert 'id="file-modal-dl-btn"' in HTML_TEMPLATE
        assert 'function openModalDirInTab(' in HTML_TEMPLATE
        assert 'function openFolderInModal(' in HTML_TEMPLATE
        assert 'function buildBreadcrumb(' in HTML_TEMPLATE
        assert 'function renderDirListing(' in HTML_TEMPLATE

    def test_file_modal_syntax_highlighting_components(self):
        assert 'highlight.js@11.9.0' in HTML_TEMPLATE
        assert 'github-dark.min.css' in HTML_TEMPLATE
        assert 'function getLanguageFromPath(' in HTML_TEMPLATE
        assert 'function getLanguageLabel(' in HTML_TEMPLATE
        assert '#file-modal-code-text .hljs' in HTML_TEMPLATE

    def test_hover_menu_javascript_functions(self):
        assert 'function registerFileLinkProvider(' in HTML_TEMPLATE
        assert 'function getFileCategory(' in HTML_TEMPLATE
        assert 'function cleanCandidatePath(' in HTML_TEMPLATE
        assert 'function isPathValidCandidate(' in HTML_TEMPLATE
        assert 'function quoteShellArg(' in HTML_TEMPLATE
        assert 'function openTabWithCommand(' in HTML_TEMPLATE
        assert 'function fetchPathStat(' in HTML_TEMPLATE
        assert 'function showFileHoverMenu(' in HTML_TEMPLATE
        assert 'function hideFileHoverMenu(' in HTML_TEMPLATE
        assert 'function openFileContentModal(' in HTML_TEMPLATE
        assert 'function closeFileContentModal(' in HTML_TEMPLATE

    def test_cat_tab_action_removed(self):
        # file-modal-tab-btn and openModalFileInNewTab removed in favor of in-tab modal
        assert 'id="file-modal-tab-btn"' not in HTML_TEMPLATE
        assert 'function openModalFileInNewTab(' not in HTML_TEMPLATE
        # cat tab spawning should not be triggered on file hover or activation
        assert 'openTabWithCommand(`cat' not in HTML_TEMPLATE


class TestFileStatEndpoint:
    """Verify backend /api/stat endpoint functionality."""

    def test_stat_regular_text_file(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.headers = {}
        handler.is_authenticated = MagicMock(return_value=True)
        handler.get_auth_token = MagicMock(return_value="valid-token")
        handler.send_json = MagicMock()
        handler.server = MagicMock()
        handler.server.terminals.get.return_value = None

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp:
            tmp.write("line 1\nline 2\nline 3\nline 4\nline 5\n")
            tmp_path = tmp.name

        try:
            handler.path = f"/api/stat?file={urllib.parse.quote(tmp_path)}"
            handler.do_GET()

            handler.send_json.assert_called_once()
            call_args = handler.send_json.call_args[0][0]
            assert call_args["success"] is True
            assert call_args["exists"] is True
            assert call_args["is_file"] is True
            assert call_args["is_dir"] is False
            assert call_args["is_text"] is True
            assert call_args["lines"] == 5
            assert call_args["size"] > 0
            assert call_args["path"] == tmp_path
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_stat_file_uri_scheme(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.headers = {}
        handler.is_authenticated = MagicMock(return_value=True)
        handler.get_auth_token = MagicMock(return_value="valid-token")
        handler.send_json = MagicMock()
        handler.server = MagicMock()
        handler.server.terminals.get.return_value = None

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp:
            tmp.write("hello from file URI")
            tmp_path = tmp.name

        try:
            # Test file:// URI resolution in /api/stat
            file_uri = f"file://{tmp_path}"
            handler.path = f"/api/stat?file={urllib.parse.quote(file_uri)}"
            handler.do_GET()

            handler.send_json.assert_called_once()
            call_args = handler.send_json.call_args[0][0]
            assert call_args["success"] is True
            assert call_args["exists"] is True
            assert call_args["is_file"] is True
            assert call_args["path"] == tmp_path
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_resolve_fs_path_file_uri_schemes(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp:
            tmp_path = tmp.name

        try:
            assert resolve_fs_path("/root", f"file://{tmp_path}") == tmp_path
            assert resolve_fs_path("/root", f"file://localhost{tmp_path}") == tmp_path
            assert resolve_fs_path("/root", f"file://{tmp_path}#L1-L10") == tmp_path
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_view_html_endpoint_raw_and_inline(self):
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

        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as tmp:
            tmp.write("<!DOCTYPE html><html><body><h1>Test HTML</h1></body></html>")
            tmp_path = tmp.name

        try:
            # 1. Standard inline view (returns text/plain for safe text modal reading)
            handler.headers = {}
            handler.path = f"/api/view?file={urllib.parse.quote(tmp_path)}&inline=1"
            handler.do_GET()

            handler.send_response.assert_called_with(200)
            headers = [call[0] for call in handler.send_header.call_args_list]
            content_type = next(h[1] for h in headers if h[0] == "Content-Type")
            assert "text/plain" in content_type

            # 2. Raw view (returns text/html with CSP for browser tab rendering)
            handler.send_response.reset_mock()
            handler.send_header.reset_mock()
            handler.path = f"/api/view?file={urllib.parse.quote(tmp_path)}&raw=1"
            handler.do_GET()

            handler.send_response.assert_called_with(200)
            raw_headers = [call[0] for call in handler.send_header.call_args_list]
            raw_type = next(h[1] for h in raw_headers if h[0] == "Content-Type")
            csp = next(h[1] for h in raw_headers if h[0] == "Content-Security-Policy")
            assert raw_type == "text/html; charset=utf-8"
            assert "sandbox" in csp
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_stat_directory(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.headers = {}
        handler.is_authenticated = MagicMock(return_value=True)
        handler.get_auth_token = MagicMock(return_value="valid-token")
        handler.send_json = MagicMock()
        handler.server = MagicMock()
        handler.server.terminals.get.return_value = None

        with tempfile.TemporaryDirectory() as tmp_dir:
            handler.path = f"/api/stat?file={urllib.parse.quote(tmp_dir)}"
            handler.do_GET()

            handler.send_json.assert_called_once()
            call_args = handler.send_json.call_args[0][0]
            assert call_args["success"] is True
            assert call_args["exists"] is True
            assert call_args["is_dir"] is True
            assert call_args["is_file"] is False

    def test_stat_nonexistent(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.headers = {}
        handler.is_authenticated = MagicMock(return_value=True)
        handler.get_auth_token = MagicMock(return_value="valid-token")
        handler.send_json = MagicMock()
        handler.server = MagicMock()
        handler.server.terminals.get.return_value = None

        handler.path = "/api/stat?file=/nonexistent_test_stat_999.xyz"
        handler.do_GET()

        handler.send_json.assert_called_once()
        call_args = handler.send_json.call_args[0][0]
        assert call_args["success"] is True
        assert call_args["exists"] is False
        assert call_args["is_dir"] is False
        assert call_args["is_file"] is False

    def test_stat_unauthorized(self):
        handler = FireSSHServerHandler.__new__(FireSSHServerHandler)
        handler.client_address = ('127.0.0.1', 12345)
        handler.headers = {}
        handler.is_authenticated = MagicMock(return_value=False)
        handler.send_json = MagicMock()

        handler.path = "/api/stat?file=/some/path"
        handler.do_GET()
        handler.send_json.assert_called_once_with({"success": False, "error": "Unauthorized session"}, status=401)


class TestFileHoverLogicWithNode:
    """Execute the exact JS helper functions extracted from HTML_TEMPLATE in Node.js to verify behavior."""

    @classmethod
    def setup_class(cls):
        # Extract JS helper functions from HTML_TEMPLATE
        match = re.search(r'(const BLOCKED_EXTENSIONS = new Set\(.*?\n\s*const registerImageLinkProvider = registerFileLinkProvider;)', HTML_TEMPLATE, re.DOTALL)
        assert match is not None, "Could not extract file hover JS block from HTML_TEMPLATE"
        md_match = re.search(r'(function parseGitHubAlerts\(.*?function renderMarkdownContent\(.*?\n    \})', HTML_TEMPLATE, re.DOTALL)
        assert md_match is not None, "Could not extract markdown parser JS block from HTML_TEMPLATE"
        cls.js_helpers = match.group(1) + "\n" + md_match.group(1)

    def _eval_js(self, js_expr: str):
        script = f"""
        {self.js_helpers}
        const result = ({js_expr});
        console.log(JSON.stringify(result));
        """
        proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
        return json.loads(proc.stdout.strip())

    def test_clean_candidate_path(self):
        assert self._eval_js("cleanCandidatePath('~/\"fire-package-pm\"')") == "~/fire-package-pm"
        assert self._eval_js("cleanCandidatePath('\"./src/index.ts\"')") == "./src/index.ts"
        assert self._eval_js("cleanCandidatePath(\"'app/main.py'\")") == "app/main.py"
        assert self._eval_js("cleanCandidatePath('simple.txt')") == "simple.txt"
        assert self._eval_js("cleanCandidatePath('file:///root/app.py')") == "/root/app.py"
        assert self._eval_js("cleanCandidatePath('file://localhost/root/test.txt')") == "/root/test.txt"
        assert self._eval_js("cleanCandidatePath('file:///root/sample%20space.txt')") == "/root/sample space.txt"
        assert self._eval_js("cleanCandidatePath('file:///root/app.py#L10-L20')") == "/root/app.py"
        assert self._eval_js("cleanCandidatePath('file:///root/app.py:42:15')") == "/root/app.py"
        assert self._eval_js("cleanCandidatePath('README.md#L10')") == "README.md"
        assert self._eval_js("cleanCandidatePath('/root/fire-package-pm/README.md#features')") == "/root/fire-package-pm/README.md"
        assert self._eval_js("cleanCandidatePath('index.html?token=xyz')") == "index.html"
        assert self._eval_js("cleanCandidatePath('app/file.md?raw=1#L5')") == "app/file.md"

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

    def test_file_category_html_support(self):
        for fn in ["index.html", "page.htm", "template.xhtml"]:
            res = self._eval_js(f"getFileCategory('{fn}')")
            assert res["isHtml"] is True
            assert res["canCat"] is True
            assert res["badge"] == "HTML"

    def test_file_category_markdown_support(self):
        for fn in ["README.md", "guide.markdown", "AGENT.MD"]:
            res = self._eval_js(f"getFileCategory('{fn}')")
            assert res["isMarkdown"] is True
            assert res["canCat"] is True
            assert res["badge"] == "MARKDOWN"

    def test_parse_github_alerts(self):
        sample = "<blockquote><p>[!NOTE]<br>This is a note callout.</p></blockquote>"
        out = self._eval_js(f"parseGitHubAlerts({json.dumps(sample)})")
        assert 'class="markdown-alert markdown-alert-note"' in out
        assert 'markdown-alert-title' in out
        assert 'This is a note callout.' in out

        sample_tip = "<blockquote><p>[!TIP]<br>This is a tip.</p></blockquote>"
        out_tip = self._eval_js(f"parseGitHubAlerts({json.dumps(sample_tip)})")
        assert 'class="markdown-alert markdown-alert-tip"' in out_tip

    def test_render_markdown_fallback(self):
        md = "# Hello Title\n\nThis is **bold** text and `inline code`.\n\n```python\nprint(123)\n```"
        html = self._eval_js(f"renderMarkdownFallback({json.dumps(md)})")
        assert "<h1>Hello Title</h1>" in html
        assert "<strong>bold</strong>" in html
        assert "<code>inline code</code>" in html
        assert '<pre><code class="language-python">print(123)</code></pre>' in html

    def test_render_markdown_content_fallback(self):
        # In node without marked loaded, renderMarkdownContent gracefully falls back
        md = "## Subtitle\n\n> [!WARNING]\n> Cautionary alert!"
        html = self._eval_js(f"renderMarkdownContent({json.dumps(md)})")
        assert "<h2>Subtitle</h2>" in html
        assert "markdown-alert-warning" in html
        assert "Cautionary alert!" in html

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
            "file:///root/fire-package-pm/app/fire_ssh.py",
            "file://localhost/root/test.txt",
            "file:///root/my%20file.txt#L10-L20",
            "./src/index.ts",
            "../config.json",
            "~/.bashrc",
            '~/"fire-package-pm"',
            '"package.json"',
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
            "some-random-word",
            "h:AGENT.md",
            "path:AGENT.md",
            "git:diff",
            "test:12"
        ]
        for p in invalid_paths:
            assert self._eval_js(f"isPathValidCandidate({json.dumps(p)})") is False, f"{p} should be rejected as path candidate"

    def test_quote_shell_arg(self):
        assert self._eval_js("quoteShellArg('simple.txt')") == '"simple.txt"'
        assert self._eval_js("quoteShellArg('file with spaces.txt')") == '"file with spaces.txt"'
        assert self._eval_js("quoteShellArg('~/projects/app.js')") == '~/"projects/app.js"'
        assert self._eval_js('quoteShellArg(\'foo"bar.txt\')') == '"foo\\"bar.txt"'

    def test_file_category_html_and_markdown_with_fragments(self):
        cat_md = self._eval_js("getFileCategory('README.md#L10')")
        assert cat_md["isMarkdown"] is True
        assert cat_md["badge"] == "MARKDOWN"

        cat_html = self._eval_js("getFileCategory('index.html?v=2#preview')")
        assert cat_html["isHtml"] is True
        assert cat_html["badge"] == "HTML"

    def test_file_modal_preview_wrap_dark_styling(self):
        assert 'id="file-modal-preview-wrap" class="hidden absolute inset-0 bg-slate-950 z-0 flex flex-col p-2 sm:p-4"' in HTML_TEMPLATE
        assert 'id="file-modal-preview-frame" class="w-full h-full border-0 bg-white rounded-lg shadow-inner"' in HTML_TEMPLATE

    def test_set_file_modal_view_mode_clean_toggle(self):
        toggle_script = """
        (() => {
            let currentModalFilePath = 'README.md#L10';
            let currentModalFileType = 'markdown';
            let currentModalFileContent = '# Hello MD';
            let previewWrapHidden = false;
            let mdWrapHidden = true;
            let codeWrapHidden = false;
            let previewFrameSrcdoc = '';
            let mdBodyHtml = '';

            const previewWrap = { classList: { add: (c) => { if (c==='hidden') previewWrapHidden = true; }, remove: (c) => { if (c==='hidden') previewWrapHidden = false; } } };
            const mdWrap = { classList: { add: (c) => { if (c==='hidden') mdWrapHidden = true; }, remove: (c) => { if (c==='hidden') mdWrapHidden = false; } } };
            const codeWrap = { classList: { add: (c) => { if (c==='hidden') codeWrapHidden = true; }, remove: (c) => { if (c==='hidden') codeWrapHidden = false; } } };
            const previewFrame = { removeAttribute: () => {}, set srcdoc(v) { previewFrameSrcdoc = v; }, get srcdoc() { return previewFrameSrcdoc; } };
            const mdBody = { set innerHTML(v) { mdBodyHtml = v; }, get innerHTML() { return mdBodyHtml; } };

            function simulateToggle(mode) {
                let isHtml = currentModalFileType === 'html';
                let isMd = currentModalFileType === 'markdown';
                if (!isHtml && !isMd && currentModalFilePath) {
                    const cleanBase = (cleanCandidatePath(currentModalFilePath).split('/').pop() || '').toLowerCase();
                    const ext = cleanBase.includes('.') ? cleanBase.split('.').pop() : '';
                    isHtml = ['html', 'htm', 'xhtml'].includes(ext);
                    isMd = ['md', 'markdown'].includes(ext);
                }

                if (mode === 'preview') {
                    codeWrap.classList.add('hidden');
                    if (isMd) {
                        previewWrap.classList.add('hidden');
                        mdWrap.classList.remove('hidden');
                        mdBody.innerHTML = renderMarkdownContent(currentModalFileContent);
                    } else if (isHtml) {
                        mdWrap.classList.add('hidden');
                        previewWrap.classList.remove('hidden');
                        previewFrame.removeAttribute('srcdoc');
                        previewFrame.srcdoc = currentModalFileContent;
                    } else {
                        previewWrap.classList.add('hidden');
                        mdWrap.classList.add('hidden');
                        codeWrap.classList.remove('hidden');
                    }
                } else {
                    previewWrap.classList.add('hidden');
                    mdWrap.classList.add('hidden');
                    codeWrap.classList.remove('hidden');
                }
            }

            simulateToggle('preview');
            const state1 = { previewWrapHidden, mdWrapHidden, codeWrapHidden, hasMd: mdBodyHtml.includes('Hello MD') };

            simulateToggle('code');
            const state2 = { previewWrapHidden, mdWrapHidden, codeWrapHidden };

            simulateToggle('preview');
            const state3 = { previewWrapHidden, mdWrapHidden, codeWrapHidden, hasMd: mdBodyHtml.includes('Hello MD') };

            return { state1, state2, state3 };
        })()
        """
        res = self._eval_js(toggle_script)
        assert res["state1"]["previewWrapHidden"] is True
        assert res["state1"]["mdWrapHidden"] is False
        assert res["state1"]["codeWrapHidden"] is True
        assert res["state1"]["hasMd"] is True

        assert res["state2"]["previewWrapHidden"] is True
        assert res["state2"]["mdWrapHidden"] is True
        assert res["state2"]["codeWrapHidden"] is False

        assert res["state3"]["previewWrapHidden"] is True
        assert res["state3"]["mdWrapHidden"] is False
        assert res["state3"]["codeWrapHidden"] is True
        assert res["state3"]["hasMd"] is True

    def test_build_breadcrumb_segments(self):
        script = """
        (() => {
            function getBreadcrumbItems(dirPath) {
                if (!dirPath) return [];
                const isAbs = dirPath.startsWith('/');
                const cleanPath = dirPath.replace(/\\/+$/, '');
                const parts = cleanPath.split('/').filter(Boolean);

                const items = [];
                if (isAbs) {
                    items.push({ name: '/', path: '/' });
                }

                let curAcc = '';
                for (let i = 0; i < parts.length; i++) {
                    const seg = parts[i];
                    curAcc = isAbs ? `${curAcc}/${seg}` : (curAcc ? `${curAcc}/${seg}` : seg);
                    items.push({ name: seg, path: curAcc });
                }

                if (items.length === 0) {
                    items.push({ name: '/', path: '/' });
                }
                return items;
            }

            return {
                root: getBreadcrumbItems('/'),
                absPath: getBreadcrumbItems('/root/fire-package-pm'),
                relPath: getBreadcrumbItems('app/components')
            };
        })()
        """
        res = self._eval_js(script)
        assert res["root"] == [{"name": "/", "path": "/"}]
        assert res["absPath"] == [
            {"name": "/", "path": "/"},
            {"name": "root", "path": "/root"},
            {"name": "fire-package-pm", "path": "/root/fire-package-pm"}
        ]
        assert res["relPath"] == [
            {"name": "app", "path": "app"},
            {"name": "components", "path": "app/components"}
        ]

    def test_dir_listing_sort_order(self):
        script = """
        (() => {
            const items = [
                { name: 'README.md', is_dir: false },
                { name: 'src', is_dir: true },
                { name: 'package.json', is_dir: false },
                { name: 'app', is_dir: true },
                { name: '.gitignore', is_dir: false }
            ];

            const sorted = [...items].sort((a, b) => {
                if (a.is_dir && !b.is_dir) return -1;
                if (!a.is_dir && b.is_dir) return 1;
                return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
            });

            return sorted.map(i => ({ name: i.name, is_dir: i.is_dir }));
        })()
        """
        res = self._eval_js(script)
        names = [item["name"] for item in res]
        assert names == ["app", "src", ".gitignore", "package.json", "README.md"]

    def test_get_language_from_path(self):
        script = """
        (() => {
            return {
                py: getLanguageFromPath('/root/server.py'),
                wsgi: getLanguageFromPath('app/wsgi.pyw'),
                js: getLanguageFromPath('index.js'),
                mjs: getLanguageFromPath('/app/module.mjs'),
                ts: getLanguageFromPath('src/main.ts'),
                tsx: getLanguageFromPath('components/App.tsx'),
                json: getLanguageFromPath('package.json'),
                sh: getLanguageFromPath('deploy.sh'),
                bashrc: getLanguageFromPath('/root/.bashrc'),
                env: getLanguageFromPath('.env.production'),
                docker: getLanguageFromPath('Dockerfile'),
                makefile: getLanguageFromPath('Makefile'),
                yaml: getLanguageFromPath('docker-compose.yml'),
                rust: getLanguageFromPath('main.rs'),
                go: getLanguageFromPath('server.go'),
                unknown: getLanguageFromPath('notes.txt')
            };
        })()
        """
        res = self._eval_js(script)
        assert res["py"] == "python"
        assert res["wsgi"] == "python"
        assert res["js"] == "javascript"
        assert res["mjs"] == "javascript"
        assert res["ts"] == "typescript"
        assert res["tsx"] == "typescript"
        assert res["json"] == "json"
        assert res["sh"] == "bash"
        assert res["bashrc"] == "bash"
        assert res["env"] == "ini"
        assert res["docker"] == "dockerfile"
        assert res["makefile"] == "makefile"
        assert res["yaml"] == "yaml"
        assert res["rust"] == "rust"
        assert res["go"] == "go"
        assert res["unknown"] is None

    def test_get_language_label(self):
        script = """
        (() => {
            return {
                py: getLanguageLabel('python', 'test.py'),
                js: getLanguageLabel('javascript', 'app.js'),
                ts: getLanguageLabel('typescript', 'types.ts'),
                json: getLanguageLabel('json', 'data.json'),
                bash: getLanguageLabel('bash', 'run.sh'),
                unknown: getLanguageLabel(null, 'file.xyz'),
                plain: getLanguageLabel(null, 'plain')
            };
        })()
        """
        res = self._eval_js(script)
        assert res["py"] == "Python"
        assert res["js"] == "JavaScript (Node.js)"
        assert res["ts"] == "TypeScript"
        assert res["json"] == "JSON"
        assert res["bash"] == "Shell / Bash"
        assert res["unknown"] == "XYZ"
        assert res["plain"] == "Plain Text"
