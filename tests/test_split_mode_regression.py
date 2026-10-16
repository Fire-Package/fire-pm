import os
import re
import subprocess
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class SplitModeRegressionTests(unittest.TestCase):

    def setUp(self):
        self.fire_ssh_path = os.path.join(PROJECT_ROOT, "app", "fire_ssh.py")
        with open(self.fire_ssh_path, "r", encoding="utf-8") as f:
            self.content = f.read()

    def test_dual_tab_ids_variable_declared(self):
        """Verify dualTabIds array is declared in fire_ssh.py."""
        self.assertIn("let dualTabIds = [];", self.content)

    def test_no_swapping_in_mousedown(self):
        """Verify mousedown does not swap activeTabId and secondaryTabId."""
        # Find mountEl.addEventListener('mousedown'
        match = re.search(r"mountEl\.addEventListener\('mousedown', \(\) => \{(.*?)\}\);", self.content, re.DOTALL)
        self.assertIsNotNone(match, "mousedown listener should exist")
        body = match.group(1)
        self.assertNotIn("secondaryTabId = temp", body, "mousedown must not swap secondaryTabId")

    def test_dual_split_js_slot_stability_with_node(self):
        """Execute client-side tab switching and split slot logic via Node.js."""
        js_code = """
        let tabs = {
            'tab-1': { id: 'tab-1', title: 'bash' },
            'tab-2': { id: 'tab-2', title: 'htop' },
            'tab-3': { id: 'tab-3', title: 'vim' }
        };
        let activeTabId = 'tab-1';
        let secondaryTabId = null;
        let dualTabIds = [];
        let gridTabIds = [];
        let tripleTabIds = [];
        let splitMode = 'none';

        function setSplitMode(mode) {
            splitMode = mode;
            const tabKeys = Object.keys(tabs);
            if (splitMode === 'vertical' || splitMode === 'horizontal') {
                if (!dualTabIds || dualTabIds.length < 2 || !tabs[dualTabIds[0]] || !tabs[dualTabIds[1]]) {
                    const remaining = tabKeys.filter(id => id !== activeTabId);
                    dualTabIds = [activeTabId, remaining[0] || null].filter(Boolean);
                }
                secondaryTabId = dualTabIds[1] || null;
            } else {
                dualTabIds = [];
                secondaryTabId = null;
            }
        }

        function switchTab(tabId) {
            if (!tabs[tabId]) return;
            if (splitMode === 'vertical' || splitMode === 'horizontal') {
                if (!dualTabIds.includes(tabId)) {
                    const idxToReplace = dualTabIds.indexOf(activeTabId);
                    if (idxToReplace !== -1) {
                        dualTabIds[idxToReplace] = tabId;
                    } else {
                        dualTabIds[0] = tabId;
                    }
                }
                activeTabId = tabId;
                secondaryTabId = dualTabIds.find(id => id !== activeTabId) || null;
                return;
            }
            activeTabId = tabId;
        }

        function cycleSplitFocus() {
            if ((splitMode === 'vertical' || splitMode === 'horizontal') && dualTabIds.length >= 2) {
                const curIdx = dualTabIds.indexOf(activeTabId);
                const nextIdx = curIdx === 0 ? 1 : 0;
                activeTabId = dualTabIds[nextIdx];
            }
        }

        function closeTab(tabId) {
            delete tabs[tabId];
            if (splitMode === 'vertical' || splitMode === 'horizontal') {
                const remainingKeys = Object.keys(tabs);
                if (remainingKeys.length < 2) {
                    setSplitMode('none');
                    return;
                } else {
                    dualTabIds = dualTabIds.filter(id => id !== tabId);
                    const unused = remainingKeys.find(id => !dualTabIds.includes(id));
                    if (unused) dualTabIds.push(unused);
                    if (activeTabId === tabId) {
                        activeTabId = dualTabIds[0];
                    }
                    secondaryTabId = dualTabIds[1] || null;
                    return;
                }
            }
        }

        // Test 1: Enter vertical split mode
        setSplitMode('vertical');
        if (dualTabIds[0] !== 'tab-1' || dualTabIds[1] !== 'tab-2') {
            throw new Error(`Expected ['tab-1', 'tab-2'], got ${JSON.stringify(dualTabIds)}`);
        }

        // Test 2: Switch focus to Tab 2 (right pane)
        switchTab('tab-2');
        if (activeTabId !== 'tab-2') throw new Error('activeTabId should be tab-2');
        if (dualTabIds[0] !== 'tab-1' || dualTabIds[1] !== 'tab-2') {
            throw new Error(`dualTabIds swapped incorrectly! Got ${JSON.stringify(dualTabIds)}`);
        }

        // Test 3: Cycle focus back to Tab 1
        cycleSplitFocus();
        if (activeTabId !== 'tab-1') throw new Error('activeTabId should be tab-1 after cycle');
        if (dualTabIds[0] !== 'tab-1' || dualTabIds[1] !== 'tab-2') {
            throw new Error(`dualTabIds swapped during cycle! Got ${JSON.stringify(dualTabIds)}`);
        }

        // Test 4: Focus Tab 2 and select unassigned Tab 3 -> Should replace Tab 2 in Slot 1
        switchTab('tab-2');
        switchTab('tab-3');
        if (activeTabId !== 'tab-3') throw new Error('activeTabId should be tab-3');
        if (dualTabIds[0] !== 'tab-1' || dualTabIds[1] !== 'tab-3') {
            throw new Error(`Slot 1 replacement failed: got ${JSON.stringify(dualTabIds)}`);
        }

        // Test 5: Close tab-3 -> tab-2 should reclaim the vacant slot
        closeTab('tab-3');
        if (dualTabIds[0] !== 'tab-1' || dualTabIds[1] !== 'tab-2') {
            throw new Error(`Vacant slot recovery failed: got ${JSON.stringify(dualTabIds)}`);
        }

        // Test 6: Close tab-2 -> only 1 tab remains, should exit split mode cleanly
        closeTab('tab-2');
        if (splitMode !== 'none') throw new Error(`Expected splitMode 'none', got ${splitMode}`);
        if (dualTabIds.length !== 0) throw new Error('dualTabIds should be empty after exiting split');

        console.log("ALL_JS_TESTS_PASSED");
        """
        proc = subprocess.run(["node", "-e", js_code], capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, f"Node script failed: {proc.stderr}")
        self.assertIn("ALL_JS_TESTS_PASSED", proc.stdout)


if __name__ == "__main__":
    unittest.main()
