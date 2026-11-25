"""Tests for embedded image/file/text previews, Show Images toggle, and modal navigation helpers in app/fire_ssh.py."""

import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from fire_ssh import HTML_TEMPLATE  # noqa: E402


class TestEmbeddedPreviewDOMAndCSS:
    """Verify UI elements, CSS rules, and JS helper definitions exist in HTML_TEMPLATE."""

    def test_embedded_preview_css_classes(self):
        expected_classes = [
            ".md-embedded-image-card",
            ".md-embedded-image-bar",
            ".md-embedded-image-body",
            ".md-local-file-link",
            ".md-inline-preview-btn",
            ".md-inline-file-preview",
            ".md-inline-file-preview-hdr",
            ".md-inline-file-preview-code",
            ".code-inline-file-link",
        ]
        for cls in expected_classes:
            assert cls in HTML_TEMPLATE, f"Missing CSS class {cls} in HTML_TEMPLATE"

    def test_modal_controls_and_refs_strip_present(self):
        expected_ids = [
            'id="image-modal-back-btn"',
            'id="file-modal-back-btn"',
            'id="file-modal-show-images-btn"',
            'id="file-modal-show-images-label"',
            'id="file-modal-refs-strip"',
            'id="file-modal-refs-count"',
            'id="file-modal-refs-toggle-btn"',
            'id="file-modal-refs-body"',
        ]
        for dom_id in expected_ids:
            assert dom_id in HTML_TEMPLATE, f"Missing DOM element {dom_id} in HTML_TEMPLATE"

    def test_js_helpers_defined(self):
        expected_fns = [
            "function normalizePosixPath(",
            "function resolvePreviewPath(",
            "function updateShowImagesButtonUI(",
            "function setEmbeddedImageCardExpanded(",
            "function togglePreviewShowImages(",
            "function toggleFileRefsStripExpanded(",
            "function buildEmbeddedImageCard(",
            "function toggleInlineFilePreviewDrawer(",
            "function createInlineFilePreviewDrawer(",
            "function extractPathCandidatesFromText(",
            "function updateModalBackButtons(",
            "function captureCurrentModalSnapshot(",
            "function navigateModalBack(",
            "function openReferencedTargetFromModal(",
            "function rewriteHtmlPreviewContent(",
            "function enhanceMarkdownPreview(",
            "function linkifyCodeElementPaths(",
            "function enhanceCodeAndRefsPreview(",
        ]
        for fn in expected_fns:
            assert fn in HTML_TEMPLATE, f"Missing JS helper {fn} in HTML_TEMPLATE"
        assert "fire-preview-open-ref" in HTML_TEMPLATE


