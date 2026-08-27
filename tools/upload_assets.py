#!/usr/bin/env python3
"""
Fire PM Asset Image Upload & Paste Utility
Allows pasting screenshots from clipboard (Ctrl+V) or uploading files
and saves them directly into /root/fire-package-pm/assets/
"""

import os
import sys
import json
import base64
import argparse
import socketserver
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
ASSETS_DIR = os.path.join(PROJECT_ROOT, "assets")
os.makedirs(ASSETS_DIR, exist_ok=True)

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en" class="h-full bg-slate-950 text-slate-100">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Fire PM — Screenshot Asset Uploader</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    .dropzone {
      border: 2px dashed #334155;
      transition: all 0.2s ease;
    }
    .dropzone.dragover {
      border-color: #f97316;
      background-color: rgba(249, 115, 22, 0.05);
    }
  </style>
</head>
<body class="min-h-full flex flex-col items-center justify-start p-4 sm:p-8">
  <div class="max-w-4xl w-full space-y-6">
    <!-- Header -->
    <header class="flex items-center justify-between border-b border-slate-800 pb-4">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-orange-500/20 border border-orange-500/30 flex items-center justify-center text-xl">
          🔥
        </div>
        <div>
          <h1 class="text-xl font-bold text-slate-100 flex items-center gap-2">
            Fire PM <span class="text-orange-500 text-sm font-mono px-2 py-0.5 bg-orange-500/10 rounded-md border border-orange-500/20">Asset Uploader</span>
          </h1>
          <p class="text-xs text-slate-400">Paste screenshots from clipboard (Ctrl+V) or drag & drop to save directly to assets/</p>
        </div>
      </div>
      <div class="text-xs font-mono text-slate-500">
        Target: <span class="text-slate-300">assets/</span>
      </div>
    </header>

    <!-- Upload Box -->
    <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <!-- Preset Selector -->
        <div>
          <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Select Target Image Preset</label>
          <select id="presetSelect" class="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-orange-500">
            <option value="web-dashboard.png">web-dashboard.png (Main Web UI Overview)</option>
            <option value="tui-dashboard.png">tui-dashboard.png (Terminal TUI Dashboard)</option>
            <option value="web-terminal.png">web-terminal.png (Remote Web Terminal / SSH)</option>
            <option value="web-logs.png">web-logs.png (Live Journalctl Logs Viewer)</option>
            <option value="web-tunnels.png">web-tunnels.png (Tunnel Management Console)</option>
            <option value="cli-live.png">cli-live.png (CLI Cockpit / Monit)</option>
            <option value="custom">Custom Filename...</option>
          </select>
        </div>

        <!-- Custom Filename Input -->
        <div>
          <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Filename</label>
          <input type="text" id="filenameInput" value="web-dashboard.png" class="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-slate-200 font-mono focus:outline-none focus:border-orange-500" placeholder="e.g. web-dashboard.png" />
        </div>
      </div>

      <!-- Drag & Drop / Paste Zone -->
      <div id="dropzone" class="dropzone rounded-2xl p-8 flex flex-col items-center justify-center text-center cursor-pointer min-h-[220px] bg-slate-950/50">
        <div id="dropPrompt" class="space-y-3">
          <div class="w-14 h-14 mx-auto rounded-2xl bg-slate-800/80 border border-slate-700 flex items-center justify-center text-2xl text-slate-300 shadow-inner">
            📋
          </div>
          <div class="space-y-1">
            <p class="text-sm font-semibold text-slate-200">
              Press <kbd class="px-2 py-1 bg-slate-800 border border-slate-700 rounded text-xs text-orange-400 font-mono">Ctrl+V</kbd> to Paste Screenshot
            </p>
            <p class="text-xs text-slate-500">or click to browse image from file system</p>
          </div>
        </div>

        <input type="file" id="fileInput" accept="image/*" class="hidden" />

        <!-- Image Preview -->
        <div id="previewContainer" class="hidden w-full space-y-4">
          <div class="relative max-h-[360px] overflow-hidden rounded-xl border border-slate-700/60 bg-black/40 flex items-center justify-center">
            <img id="previewImg" class="max-h-[340px] max-w-full object-contain rounded-lg shadow-lg" />
          </div>
          <div class="flex items-center justify-between text-xs text-slate-400 font-mono px-1">
            <span id="previewInfo">0 KB</span>
            <button id="clearBtn" class="text-rose-400 hover:text-rose-300 transition-colors">Clear</button>
          </div>
        </div>
      </div>

      <!-- Action Button -->
      <div class="flex items-center justify-between pt-2">
        <div id="statusMsg" class="text-xs font-medium"></div>
        <button id="saveBtn" disabled class="px-6 py-2.5 rounded-xl bg-orange-500 hover:bg-orange-600 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-semibold shadow-lg shadow-orange-500/20 transition-all flex items-center gap-2">
          <span>💾 Save Image to assets/</span>
        </button>
      </div>
    </div>

    <!-- Gallery of existing assets -->
    <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="text-sm font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
          <span>📁 Saved Assets in /assets</span>
          <span id="assetCount" class="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 font-mono">0</span>
        </h2>
        <button onclick="loadAssets()" class="text-xs text-slate-400 hover:text-slate-200 transition-colors">🔄 Refresh</button>
      </div>

      <div id="assetsGrid" class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
        <p class="text-xs text-slate-500 italic col-span-full py-4 text-center">No images uploaded yet.</p>
      </div>
    </div>
  </div>

  <script>
    let currentDataUrl = null;

    const presetSelect = document.getElementById('presetSelect');
    const filenameInput = document.getElementById('filenameInput');
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('fileInput');
    const dropPrompt = document.getElementById('dropPrompt');
    const previewContainer = document.getElementById('previewContainer');
    const previewImg = document.getElementById('previewImg');
    const previewInfo = document.getElementById('previewInfo');
    const clearBtn = document.getElementById('clearBtn');
    const saveBtn = document.getElementById('saveBtn');
    const statusMsg = document.getElementById('statusMsg');

    presetSelect.addEventListener('change', (e) => {
      if (e.target.value !== 'custom') {
        filenameInput.value = e.target.value;
      } else {
        filenameInput.value = '';
        filenameInput.focus();
      }
    });

    filenameInput.addEventListener('input', () => {
      let matched = false;
      for (const opt of presetSelect.options) {
        if (opt.value === filenameInput.value) {
          presetSelect.value = opt.value;
          matched = true;
          break;
        }
      }
      if (!matched) presetSelect.value = 'custom';
    });

    // Global Paste Listener (Ctrl+V)
    window.addEventListener('paste', (e) => {
      const items = (e.clipboardData || e.originalEvent.clipboardData).items;
      for (const item of items) {
        if (item.kind === 'file' && item.type.startsWith('image/')) {
          const blob = item.getAsFile();
          handleFile(blob);
          e.preventDefault();
          break;
        }
      }
    });

    // Drag & Drop
    dropzone.addEventListener('click', (e) => {
      if (e.target !== clearBtn) fileInput.click();
    });

    fileInput.addEventListener('change', (e) => {
      if (e.target.files && e.target.files[0]) {
        handleFile(e.target.files[0]);
      }
    });

    ['dragenter', 'dragover'].forEach(name => {
      dropzone.addEventListener(name, (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
      });
    });

    ['dragleave', 'drop'].forEach(name => {
      dropzone.addEventListener(name, (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
      });
    });

    dropzone.addEventListener('drop', (e) => {
      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        handleFile(e.dataTransfer.files[0]);
      }
    });

    function handleFile(file) {
      if (!file.type.startsWith('image/')) {
        showStatus('Only image files are allowed', 'text-rose-400');
        return;
      }
      const reader = new FileReader();
      reader.onload = (e) => {
        currentDataUrl = e.target.result;
        previewImg.src = currentDataUrl;
        const sizeKb = (file.size / 1024).toFixed(1);
        previewInfo.textContent = `${file.name || 'Pasted Image'} • ${sizeKb} KB`;
        dropPrompt.classList.add('hidden');
        previewContainer.classList.remove('hidden');
        saveBtn.disabled = false;
        showStatus('Image loaded! Click "Save Image" to write to assets/', 'text-emerald-400');
      };
      reader.readAsDataURL(file);
    }

    clearBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      resetForm();
    });

    function resetForm() {
      currentDataUrl = null;
      fileInput.value = '';
      previewImg.src = '';
      previewContainer.classList.add('hidden');
      dropPrompt.classList.remove('hidden');
      saveBtn.disabled = true;
      statusMsg.textContent = '';
    }

    function showStatus(text, colorClass) {
      statusMsg.textContent = text;
      statusMsg.className = `text-xs font-medium ${colorClass}`;
    }

    saveBtn.addEventListener('click', async () => {
      let fname = filenameInput.value.trim();
      if (!fname) {
        showStatus('Please specify a filename', 'text-rose-400');
        return;
      }
      if (!fname.endsWith('.png') && !fname.endsWith('.jpg') && !fname.endsWith('.jpeg') && !fname.endsWith('.webp')) {
        fname += '.png';
        filenameInput.value = fname;
      }
      if (!currentDataUrl) {
        showStatus('No image data found', 'text-rose-400');
        return;
      }

      saveBtn.disabled = true;
      showStatus('Saving...', 'text-slate-400');

      try {
        const res = await fetch('/api/upload', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename: fname, data: currentDataUrl })
        });
        const data = await res.json();
        if (data.success) {
          showStatus(`✔ Successfully saved to assets/${data.filename}`, 'text-emerald-400 font-bold');
          loadAssets();
          advancePreset(fname);
        } else {
          showStatus(`Error: ${data.error}`, 'text-rose-400');
          saveBtn.disabled = false;
        }
      } catch (err) {
        showStatus(`Network Error: ${err.message}`, 'text-rose-400');
        saveBtn.disabled = false;
      }
    });

    function advancePreset(savedName) {
      const presets = [
        'web-dashboard.png',
        'tui-dashboard.png',
        'web-terminal.png',
        'web-logs.png',
        'web-tunnels.png',
        'cli-live.png'
      ];
      const idx = presets.indexOf(savedName);
      if (idx !== -1 && idx + 1 < presets.length) {
        const next = presets[idx + 1];
        presetSelect.value = next;
        filenameInput.value = next;
      }
    }

    async function loadAssets() {
      try {
        const res = await fetch('/api/list');
        const data = await res.json();
        const grid = document.getElementById('assetsGrid');
        document.getElementById('assetCount').textContent = data.files.length;

        if (data.files.length === 0) {
          grid.innerHTML = '<p class="text-xs text-slate-500 italic col-span-full py-4 text-center">No images uploaded yet.</p>';
          return;
        }

        grid.innerHTML = data.files.map(f => `
          <div class="bg-slate-950 border border-slate-800 rounded-xl overflow-hidden group hover:border-slate-700 transition-all flex flex-col">
            <div class="h-32 bg-slate-900 flex items-center justify-center overflow-hidden relative">
              <img src="/assets/${encodeURIComponent(f.name)}?t=${Date.now()}" class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
            </div>
            <div class="p-3 space-y-1 flex-1 flex flex-col justify-between">
              <div>
                <p class="text-xs font-semibold text-slate-200 font-mono truncate" title="${f.name}">${f.name}</p>
                <p class="text-[11px] text-slate-500 font-mono">${(f.size / 1024).toFixed(1)} KB</p>
              </div>
              <div class="flex items-center justify-between pt-2 border-t border-slate-900 text-xs">
                <a href="/assets/${encodeURIComponent(f.name)}?t=${Date.now()}" target="_blank" class="text-orange-400 hover:text-orange-300">View ↗</a>
                <button onclick="deleteAsset('${f.name}')" class="text-rose-400 hover:text-rose-300">Delete</button>
              </div>
            </div>
          </div>
        `).join('');
      } catch (e) {
        console.error(e);
      }
    }

    async function deleteAsset(name) {
      if (!confirm(`Delete ${name}?`)) return;
      await fetch('/api/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: name })
      });
      loadAssets();
    }

    loadAssets();
  </script>
