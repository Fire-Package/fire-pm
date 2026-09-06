#!/usr/bin/env python3
"""
Fire PM — Remote Web Terminal (fire ssh)
Provides secure, persistent, browser-based remote terminal access over WebSockets/PTY
with salted PBKDF2 password authentication, session persistence, automatic reconnection,
reliable signal interception (Ctrl+C / Ctrl+Z), and brute-force rate limiting.
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
SESSION_EXPIRY_SECONDS = 86400  # 24 hours
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 300  # 5 minutes
WINDOW_SECONDS = 300
SCROLLBACK_BUFFER_SIZE = 128 * 1024  # 128 KB scrollback replay buffer
DETACHED_SESSION_TTL = 3 * 86400  # Keep detached sessions alive for 3 days (259,200 seconds)

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


# ==================== PERSISTENT TERMINAL ENGINE ====================

class TerminalSession:
    """Manages a persistent PTY process that survives network disconnects and page reloads."""
    def __init__(self, session_id: str, shell: str = None):
        self.session_id = session_id
        self.shell = shell or '/bin/bash'
        self.master_fd = None
        self.pid = None
        self.sock = None
        self.sock_lock = threading.Lock()
        self.output_buffer = bytearray()
        self.buffer_lock = threading.Lock()
        self.cols = 80
        self.rows = 24
        self.created_at = time.time()
        self.last_seen = time.time()
        self.closed = False
        self.reader_thread = None
        self.start()

    def start(self):
        master_fd, slave_fd = pty.openpty()
        self.master_fd = master_fd

        winsize = struct.pack("HHHH", self.rows, self.cols, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)

        shell = self.shell
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
        self.pid = pid

        self.reader_thread = threading.Thread(target=self._pty_reader_loop, daemon=True)
        self.reader_thread.start()

    def _pty_reader_loop(self):
        while not self.closed:
            try:
                if self.pid:
                    pid_res, _ = os.waitpid(self.pid, os.WNOHANG)
                    if pid_res != 0:
                        self.closed = True
                        break

                rlist, _, _ = select.select([self.master_fd], [], [], 0.5)
                if not rlist:
                    continue

                data = os.read(self.master_fd, 8192)
                if not data:
                    self.closed = True
                    break

                with self.buffer_lock:
                    self.output_buffer.extend(data)
                    if len(self.output_buffer) > SCROLLBACK_BUFFER_SIZE:
                        self.output_buffer = self.output_buffer[-SCROLLBACK_BUFFER_SIZE:]

                with self.sock_lock:
                    if self.sock:
                        try:
                            frame = ws_make_frame(data, opcode=2)
                            self.sock.sendall(frame)
                        except Exception:
                            self.sock = None
            except (BlockingIOError, InterruptedError):
                continue
            except Exception:
                break

        self.close()

    def attach_socket(self, sock):
        with self.sock_lock:
            self.sock = sock
            self.last_seen = time.time()
            with self.buffer_lock:
                if self.output_buffer:
                    try:
                        frame = ws_make_frame(bytes(self.output_buffer), opcode=2)
                        sock.sendall(frame)
                    except Exception:
                        self.sock = None

    def detach_socket(self, sock=None):
        with self.sock_lock:
            if sock is None or self.sock == sock:
                self.sock = None
                self.last_seen = time.time()

    def write_input(self, data: bytes):
        if self.master_fd and not self.closed:
            try:
                os.write(self.master_fd, data)
            except Exception:
                pass

    def send_signal(self, sig=signal.SIGINT):
        """Sends signal to the active foreground process group in the PTY."""
        signaled = False
        if self.master_fd and not self.closed:
            try:
                pgrp = os.tcgetpgrp(self.master_fd)
                if pgrp > 0:
                    os.killpg(pgrp, sig)
                    signaled = True
            except Exception:
                pass
        
        if not signaled and self.pid and not self.closed:
            try:
                os.kill(self.pid, sig)
                signaled = True
            except Exception:
                pass

        if sig == signal.SIGINT:
            self.write_input(b'\x03')
        elif sig == signal.SIGTSTP:
            self.write_input(b'\x1a')
        elif sig == signal.SIGQUIT:
            self.write_input(b'\x1c')

    def resize(self, cols: int, rows: int):
        if self.master_fd and not self.closed:
            try:
                self.cols = cols
                self.rows = rows
                wsz = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, wsz)
            except Exception:
                pass

    def measure_pty_latency(self) -> float:
        """Measures PTY subsystem and process communication responsiveness in ms."""
        if self.closed or not self.master_fd or not self.pid:
            return -1
        try:
            t0 = time.perf_counter()
            _ = os.tcgetpgrp(self.master_fd)
            os.kill(self.pid, 0)
            _ = termios.tcgetattr(self.master_fd)
            t1 = time.perf_counter()
            elapsed_ms = (t1 - t0) * 1000
            return max(0.1, round(elapsed_ms, 2))
        except Exception:
            return -1

    def is_alive(self) -> bool:
        if self.closed or not self.pid:
            return False
        try:
            pid_res, _ = os.waitpid(self.pid, os.WNOHANG)
            return pid_res == 0
        except Exception:
            return False

    def close(self):
        self.closed = True
        with self.sock_lock:
            if self.sock:
                try:
                    self.sock.sendall(ws_make_frame(b"", opcode=8))
                except Exception:
                    pass
                self.sock = None

        if self.master_fd:
            try:
                os.close(self.master_fd)
            except Exception:
                pass
            self.master_fd = None

        if self.pid:
            try:
                os.kill(self.pid, signal.SIGTERM)
                time.sleep(0.05)
                os.kill(self.pid, signal.SIGKILL)
            except Exception:
                pass
            try:
                os.waitpid(self.pid, os.WNOHANG)
            except Exception:
                pass
            self.pid = None


class TerminalSessionManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.sessions = {}  # token -> TerminalSession
        self.reaper_thread = threading.Thread(target=self._reaper_loop, daemon=True)
        self.reaper_thread.start()

    def get_or_create(self, token: str, shell: str = None) -> TerminalSession:
        with self.lock:
            session = self.sessions.get(token)
            if session and session.is_alive():
                return session
            if session:
                session.close()
            session = TerminalSession(token, shell)
            self.sessions[token] = session
            return session

    def remove(self, token: str):
        with self.lock:
            session = self.sessions.pop(token, None)
            if session:
                session.close()

    def _reaper_loop(self):
        while True:
            time.sleep(30)
            now = time.time()
            with self.lock:
                to_delete = []
                for token, session in self.sessions.items():
                    if not session.is_alive():
                        to_delete.append(token)
                    elif session.sock is None and (now - session.last_seen > DETACHED_SESSION_TTL):
                        to_delete.append(token)
                for token in to_delete:
                    sess = self.sessions.pop(token, None)
                    if sess:
                        sess.close()


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
          <p class="text-xs text-slate-400">Persistent Remote Terminal</p>
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
          Persistent Session
        </span>
        <span>Rate Limited (5 max)</span>
      </div>
    </div>
  </div>

  <!-- TERMINAL CONTAINER -->
  <div id="terminal-view" class="hidden flex-1 flex flex-col h-full">
    <!-- Header bar with Quick Action Signal Buttons -->
    <header class="h-12 bg-slate-900 border-b border-slate-800 px-3 sm:px-4 flex items-center justify-between select-none">
      <div class="flex items-center space-x-2 sm:space-x-3">
        <span class="text-lg">🔥</span>
        <span class="text-xs sm:text-sm font-semibold text-white">Fire PM Terminal</span>
        <span id="conn-badge" class="text-[11px] sm:text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 font-mono flex items-center gap-1">
          <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
          Connected
        </span>
      </div>

      <!-- Quick Control Action Toolbar -->
      <div class="flex items-center space-x-1.5 sm:space-x-2">
        <button onclick="sendInterrupt()" title="Break / Interrupt (Ctrl+C)" class="px-2.5 py-1 text-xs bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/30 rounded-lg transition font-mono font-bold flex items-center gap-1">
          <span>⎋</span>
          <span>Ctrl+C</span>
        </button>
        <button onclick="sendSuspend()" title="Suspend Foreground Job (Ctrl+Z)" class="hidden sm:inline-flex px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono">^Z</button>
        <button onclick="sendEOF()" title="EOF / Exit (Ctrl+D)" class="hidden sm:inline-flex px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono">^D</button>
        <button onclick="sendCtrlW()" title="Send Ctrl+W (Where Is in nano / erase word in bash)" class="hidden sm:inline-flex px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono">^W</button>
        <button onclick="clearTerm()" title="Clear Terminal Output" class="px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition">Clear</button>
        <button onclick="termFit()" title="Fit Terminal Window" class="px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition">⛶ Fit</button>
        <button onclick="toggleFullscreen()" title="Fullscreen mode (locks Ctrl+W from closing tab)" class="hidden sm:inline-flex px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition">⛶ Fullscreen</button>
        <button onclick="copySelectionToClipboard(true)" title="Copy Selected Text (Ctrl+C / Cmd+C)" class="px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono flex items-center gap-1">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-slate-400">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
          </svg>
          <span>Copy</span>
        </button>
        <button onclick="pasteFromClipboard(true, true)" title="Paste from Clipboard (Ctrl+V / Cmd+V)" class="px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono flex items-center gap-1">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-slate-400">
            <rect x="8" y="2" width="8" height="4" rx="1" ry="1"/>
            <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>
          </svg>
          <span>Paste</span>
        </button>
        <button id="predictive-btn" onclick="togglePredictiveMode()" title="0ms Direct In-Terminal Typing (Local Echo for bash / antigravity) [Alt+P]" class="px-2 py-1 text-xs bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/40 rounded-lg transition font-mono flex items-center gap-1">
          <span>⚡</span>
          <span id="predictive-btn-text">0ms Direct</span>
        </button>
        <button id="buffer-toggle-btn" onclick="toggleBufferMode()" title="Toggle Command Bar [Alt+B]" class="hidden md:inline-flex px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 border border-transparent rounded-lg transition font-mono items-center gap-1">
          <span>Command Bar</span>
        </button>
        <div class="relative">
          <button id="network-btn" onclick="toggleLatencyPanel()" title="Network Latency" class="px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition flex items-center gap-1.5">
            <svg id="wifi-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M1.42 9a16 16 0 0 1 21.16 0"/>
              <path d="M5 12.55a11 11 0 0 1 14.08 0"/>
              <path d="M8.53 16.11a6 6 0 0 1 6.95 0"/>
              <circle cx="12" cy="20" r="1.5" fill="currentColor" stroke="none"/>
            </svg>
            <span id="latency-badge" class="text-[10px] font-mono hidden">--</span>
          </button>
          <div id="latency-panel" class="hidden absolute right-0 top-full mt-1.5 w-64 bg-slate-900/95 backdrop-blur-sm border border-slate-700/80 rounded-xl shadow-2xl shadow-black/50 p-3.5 z-50">
            <div class="flex items-center justify-between mb-3">
              <span class="text-[11px] font-semibold text-slate-200 uppercase tracking-wider">Network Latency</span>
              <button onclick="measureLatency()" title="Refresh" class="text-slate-500 hover:text-white transition p-0.5">
                <svg id="refresh-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 4v6h6"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>
                </svg>
              </button>
            </div>
            <div class="space-y-2">
              <div class="flex items-center justify-between py-1">
                <div class="flex items-center gap-2">
                  <span id="latency-cs-dot" class="w-1.5 h-1.5 rounded-full bg-slate-600 shrink-0"></span>
                  <span class="text-[11px] text-slate-400">Client ↔ Server</span>
                </div>
                <span id="latency-cs" class="text-[11px] font-mono text-slate-300">—</span>
              </div>
              <div class="flex items-center justify-between py-1">
                <div class="flex items-center gap-2">
                  <span id="latency-st-dot" class="w-1.5 h-1.5 rounded-full bg-slate-600 shrink-0"></span>
                  <span class="text-[11px] text-slate-400">Server ↔ Terminal</span>
                </div>
                <span id="latency-st" class="text-[11px] font-mono text-slate-300">—</span>
              </div>
            </div>
            <div class="mt-3 pt-2.5 border-t border-slate-800/80 text-[10px] text-slate-500 text-center">Auto-refreshing every 3s</div>
          </div>
        </div>
        <button onclick="handleLogout()" class="px-2.5 py-1 text-xs bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 rounded-lg transition">Disconnect</button>
      </div>
    </header>

    <!-- Xterm mount -->
    <div id="terminal" class="flex-1 w-full bg-[#020617] relative"></div>

    <!-- Local Command Buffer Bar (Low-Latency Line Mode for High Ping Connections) -->
    <div id="local-buffer-bar" class="hidden bg-slate-900 border-t border-slate-800 p-2 sm:px-3 sm:py-2 flex items-center gap-2 select-none">
      <div class="flex items-center gap-1 text-amber-400 text-xs font-mono shrink-0 select-none">
        <span class="animate-pulse">⚡</span>
        <span class="hidden md:inline text-[11px] text-slate-400">Buffer:</span>
      </div>
      <div class="flex-1 relative flex items-center">
        <input id="local-buffer-input" type="text" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false"
               placeholder="Type command locally with 0ms lag (Press Enter to send, ↑/↓ for history)..."
               class="w-full bg-slate-950 text-emerald-400 placeholder:text-slate-600 font-mono text-xs sm:text-sm px-3 py-1.5 rounded-lg border border-slate-700/70 focus:outline-none focus:border-amber-400/80 focus:ring-1 focus:ring-amber-400/50 transition">
        <span id="buffer-history-tip" class="hidden lg:inline absolute right-2.5 text-[10px] text-slate-600 font-mono pointer-events-none">Enter ↵</span>
      </div>
      <button onclick="submitLocalBuffer()" title="Send Command to Remote Server (Enter)" class="px-2.5 py-1.5 text-xs bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 rounded-lg transition font-mono font-medium flex items-center gap-1 shrink-0">
        <span>Send</span>
        <span class="text-[10px] opacity-70">↵</span>
      </button>
      <button onclick="toggleBufferMode()" title="Hide Local Buffer (Alt+B)" class="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg transition shrink-0">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
    </div>

    <!-- Toast Notification -->
    <div id="term-toast" class="pointer-events-none fixed bottom-6 right-6 z-50 transition-all duration-200 opacity-0 translate-y-2 bg-slate-800/95 border border-slate-700 text-slate-200 text-xs px-3 py-1.5 rounded-lg shadow-xl font-mono flex items-center gap-2">
      <span id="term-toast-msg">Copied to clipboard</span>
    </div>

    <!-- Custom Right-Click Context Menu -->
    <div id="term-context-menu" class="hidden fixed z-50 bg-slate-900/95 backdrop-blur-sm border border-slate-800 rounded-xl shadow-2xl shadow-black/60 py-1 min-w-[170px] text-xs select-none">
      <button onclick="copySelectionToClipboard(true); hideContextMenu();" class="w-full text-left px-3 py-1.5 text-slate-300 hover:bg-slate-800 hover:text-white flex items-center justify-between">
        <span class="flex items-center gap-2">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
          <span>Copy</span>
        </span>
        <span class="text-[10px] text-slate-500 font-mono">Ctrl+C</span>
      </button>
      <button onclick="pasteFromClipboard(true, true); hideContextMenu();" class="w-full text-left px-3 py-1.5 text-slate-300 hover:bg-slate-800 hover:text-white flex items-center justify-between">
        <span class="flex items-center gap-2">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/></svg>
          <span>Paste</span>
        </span>
        <span class="text-[10px] text-slate-500 font-mono">Ctrl+V</span>
      </button>
      <button onclick="selectAllTerm(); hideContextMenu();" class="w-full text-left px-3 py-1.5 text-slate-300 hover:bg-slate-800 hover:text-white flex items-center justify-between">
        <span class="flex items-center gap-2">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18M15 3v18M3 9h18M3 15h18"/></svg>
          <span>Select All</span>
        </span>
        <span class="text-[10px] text-slate-500 font-mono">Ctrl+Shift+A</span>
      </button>
      <button onclick="sendCtrlW(); hideContextMenu();" class="w-full text-left px-3 py-1.5 text-slate-300 hover:bg-slate-800 hover:text-white flex items-center justify-between">
        <span class="flex items-center gap-2">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <span>Search (Where Is)</span>
        </span>
        <span class="text-[10px] text-slate-500 font-mono">Alt+W / ^W</span>
      </button>
      <button onclick="toggleBufferMode(); hideContextMenu();" class="w-full text-left px-3 py-1.5 text-slate-300 hover:bg-slate-800 hover:text-white flex items-center justify-between">
        <span class="flex items-center gap-2">
          <span class="text-amber-400">⚡</span>
          <span>Buffer Mode</span>
        </span>
        <span class="text-[10px] text-slate-500 font-mono">Alt+B</span>
      </button>
      <div class="h-px bg-slate-800 my-1"></div>
      <button onclick="clearTerm(); hideContextMenu();" class="w-full text-left px-3 py-1.5 text-slate-300 hover:bg-slate-800 hover:text-white flex items-center justify-between">
        <span class="flex items-center gap-2">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
          <span>Clear</span>
        </span>
        <span class="text-[10px] text-slate-500 font-mono">Ctrl+L</span>
      </button>
    </div>
  </div>

  <script>
    let term, fitAddon, socket, sessionToken = '', pingTimer = null, reconnectTimer = null;
    let latencyPingSent = 0, clientServerLatency = -1, serverTerminalLatency = -1, latencyInterval = null;

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

    function sendInterrupt() {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'signal', signal: 'SIGINT' }));
        socket.send(JSON.stringify({ type: 'input', data: '\x03' }));
      }
      if (term) term.focus();
    }

    function sendSuspend() {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'signal', signal: 'SIGTSTP' }));
        socket.send(JSON.stringify({ type: 'input', data: '\x1a' }));
      }
      if (term) term.focus();
    }

    function sendEOF() {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'input', data: '\x04' }));
      }
      if (term) term.focus();
    }

    function sendCtrlW() {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'input', data: '\x17' }));
      }
      if (term) term.focus();
    }

    function toggleFullscreen() {
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().then(() => {
          if (navigator.keyboard && navigator.keyboard.lock) {
            navigator.keyboard.lock(['KeyW', 'KeyN', 'KeyT']).catch(() => {});
          }
          termFit();
          if (term) term.focus();
          showToast('Fullscreen on (Ctrl+W locked to terminal)');
        }).catch(() => {
          showToast('Fullscreen not permitted');
        });
      } else {
        if (document.exitFullscreen) {
          document.exitFullscreen().then(() => {
            if (navigator.keyboard && navigator.keyboard.unlock) {
              navigator.keyboard.unlock();
            }
            termFit();
            if (term) term.focus();
          }).catch(() => {});
        }
      }
    }

    let predictiveEchoEnabled = true;
    let localLine = '';
    let pendingEchoQueue = [];
    let pendingEchoTimeout = null;

    function togglePredictiveMode(force) {
      predictiveEchoEnabled = force !== undefined ? force : !predictiveEchoEnabled;
      const btn = document.getElementById('predictive-btn');
      const text = document.getElementById('predictive-btn-text');
      if (predictiveEchoEnabled) {
        if (btn) {
          btn.className = 'px-2 py-1 text-xs bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/40 rounded-lg transition font-mono flex items-center gap-1';
        }
        if (text) text.textContent = '0ms Direct';
        showToast('0ms In-Terminal Typing: ON (Direct typing in bash/antigravity)');
      } else {
        if (btn) {
          btn.className = 'px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-400 border border-transparent rounded-lg transition font-mono flex items-center gap-1';
        }
        if (text) text.textContent = '0ms Off';
        localLine = '';
        pendingEchoQueue = [];
        showToast('0ms In-Terminal Typing: OFF (Raw server echo)');
      }
      if (term) term.focus();
    }

    function renderServerOutput(raw) {
      const isAlt = term && term.buffer && term.buffer.active && term.buffer.active.type === 'alternate';
      if (!isAlt && predictiveEchoEnabled && pendingEchoQueue.length > 0) {
        let str = typeof raw === 'string' ? raw : new TextDecoder().decode(raw);
        const expected = pendingEchoQueue[0];
        const matchIdx = str.indexOf(expected);
        if (matchIdx >= 0 && matchIdx <= 16) {
          str = str.slice(0, matchIdx) + str.slice(matchIdx + expected.length);
          pendingEchoQueue.shift();
          if (pendingEchoTimeout) clearTimeout(pendingEchoTimeout);
        }
        term.write(str);
      } else {
        term.write(raw);
      }
    }

    let bufferHistory = [];
    let bufferHistoryIdx = -1;
    let bufferAutoPrompted = false;

    function toggleBufferMode(force) {
      const bar = document.getElementById('local-buffer-bar');
      const btn = document.getElementById('buffer-toggle-btn');
      const input = document.getElementById('local-buffer-input');
      if (!bar) return;

      const shouldShow = force !== undefined ? force : bar.classList.contains('hidden');
      if (shouldShow) {
        bar.classList.remove('hidden');
        if (btn) {
          btn.classList.add('bg-amber-500/20', 'text-amber-300', 'border-amber-500/40');
          btn.classList.remove('animate-pulse');
        }
        if (input) {
          input.focus();
          input.select();
        }
        showToast('Local Buffer active: 0ms typing lag');
      } else {
        bar.classList.add('hidden');
        if (btn) btn.classList.remove('bg-amber-500/20', 'text-amber-300', 'border-amber-500/40');
        if (term) term.focus();
      }
      termFit();
    }

    function submitLocalBuffer() {
      const input = document.getElementById('local-buffer-input');
      if (!input) return;
      const cmd = input.value;
      if (cmd !== '') {
        if (bufferHistory.length === 0 || bufferHistory[bufferHistory.length - 1] !== cmd) {
          bufferHistory.push(cmd);
          if (bufferHistory.length > 100) bufferHistory.shift();
        }
        bufferHistoryIdx = bufferHistory.length;

        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'input', data: cmd + '\r' }));
        }
        input.value = '';
      } else {
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'input', data: '\r' }));
        }
      }
      input.focus();
    }

    function initLocalBufferListeners() {
      const input = document.getElementById('local-buffer-input');
      if (!input) return;

      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          submitLocalBuffer();
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          if (bufferHistory.length > 0) {
            if (bufferHistoryIdx > 0) {
              bufferHistoryIdx--;
            }
            input.value = bufferHistory[bufferHistoryIdx] || '';
          }
        } else if (e.key === 'ArrowDown') {
          e.preventDefault();
          if (bufferHistoryIdx < bufferHistory.length - 1) {
            bufferHistoryIdx++;
            input.value = bufferHistory[bufferHistoryIdx];
          } else {
            bufferHistoryIdx = bufferHistory.length;
            input.value = '';
          }
        } else if (e.key === 'Escape') {
          e.preventDefault();
          if (term) term.focus();
        } else if (e.ctrlKey && (e.key === 'c' || e.key === 'C')) {
          if (input.selectionStart === input.selectionEnd) {
            input.value = '';
            sendInterrupt();
          }
        } else if (e.altKey && (e.key === 'b' || e.key === 'B')) {
          e.preventDefault();
          toggleBufferMode(false);
        }
      });
    }

    let toastTimer = null;
    function showToast(msg) {
      const toast = document.getElementById('term-toast');
      const msgEl = document.getElementById('term-toast-msg');
      if (!toast || !msgEl) return;
      msgEl.textContent = msg;
      toast.classList.remove('opacity-0', 'translate-y-2');
      toast.classList.add('opacity-100', 'translate-y-0');
      if (toastTimer) clearTimeout(toastTimer);
      toastTimer = setTimeout(() => {
        toast.classList.remove('opacity-100', 'translate-y-0');
        toast.classList.add('opacity-0', 'translate-y-2');
      }, 1800);
    }

    function showContextMenu(x, y) {
      const menu = document.getElementById('term-context-menu');
      if (!menu) return;
      menu.style.left = `${Math.min(x, window.innerWidth - 180)}px`;
      menu.style.top = `${Math.min(y, window.innerHeight - 150)}px`;
      menu.classList.remove('hidden');
    }

    function hideContextMenu() {
      const menu = document.getElementById('term-context-menu');
      if (menu) menu.classList.add('hidden');
    }

    function selectAllTerm() {
      if (term) {
        term.selectAll();
        showToast('All terminal text selected');
      }
    }

    function copySelectionToClipboard(showFeedback = false) {
      if (!term || !term.hasSelection()) {
        if (showFeedback) showToast('No text selected');
        return;
      }
      const text = term.getSelection();
      if (!text) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
          if (showFeedback) showToast('Copied to clipboard');
        }).catch(() => {
          fallbackCopyText(text);
          if (showFeedback) showToast('Copied to clipboard');
        });
      } else {
        fallbackCopyText(text);
        if (showFeedback) showToast('Copied to clipboard');
      }
    }

    function fallbackCopyText(text) {
      const el = document.createElement('textarea');
      el.value = text;
      el.setAttribute('readonly', '');
      el.style.position = 'fixed';
      el.style.top = '-9999px';
      el.style.left = '-9999px';
      document.body.appendChild(el);
      el.focus();
      el.select();
      try {
        document.execCommand('copy');
      } catch (e) {}
      document.body.removeChild(el);
      if (term) term.focus();
    }

    function clearTerm() {
      if (term) {
        term.clear();
        term.focus();
        showToast('Terminal cleared');
      }
    }

    async function pasteFromClipboard(promptFallback = true, showFeedback = false) {
      try {
        if (navigator.clipboard && navigator.clipboard.readText) {
          const text = await navigator.clipboard.readText();
          if (text) {
            insertPastedText(text);
            if (showFeedback) showToast('Pasted');
          }
          if (term) term.focus();
          return;
        }
      } catch (err) {
        console.warn('Clipboard readText failed or permission denied:', err);
      }

      if (promptFallback) {
        try {
          const manualText = prompt('Paste text here (press Ctrl+V and click OK):');
          if (manualText) {
            insertPastedText(manualText);
            if (showFeedback) showToast('Pasted');
          }
        } catch (e) {}
      }
      if (term) term.focus();
    }

    function insertPastedText(text) {
      if (!text) return;
      if (term && typeof term.paste === 'function') {
        term.paste(text);
      } else if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'input', data: text }));
      }
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

      document.addEventListener('copy', (e) => {
        if (term && term.hasSelection()) {
          const text = term.getSelection();
          if (text && e.clipboardData) {
            e.clipboardData.setData('text/plain', text);
            e.preventDefault();
            showToast('Copied to clipboard');
          }
        }
      });

      document.addEventListener('paste', (e) => {
        const active = document.activeElement;
        if (active && (active.tagName === 'INPUT' || (active.tagName === 'TEXTAREA' && !active.classList.contains('xterm-helper-textarea')))) {
          return;
        }
        if (e.defaultPrevented) return;
        const text = e.clipboardData ? e.clipboardData.getData('text/plain') : '';
        if (text) {
          e.preventDefault();
          insertPastedText(text);
          showToast('Pasted');
        }
      });

      // Mouse and gesture interaction listeners
      mount.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        showContextMenu(e.clientX, e.clientY);
      });

      mount.addEventListener('auxclick', (e) => {
        if (e.button === 1) { // Middle click paste
          e.preventDefault();
          pasteFromClipboard(false, true);
        }
      });

      mount.addEventListener('dragover', (e) => {
        e.preventDefault();
      });

      mount.addEventListener('drop', (e) => {
        e.preventDefault();
        const text = e.dataTransfer ? e.dataTransfer.getData('text/plain') : '';
        if (text) {
          insertPastedText(text);
          showToast('Pasted');
        }
      });

      document.addEventListener('click', (e) => {
        const menu = document.getElementById('term-context-menu');
        if (menu && !menu.contains(e.target)) {
          hideContextMenu();
        }
      });

      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
          hideContextMenu();
        }
      });

      // Comprehensive keyboard shortcuts
      term.attachCustomKeyEventHandler((e) => {
        if (e.type === 'keydown') {
          const isCtrlOrMeta = e.ctrlKey || e.metaKey;

          // Copy: Ctrl+C, Cmd+C, Ctrl+Shift+C, or Ctrl+Insert
          if ((isCtrlOrMeta && (e.key === 'c' || e.key === 'C')) ||
              (isCtrlOrMeta && e.key === 'Insert')) {
            if (term.hasSelection()) {
              copySelectionToClipboard(true);
              return false;
            }
            // Cmd+C on macOS without selection must not trigger SIGINT
            if (e.metaKey && !e.ctrlKey) {
              return false;
            }
            if (e.shiftKey) {
              return false;
            }
            sendInterrupt();
            return false;
          }

          // Paste: Ctrl+V, Cmd+V, Ctrl+Shift+V, or Shift+Insert
          if ((isCtrlOrMeta && (e.key === 'v' || e.key === 'V')) ||
              (e.shiftKey && (e.key === 'Insert' || e.key === 'Paste'))) {
            pasteFromClipboard(true, true);
            return false;
          }

          // Select All: Cmd+A (Mac) or Ctrl+Shift+A (Linux/Windows)
          if (((e.metaKey && !e.ctrlKey) || (e.ctrlKey && e.shiftKey)) && (e.key === 'a' || e.key === 'A')) {
            selectAllTerm();
            return false;
          }

          // Clear Terminal: Cmd+K (Mac standard)
          if (e.metaKey && !e.ctrlKey && (e.key === 'k' || e.key === 'K')) {
            clearTerm();
            return false;
          }

          // Ctrl+Z (Suspend)
          if (e.ctrlKey && (e.key === 'z' || e.key === 'Z')) {
            sendSuspend();
            return false;
          }

          // Ctrl+D (EOF)
          if (e.ctrlKey && (e.key === 'd' || e.key === 'D')) {
            sendEOF();
            return false;
          }

          // Ctrl+L (Clear screen)
          if (e.ctrlKey && (e.key === 'l' || e.key === 'L')) {
            if (socket && socket.readyState === WebSocket.OPEN) {
              socket.send(JSON.stringify({ type: 'input', data: '\x0c' }));
            }
            return false;
          }

          // Ctrl+W: nano search / bash erase word
          // Safe aliases: Alt+W or Ctrl+Shift+W (never close browser tab)
          if (((e.ctrlKey && e.shiftKey) || e.altKey) && (e.key === 'w' || e.key === 'W')) {
            e.preventDefault();
            sendCtrlW();
            return false;
          }
          // Direct Ctrl+W: intercept in fullscreen / supported environments
          if (e.ctrlKey && !e.shiftKey && !e.altKey && (e.key === 'w' || e.key === 'W')) {
            e.preventDefault();
            sendCtrlW();
            return false;
          }

          // Alt+B: Toggle Local Buffer Mode (0ms input lag for high ping)
          if (e.altKey && (e.key === 'b' || e.key === 'B')) {
            toggleBufferMode();
            return false;
          }

          // Alt+P: Toggle 0ms Direct In-Terminal Typing Mode
          if (e.altKey && (e.key === 'p' || e.key === 'P')) {
            togglePredictiveMode();
            return false;
          }
        }
        return true;
      });

      connectWebSocket();

      term.onData(data => {
        const isAlternateScreen = term.buffer && term.buffer.active && term.buffer.active.type === 'alternate';
        if (!predictiveEchoEnabled || isAlternateScreen) {
          if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: 'input', data }));
          }
          return;
        }

        if (data === '\r') {
          if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: 'input', data: localLine + '\r' }));
          }
          if (localLine.length > 0) {
            pendingEchoQueue.push(localLine);
            if (pendingEchoTimeout) clearTimeout(pendingEchoTimeout);
            pendingEchoTimeout = setTimeout(() => {
              pendingEchoQueue = [];
            }, 5000);
            localLine = '';
          }
        } else if (data === '\x7f' || data === '\b') {
          if (localLine.length > 0) {
            localLine = localLine.slice(0, -1);
            term.write('\b \b');
          }
        } else if (data === '\x03') {
          localLine = '';
          pendingEchoQueue = [];
          term.write('^C\r\n');
          sendInterrupt();
        } else if (data === '\x15') {
          if (localLine.length > 0) {
            term.write('\b \b'.repeat(localLine.length));
            localLine = '';
          }
        } else if (data.length === 1 && data.charCodeAt(0) >= 32 && data.charCodeAt(0) <= 126) {
          localLine += data;
          term.write(data);
        } else {
          if (localLine.length > 0) {
            pendingEchoQueue.push(localLine);
            if (pendingEchoTimeout) clearTimeout(pendingEchoTimeout);
            pendingEchoTimeout = setTimeout(() => {
              pendingEchoQueue = [];
            }, 5000);
            if (socket && socket.readyState === WebSocket.OPEN) {
              socket.send(JSON.stringify({ type: 'input', data: localLine }));
            }
            localLine = '';
          }
          if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: 'input', data }));
          }
        }
      });

      window.addEventListener('resize', () => termFit());
      initLocalBufferListeners();
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
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (pingTimer) clearInterval(pingTimer);

      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${proto}//${window.location.host}/ws?token=${encodeURIComponent(sessionToken)}`;

      socket = new WebSocket(wsUrl);
      socket.binaryType = 'arraybuffer';

      socket.onopen = () => {
        document.getElementById('conn-badge').innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span> Connected';
        document.getElementById('conn-badge').className = 'text-[11px] sm:text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 font-mono flex items-center gap-1';
        termFit();
        term.focus();

        pingTimer = setInterval(() => {
          if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: 'ping' }));
          }
        }, 15000);
        setTimeout(measureLatency, 1000);
      };

      socket.onmessage = (event) => {
        if (typeof event.data === 'string') {
          try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'output') {
              renderServerOutput(msg.data);
            } else if (msg.type === 'pong') {
              // Heartbeat ack
            } else if (msg.type === 'latency_pong') {
              clientServerLatency = performance.now() - msg.timestamp;
              updateLatencyDisplay();
            } else if (msg.type === 'latency_terminal_result') {
              serverTerminalLatency = msg.latency;
              updateLatencyDisplay();
            }
          } catch(e) {
            renderServerOutput(event.data);
          }
        } else {
          const uint8 = new Uint8Array(event.data);
          renderServerOutput(uint8);
        }
      };

      socket.onclose = () => {
        if (pingTimer) clearInterval(pingTimer);
        if (latencyInterval) { clearInterval(latencyInterval); latencyInterval = null; }
        document.getElementById('conn-badge').innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-ping"></span> Reconnecting...';
        document.getElementById('conn-badge').className = 'text-[11px] sm:text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 font-mono flex items-center gap-1';
        
        reconnectTimer = setTimeout(() => {
          if (!document.getElementById('terminal-view').classList.contains('hidden')) {
            connectWebSocket();
          }
        }, 1500);
      };

      socket.onerror = (err) => {
        console.error('WebSocket Error:', err);
      };
    }

    let isLoggingOut = false;
    window.addEventListener('beforeunload', (e) => {
      if (!isLoggingOut && socket && socket.readyState === WebSocket.OPEN) {
        e.preventDefault();
        e.returnValue = '';
      }
    });

    async function handleLogout() {
      isLoggingOut = true;
      if (pingTimer) clearInterval(pingTimer);
      if (latencyInterval) { clearInterval(latencyInterval); latencyInterval = null; }
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (socket) socket.close();
      await fetch('/api/logout', { method: 'POST' });
      window.location.reload();
    }

    function toggleLatencyPanel() {
      const panel = document.getElementById('latency-panel');
      const isHidden = panel.classList.contains('hidden');
      panel.classList.toggle('hidden');
      if (isHidden) {
        measureLatency();
        latencyInterval = setInterval(measureLatency, 3000);
      } else {
        if (latencyInterval) { clearInterval(latencyInterval); latencyInterval = null; }
      }
      if (term) term.focus();
    }

    function measureLatency() {
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      latencyPingSent = performance.now();
      socket.send(JSON.stringify({ type: 'latency_ping', timestamp: latencyPingSent }));
      socket.send(JSON.stringify({ type: 'latency_terminal' }));
    }

    function updateLatencyDisplay() {
      const csEl = document.getElementById('latency-cs');
      const stEl = document.getElementById('latency-st');
      const csDot = document.getElementById('latency-cs-dot');
      const stDot = document.getElementById('latency-st-dot');
      const badge = document.getElementById('latency-badge');
      const wifiIcon = document.getElementById('wifi-icon');

      if (clientServerLatency >= 0) {
        const ms = Math.round(clientServerLatency);
        csEl.textContent = ms + ' ms';
        csDot.className = 'w-1.5 h-1.5 rounded-full shrink-0 ' + latencyDotColor(clientServerLatency);
        badge.textContent = ms + 'ms';
        badge.classList.remove('hidden');
      }
      if (serverTerminalLatency >= 0) {
        stEl.textContent = serverTerminalLatency < 1 ? '<1 ms' : Math.round(serverTerminalLatency) + ' ms';
        stDot.className = 'w-1.5 h-1.5 rounded-full shrink-0 ' + latencyDotColor(serverTerminalLatency);
      }

      const lat = clientServerLatency >= 0 ? clientServerLatency : 999;
      wifiIcon.style.color = lat < 80 ? '#4ade80' : lat < 200 ? '#fbbf24' : '#f87171';

      if (clientServerLatency >= 400 && !bufferAutoPrompted) {
        bufferAutoPrompted = true;
        const btn = document.getElementById('buffer-toggle-btn');
        if (btn) {
          btn.classList.add('border-amber-400', 'animate-pulse');
        }
        showToast(`High latency detected (${Math.round(clientServerLatency)}ms). Click ⚡ Buffer or press Alt+B for 0ms typing!`);
      }
    }

    function latencyDotColor(ms) {
      if (ms < 80) return 'bg-emerald-400';
      if (ms < 200) return 'bg-amber-400';
      return 'bg-red-400';
    }

    document.addEventListener('click', (e) => {
      const panel = document.getElementById('latency-panel');
      const btn = document.getElementById('network-btn');
      if (panel && btn && !panel.contains(e.target) && !btn.contains(e.target)) {
        panel.classList.add('hidden');
        if (latencyInterval) { clearInterval(latencyInterval); latencyInterval = null; }
      }
    });

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
            self.handle_websocket(token)
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
                old_token = self.get_cookie_token()
                token = self.server.sessions.create_session(ip)
                if old_token and old_token in self.server.terminals.sessions:
                    with self.server.terminals.lock:
                        old_sess = self.server.terminals.sessions.pop(old_token, None)
                        if old_sess and old_sess.is_alive():
                            old_sess.session_id = token
                            self.server.terminals.sessions[token] = old_sess
                
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
                self.server.terminals.remove(token)
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

    def handle_websocket(self, token: str):
        """Bridges WebSocket client with a persistent TerminalSession."""
        sock = self.connection
        sock.setblocking(True)

        session = self.server.terminals.get_or_create(token, self.server.target_shell)
        session.attach_socket(sock)

        last_ping_sent = time.time()

        try:
            while session.is_alive():
                rlist, _, _ = select.select([sock], [], [], 5.0)

                # Proactive server WebSocket ping frame every 20 seconds
                now = time.time()
                if now - last_ping_sent > 20:
                    try:
                        sock.sendall(ws_make_frame(b"", opcode=9))
                        last_ping_sent = now
                    except Exception:
                        break

                if not rlist:
                    continue

                opcode, payload = ws_read_frame(sock)
                if opcode is None or opcode == 8:
                    break
                elif opcode == 9:
                    sock.sendall(ws_make_frame(payload, opcode=10))
                elif opcode == 10:
                    pass
                elif opcode == 1:
                    try:
                        msg = json.loads(payload.decode('utf-8', errors='ignore'))
                        mtype = msg.get('type')
                        if mtype == 'input':
                            session.write_input(msg.get('data', '').encode('utf-8'))
                        elif mtype == 'signal' or mtype == 'interrupt':
                            sig_name = msg.get('signal', 'SIGINT')
                            sig_map = {
                                'SIGINT': signal.SIGINT,
                                'SIGQUIT': signal.SIGQUIT,
                                'SIGTSTP': signal.SIGTSTP,
                                'SIGKILL': signal.SIGKILL
                            }
                            session.send_signal(sig_map.get(sig_name, signal.SIGINT))
                        elif mtype == 'resize':
                            cols = int(msg.get('cols', 80))
                            rows = int(msg.get('rows', 24))
                            session.resize(cols, rows)
                        elif mtype == 'ping':
                            sock.sendall(ws_make_frame(json.dumps({"type": "pong"}), opcode=1))
                        elif mtype == 'latency_ping':
                            ts = msg.get('timestamp', 0)
                            sock.sendall(ws_make_frame(json.dumps({"type": "latency_pong", "timestamp": ts}), opcode=1))
                        elif mtype == 'latency_terminal':
                            pty_lat = session.measure_pty_latency()
                            sock.sendall(ws_make_frame(json.dumps({"type": "latency_terminal_result", "latency": round(pty_lat, 2)}), opcode=1))
                    except Exception:
                        pass
                elif opcode == 2:
                    session.write_input(payload)

        finally:
            session.detach_socket(sock)

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
    server.terminals = TerminalSessionManager()

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
