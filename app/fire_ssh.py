#!/usr/bin/env python3
"""
Fire PM — Remote Web Terminal (fire ssh)
Provides secure, browser-based remote terminal access over WebSockets/PTY
with salted PBKDF2 password authentication, brute-force rate limiting, and session security.
"""

import os
import sys
import time
import json
import pty
import select
import struct
import fcntl
import termios
import signal
import socket
import secrets
import hashlib
import hmac
import base64
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import threading

# Configuration Constants
DEFAULT_PORT = 7681
AUTH_FILE = "/etc/fire-pm/ssh-auth.json"
USER_AUTH_FILE = os.path.expanduser("~/.fire/ssh-auth.json")
SESSION_EXPIRY_SECONDS = 14400  # 4 hours
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 300  # 5 minutes
WINDOW_SECONDS = 300

# ==================== PASSWORD & SECURITY ====================

class PasswordManager:
    @staticmethod
    def hash_password(plain_text: str, salt_hex: str = None) -> tuple:
        if not salt_hex:
            salt_bytes = secrets.token_bytes(16)
            salt_hex = salt_bytes.hex()
        else:
            salt_bytes = bytes.fromhex(salt_hex)
        
        derived = hashlib.pbkdf2_hmac(
            'sha256',
            plain_text.encode('utf-8'),
            salt_bytes,
            iterations=100_000
        )
        return salt_hex, derived.hex()

    @staticmethod
    def verify(plain_text: str, salt_hex: str, hash_hex: str) -> bool:
        if not plain_text or not salt_hex or not hash_hex:
            return False
        try:
            _, check_hash = PasswordManager.hash_password(plain_text, salt_hex)
            return hmac.compare_digest(check_hash, hash_hex)
        except Exception:
            return False

    @staticmethod
    def get_auth_file_path() -> str:
        if os.geteuid() == 0:
            os.makedirs(os.path.dirname(AUTH_FILE), exist_ok=True)
            return AUTH_FILE
        else:
            os.makedirs(os.path.dirname(USER_AUTH_FILE), exist_ok=True)
            return USER_AUTH_FILE

    @staticmethod
    def load_stored_credentials() -> tuple:
        path = PasswordManager.get_auth_file_path()
        if os.path.isfile(path):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                    return data.get('salt'), data.get('hash')
            except Exception:
                pass
        return None, None

    @staticmethod
    def save_credentials(salt_hex: str, hash_hex: str):
        path = PasswordManager.get_auth_file_path()
        try:
            with open(path, 'w') as f:
                json.dump({'salt': salt_hex, 'hash': hash_hex, 'updated_at': int(time.time())}, f, indent=2)
            os.chmod(path, 0o600)
        except Exception as e:
            sys.stderr.write(f"Warning: Could not save credentials to {path}: {e}\n")


class RateLimiter:
    def __init__(self):
        self.lock = threading.Lock()
        self.failures = {}  # ip -> [timestamps]
        self.lockouts = {}  # ip -> lockout_until_timestamp

    def is_locked(self, ip: str) -> tuple:
        with self.lock:
            now = time.time()
            if ip in self.lockouts:
                until = self.lockouts[ip]
                if now < until:
                    return True, int(until - now)
                else:
                    del self.lockouts[ip]
                    self.failures[ip] = []
            return False, 0

    def record_failure(self, ip: str) -> tuple:
        with self.lock:
            now = time.time()
            attempts = self.failures.get(ip, [])
            attempts = [t for t in attempts if now - t < WINDOW_SECONDS]
            attempts.append(now)
            self.failures[ip] = attempts

            if len(attempts) >= MAX_ATTEMPTS:
                self.lockouts[ip] = now + LOCKOUT_SECONDS
                return True, LOCKOUT_SECONDS, 0
            else:
                remaining = MAX_ATTEMPTS - len(attempts)
                return False, 0, remaining

    def record_success(self, ip: str):
        with self.lock:
            self.failures.pop(ip, None)
            self.lockouts.pop(ip, None)


class SessionManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.sessions = {}  # token -> {"ip": str, "created_at": float}

    def create_session(self, ip: str) -> str:
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.sessions[token] = {"ip": ip, "created_at": time.time()}
        return token

    def is_valid(self, token: str, ip: str = None) -> bool:
        if not token:
            return False
        with self.lock:
            info = self.sessions.get(token)
            if not info:
                return False
            if time.time() - info["created_at"] > SESSION_EXPIRY_SECONDS:
                del self.sessions[token]
                return False
            return True

    def revoke(self, token: str):
        with self.lock:
            self.sessions.pop(token, None)


# ==================== RFC 6455 WEBSOCKET PROTOCOL ====================

def ws_handshake_response(key: str) -> bytes:
    magic = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    accept = base64.b64encode(hashlib.sha1(key.strip().encode('ascii') + magic).digest()).decode('ascii')
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        "\r\n"
    )
    return response.encode('ascii')


def ws_read_frame(sock: socket.socket) -> tuple:
    """Reads a complete WebSocket frame from a raw socket. Returns (opcode, payload)."""
    header = sock.recv(2)
    if not header or len(header) < 2:
        return None, b""
    
    b1, b2 = header[0], header[1]
    fin = bool(b1 & 0x80)
    opcode = b1 & 0x0f
    masked = bool(b2 & 0x80)
    payload_len = b2 & 0x7f

    if payload_len == 126:
        ext = sock.recv(2)
        if len(ext) < 2: return None, b""
        payload_len = struct.unpack(">H", ext)[0]
    elif payload_len == 127:
        ext = sock.recv(8)
        if len(ext) < 8: return None, b""
        payload_len = struct.unpack(">Q", ext)[0]

    mask = b""
    if masked:
        mask = sock.recv(4)
        if len(mask) < 4: return None, b""

    data = bytearray()
    while len(data) < payload_len:
        chunk = sock.recv(min(4096, payload_len - len(data)))
        if not chunk:
            break
        data.extend(chunk)

    if masked:
        unmasked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        return opcode, unmasked
    return opcode, bytes(data)


def ws_make_frame(payload: bytes, opcode: int = 1) -> bytes:
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    length = len(payload)
    if length < 126:
        header = struct.pack("!BB", 0x80 | opcode, length)
    elif length <= 65535:
        header = struct.pack("!BBH", 0x80 | opcode, 126, length)
    else:
        header = struct.pack("!BBQ", 0x80 | opcode, 127, length)
    return header + payload