class TestEmbeddedPreviewLogicWithNode:
    """Execute the exact preview JS helpers extracted from HTML_TEMPLATE in Node.js."""

    @classmethod
    def setup_class(cls):
        esc_match = re.search(
            r'(function escapeHtml\(.*?\n    \})',
            HTML_TEMPLATE,
            re.DOTALL,
        )
        assert esc_match is not None, "Could not extract escapeHtml"

        hover_match = re.search(
            r'(const BLOCKED_EXTENSIONS = new Set\(.*?\n    function cleanCandidatePath\(.*?\n    \})',
            HTML_TEMPLATE,
            re.DOTALL,
        )
        assert hover_match is not None, "Could not extract cleanCandidatePath block"

        cat_match = re.search(
            r'(function getFileCategory\(.*?\n    \})',
            HTML_TEMPLATE,
            re.DOTALL,
        )
        assert cat_match is not None, "Could not extract getFileCategory"

        build_url_match = re.search(
            r'(function buildImageUrl\(.*?\n    \})',
            HTML_TEMPLATE,
            re.DOTALL,
        )
        assert build_url_match is not None, "Could not extract buildImageUrl"

        preview_match = re.search(
            r'(let currentModalFilePath = \x27\x27;.*?\n    function getLanguageFromPath\(.*?\n    \})',
            HTML_TEMPLATE,
            re.DOTALL,
        )
        assert preview_match is not None, "Could not extract preview state + getLanguageFromPath"

        tail_match = re.search(
            r'(function sanitizeMarkdownHtml\(.*?\n    async function enhanceCodeAndRefsPreview\(.*?\n    \})',
            HTML_TEMPLATE,
            re.DOTALL,
        )
        assert tail_match is not None, "Could not extract preview enhancement helpers"

        cls.js_bundle = "\n".join([
            esc_match.group(1),
            hover_match.group(1),
            cat_match.group(1),
            build_url_match.group(1),
            preview_match.group(1),
            tail_match.group(1),
        ])

    def _run_node(self, body_js: str):
        prelude = r"""
        const _store = {};
        globalThis.localStorage = {
          getItem(k) { return Object.prototype.hasOwnProperty.call(_store, k) ? _store[k] : null; },
          setItem(k, v) { _store[k] = String(v); },
          removeItem(k) { delete _store[k]; },
        };
        let activeTabId = 'tab-1';
        let sessionToken = 'tok-test';
        let isModalEditing = false;
        const _toasts = [];
        function showToast(msg) { _toasts.push(String(msg)); }

        function makeClassList(el) {
          const set = new Set();
          return {
            _set: set,
            add(...cls) { cls.forEach(c => { if (c) set.add(c); }); },
            remove(...cls) { cls.forEach(c => set.delete(c)); },
            contains(c) { return set.has(c); },
            toggle(c, force) {
              if (force === undefined) {
                if (set.has(c)) { set.delete(c); return false; }
                set.add(c); return true;
              }
              if (force) set.add(c); else set.delete(c);
              return Boolean(force);
            },
            toString() { return Array.from(set).join(' '); },
          };
        }

        const _domRegistry = new Map();
        const _allElements = [];

        function makeMockElement(tagName, attrs = {}) {
          const el = {
            tagName: String(tagName || 'div').toUpperCase(),
            attrs: Object.assign({}, attrs),
            children: [],
            parentNode: null,
            textContent: '',
            style: {},
            title: '',
            loading: '',
            alt: '',
            href: '',
            type: '',
            onclick: null,
            onload: null,
            onerror: null,
            classList: null,
            setAttribute(k, v) {
              const val = String(v);
              this.attrs[k] = val;
              if (k === 'class') {
                val.split(/\s+/).filter(Boolean).forEach(c => this.classList.add(c));
              } else if (k === 'alt') {
                this.alt = val;
              }
            },
            getAttribute(k) {
              if (k === 'alt' && this.alt && !('alt' in this.attrs)) return this.alt;
              return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null;
            },
            removeAttribute(k) {
              delete this.attrs[k];
              if (k === 'href') this.href = '';
            },
            appendChild(child) {
              child.parentNode = this;
              this.children.push(child);
              return child;
            },
            insertAdjacentElement(_pos, node) {
              if (this.parentNode) this.parentNode.appendChild(node);
              return node;
            },
            replaceWith(node) {
              node.parentNode = this.parentNode;
              if (this.parentNode) {
                const idx = this.parentNode.children.indexOf(this);
                if (idx >= 0) this.parentNode.children[idx] = node;
              }
              this._replacedBy = node;
            },
            querySelector(sel) {
              return this.querySelectorAll(sel)[0] || null;
            },
            querySelectorAll(sel) {
              const parts = sel.split(',').map(s => s.trim().toLowerCase());
              const out = [];
              const walk = (node) => {
                for (const ch of (node.children || [])) {
                  const tag = (ch.tagName || '').toLowerCase();
                  const hit = parts.some(p => {
                    if (p.startsWith('.')) return ch.classList.contains(p.slice(1));
                    const attrMatch = /^([a-z0-9_-]*)\[([a-z0-9_-]+)\]$/.exec(p);
                    if (attrMatch) {
                      const [, reqTag, reqAttr] = attrMatch;
                      return (!reqTag || tag === reqTag) && ch.getAttribute(reqAttr) !== null;
                    }
                    return tag === p;
                  });
                  if (hit) out.push(ch);
                  walk(ch);
                }
              };
              walk(this);
              return out;
            },
            get innerHTML() {
              return this.children.map(c => c.outerHTML).join('');
            },
            set innerHTML(v) {
              this.children = [];
              if (v) this.textContent = String(v);
            },
            get outerHTML() {
              const t = this.tagName.toLowerCase();
              if (t === 'source' || t === 'img') {
                const attrStr = Object.entries(this.attrs).map(([k, v]) => ` ${k}="${escapeHtml(v)}"`).join('');
                return `<${t}${attrStr}>`;
              }
              const attrStr = Object.entries(this.attrs).map(([k, v]) => ` ${k}="${escapeHtml(v)}"`).join('');
              const body = this.children.length > 0 ? this.children.map(c => c.outerHTML).join('') : (this.textContent || '');
              return `<${t}${attrStr}>${body}</${t}>`;
            },
          };
          el.classList = makeClassList(el);
          const toDataAttr = (prop) => 'data-' + String(prop).replace(/[A-Z]/g, m => '-' + m.toLowerCase());
          el.dataset = new Proxy({}, {
            get(_t, prop) {
              const k = toDataAttr(prop);
              return Object.prototype.hasOwnProperty.call(el.attrs, k) ? el.attrs[k] : undefined;
            },
            set(_t, prop, val) {
              el.attrs[toDataAttr(prop)] = String(val);
              return true;
            },
            deleteProperty(_t, prop) {
              delete el.attrs[toDataAttr(prop)];
              return true;
            },
          });
          Object.defineProperty(el, 'src', {
            get() { return el.attrs.src || ''; },
            set(val) {
              if (val === null || val === undefined || val === '') delete el.attrs.src;
              else el.attrs.src = String(val);
            },
          });
          Object.defineProperty(el, 'className', {
            get() { return Array.from(el.classList._set).join(' '); },
            set(val) {
              el.classList._set.clear();
              String(val || '').split(/\s+/).filter(Boolean).forEach(c => el.classList.add(c));
            },
          });
          _allElements.push(el);
          return el;
        }

        function registerMockId(id, tag = 'div') {
          const el = makeMockElement(tag, { id });
          _domRegistry.set(id, el);
          return el;
        }

        globalThis.document = {
          getElementById(id) { return _domRegistry.get(id) || null; },
          createElement(tag) { return makeMockElement(tag); },
          querySelectorAll(sel) {
            if (sel.startsWith('.')) {
              const cls = sel.slice(1);
              return _allElements.filter(e => e.classList.contains(cls));
            }
            return [];
          },
        };

        class MockDOMParser {
          parseFromString(html, _mime) {
            const docEl = makeMockElement('html');
            const body = makeMockElement('body');
            docEl.appendChild(body);
            const tagRe = /<(img|video|audio|source|a)\b([^>]*)>(?:([\s\S]*?)<\/\1>)?/gi;
            let m;
            while ((m = tagRe.exec(html)) !== null) {
              const tag = m[1].toLowerCase();
              const rawAttrs = m[2] || '';
              const inner = m[3] || '';
              const attrs = {};
              const attrRe = /([A-Za-z0-9_:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g;
              let am;
              while ((am = attrRe.exec(rawAttrs)) !== null) {
                attrs[am[1]] = am[2] !== undefined ? am[2] : am[3];
              }
              const node = makeMockElement(tag, attrs);
              if (inner) node.textContent = inner;
              body.appendChild(node);
            }
            return {
              body,
              documentElement: docEl,
              createElement(tag) { return makeMockElement(tag); },
              querySelectorAll(sel) { return body.querySelectorAll(sel); },
            };
          }
        }
        globalThis.DOMParser = MockDOMParser;
        """
        script = f"""
        {prelude}
        {self.js_bundle}
        const __result = (() => {{
        {body_js}
        }})();
        console.log(JSON.stringify(__result));
        """
        proc = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        if proc.returncode != 0:
            raise AssertionError(f"Node execution failed (rc={proc.returncode}):\n{proc.stderr}")
        return json.loads(proc.stdout.strip())

    def test_resolve_preview_path_cases(self):
        res = self._run_node("""
        const base = '/root/fire-pm/docs/README.md';
        return {
          dotRel: resolvePreviewPath('./arch.png', base),
          dotDotRel: resolvePreviewPath('../assets/logo.svg#L12', base),
          bareRel: resolvePreviewPath('screens/demo.jpg', base),
          fileUriLine: resolvePreviewPath('file:///var/log/app.log:42:5', base),
          tildeLine: resolvePreviewPath('~/notes/todo.md#L7', base),
          anchor: resolvePreviewPath('#quick-start', base),
          external: resolvePreviewPath('https://example.com/pic.png', base),
          jsUnsafe: resolvePreviewPath('javascript:alert(1)', base),
          dataHtmlUnsafe: resolvePreviewPath('data:text/html,<script>alert(1)</script>', base),
        };
        """)
        assert res["dotRel"]["path"] == "/root/fire-pm/docs/arch.png"
        assert res["dotRel"]["line"] is None
        assert res["dotDotRel"]["path"] == "/root/fire-pm/assets/logo.svg"
        assert res["dotDotRel"]["line"] == 12
        assert res["bareRel"]["path"] == "/root/fire-pm/docs/screens/demo.jpg"
        assert res["fileUriLine"]["path"] == "/var/log/app.log"
        assert res["fileUriLine"]["line"] == 42
        assert res["tildeLine"]["path"] == "~/notes/todo.md"
        assert res["tildeLine"]["line"] == 7
        assert res["anchor"]["isAnchor"] is True
        assert res["external"]["isExternal"] is True
        assert res["jsUnsafe"]["isUnsafe"] is True
        assert res["dataHtmlUnsafe"]["isUnsafe"] is True

    def test_extract_path_candidates_from_text(self):
        cands = self._run_node(r"""
        const sample = [
          'See ![Diagram](./img/flow.png) and [Guide](../docs/GUIDE.md#L15)',
          'HTML: <img src="assets/shot.jpg"> <a href="https://example.com/skip.png">web</a>',
          'Code refs: `./scripts/run.sh:22`, `/etc/hosts`, `file:///tmp/out.txt`, v1.2 123.45 #hash',
        ].join('\n');
        return extractPathCandidatesFromText(sample);
        """)
        assert "./img/flow.png" in cands
        assert "../docs/GUIDE.md#L15" in cands
        assert "assets/shot.jpg" in cands
        assert "./scripts/run.sh:22" in cands
        assert "/etc/hosts" in cands
        assert "file:///tmp/out.txt" in cands
        assert all("https://example.com" not in c for c in cands)
        assert "123.45" not in cands

    def test_render_markdown_fallback_images_before_links(self):
        html = self._run_node(r"""
        return renderMarkdownFallback('![Architecture](./arch.png)\n\nRead [Guide](./GUIDE.md) and ![Icon](icon.svg)');
        """)
        assert '<img src="./arch.png" alt="Architecture"' in html
        assert '<img src="icon.svg" alt="Icon"' in html
        assert '<a href="./GUIDE.md"' in html
        # Ensure ![...](...) was NOT converted into a broken !<a href=...> tag
        assert '!<a ' not in html

    def test_show_images_toggle_and_card_expand_collapse(self):
        res = self._run_node(r"""
        const btn = registerMockId('file-modal-show-images-btn', 'button');
        const lbl = registerMockId('file-modal-show-images-label', 'span');

        const initialFlag = showImagesInPreview;
        const card = buildEmbeddedImageCard('/root/docs/pic.png', '/api/preview?file=%2Froot%2Fdocs%2Fpic.png', 'pic.png', 'Sample', 'tab-1', false);
        const bodyInitiallyHidden = card.querySelector('.md-embedded-image-body').classList.contains('hidden');
        const srcInitially = card.querySelector('img').getAttribute('src');

        // Turn OFF Show Images globally -> card body hides
        togglePreviewShowImages();
        const afterOff = {
          flag: showImagesInPreview,
          stored: localStorage.getItem('fire_ssh_show_images_preview'),
          label: lbl.textContent,
          aria: btn.getAttribute('aria-pressed'),
          cardExpanded: card.dataset.expanded,
          bodyHidden: card.querySelector('.md-embedded-image-body').classList.contains('hidden'),
        };

        // Expand single card manually even while global default is OFF
        setEmbeddedImageCardExpanded(card, true);
        const manualExpand = {
          expanded: card.dataset.expanded,
          bodyHidden: card.querySelector('.md-embedded-image-body').classList.contains('hidden'),
          imgSrc: card.querySelector('img').getAttribute('src'),
        };

        // Collapse single card, then turn ON Show Images globally -> card expands again
        setEmbeddedImageCardExpanded(card, false);
        togglePreviewShowImages();
        const afterOn = {
          flag: showImagesInPreview,
          stored: localStorage.getItem('fire_ssh_show_images_preview'),
          label: lbl.textContent,
          aria: btn.getAttribute('aria-pressed'),
          cardExpanded: card.dataset.expanded,
          bodyHidden: card.querySelector('.md-embedded-image-body').classList.contains('hidden'),
          imgSrc: card.querySelector('img').getAttribute('src'),
        };

        return { initialFlag, bodyInitiallyHidden, srcInitially, afterOff, manualExpand, afterOn };
        """)
        assert res["initialFlag"] is True
        assert res["bodyInitiallyHidden"] is False
        assert res["srcInitially"] == "/api/preview?file=%2Froot%2Fdocs%2Fpic.png"
        assert res["afterOff"]["flag"] is False
        assert res["afterOff"]["stored"] == "false"
        assert res["afterOff"]["label"] == "Show Images: OFF"
        assert res["afterOff"]["aria"] == "false"
        assert res["afterOff"]["cardExpanded"] == "0"
        assert res["afterOff"]["bodyHidden"] is True
        assert res["manualExpand"]["expanded"] == "1"
        assert res["manualExpand"]["bodyHidden"] is False
        assert res["manualExpand"]["imgSrc"] == "/api/preview?file=%2Froot%2Fdocs%2Fpic.png"
        assert res["afterOn"]["flag"] is True
        assert res["afterOn"]["stored"] == "true"
        assert res["afterOn"]["label"] == "Show Images: ON"
        assert res["afterOn"]["aria"] == "true"
        assert res["afterOn"]["cardExpanded"] == "1"
        assert res["afterOn"]["bodyHidden"] is False
        assert res["afterOn"]["imgSrc"] == "/api/preview?file=%2Froot%2Fdocs%2Fpic.png"

    def test_rewrite_html_preview_content_respects_show_images_and_rewrites_links(self):
        res = self._run_node(r"""
        const raw = [
          '<img src="./shot.png" alt="Screen">',
          '<img src="https://cdn.example.com/ext.png" alt="Ext">',
          '<a href="../docs/README.md#L25">Readme</a>',
          '<a href="https://example.com">Web</a>',
          '<a href="javascript:alert(1)">Bad</a>',
        ].join('\n');

        showImagesInPreview = false;
        const hiddenOut = rewriteHtmlPreviewContent(raw, '/root/app/index.html', 'tab-1');

        showImagesInPreview = true;
        const shownOut = rewriteHtmlPreviewContent(raw, '/root/app/index.html', 'tab-1');
        return { hiddenOut, shownOut };
        """)
        hidden_out = res["hiddenOut"]
        shown_out = res["shownOut"]

        assert "Image hidden: Screen" in hidden_out
        assert "Image hidden: Ext" in hidden_out
        assert 'src="/api/preview?file=%2Froot%2Fapp%2Fshot.png' not in hidden_out

        assert 'src="/api/preview?file=%2Froot%2Fapp%2Fshot.png&amp;tab=tab-1&amp;token=tok-test"' in shown_out
        assert 'src="https://cdn.example.com/ext.png"' in shown_out
        assert 'data-fire-local-path="/root/docs/README.md"' in shown_out
        assert 'data-fire-local-line="25"' in shown_out
        assert 'target="_blank"' in shown_out
        assert 'javascript:alert(1)' not in shown_out
        assert "fire-preview-open-ref" in shown_out
