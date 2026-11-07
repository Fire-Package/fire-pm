import os
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class TestPdfViewerModal(unittest.TestCase):
    def setUp(self):
        self.fire_ssh_path = os.path.join(PROJECT_ROOT, "app", "fire_ssh.py")
        with open(self.fire_ssh_path, "r", encoding="utf-8") as f:
            self.content = f.read()

    def test_pdf_modal_html_elements(self):
        """Verify HTML template contains required PDF viewer containers and progress elements."""
        self.assertIn('id="file-modal-pdf-wrap"', self.content)
        self.assertIn('id="file-modal-pdf-loading"', self.content)
        self.assertIn('id="file-modal-pdf-progress"', self.content)
        self.assertIn('id="file-modal-pdf-bar-track"', self.content)
        self.assertIn('id="file-modal-pdf-actions"', self.content)
        self.assertIn('id="file-modal-pdf-retry-btn"', self.content)
        self.assertIn('id="file-modal-pdf-frame"', self.content)

    def test_pdf_abort_and_blob_state_management(self):
        """Verify AbortController and Blob URL lifecycle variables are defined."""
        self.assertIn("let currentPdfAbortController = null;", self.content)
        self.assertIn("let currentPdfBlobUrl = null;", self.content)

    def test_pdf_cleanup_on_modal_close(self):
        """Verify closing file modal cleans up in-flight requests and object URLs."""
        self.assertIn("if (currentPdfAbortController) {", self.content)
        self.assertIn("currentPdfAbortController.abort()", self.content)
        self.assertIn("URL.revokeObjectURL(currentPdfBlobUrl)", self.content)

    def test_chunked_stream_reader_and_real_progress(self):
        """Verify openPdfModal uses stream reader and calculates real progress from Content-Length."""
        self.assertIn("const reader = response.body ? response.body.getReader() : null;", self.content)
        self.assertIn("receivedBytes += value.length;", self.content)
        self.assertIn("const pct = Math.min(100, Math.round((receivedBytes / totalBytes) * 100));", self.content)
        self.assertIn("URL.createObjectURL(pdfBlob)", self.content)

    def test_open_tab_and_fallback_actions_available(self):
        """Verify openTabBtn is not hidden in PDF mode, giving users an escape hatch."""
        self.assertIn("if (openTabBtn) openTabBtn.classList.remove('hidden');", self.content)
        self.assertIn("onclick=\"openModalFileInBrowser()\"", self.content)
        self.assertIn("onclick=\"downloadModalFile()\"", self.content)

if __name__ == "__main__":
    unittest.main()