# ==================== HTML / CLIENT ASSETS ====================

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en" class="h-full bg-slate-950 text-slate-100">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Fire PM — Remote Terminal</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css" />
  <script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/xterm-addon-web-links@0.9.0/lib/xterm-addon-web-links.js"></script>
  <style>
    .xterm { height: 100%; padding: 4px; }
    .xterm-viewport { background-color: #020617 !important; }
    /* Scrollbar */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #020617; }
    ::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #334155; }
  </style>
</head>
<body class="h-full flex flex-col font-sans antialiased overflow-hidden select-none bg-[#020617]">

  <!-- LOGIN CONTAINER -->
  <div id="login-view" class="flex-1 flex items-center justify-center p-4">
    <div class="w-full max-w-md bg-slate-900 border border-slate-800 rounded-2xl p-8 shadow-2xl backdrop-blur">
      <div class="flex items-center space-x-3 mb-6">
        <div class="w-10 h-10 rounded-xl bg-orange-500/10 border border-orange-500/20 flex items-center justify-center text-xl">
          🔥
        </div>
        <div>
          <h1 class="text-xl font-bold text-white tracking-tight flex items-center gap-2">
            Fire PM
            <span class="text-xs px-2 py-0.5 rounded-full bg-orange-500/20 text-orange-400 font-mono font-medium">SSH</span>
          </h1>
          <p class="text-xs text-slate-400">Secure Remote Terminal Access</p>
        </div>
      </div>

      <div id="error-box" class="hidden mb-4 p-3.5 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-start space-x-2">
        <span class="text-base leading-none">⚠️</span>
        <span id="error-msg" class="flex-1"></span>
      </div>

      <form id="login-form" class="space-y-4" onsubmit="handleLogin(event)">
        <div>
          <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5">Access Password</label>
          <div class="relative">
            <input type="password" id="password" required autofocus autocomplete="current-password"
              placeholder="Enter terminal password"
              class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:border-orange-500 focus:ring-1 focus:ring-orange-500 transition text-sm">
            <button type="button" onclick="togglePassword()" class="absolute right-3 top-3 text-slate-400 hover:text-slate-200 text-xs px-1 py-0.5">Show</button>
          </div>
        </div>

        <button type="submit" id="submit-btn"
          class="w-full bg-orange-500 hover:bg-orange-600 active:bg-orange-700 text-white font-semibold py-3 rounded-xl transition flex items-center justify-center space-x-2 text-sm shadow-lg shadow-orange-500/20">
          <span>Authenticate & Connect</span>
          <span class="text-xs">→</span>
        </button>
      </form>

      <div class="mt-6 pt-6 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-500">
        <span class="flex items-center gap-1.5">
          <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
          PBKDF2-HMAC Salted
        </span>
        <span>Rate Limited (5 max)</span>
      </div>
    </div>
  </div>

  <!-- TERMINAL CONTAINER -->
  <div id="terminal-view" class="hidden flex-1 flex flex-col h-full">
    <!-- Header bar -->
    <header class="h-12 bg-slate-900 border-b border-slate-800 px-4 flex items-center justify-between select-none">
      <div class="flex items-center space-x-3">
        <span class="text-lg">🔥</span>
        <span class="text-sm font-semibold text-white">Fire PM Terminal</span>
        <span id="conn-badge" class="text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 font-mono flex items-center gap-1">
          <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
          Connected
        </span>
      </div>

      <div class="flex items-center space-x-2">
        <button onclick="termFit()" title="Fit Window" class="px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition">⛶ Fit</button>
        <button onclick="handleLogout()" class="px-2.5 py-1 text-xs bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 rounded-lg transition">Disconnect</button>
      </div>
    </header>

    <!-- Xterm mount -->
    <div id="terminal" class="flex-1 w-full bg-[#020617] relative"></div>
  </div>

  <script>
    let term, fitAddon, socket, sessionToken = '';

    function togglePassword() {
      const el = document.getElementById('password');
      el.type = el.type === 'password' ? 'text' : 'password';
    }

    async function handleLogin(e) {
      e.preventDefault();
      const pwd = document.getElementById('password').value;
      const btn = document.getElementById('submit-btn');
      const errBox = document.getElementById('error-box');
      const errMsg = document.getElementById('error-msg');

      btn.disabled = true;
      btn.innerHTML = '<span class="animate-spin mr-2">⏳</span> Authenticating...';
      errBox.classList.add('hidden');

      try {
        const res = await fetch('/api/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password: pwd })
        });
        const data = await res.json();

        if (res.ok && data.success) {
          sessionToken = data.token;
          showTerminal();
        } else {
          errBox.classList.remove('hidden');
          errMsg.innerText = data.error || 'Authentication failed';
        }
      } catch (err) {
        errBox.classList.remove('hidden');
        errMsg.innerText = 'Connection error: ' + err.message;
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>Authenticate & Connect</span><span class="text-xs">→</span>';
      }
    }

    async function checkAuth() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        if (data.authenticated) {
          showTerminal();
        }
      } catch (e) {}
    }

    function showTerminal() {
      document.getElementById('login-view').classList.add('hidden');
      document.getElementById('terminal-view').classList.remove('hidden');
      initTerminal();
    }

    function initTerminal() {
      if (term) return;

      term = new Terminal({
        cursorBlink: true,
        cursorStyle: 'bar',
        fontSize: 14,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
        theme: {
          background: '#020617',
          foreground: '#f8fafc',
          cursor: '#f97316',
          selectionBackground: '#334155',
          black: '#020617',
          red: '#ef4444',
          green: '#22c55e',
          yellow: '#eab308',
          blue: '#3b82f6',
          magenta: '#d946ef',
          cyan: '#06b6d4',
          white: '#f8fafc',
          brightBlack: '#64748b',
          brightRed: '#f87171',
          brightGreen: '#4ade80',
          brightYellow: '#fde047',
          brightBlue: '#60a5fa',
          brightMagenta: '#e879f9',
          brightCyan: '#22d3ee',
          brightWhite: '#ffffff'
        }
      });

      fitAddon = new FitAddon.FitAddon();
      term.loadAddon(fitAddon);
      if (typeof WebLinksAddon !== 'undefined') {
        term.loadAddon(new WebLinksAddon.WebLinksAddon());
      }

      const mount = document.getElementById('terminal');
      term.open(mount);
      fitAddon.fit();

      connectWebSocket();

      term.onData(data => {
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'input', data }));
        }
      });

      window.addEventListener('resize', () => termFit());
    }

    function termFit() {
      if (fitAddon && term) {
        fitAddon.fit();
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
        }
      }
    }

    function connectWebSocket() {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${proto}//${window.location.host}/ws?token=${encodeURIComponent(sessionToken)}`;

      socket = new WebSocket(wsUrl);
      socket.binaryType = 'arraybuffer';

      socket.onopen = () => {
        document.getElementById('conn-badge').innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span> Connected';
        document.getElementById('conn-badge').className = 'text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 font-mono flex items-center gap-1';
        termFit();
        term.focus();
      };

      socket.onmessage = (event) => {
        if (typeof event.data === 'string') {
          try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'output') {
              term.write(msg.data);
            }
          } catch(e) {
            term.write(event.data);
          }
        } else {
          const uint8 = new Uint8Array(event.data);
          term.write(uint8);
        }
      };

      socket.onclose = () => {
        document.getElementById('conn-badge').innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-red-400"></span> Disconnected';
        document.getElementById('conn-badge').className = 'text-xs px-2 py-0.5 rounded-full bg-red-500/20 text-red-400 font-mono flex items-center gap-1';
        term.write('\r\n\x1b[31m[Session terminated. Reconnecting in 3s...]\x1b[0m\r\n');
        setTimeout(() => {
          if (!document.getElementById('terminal-view').classList.contains('hidden')) {
            connectWebSocket();
          }
        }, 3000);
      };

      socket.onerror = (err) => {
        console.error('WebSocket Error:', err);
      };
    }

    async function handleLogout() {
      if (socket) socket.close();
      await fetch('/api/logout', { method: 'POST' });
      window.location.reload();
    }

    checkAuth();
  </script>