</body>
</html>
"""

class AssetUploadHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        
        if parsed.path == '/' or parsed.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode('utf-8'))
            return

        elif parsed.path == '/api/list':
            files = []
            if os.path.exists(ASSETS_DIR):
                for f in sorted(os.listdir(ASSETS_DIR)):
                    if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg')):
                        fpath = os.path.join(ASSETS_DIR, f)
                        files.append({
                            "name": f,
                            "size": os.path.getsize(fpath)
                        })
            self.send_json({"files": files})
            return

        elif parsed.path.startswith('/assets/'):
            filename = os.path.basename(urllib.parse.unquote(parsed.path[8:]))
            filepath = os.path.join(ASSETS_DIR, filename)
            if os.path.exists(filepath) and os.path.isfile(filepath):
                ext = os.path.splitext(filename)[1].lower()
                mime = {
                    '.png': 'image/png',
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.webp': 'image/webp',
                    '.svg': 'image/svg+xml'
                }.get(ext, 'application/octet-stream')

                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(os.path.getsize(filepath)))
                self.end_headers()
                with open(filepath, 'rb') as img:
                    self.wfile.write(img.read())
                return
            else:
                self.send_error(404, "Asset Not Found")
                return

        self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)

        try:
            payload = json.loads(body.decode('utf-8'))
        except Exception:
            self.send_json({"success": False, "error": "Invalid JSON"}, status=400)
            return

        if parsed.path == '/api/upload':
            filename = payload.get('filename', '').strip()
            data_url = payload.get('data', '')

            if not filename:
                self.send_json({"success": False, "error": "Filename is required"}, status=400)
                return

            # Sanitize filename (alphanumeric, dash, underscore, dot)
            filename = os.path.basename(filename)
            filename = "".join(c for c in filename if c.isalnum() or c in "._-")
            if not filename:
                self.send_json({"success": False, "error": "Invalid filename characters"}, status=400)
                return

            if not data_url or ',' not in data_url:
                self.send_json({"success": False, "error": "Invalid image data payload"}, status=400)
                return

            try:
                base64_data = data_url.split(',', 1)[1]
                raw_bytes = base64.b64decode(base64_data)
                target_path = os.path.join(ASSETS_DIR, filename)
                with open(target_path, 'wb') as f:
                    f.write(raw_bytes)

                print(f"[Upload] Saved: {target_path} ({len(raw_bytes)} bytes)")
                self.send_json({"success": True, "filename": filename, "size": len(raw_bytes)})
                return
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=500)
                return

        elif parsed.path == '/api/delete':
            filename = os.path.basename(payload.get('filename', ''))
            target_path = os.path.join(ASSETS_DIR, filename)
            if os.path.exists(target_path):
                os.remove(target_path)
                self.send_json({"success": True})
            else:
                self.send_json({"success": False, "error": "File not found"}, status=404)
            return

        self.send_error(404, "Unknown API endpoint")

    def send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass

class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

def main():
    parser = argparse.ArgumentParser(description="Fire PM Screenshot Asset Uploader")
    parser.add_argument('--port', type=int, default=8899, help="Port to run the uploader on (default: 8899)")
    args = parser.parse_args()

    port = args.port
    server = ThreadedHTTPServer(('0.0.0.0', port), AssetUploadHandler)
    print(f"\n=======================================================")
    print(f"🔥 Fire PM Screenshot Asset Uploader is running!")
    print(f"  • Local URL:  http://localhost:{port}")
    print(f"  • Target Dir: {ASSETS_DIR}")
    print(f"  • Paste (Ctrl+V) from any screenshot tool directly")
    print(f"=======================================================\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping uploader...")
        server.server_close()

if __name__ == '__main__':
    main()
