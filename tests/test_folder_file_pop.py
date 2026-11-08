import os
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class TestFolderFilePopNavigation(unittest.TestCase):
    def setUp(self):
        self.fire_ssh_path = os.path.join(PROJECT_ROOT, "app", "fire_ssh.py")
        with open(self.fire_ssh_path, "r", encoding="utf-8") as f:
            self.content = f.read()

    def test_state_variables_declared(self):
        """Verify modalParentDirPath and mediaModalParentDirPath state variables are defined."""
        self.assertIn("let modalParentDirPath = null;", self.content)
        self.assertIn("let mediaModalParentDirPath = null;", self.content)

    def test_folder_listing_captures_origin_folder(self):
        """Verify renderDirListing card clicks record origin folder and pass to modal openers."""
        self.assertIn("const originFolder = currentModalDirPath;", self.content)
        self.assertIn("openImagePreviewModal(fullPath, currentModalFileTabId, originFolder);", self.content)
        self.assertIn("openDatabaseModal(fullPath, currentModalFileTabId, null, originFolder);", self.content)
        self.assertIn("openPdfModal(fullPath, currentModalFileTabId, originFolder);", self.content)
        self.assertIn("openFileContentModal(fullPath, currentModalFileTabId, null, (cat && (cat.isHtml || cat.isMarkdown)) ? 'preview' : 'code', originFolder);", self.content)

    def test_modal_openers_accept_parent_dir(self):
        """Verify all modal open functions accept optional parentDir parameter."""
        self.assertIn("async function openFileContentModal(path, tabId, statData, initialMode = null, parentDir = null)", self.content)
        self.assertIn("async function openPdfModal(path, tabId, parentDir = null)", self.content)
        self.assertIn("async function openDatabaseModal(path, tabId, statData, parentDir = null)", self.content)
        self.assertIn("function openImagePreviewModal(path, tabId, parentDir = null)", self.content)

    def test_close_file_content_modal_pops_back_to_folder(self):
        """Verify closing file modal returns to parent folder if opened from directory listing."""
        self.assertIn("if (!forceCloseAll && modalParentDirPath && !currentModalIsDir) {", self.content)
        self.assertIn("const returnDir = modalParentDirPath;", self.content)
        self.assertIn("cleanupFileModalView();", self.content)
        self.assertIn("openFolderInModal(returnDir, returnTab);", self.content)

    def test_close_image_preview_modal_pops_back_to_folder(self):
        """Verify closing image/media modal returns to parent folder if opened from directory listing."""
        self.assertIn("const returnDir = (!forceCloseAll) ? mediaModalParentDirPath : null;", self.content)
        self.assertIn("if (returnDir) {", self.content)
        self.assertIn("openFolderInModal(returnDir, returnTab);", self.content)

    def test_force_close_avoids_pop_back_loops(self):
        """Verify tab actions and folder re-entry pass forceCloseAll to avoid recursive pop-back loops."""
        self.assertIn("closeImagePreviewModal(false, true);", self.content)
        self.assertIn("closeFileContentModal(true);", self.content)

if __name__ == "__main__":
    unittest.main()