</body>
</html>
"""

# ==================== HTTP & WEBSOCKET SERVER ====================

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class FireSSHServerHandler(BaseHTTPRequestHandler):
    def get_client_ip(self) -> str:
        forwarded = self.headers.get('CF-Connecting-IP') or self.headers.get('X-Forwarded-For')
        if forwarded:
            return forwarded.split(',')[0].strip()
        return self.client_address[0]

    def get_cookie_token(self) -> str:
        cookie_header = self.headers.get('Cookie', '')
        for part in cookie_header.split(';'):
            part = part.strip()
            if part.startswith('fire_ssh_session='):
                return part.split('=', 1)[1]
        return None

    def is_authenticated(self) -> bool:
        token = self.get_cookie_token()
        if token and self.server.sessions.is_valid(token, self.get_client_ip()):
            return True
        return False

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        ip = self.get_client_ip()

        if parsed.path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
            return

        # WebSocket Upgrade
        if parsed.path == '/ws':
            query = urllib.parse.parse_qs(parsed.query)
            token = query.get('token', [None])[0] or self.get_cookie_token()

            if not self.server.sessions.is_valid(token, ip):
                self.send_error(401, "Unauthorized")
                return

            ws_key = self.headers.get('Sec-WebSocket-Key')
            if not ws_key:
                self.send_error(400, "Bad WebSocket Request")
                return

            self.wfile.write(ws_handshake_response(ws_key))
            self.wfile.flush()
            self.handle_websocket()
            return

        elif parsed.path == '/api/status':
            auth = self.is_authenticated()
            locked, rem = self.server.rate_limiter.is_locked(ip)
            data = {"authenticated": auth, "locked": locked, "lockout_remaining": rem}
            self.send_json(data)
            return

        elif parsed.path == '/health':
            self.send_json({"status": "ok", "service": "fire-ssh"})
            return

        elif parsed.path == '/' or parsed.path == '/index.html':
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode('utf-8'))
            return

        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        ip = self.get_client_ip()

        if parsed.path == '/api/login':
            locked, rem = self.server.rate_limiter.is_locked(ip)
            if locked:
                self.send_json({
                    "success": False,
                    "error": f"Too many failed login attempts. Locked out for {rem} seconds."
                }, status=429)
                return

            content_len = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_len).decode('utf-8', errors='ignore')
            
            password = ""
            try:
                data = json.loads(body)
                password = data.get('password', '')
            except Exception:
                post_data = urllib.parse.parse_qs(body)
                password = post_data.get('password', [''])[0]

            if not password:
                self.send_json({"success": False, "error": "Password is required"}, status=400)
                return

            valid = False
            if self.server.salt_hex and self.server.hash_hex:
                valid = PasswordManager.verify(password, self.server.salt_hex, self.server.hash_hex)
            elif self.server.plain_password:
                valid = hmac.compare_digest(password, self.server.plain_password)

            if valid:
                self.server.rate_limiter.record_success(ip)
                token = self.server.sessions.create_session(ip)
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Set-Cookie", f"fire_ssh_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_EXPIRY_SECONDS}")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "token": token}).encode('utf-8'))
            else:
                is_now_locked, lock_sec, attempts_left = self.server.rate_limiter.record_failure(ip)
                if is_now_locked:
                    self.send_json({
                        "success": False,
                        "error": f"Invalid password. Maximum attempts exceeded. Locked out for {lock_sec} seconds."
                    }, status=429)
                else:
                    self.send_json({
                        "success": False,
                        "error": f"Invalid password. {attempts_left} attempt(s) remaining."
                    }, status=401)
            return

        elif parsed.path == '/api/logout':
            token = self.get_cookie_token()
            if token:
                self.server.sessions.revoke(token)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", "fire_ssh_session=; Path=/; HttpOnly; Max-Age=0")
            self.end_headers()
            self.wfile.write(b'{"success":true}')
            return

        else:
            self.send_error(404, "Not Found")

    def send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_websocket(self):
        """Spawns user PTY shell and bridges I/O with WebSocket client."""
        sock = self.connection
        sock.setblocking(True)

        master_fd, slave_fd = pty.openpty()
        
        winsize = struct.pack("HHHH", 24, 80, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)

        shell = self.server.target_shell or os.environ.get('SHELL', '/bin/bash')
        if not os.path.exists(shell):
            shell = '/bin/bash' if os.path.exists('/bin/bash') else '/bin/sh'

        pid = os.fork()
        if pid == 0:
            os.close(master_fd)
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            if slave_fd > 2:
                os.close(slave_fd)

            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            env["COLORTERM"] = "truecolor"
            env["LANG"] = env.get("LANG", "C.UTF-8")
            env["LC_ALL"] = env.get("LC_ALL", "C.UTF-8")
            
            try:
                os.execvpe(shell, [shell, "-l"], env)
            except Exception:
                os.execvpe(shell, [shell], env)
            sys.exit(1)

        os.close(slave_fd)
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        running = True

        try:
            while running:
                rlist, _, _ = select.select([sock, master_fd], [], [], 30.0)
                
                pid_res, status = os.waitpid(pid, os.WNOHANG)
                if pid_res != 0:
                    running = False
                    break

                for src in rlist:
                    if src == master_fd:
                        try:
                            data = os.read(master_fd, 4096)
                            if not data:
                                running = False
                                break
                            frame = ws_make_frame(data, opcode=2)
                            sock.sendall(frame)
                        except (BlockingIOError, InterruptedError):
                            continue
                        except Exception:
                            running = False
                            break

                    elif src == sock:
                        opcode, payload = ws_read_frame(sock)
                        if opcode is None or opcode == 8:
                            running = False
                            break
                        elif opcode == 9:
                            sock.sendall(ws_make_frame(payload, opcode=10))
                        elif opcode == 1:
                            try:
                                msg = json.loads(payload.decode('utf-8', errors='ignore'))
                                mtype = msg.get('type')
                                if mtype == 'input':
                                    os.write(master_fd, msg.get('data', '').encode('utf-8'))
                                elif mtype == 'resize':
                                    cols = int(msg.get('cols', 80))
                                    rows = int(msg.get('rows', 24))
                                    wsz = struct.pack("HHHH", rows, cols, 0, 0)
                                    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, wsz)
                            except Exception:
                                pass
                        elif opcode == 2:
                            os.write(master_fd, payload)

        finally:
            try:
                os.close(master_fd)
            except Exception:
                pass
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.1)
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
            try:
                os.waitpid(pid, 0)
            except Exception:
                pass

    def log_message(self, format, *args):
        pass


def run_server(port: int, plain_password: str = None, salt_hex: str = None, hash_hex: str = None, shell: str = None):
    if not plain_password and not hash_hex:
        salt_hex, hash_hex = PasswordManager.load_stored_credentials()

    server = ThreadedHTTPServer(('127.0.0.1', port), FireSSHServerHandler)
    server.plain_password = plain_password
    server.salt_hex = salt_hex
    server.hash_hex = hash_hex
    server.target_shell = shell
    server.rate_limiter = RateLimiter()
    server.sessions = SessionManager()

    print(json.dumps({
        "status": "ready",
        "port": port,
        "auth_configured": bool(plain_password or hash_hex),
        "shell": shell or os.environ.get('SHELL', '/bin/bash')
    }), flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# ==================== CLI ENTRYPOINT ====================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fire PM Remote Terminal Engine")
    subparsers = parser.add_subparsers(dest="command")

    p_start = subparsers.add_parser("start", help="Start web terminal server")
    p_start.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind (127.0.0.1)")
    p_start.add_argument("--password", type=str, help="Plaintext session password")
    p_start.add_argument("--salt", type=str, help="Salt hex for PBKDF2 hash")
    p_start.add_argument("--hash", type=str, help="Hash hex for PBKDF2 verification")
    p_start.add_argument("--shell", type=str, help="Target shell executable")

    p_hash = subparsers.add_parser("hash-password", help="Hash password using PBKDF2-HMAC-SHA256")
    p_hash.add_argument("password", type=str, help="Plaintext password to hash")
    p_hash.add_argument("--save", action="store_true", help="Save hashed password to /etc/fire-pm/ssh-auth.json")

    p_check = subparsers.add_parser("check-password", help="Verify password against salt and hash")
    p_check.add_argument("password", type=str, help="Plaintext password")
    p_check.add_argument("salt", type=str, help="Salt hex")
    p_check.add_argument("hash", type=str, help="Hash hex")

    args = parser.parse_args()

    if args.command == "hash-password":
        salt, hsh = PasswordManager.hash_password(args.password)
        if args.save:
            PasswordManager.save_credentials(salt, hsh)
            print(json.dumps({"success": True, "saved": True, "path": PasswordManager.get_auth_file_path(), "salt": salt, "hash": hsh}))
        else:
            print(json.dumps({"success": True, "salt": salt, "hash": hsh}))

    elif args.command == "check-password":
        valid = PasswordManager.verify(args.password, args.salt, args.hash)
        print(json.dumps({"valid": valid}))

    elif args.command == "start":
        run_server(args.port, plain_password=args.password, salt_hex=args.salt, hash_hex=args.hash, shell=args.shell)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
