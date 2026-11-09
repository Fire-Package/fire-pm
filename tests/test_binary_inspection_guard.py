import os
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class TestBinaryInspectionGuard(unittest.TestCase):
    def setUp(self):
        self.fire_ssh_path = os.path.join(PROJECT_ROOT, "app", "fire_ssh.py")
        with open(self.fire_ssh_path, "r", encoding="utf-8") as f:
            self.content = f.read()

    def test_html_template_contains_binary_card_elements(self):
        """Verify HTML template contains dedicated binary/large-file placeholder card."""
        self.assertIn('id="file-modal-binary-wrap"', self.content)
        self.assertIn('id="file-modal-binary-title"', self.content)
        self.assertIn('id="file-modal-binary-badge"', self.content)
        self.assertIn('id="file-modal-binary-msg"', self.content)
        self.assertIn('id="file-modal-binary-icon"', self.content)

    def test_render_binary_modal_card_defined(self):
        """Verify renderBinaryModalCard JavaScript helper is defined and configures the binary card."""
        self.assertIn("function renderBinaryModalCard(path, cat, stat, customMsg = null, customBadge = null)", self.content)
        self.assertIn("binaryWrap.classList.remove('hidden')", self.content)
        self.assertIn("BINARY EXECUTABLE", self.content)

    def test_terminal_link_provider_guards_against_blocked_files(self):
        """Verify terminal link activation doesn't open code modal for blocked or binary files."""
        self.assertIn("cat.type !== 'blocked'", self.content)
        self.assertIn("targetStat.is_text && !targetStat.is_binary", self.content)

    def test_open_file_content_modal_handles_413_and_415(self):
        """Verify openFileContentModal handles HTTP 413 (Too Large) and 415 (Binary)."""
        self.assertIn("res.status === 413", self.content)
        self.assertIn("res.status === 415", self.content)
        self.assertIn("FILE TOO LARGE", self.content)
        self.assertIn("renderBinaryModalCard", self.content)

    def test_content_length_and_null_byte_guards_in_frontend(self):
        """Verify frontend checks Content-Length and null bytes before parsing code."""
        self.assertIn("if (clBytes > 5 * 1024 * 1024)", self.content)
        self.assertIn("if (text.includes('\\x00'))", self.content)

    def test_hljs_highlight_length_guard(self):
        """Verify syntax highlighting is bypassed for very large text to prevent main-thread freeze."""
        self.assertIn("byteSize <= 256 * 1024 && lineCount <= 3000", self.content)

    def test_api_view_backend_size_and_binary_checks(self):
        """Verify /api/view backend enforces 5MB limit and blocked extensions in do_GET and do_HEAD."""
        self.assertIn("if file_size > 5 * 1024 * 1024:", self.content)
        self.assertIn("FILE_TOO_LARGE", self.content)
        self.assertIn("BINARY_FILE", self.content)
        self.assertIn("b'\\x7fELF'", self.content)
        self.assertIn("b'MZ'", self.content)

    def test_api_stat_detects_binary_magic_bytes(self):
        """Verify /api/stat detects binary files via magic signatures."""
        self.assertIn('"is_binary": is_binary', self.content)
        self.assertIn("sample.startswith(b'\\x7fELF')", self.content)

if __name__ == "__main__":
    unittest.main()
