import os
import re
import subprocess
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class TabDragFileConflictRegressionTests(unittest.TestCase):

    def setUp(self):
        self.fire_ssh_path = os.path.join(PROJECT_ROOT, "app", "fire_ssh.py")
        with open(self.fire_ssh_path, "r", encoding="utf-8") as f:
            self.content = f.read()

    def test_is_file_drag_event_defined(self):
        """Verify isFileDragEvent helper exists and checks for Files and draggedTabId."""
        self.assertIn("function isFileDragEvent(e)", self.content)
        self.assertIn("if (typeof draggedTabId !== 'undefined' && draggedTabId) return false;", self.content)
        self.assertIn("types[i] === 'Files'", self.content)

    def test_window_drag_listeners_use_is_file_drag_event(self):
        """Verify window drag listeners guard against non-file drag events."""
        # dragenter
        match_enter = re.search(r"window\.addEventListener\('dragenter',\s*\(e\)\s*=>\s*\{([^}]+)\}", self.content)
        self.assertIsNotNone(match_enter, "window dragenter listener should exist")
        self.assertIn("isFileDragEvent(e)", match_enter.group(1))

        # dragover
        match_over = re.search(r"window\.addEventListener\('dragover',\s*\(e\)\s*=>\s*\{([^}]+)\}", self.content)
        self.assertIsNotNone(match_over, "window dragover listener should exist")
        self.assertIn("isFileDragEvent(e)", match_over.group(1))

        # dragleave
        match_leave = re.search(r"window\.addEventListener\('dragleave',\s*\(e\)\s*=>\s*\{([^}]+)\}", self.content)
        self.assertIsNotNone(match_leave, "window dragleave listener should exist")
        self.assertIn("isFileDragEvent(e)", match_leave.group(1))

        # drop
        match_drop = re.search(r"window\.addEventListener\('drop',\s*\(e\)\s*=>\s*\{([^}]+)\}", self.content)
        self.assertIsNotNone(match_drop, "window drop listener should exist")
        self.assertIn("isFileDragEvent(e)", match_drop.group(1))

    def test_tab_drop_bubbles_when_not_tab_drag(self):
        """Verify handleTabDrop allows external file drops to bubble by not calling preventDefault."""
        match_handle_drop = re.search(r"function handleTabDrop\([^)]*\)\s*\{([\s\S]*?)\n    \}", self.content)
        self.assertIsNotNone(match_handle_drop, "handleTabDrop should exist")
        drop_fn_body = match_handle_drop.group(1)
        # Should check if (!draggedTabId) return BEFORE e.preventDefault()
        idx_check = drop_fn_body.find("if (!draggedTabId)")
        idx_prevent = drop_fn_body.find("e.preventDefault()")
        self.assertNotEqual(idx_check, -1, "Must check !draggedTabId")
        self.assertNotEqual(idx_prevent, -1, "Must call e.preventDefault() for tab drag")
        self.assertLess(idx_check, idx_prevent, "Must return early on !draggedTabId before e.preventDefault()")

    def test_tab_drag_end_resets_overlay_and_counter(self):
        """Verify handleTabDragEnd clears overlay and resets counter."""
        match_drag_end = re.search(r"function handleTabDragEnd\([^)]*\)\s*\{([\s\S]*?)\n    \}", self.content)
        self.assertIsNotNone(match_drag_end, "handleTabDragEnd should exist")
        end_fn_body = match_drag_end.group(1)
        self.assertIn("draggedTabId = null;", end_fn_body)
        self.assertIn("dragCounter = 0;", end_fn_body)

    def test_drag_event_node_simulation(self):
        """Simulate tab dragging vs file dropping logic in Node.js."""
        js_code = """
        let draggedTabId = null;
        let dragCounter = 0;
        let overlayHidden = true;
        let uploadModalOpened = false;
        let tabReordered = false;

        function isFileDragEvent(e) {
          if (typeof draggedTabId !== 'undefined' && draggedTabId) return false;
          if (!e || !e.dataTransfer) return false;
          const types = e.dataTransfer.types;
          if (!types) return false;
          for (let i = 0; i < types.length; i++) {
            if (types[i] === 'Files' || types[i] === 'application/x-moz-file') {
              return true;
            }
          }
          return false;
        }

        // Window event simulation
        function onWindowDragEnter(e) {
          if (!isFileDragEvent(e)) return;
          e.preventDefault();
          dragCounter++;
          if (dragCounter === 1) {
            overlayHidden = false;
          }
        }

        function onWindowDragLeave(e) {
          if (!isFileDragEvent(e)) return;
          e.preventDefault();
          dragCounter--;
          if (dragCounter <= 0) {
            dragCounter = 0;
            overlayHidden = true;
          }
        }

        function onWindowDrop(e) {
          if (!isFileDragEvent(e)) {
            dragCounter = 0;
            overlayHidden = true;
            return;
          }
          e.preventDefault();
          dragCounter = 0;
          overlayHidden = true;
          uploadModalOpened = true;
        }

        // Tab drag simulation
        function handleTabDragStart(tabId) {
          draggedTabId = tabId;
        }

        function handleTabDrop(e, targetId) {
          if (!draggedTabId) {
            // External file drop: do not preventDefault, bubble!
            return;
          }
          e.preventDefault();
          if (draggedTabId === targetId) {
            draggedTabId = null;
            return;
          }
          tabReordered = true;
          draggedTabId = null;
        }

        function handleTabDragEnd() {
          draggedTabId = null;
          dragCounter = 0;
          overlayHidden = true;
        }

        // --- Scenario 1: User drags a tab to reorder ---
        handleTabDragStart('tab-1');
        const tabDragEvent = {
          dataTransfer: { types: ['text/plain', 'application/x-fire-ssh-tab'] },
          defaultPrevented: false,
          preventDefault() { this.defaultPrevented = true; }
        };

        // Window dragenter while dragging tab
        onWindowDragEnter(tabDragEvent);
        if (!overlayHidden) throw new Error("Drop overlay showed up during tab reorder!");
        if (dragCounter !== 0) throw new Error("dragCounter was incremented during tab reorder!");

        // Drop tab on tab-2
        handleTabDrop(tabDragEvent, 'tab-2');
        if (!tabDragEvent.defaultPrevented) throw new Error("Tab drop did not preventDefault for tab reorder!");
        if (!tabReordered) throw new Error("Tab was not reordered!");

        handleTabDragEnd();
        if (draggedTabId !== null) throw new Error("draggedTabId not cleared after tab drag end!");

        // --- Scenario 2: User drags a file from OS onto tab bar ---
        tabReordered = false;
        uploadModalOpened = false;

        const fileDragEvent = {
          dataTransfer: { types: ['Files'], dropEffect: 'none' },
          defaultPrevented: false,
          preventDefault() { this.defaultPrevented = true; }
        };

        // Window dragenter with file
        onWindowDragEnter(fileDragEvent);
        if (overlayHidden) throw new Error("Drop overlay should be visible for file drag!");
        if (dragCounter !== 1) throw new Error("dragCounter should be 1 for file drag!");

        // File drop directly on tab bar (handleTabDrop)
        const fileDropOnTab = {
          dataTransfer: { types: ['Files'] },
          defaultPrevented: false,
          preventDefault() { this.defaultPrevented = true; }
        };
        handleTabDrop(fileDropOnTab, 'tab-1');
        if (fileDropOnTab.defaultPrevented) {
          throw new Error("handleTabDrop should NOT preventDefault on external file drop (must bubble)!");
        }

        // Event bubbles up to window drop
        onWindowDrop(fileDropOnTab);
        if (!fileDropOnTab.defaultPrevented) throw new Error("Window drop should preventDefault!");
        if (!overlayHidden) throw new Error("Overlay should hide after drop!");
        if (!uploadModalOpened) throw new Error("Upload modal should open for file dropped on tab bar!");

        console.log("ALL_TAB_DRAG_CONFLICT_TESTS_PASSED");
        """
        proc = subprocess.run(["node", "-e", js_code], capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, f"Node script failed: {proc.stderr}")
        self.assertIn("ALL_TAB_DRAG_CONFLICT_TESTS_PASSED", proc.stdout)


if __name__ == "__main__":
    unittest.main()
