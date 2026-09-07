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
import mimetypes
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
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB maximum file upload size

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


class ShareTokenManager:
    """Manages secure, temporary read-only sharing tokens for web terminal sessions."""
    def __init__(self):
        self.lock = threading.Lock()
        self.shares = {}  # share_token -> {"session_token": str, "created_at": float, "expires_at": float | None, "label": str, "active_socks": set()}

    def create_share(self, session_token: str, expires_in_seconds: float = None, label: str = "") -> str:
        share_token = secrets.token_urlsafe(32)
        now = time.time()
        expires_at = (now + expires_in_seconds) if expires_in_seconds and expires_in_seconds > 0 else None
        with self.lock:
            self.shares[share_token] = {
                "session_token": session_token,
                "created_at": now,
                "expires_at": expires_at,
                "label": label or "Shared Session",
                "active_socks": set()
            }
        return share_token

    def validate(self, share_token: str) -> dict:
        if not share_token:
            return None
        now = time.time()
        with self.lock:
            info = self.shares.get(share_token)
            if not info:
                return None
            if info["expires_at"] and now > info["expires_at"]:
                self._close_socks_unlocked(info)
                del self.shares[share_token]
                return None
            return dict(info)

    def register_socket(self, share_token: str, sock):
        with self.lock:
            info = self.shares.get(share_token)
            if info:
                info["active_socks"].add(sock)

    def unregister_socket(self, share_token: str, sock):
        with self.lock:
            info = self.shares.get(share_token)
            if info:
                info["active_socks"].discard(sock)

    def _close_socks_unlocked(self, info: dict):
        for s in list(info.get("active_socks", [])):
            try:
                s.close()
            except Exception:
                pass
        info["active_socks"].clear()

    def revoke(self, share_token: str) -> bool:
        with self.lock:
            info = self.shares.pop(share_token, None)
            if info:
                self._close_socks_unlocked(info)
                return True
            return False

    def revoke_by_session(self, session_token: str):
        with self.lock:
            to_remove = [k for k, v in self.shares.items() if v["session_token"] == session_token]
            for k in to_remove:
                info = self.shares.pop(k, None)
                if info:
                    self._close_socks_unlocked(info)

    def list_shares(self, session_token: str) -> list:
        now = time.time()
        result = []
        with self.lock:
            expired = []
            for k, v in self.shares.items():
                if v["expires_at"] and now > v["expires_at"]:
                    expired.append(k)
                    continue
                if v["session_token"] == session_token:
                    result.append({
                        "token": k,
                        "label": v["label"],
                        "created_at": v["created_at"],
                        "expires_at": v["expires_at"],
                        "active_viewers": len(v.get("active_socks", []))
                    })
            for k in expired:
                info = self.shares.pop(k, None)
                if info:
                    self._close_socks_unlocked(info)
        return result


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
        self.readonly_socks = set()
        self.sock_lock = threading.Lock()
        self.output_buffer = bytearray()
        self.buffer_lock = threading.Lock()
        self.cols = 80
        self.rows = 24
        self.created_at = time.time()
        self.last_seen = time.time()
        self.closed = False
        self.reader_thread = None
        self.shell_pgid = None
        self.active_cmd_pgid = None
        self.active_cmd_start_time = None
        self.active_cmd_name = ""
        self.last_reported_comm = ""
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
                os.execvpe(shell, [shell, "-l", "-i"], env)
            except Exception:
                try:
                    os.execvpe(shell, [shell, "-l"], env)
                except Exception:
                    os.execvpe(shell, [shell], env)
            sys.exit(1)

        os.close(slave_fd)
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self.pid = pid
        try:
            self.shell_pgid = os.getpgid(pid)
        except Exception:
            self.shell_pgid = pid

        self.reader_thread = threading.Thread(target=self._pty_reader_loop, daemon=True)
        self.reader_thread.start()

    def _broadcast_frame_unlocked(self, frame: bytes):
        if self.sock:
            try:
                self.sock.sendall(frame)
            except Exception:
                self.sock = None
        dead_ro = []
        for ro in list(self.readonly_socks):
            try:
                ro.sendall(frame)
            except Exception:
                dead_ro.append(ro)
        for ro in dead_ro:
            self.readonly_socks.discard(ro)

    def _check_fg_process(self):
        if not self.master_fd or self.closed:
            return
        fg_pgid = 0
        try:
            fg_pgid = os.tcgetpgrp(self.master_fd)
        except Exception:
            pass

        comm = ""
        if fg_pgid and fg_pgid > 0:
            try:
                with open(f"/proc/{fg_pgid}/comm", "r") as f:
                    comm = f.read().strip()
            except Exception:
                pass

        SHELLS = ('bash', 'sh', 'zsh', 'fish', 'dash', 'ash')
        if (not comm or comm in SHELLS) and self.pid:
            try:
                with open(f"/proc/{self.pid}/task/{self.pid}/children", "r") as f:
                    children = f.read().split()
                    if children:
                        with open(f"/proc/{children[-1]}/comm", "r") as cf:
                            child_comm = cf.read().strip()
                            if child_comm:
                                comm = child_comm
            except Exception:
                pass

        now = time.time()
        if comm and comm != self.last_reported_comm:
            self.last_reported_comm = comm
            with self.sock_lock:
                frame = ws_make_frame(json.dumps({"type": "process_name", "name": comm}).encode("utf-8"), opcode=1)
                self._broadcast_frame_unlocked(frame)

        if comm in SHELLS:
            self.shell_pgid = fg_pgid
            if self.active_cmd_name and self.active_cmd_start_time:
                duration = now - self.active_cmd_start_time
                finished_cmd = self.active_cmd_name
                self.active_cmd_name = ""
                self.active_cmd_start_time = None
                self.active_cmd_pgid = None

                if duration >= 3.0:
                    alert_payload = json.dumps({
                        "type": "task_alert",
                        "command": finished_cmd,
                        "duration": round(duration, 1),
                        "source": "process"
                    })
                    with self.sock_lock:
                        frame = ws_make_frame(alert_payload.encode("utf-8"), opcode=1)
                        self._broadcast_frame_unlocked(frame)
        elif comm != "":
            if self.active_cmd_name != comm:
                self.active_cmd_name = comm
                self.active_cmd_start_time = now
                self.active_cmd_pgid = fg_pgid

    def _pty_reader_loop(self):
        while not self.closed:
            try:
                if self.pid:
                    pid_res, _ = os.waitpid(self.pid, os.WNOHANG)
                    if pid_res != 0:
                        self.closed = True
                        break

                rlist, _, _ = select.select([self.master_fd], [], [], 0.5)
                self._check_fg_process()
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
                    frame = ws_make_frame(data, opcode=2)
                    self._broadcast_frame_unlocked(frame)
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

    def attach_readonly_socket(self, sock):
        with self.sock_lock:
            self.readonly_socks.add(sock)
            with self.buffer_lock:
                if self.output_buffer:
                    try:
                        frame = ws_make_frame(bytes(self.output_buffer), opcode=2)
                        sock.sendall(frame)
                    except Exception:
                        self.readonly_socks.discard(sock)

    def detach_readonly_socket(self, sock):
        with self.sock_lock:
            self.readonly_socks.discard(sock)

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

    def get_cwd(self) -> str:
        """Returns the current working directory of the shell session."""
        if self.pid and not self.closed:
            try:
                cwd = os.readlink(f"/proc/{self.pid}/cwd")
                if os.path.isdir(cwd):
                    return cwd
            except Exception:
                pass
        return os.environ.get("HOME", "/root")

    def close(self):
        self.closed = True
        with self.sock_lock:
            if self.sock:
                try:
                    self.sock.sendall(ws_make_frame(b"", opcode=8))
                except Exception:
                    pass
                self.sock = None
            for ro in list(self.readonly_socks):
                try:
                    ro.sendall(ws_make_frame(b"", opcode=8))
                    ro.close()
                except Exception:
                    pass
            self.readonly_socks.clear()

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
        self.sessions = {}  # session_key -> TerminalSession
        self.reaper_thread = threading.Thread(target=self._reaper_loop, daemon=True)
        self.reaper_thread.start()

    def _make_key(self, token: str, tab_id: str = None) -> str:
        if not token:
            return ""
        if tab_id:
            return f"{token}:{tab_id}"
        return token

    def get(self, token: str, tab_id: str = None):
        key = self._make_key(token, tab_id)
        with self.lock:
            if key and key in self.sessions:
                sess = self.sessions[key]
                if sess.is_alive():
                    return sess
            if not tab_id:
                if token and token in self.sessions:
                    sess = self.sessions[token]
                    if sess.is_alive():
                        return sess
                if token:
                    for k, sess in self.sessions.items():
                        if (k == token or k.startswith(f"{token}:")) and sess.is_alive():
                            return sess
                if len(self.sessions) == 1:
                    sess = next(iter(self.sessions.values()))
                    if sess.is_alive():
                        return sess
            return None

    def get_or_create(self, token: str, tab_id: str = None, shell: str = None) -> TerminalSession:
        key = self._make_key(token, tab_id)
        with self.lock:
            session = self.sessions.get(key)
            if session and session.is_alive():
                return session
            if session:
                session.close()
            session = TerminalSession(key, shell)
            self.sessions[key] = session
            return session

    def remove(self, token: str, tab_id: str = None):
        with self.lock:
            if tab_id:
                key = self._make_key(token, tab_id)
                session = self.sessions.pop(key, None)
                if session:
                    session.close()
            else:
                keys_to_remove = [k for k in self.sessions if k == token or k.startswith(f"{token}:")]
                for k in keys_to_remove:
                    sess = self.sessions.pop(k, None)
                    if sess:
                        sess.close()

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
  <div id="terminal-view" class="hidden flex-1 flex flex-col h-full relative">
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
        <div class="relative">
          <button id="notify-btn" onclick="toggleNotificationPanel()" title="Task Alerts & Notifications (Alerts when long commands or Antigravity finish)" class="px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono flex items-center gap-1.5">
            <span id="notify-icon">🔔</span>
            <span id="notify-badge" class="w-1.5 h-1.5 rounded-full bg-slate-500"></span>
          </button>
          <div id="notify-panel" class="hidden absolute right-0 top-full mt-1.5 w-72 bg-slate-900/95 backdrop-blur-sm border border-slate-700/80 rounded-xl shadow-2xl shadow-black/50 p-3.5 z-50 text-left font-sans">
            <div class="flex items-center justify-between mb-2.5 pb-2 border-b border-slate-800">
              <span class="text-[11px] font-semibold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
                <span>🔔</span> Task Alerts & Chimes
              </span>
              <button onclick="playNotificationChime()" title="Test Audio Chime" class="px-2 py-0.5 text-[10px] bg-slate-800 hover:bg-slate-700 text-emerald-300 border border-slate-700 rounded transition font-mono flex items-center gap-1">
                <span>🔊</span> Test
              </button>
            </div>
            
            <div class="space-y-2.5 text-xs">
              <div class="flex items-center justify-between">
                <div>
                  <div class="font-medium text-slate-200">Audio Chime</div>
                  <div class="text-[10px] text-slate-400">Plays gentle chime on completion</div>
                </div>
                <span class="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 font-mono">Active</span>
              </div>

              <div class="pt-2 border-t border-slate-800/80">
                <div class="flex items-center justify-between mb-1">
                  <div class="font-medium text-slate-200">Desktop Notification</div>
                  <span id="notify-perm-status" class="text-[10px] font-mono text-slate-400">Checking...</span>
                </div>
                <div id="notify-perm-action" class="mt-1"></div>
              </div>

              <div class="pt-2 border-t border-slate-800/80 text-[10px] text-slate-400 leading-relaxed">
                ⚡ Alerts trigger for commands running <span class="text-slate-300 font-mono">≥ 3s</span>, Antigravity AI turns, and terminal bells.
              </div>
            </div>
          </div>
        </div>
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
        <div id="readonly-badge" class="hidden px-2.5 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/30 text-amber-300 font-mono text-[11px] sm:text-xs flex items-center gap-1.5 font-medium">
          <span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span>
          <span>Read-Only Live View</span>
        </div>
        <button id="share-btn" onclick="openShareModal()" title="Share Live Terminal (Read-Only)" class="px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-slate-400">
            <circle cx="18" cy="5" r="3"></circle>
            <circle cx="6" cy="12" r="3"></circle>
            <circle cx="18" cy="19" r="3"></circle>
            <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"></line>
            <line x1="15.41" y1="6.51" x2="8.59" y2="10.49"></line>
          </svg>
          <span class="hidden md:inline">Share</span>
        </button>
        <button id="upload-btn" onclick="triggerFileInput()" title="Upload File to Terminal Directory" class="px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-slate-400">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="17 8 12 3 7 8"/>
            <line x1="12" y1="3" x2="12" y2="15"/>
          </svg>
          <span class="hidden md:inline">Upload</span>
        </button>
        <input id="file-upload-input" type="file" multiple class="hidden" onchange="handleFileSelect(event)">
        <button id="download-btn" onclick="openDownloadModal()" title="Download File from Remote Server" class="px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-slate-400">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          <span class="hidden md:inline">Download</span>
        </button>
        <button id="logout-btn" onclick="handleLogout()" class="px-2.5 py-1 text-xs bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 rounded-lg transition">Disconnect</button>
      </div>
    </header>

    <!-- Tab Bar -->
    <div id="tab-bar-container" class="bg-slate-950 border-b border-slate-800/80 px-2 sm:px-3 pt-1 flex items-center justify-between select-none shrink-0 overflow-hidden">
      <div id="tabs-list" class="flex items-center space-x-1 overflow-x-auto scrollbar-none py-0.5 max-w-[calc(100vw-7rem)] sm:max-w-[calc(100vw-12rem)]"></div>
      <div class="flex items-center pl-2 shrink-0">
        <button id="new-tab-btn" onclick="createNewTab()" title="New Terminal Tab (Alt+T / Ctrl+Shift+T)" class="px-2 py-1 bg-slate-800/80 hover:bg-slate-700 text-slate-300 hover:text-white rounded-lg transition text-xs flex items-center gap-1 font-mono">
          <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          <span class="hidden sm:inline text-[11px]">New Tab</span>
        </button>
      </div>
    </div>

    <!-- Terminal Mounting Area (holds per-tab terminal mount divs) -->
    <div id="terminal-container" class="flex-1 w-full bg-[#020617] relative overflow-hidden"></div>

    <!-- Drag & Drop Upload Overlay -->
    <div id="drop-overlay" class="hidden absolute inset-0 z-40 bg-slate-950/85 backdrop-blur-sm border-2 border-dashed border-orange-500 rounded-lg flex flex-col items-center justify-center pointer-events-none transition-all duration-150">
      <div class="p-6 rounded-2xl bg-slate-900 border border-slate-700 shadow-2xl flex flex-col items-center gap-3 text-center max-w-sm mx-4">
        <div class="w-14 h-14 rounded-2xl bg-orange-500/20 text-orange-400 flex items-center justify-center text-3xl animate-bounce">
          📁
        </div>
        <div>
          <div class="font-semibold text-white text-sm sm:text-base">Drop files to upload</div>
          <div id="drop-target-dir" class="text-xs font-mono text-orange-300 mt-1.5 px-2.5 py-1 bg-slate-950 rounded-lg border border-slate-800 break-all">...</div>
        </div>
        <div class="text-[11px] text-slate-400">Files will be uploaded directly to the active shell directory</div>
      </div>
    </div>


    <!-- Toast Notification -->
    <div id="term-toast" class="pointer-events-none fixed bottom-6 right-6 z-50 transition-all duration-200 opacity-0 translate-y-2 bg-slate-800/95 border border-slate-700 text-slate-200 text-xs px-3 py-1.5 rounded-lg shadow-xl font-mono flex items-center gap-2">
      <span id="term-toast-msg">Copied to clipboard</span>
    </div>

    <!-- Upload Progress Card -->
    <div id="upload-progress-card" class="hidden fixed bottom-6 left-6 z-50 bg-slate-900/95 backdrop-blur border border-slate-700/80 rounded-xl shadow-2xl p-3.5 w-80 max-w-[calc(100vw-3rem)] font-sans text-xs">
      <div class="flex items-center justify-between mb-1.5">
        <span id="upload-filename" class="font-mono text-slate-200 truncate max-w-[190px]">uploading...</span>
        <span id="upload-percent" class="font-mono text-orange-400 font-semibold">0%</span>
      </div>
      <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
        <div id="upload-bar" class="bg-orange-500 h-full w-0 transition-all duration-100"></div>
      </div>
      <div class="flex items-center justify-between mt-1.5 text-[10px] text-slate-500 font-mono">
        <span id="upload-bytes">0 B / 0 B</span>
        <span>Uploading...</span>
      </div>
    </div>

    <!-- Download Modal Dialog -->
    <div id="download-modal" class="hidden fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div class="bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl p-5 w-full max-w-md text-left font-sans">
        <div class="flex items-center justify-between mb-3 pb-2 border-b border-slate-800">
          <div class="flex items-center gap-2">
            <span class="text-base">📥</span>
            <span class="font-semibold text-sm text-white">Download Remote File</span>
          </div>
          <button type="button" onclick="closeDownloadModal()" class="text-slate-400 hover:text-slate-200 text-sm p-1">✕</button>
        </div>
        <form onsubmit="handleDownloadSubmit(event)" class="space-y-3.5">
          <div>
            <label class="block text-xs font-medium text-slate-300 mb-1">File Path to Download</label>
            <div class="text-[11px] text-slate-400 mb-1.5 font-mono truncate">
              Working directory: <span id="download-cwd-hint" class="text-orange-300">/root</span>
            </div>
            <input type="text" id="download-path-input" required placeholder="e.g. filename.ext or /var/log/syslog"
                   class="w-full bg-slate-950 border border-slate-700 rounded-xl px-3.5 py-2.5 text-xs text-white font-mono placeholder:text-slate-600 focus:outline-none focus:border-orange-500 focus:ring-1 focus:ring-orange-500">
            <p class="text-[10px] text-slate-500 mt-1">Relative paths are resolved against the active terminal directory.</p>
          </div>
          <div class="flex items-center justify-end gap-2 pt-2">
            <button type="button" onclick="closeDownloadModal()" class="px-3 py-1.5 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl transition">Cancel</button>
            <button type="submit" class="px-3.5 py-1.5 text-xs bg-orange-500 hover:bg-orange-600 text-white font-semibold rounded-xl transition flex items-center gap-1.5 shadow-lg shadow-orange-500/20">
              <span>Download</span>
              <span class="text-[10px]">↓</span>
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Session Share Modal Dialog -->
    <div id="share-modal" class="hidden fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div class="bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl p-5 w-full max-w-lg text-left font-sans max-h-[90vh] flex flex-col">
        <div class="flex items-center justify-between mb-3 pb-2 border-b border-slate-800 shrink-0">
          <div class="flex items-center gap-2">
            <span class="text-base">👥</span>
            <div>
              <span class="font-semibold text-sm text-white block">Share Live Terminal Session</span>
              <span class="text-[11px] text-slate-400">Generate a secure read-only live viewing link.</span>
            </div>
          </div>
          <button type="button" onclick="closeShareModal()" class="text-slate-400 hover:text-slate-200 text-sm p-1">✕</button>
        </div>

        <div class="overflow-y-auto pr-1 space-y-4 flex-1 scrollbar-thin scrollbar-thumb-slate-700">
          <!-- Generate Link Form -->
          <form onsubmit="handleCreateShare(event)" class="bg-slate-950/60 border border-slate-800/80 rounded-xl p-3.5 space-y-3">
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label class="block text-xs font-medium text-slate-300 mb-1">Session Label (Optional)</label>
                <input type="text" id="share-label-input" placeholder="e.g. Code Review" maxlength="30"
                       class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white font-mono placeholder:text-slate-600 focus:outline-none focus:border-orange-500">
              </div>
              <div>
                <label class="block text-xs font-medium text-slate-300 mb-1">Link Expiration</label>
                <select id="share-expiry-select" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white font-mono focus:outline-none focus:border-orange-500">
                  <option value="3600" selected>1 Hour</option>
                  <option value="21600">6 Hours</option>
                  <option value="86400">24 Hours</option>
                  <option value="0">Until Session Ends</option>
                </select>
              </div>
            </div>
            <div class="flex justify-end pt-1">
              <button type="submit" id="create-share-btn" class="px-3.5 py-1.5 text-xs bg-orange-500 hover:bg-orange-600 text-white font-semibold rounded-lg transition flex items-center gap-1.5 shadow-md shadow-orange-500/20">
                <span>Generate Read-Only Link</span>
                <span class="text-xs">🔗</span>
              </button>
            </div>
          </form>

          <!-- Newly Created Share Link Alert -->
          <div id="new-share-result" class="hidden bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-3 space-y-2">
            <div class="flex items-center justify-between text-xs text-emerald-400 font-medium">
              <span>✓ Read-Only Share Link Ready</span>
              <span class="text-[11px] text-emerald-400/80">Viewers cannot type or run commands</span>
            </div>
            <div class="flex items-center gap-2">
              <input type="text" id="new-share-url" readonly
                     class="flex-1 bg-slate-950 border border-emerald-500/30 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 font-mono select-all">
              <button type="button" onclick="copyShareUrl()" id="copy-share-btn"
                      class="px-3 py-1.5 text-xs bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg transition font-mono shrink-0">
                Copy Link
              </button>
            </div>
          </div>

          <!-- Active Shares List -->
          <div>
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs font-semibold text-slate-300">Active Share Links</span>
              <button type="button" onclick="loadShareLinks()" class="text-[11px] text-orange-400 hover:underline">Refresh</button>
            </div>
            <div id="active-shares-container" class="space-y-2 text-xs">
              <div class="text-slate-500 text-center py-3">Loading active links...</div>
            </div>
          </div>
        </div>

        <div class="flex items-center justify-end pt-3 border-t border-slate-800 shrink-0 mt-3">
          <button type="button" onclick="closeShareModal()" class="px-3.5 py-1.5 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl transition">Done</button>
        </div>
      </div>
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
      <button id="ctx-new-tab" onclick="createNewTab(); hideContextMenu();" class="w-full text-left px-3 py-1.5 text-slate-300 hover:bg-slate-800 hover:text-white flex items-center justify-between">
        <span class="flex items-center gap-2">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          <span>New Tab</span>
        </span>
        <span class="text-[10px] text-slate-500 font-mono">Alt+T</span>
      </button>
      <button id="ctx-close-tab" onclick="closeCurrentTab(); hideContextMenu();" class="w-full text-left px-3 py-1.5 text-slate-300 hover:bg-slate-800 hover:text-white flex items-center justify-between">
        <span class="flex items-center gap-2">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          <span>Close Tab</span>
        </span>
        <span class="text-[10px] text-slate-500 font-mono">Alt+W</span>
      </button>
      <div class="h-px bg-slate-800 my-1"></div>
      <button onclick="triggerFileInput(); hideContextMenu();" class="w-full text-left px-3 py-1.5 text-slate-300 hover:bg-slate-800 hover:text-white flex items-center justify-between">
        <span class="flex items-center gap-2">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          <span>Upload File...</span>
        </span>
      </button>
      <button onclick="openDownloadModal(); hideContextMenu();" class="w-full text-left px-3 py-1.5 text-slate-300 hover:bg-slate-800 hover:text-white flex items-center justify-between">
        <span class="flex items-center gap-2">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          <span>Download File...</span>
        </span>
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
    let sessionToken = '';
    let latencyPingSent = 0, clientServerLatency = -1, serverTerminalLatency = -1, latencyInterval = null;
    let tabs = {}; // tabId -> tabObj
    let activeTabId = null;
    let tabSequence = 0;

    function getActiveTab() {
      return activeTabId ? tabs[activeTabId] : null;
    }

    Object.defineProperty(window, 'term', {
      get() { const t = getActiveTab(); return t ? t.term : null; },
      configurable: true
    });
    Object.defineProperty(window, 'fitAddon', {
      get() { const t = getActiveTab(); return t ? t.fitAddon : null; },
      configurable: true
    });
    Object.defineProperty(window, 'socket', {
      get() { const t = getActiveTab(); return t ? t.socket : null; },
      configurable: true
    });

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
      if (window.IS_READONLY) {
        showTerminal();
        return;
      }
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
      if (window.IS_READONLY) {
        applyReadonlyUI();
      }
      initTerminal();
    }

    function sendInterrupt() {
      const cur = getActiveTab();
      const s = cur && cur.socket ? cur.socket : socket;
      if (s && s.readyState === WebSocket.OPEN) {
        s.send(JSON.stringify({ type: 'signal', signal: 'SIGINT' }));
        s.send(JSON.stringify({ type: 'input', data: '\x03' }));
      }
      if (term) term.focus();
    }

    function sendSuspend() {
      const cur = getActiveTab();
      const s = cur && cur.socket ? cur.socket : socket;
      if (s && s.readyState === WebSocket.OPEN) {
        s.send(JSON.stringify({ type: 'signal', signal: 'SIGTSTP' }));
        s.send(JSON.stringify({ type: 'input', data: '\x1a' }));
      }
      if (term) term.focus();
    }

    function sendEOF() {
      const cur = getActiveTab();
      const s = cur && cur.socket ? cur.socket : socket;
      if (s && s.readyState === WebSocket.OPEN) {
        s.send(JSON.stringify({ type: 'input', data: '\x04' }));
      }
      if (term) term.focus();
    }

    function sendCtrlW() {
      const cur = getActiveTab();
      const s = cur && cur.socket ? cur.socket : socket;
      if (s && s.readyState === WebSocket.OPEN) {
        s.send(JSON.stringify({ type: 'input', data: '\x17' }));
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

    document.addEventListener('fullscreenchange', () => {
      if (document.fullscreenElement) {
        if (navigator.keyboard && navigator.keyboard.lock) {
          navigator.keyboard.lock(['KeyW', 'KeyN', 'KeyT']).catch(() => {});
        }
        showToast('Fullscreen: Ctrl+W locked to terminal');
      } else {
        if (navigator.keyboard && navigator.keyboard.unlock) {
          navigator.keyboard.unlock();
        }
      }
      setTimeout(termFit, 100);
    });

    window.addEventListener('keydown', (e) => {
      if (e.ctrlKey && !e.shiftKey && !e.altKey && (e.key === 'w' || e.key === 'W')) {
        e.preventDefault();
        e.stopPropagation();
        sendCtrlW();
        return false;
      }
      if (((e.ctrlKey && e.shiftKey) || e.altKey) && (e.key === 'w' || e.key === 'W')) {
        e.preventDefault();
        e.stopPropagation();
        sendCtrlW();
        return false;
      }
    }, { capture: true });

    let originalDocTitle = document.title || 'Fire SSH';
    let titleBlinkInterval = null;

    function playNotificationChime() {
      try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (!AudioCtx) return;
        const ctx = new AudioCtx();
        if (ctx.state === 'suspended') ctx.resume();
        const now = ctx.currentTime;

        const osc1 = ctx.createOscillator();
        const gain1 = ctx.createGain();
        osc1.type = 'sine';
        osc1.frequency.setValueAtTime(587.33, now); // D5
        gain1.gain.setValueAtTime(0.12, now);
        gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.28);
        osc1.connect(gain1);
        gain1.connect(ctx.destination);
        osc1.start(now);
        osc1.stop(now + 0.28);

        const osc2 = ctx.createOscillator();
        const gain2 = ctx.createGain();
        osc2.type = 'sine';
        osc2.frequency.setValueAtTime(880, now + 0.12); // A5
        gain2.gain.setValueAtTime(0.12, now + 0.12);
        gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.42);
        osc2.connect(gain2);
        gain2.connect(ctx.destination);
        osc2.start(now + 0.12);
        osc2.stop(now + 0.42);
      } catch (e) {}
    }

    function triggerTaskAlert(title, message, source) {
      playNotificationChime();

      if (document.hidden || !document.hasFocus()) {
        try {
          if ('Notification' in window && Notification.permission === 'granted') {
            const notif = new Notification(title, {
              body: message,
              tag: 'fire-task-alert'
            });
            notif.onclick = () => {
              window.focus();
              notif.close();
            };
          }
        } catch(e) {}

        if (!titleBlinkInterval) {
          let blink = false;
          titleBlinkInterval = setInterval(() => {
            blink = !blink;
            document.title = blink ? `🔔 ${title}!` : originalDocTitle;
          }, 1000);
        }
      }

      showToast(`🔔 ${title}: ${message}`);
    }

    window.addEventListener('focus', () => {
      if (titleBlinkInterval) {
        clearInterval(titleBlinkInterval);
        titleBlinkInterval = null;
        document.title = originalDocTitle;
      }
    });

    function toggleNotificationPanel() {
      const panel = document.getElementById('notify-panel');
      if (!panel) return;
      const isHidden = panel.classList.contains('hidden');
      const latPanel = document.getElementById('latency-panel');
      if (latPanel) latPanel.classList.add('hidden');

      panel.classList.toggle('hidden');
      if (isHidden) {
        updateNotifyPanelUI();
        if ('Notification' in window && Notification.permission === 'default') {
          requestDesktopNotificationPerm();
        }
      }
    }

    function updateNotifyPanelUI() {
      const statusEl = document.getElementById('notify-perm-status');
      const actionEl = document.getElementById('notify-perm-action');
      const badge = document.getElementById('notify-badge');
      if (!statusEl || !actionEl) return;

      if (!('Notification' in window)) {
        statusEl.innerHTML = '<span class="text-amber-400">Unsupported</span>';
        actionEl.innerHTML = '<p class="text-[10px] text-slate-400">Browser does not support desktop notifications. Audio chime is active.</p>';
        if (badge) badge.className = 'w-1.5 h-1.5 rounded-full bg-amber-400';
        return;
      }

      const perm = Notification.permission;
      if (perm === 'granted') {
        statusEl.innerHTML = '<span class="text-emerald-400 font-semibold">● Allowed</span>';
        actionEl.innerHTML = '<button onclick="playNotificationChime(); showToast(\'Desktop notifications active!\'); try { new Notification(\'Fire SSH\', { body: \'Test notification successful!\' }); } catch(e){}" class="w-full py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg transition font-mono flex items-center justify-center gap-1"><span>📬</span> Send Test Notification</button>';
        if (badge) badge.className = 'w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse';
      } else if (perm === 'denied') {
        statusEl.innerHTML = '<span class="text-red-400 font-semibold">● Blocked in Browser</span>';
        actionEl.innerHTML = '<div class="p-2 bg-red-950/40 border border-red-500/30 rounded-lg text-[11px] text-red-300 leading-tight"><span class="font-semibold">How to enable:</span><br>Click the 🔒 or ⚙️ icon in your browser URL address bar and set <b>Notifications</b> to <b>Allow</b>.</div>';
        if (badge) badge.className = 'w-1.5 h-1.5 rounded-full bg-red-400';
      } else {
        statusEl.innerHTML = '<span class="text-amber-400 font-semibold">● Not Enabled</span>';
        actionEl.innerHTML = '<button onclick="requestDesktopNotificationPerm()" class="w-full py-1 text-xs bg-emerald-600 hover:bg-emerald-500 text-white font-medium rounded-lg shadow transition flex items-center justify-center gap-1"><span>🔔</span> Enable Desktop Alerts</button>';
        if (badge) badge.className = 'w-1.5 h-1.5 rounded-full bg-amber-400';
      }
    }

    function requestDesktopNotificationPerm() {
      if (!('Notification' in window)) {
        showToast('Desktop notifications not supported in this browser');
        return;
      }
      let handled = false;
      function onDone(perm) {
        if (handled) return;
        handled = true;
        updateNotifyPanelUI();
        if (perm === 'granted') {
          playNotificationChime();
          showToast('Notifications enabled!');
          try {
            new Notification('Fire SSH', { body: 'Notifications enabled successfully!' });
          } catch(e) {}
        } else if (perm === 'denied') {
          showToast('Notifications blocked in browser settings.');
        }
      }
      try {
        const req = Notification.requestPermission(onDone);
        if (req && typeof req.then === 'function') {
          req.then(onDone).catch(() => {});
        }
      } catch(e) {
        console.error(e);
      }
    }

    document.addEventListener('click', (e) => {
      const panel = document.getElementById('notify-panel');
      const btn = document.getElementById('notify-btn');
      if (panel && btn && !panel.contains(e.target) && !btn.contains(e.target)) {
        panel.classList.add('hidden');
      }
    });

    function updateNotifyBtnState() {
      updateNotifyPanelUI();
    }

    function toggleNotifications() {
      toggleNotificationPanel();
    }

    // ==================== FILE TRANSFER & DRAG-AND-DROP ====================
    let dragCounter = 0;
    let currentCwd = '/root';

    async function updateCwd() {
      try {
        const tabParam = activeTabId ? `?tab=${encodeURIComponent(activeTabId)}` : '';
        const res = await fetch(`/api/cwd${tabParam}`);
        if (res.ok) {
          const data = await res.json();
          if (data && data.cwd) {
            currentCwd = data.cwd;
            const dropDirEl = document.getElementById('drop-target-dir');
            if (dropDirEl) dropDirEl.textContent = currentCwd;
            const dlHintEl = document.getElementById('download-cwd-hint');
            if (dlHintEl) dlHintEl.textContent = currentCwd;
          }
        }
      } catch(e) {}
    }

    function formatBytes(bytes) {
      if (bytes === 0) return '0 B';
      const k = 1024;
      const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    window.addEventListener('dragenter', (e) => {
      if (window.IS_READONLY) return;
      e.preventDefault();
      dragCounter++;
      if (dragCounter === 1) {
        updateCwd();
        const overlay = document.getElementById('drop-overlay');
        if (overlay) overlay.classList.remove('hidden');
      }
    });

    window.addEventListener('dragover', (e) => {
      e.preventDefault();
    });

    window.addEventListener('dragleave', (e) => {
      if (window.IS_READONLY) return;
      e.preventDefault();
      dragCounter--;
      if (dragCounter <= 0) {
        dragCounter = 0;
        const overlay = document.getElementById('drop-overlay');
        if (overlay) overlay.classList.add('hidden');
      }
    });

    window.addEventListener('drop', (e) => {
      if (window.IS_READONLY) return;
      e.preventDefault();
      dragCounter = 0;
      const overlay = document.getElementById('drop-overlay');
      if (overlay) overlay.classList.add('hidden');

      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        uploadFiles(e.dataTransfer.files);
      }
    });

    function triggerFileInput() {
      updateCwd();
      const fileInput = document.getElementById('file-upload-input');
      if (fileInput) {
        fileInput.value = '';
        fileInput.click();
      }
    }

    function handleFileSelect(e) {
      if (e.target && e.target.files && e.target.files.length > 0) {
        uploadFiles(e.target.files);
      }
    }

    async function uploadFiles(files) {
      if (!files || files.length === 0) return;
      await updateCwd();

      const progressCard = document.getElementById('upload-progress-card');
      const filenameEl = document.getElementById('upload-filename');
      const percentEl = document.getElementById('upload-percent');
      const barEl = document.getElementById('upload-bar');
      const bytesEl = document.getElementById('upload-bytes');

      let successCount = 0;
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        if (progressCard) progressCard.classList.remove('hidden');
        if (filenameEl) filenameEl.textContent = files.length > 1 ? `(${i + 1}/${files.length}) ${file.name}` : file.name;
        if (percentEl) percentEl.textContent = '0%';
        if (barEl) barEl.style.width = '0%';
        if (bytesEl) bytesEl.textContent = `0 B / ${formatBytes(file.size)}`;

        try {
          await new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            const tabParam = activeTabId ? `&tab=${encodeURIComponent(activeTabId)}` : '';
            const url = `/api/upload?name=${encodeURIComponent(file.name)}&dest=${encodeURIComponent(currentCwd)}${tabParam}`;
            xhr.open('POST', url, true);

            xhr.upload.onprogress = (evt) => {
              if (evt.lengthComputable) {
                const pct = Math.round((evt.loaded / evt.total) * 100);
                if (percentEl) percentEl.textContent = `${pct}%`;
                if (barEl) barEl.style.width = `${pct}%`;
                if (bytesEl) bytesEl.textContent = `${formatBytes(evt.loaded)} / ${formatBytes(evt.total)}`;
              }
            };

            xhr.onload = () => {
              if (xhr.status === 200) {
                successCount++;
                showToast(`Uploaded ${file.name} to ${currentCwd}`);
                resolve();
              } else {
                let errMsg = 'Upload failed';
                try {
                  const res = JSON.parse(xhr.responseText);
                  if (res && res.error) errMsg = res.error;
                } catch(e) {}
                showToast(`Upload failed: ${errMsg}`);
                reject(new Error(errMsg));
              }
            };

            xhr.onerror = () => {
              showToast(`Network error uploading ${file.name}`);
              reject(new Error('Network error'));
            };

            xhr.send(file);
          });
        } catch(err) {
          console.error('File upload error:', err);
        }
      }

      if (progressCard) {
        setTimeout(() => {
          progressCard.classList.add('hidden');
        }, 1200);
      }

      if (successCount > 0) {
        playNotificationChime();
        if ('Notification' in window && Notification.permission === 'granted') {
          new Notification('Fire SSH', {
            body: `Uploaded ${successCount} file(s) to ${currentCwd}`
          });
        }
      }
    }

    function openDownloadModal() {
      updateCwd();
      const modal = document.getElementById('download-modal');
      const input = document.getElementById('download-path-input');
      if (modal) modal.classList.remove('hidden');
      if (input) {
        input.value = '';
        setTimeout(() => input.focus(), 50);
      }
    }

    function closeDownloadModal() {
      const modal = document.getElementById('download-modal');
      if (modal) modal.classList.add('hidden');
    }

    function handleDownloadSubmit(e) {
      e.preventDefault();
      const input = document.getElementById('download-path-input');
      if (!input) return;
      const val = input.value.trim();
      if (!val) return;

      closeDownloadModal();
      const tabParam = activeTabId ? `&tab=${encodeURIComponent(activeTabId)}` : '';
      const dlUrl = `/api/download?file=${encodeURIComponent(val)}${tabParam}`;

      fetch(dlUrl, { method: 'HEAD' }).then(res => {
        if (res.ok) {
          const a = document.createElement('a');
          a.href = dlUrl;
          a.download = val.split('/').pop() || 'download';
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          showToast(`Downloading ${val}...`);
        } else {
          res.json().then(data => {
            showToast(`Download error: ${data.error || res.statusText}`);
          }).catch(() => {
            showToast(`Download failed with status ${res.status}`);
          });
        }
      }).catch(() => {
        const a = document.createElement('a');
        a.href = dlUrl;
        a.download = val.split('/').pop() || 'download';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      });
    }

    // ==================== READ-ONLY LIVE SESSION SHARING ====================
    function openShareModal() {
      const modal = document.getElementById('share-modal');
      if (modal) {
        modal.classList.remove('hidden');
        loadShareLinks();
      }
    }

    function closeShareModal() {
      const modal = document.getElementById('share-modal');
      if (modal) modal.classList.add('hidden');
    }

    async function loadShareLinks() {
      const container = document.getElementById('active-shares-container');
      if (!container) return;
      try {
        const res = await fetch('/api/share/list');
        if (!res.ok) {
          container.innerHTML = '<div class="text-slate-500 text-center py-2">Failed to load share links</div>';
          return;
        }
        const data = await res.json();
        const shares = data.shares || [];
        if (shares.length === 0) {
          container.innerHTML = '<div class="text-slate-500 text-center py-3">No active share links. Generate one above!</div>';
          return;
        }

        const now = Date.now() / 1000;
        container.innerHTML = shares.map(s => {
          let expText = 'Until session ends';
          if (s.expires_at) {
            const rem = Math.max(0, Math.round(s.expires_at - now));
            if (rem <= 0) expText = 'Expired';
            else if (rem < 3600) expText = `${Math.round(rem / 60)}m remaining`;
            else expText = `${(rem / 3600).toFixed(1)}h remaining`;
          }
          const fullUrl = `${window.location.origin}/?share=${encodeURIComponent(s.token)}`;
          return `
            <div class="flex items-center justify-between p-2.5 rounded-lg bg-slate-950/60 border border-slate-800 gap-2 font-mono">
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <span class="font-semibold text-slate-200 truncate">${s.label || 'Shared Session'}</span>
                  <span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">${expText}</span>
                  ${s.active_viewers > 0 ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400 font-sans">${s.active_viewers} live viewer(s)</span>` : ''}
                </div>
                <div class="text-[11px] text-slate-500 truncate mt-0.5 select-all">${fullUrl}</div>
              </div>
              <div class="flex items-center gap-1.5 shrink-0">
                <button type="button" onclick="navigator.clipboard.writeText('${fullUrl}'); showToast('Share link copied!');" class="p-1 px-2 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] transition">Copy</button>
                <button type="button" onclick="handleRevokeShare('${s.token}')" class="p-1 px-2 rounded bg-red-500/10 hover:bg-red-500/20 text-red-400 text-[11px] transition">Revoke</button>
              </div>
            </div>
          `;
        }).join('');
      } catch(e) {
        container.innerHTML = '<div class="text-slate-500 text-center py-2">Error loading share links</div>';
      }
    }

    async function handleCreateShare(e) {
      e.preventDefault();
      const labelInput = document.getElementById('share-label-input');
      const expirySelect = document.getElementById('share-expiry-select');
      const label = labelInput ? labelInput.value.trim() : '';
      const exp = expirySelect ? parseInt(expirySelect.value, 10) : 3600;

      const btn = document.getElementById('create-share-btn');
      if (btn) btn.disabled = true;

      try {
        const res = await fetch('/api/share/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ label, expires_in: exp })
        });
        const data = await res.json();
        if (data.success && data.share_token) {
          const fullUrl = `${window.location.origin}/?share=${encodeURIComponent(data.share_token)}`;
          const resBox = document.getElementById('new-share-result');
          const urlInput = document.getElementById('new-share-url');
          if (resBox && urlInput) {
            urlInput.value = fullUrl;
            resBox.classList.remove('hidden');
          }
          if (labelInput) labelInput.value = '';
          loadShareLinks();
          showToast('Share link generated!');
          navigator.clipboard.writeText(fullUrl).catch(() => {});
        } else {
          showToast(`Failed: ${data.error || 'Could not create link'}`);
        }
      } catch(err) {
        showToast('Network error creating share link');
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    function copyShareUrl() {
      const urlInput = document.getElementById('new-share-url');
      if (!urlInput) return;
      navigator.clipboard.writeText(urlInput.value).then(() => {
        showToast('Share link copied to clipboard!');
      }).catch(() => {
        urlInput.select();
        document.execCommand('copy');
        showToast('Share link copied!');
      });
    }

    async function handleRevokeShare(token) {
      if (!confirm('Revoke this share link? Connected viewers will be disconnected immediately.')) return;
      try {
        const res = await fetch('/api/share/revoke', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ share_token: token })
        });
        const data = await res.json();
        if (data.success) {
          showToast('Share link revoked');
          loadShareLinks();
        } else {
          showToast(`Error: ${data.error || 'Failed to revoke'}`);
        }
      } catch(e) {
        showToast('Network error revoking share link');
      }
    }

    function applyReadonlyUI() {
      const roBadge = document.getElementById('readonly-badge');
      if (roBadge) roBadge.classList.remove('hidden');

      const toHide = [
        'share-btn', 'upload-btn', 'download-btn', 'logout-btn',
        'settings-btn', 'new-tab-btn'
      ];
      toHide.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.add('hidden');
      });

      const ctxNewTab = document.getElementById('ctx-new-tab');
      const ctxCloseTab = document.getElementById('ctx-close-tab');
      if (ctxNewTab) ctxNewTab.classList.add('hidden');
      if (ctxCloseTab) ctxCloseTab.classList.add('hidden');
    }

    function renderServerOutput(raw) {
      const cur = getActiveTab();
      if (cur) {
        renderTabOutput(cur, raw);
      } else if (term) {
        term.write(raw);
      }
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
      const cur = getActiveTab();
      if (cur) {
        if (cur.socket && cur.socket.readyState === WebSocket.OPEN) {
          cur.socket.send(JSON.stringify({ type: 'input', data: text }));
        } else if (cur.term && typeof cur.term.paste === 'function') {
          cur.term.paste(text);
        }
      } else if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'input', data: text }));
      }
    }

    function initTerminal() {
      if (Object.keys(tabs).length === 0) {
        createNewTab('bash');
      }
      initGlobalShortcuts();
    }

    function createNewTab(initialTitle) {
      tabSequence++;
      const tabId = 'tab-' + tabSequence;
      const tabIndex = Object.keys(tabs).length + 1;
      const title = initialTitle || 'bash';

      const container = document.getElementById('terminal-container');
      if (!container) return;

      const mountEl = document.createElement('div');
      mountEl.id = `term-mount-${tabId}`;
      mountEl.className = 'w-full h-full';
      container.appendChild(mountEl);

      const isReadOnly = !!window.IS_READONLY;
      const t = new Terminal({
        cursorBlink: !isReadOnly,
        disableStdin: isReadOnly,
        cursorStyle: isReadOnly ? 'underline' : 'bar',
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

      const fa = new FitAddon.FitAddon();
      t.loadAddon(fa);
      if (typeof WebLinksAddon !== 'undefined') {
        t.loadAddon(new WebLinksAddon.WebLinksAddon());
      }
      t.open(mountEl);

      const tabObj = {
        id: tabId,
        index: tabIndex,
        title: title,
        term: t,
        fitAddon: fa,
        socket: null,
        mountEl: mountEl,
        reconnectTimer: null,
        pingTimer: null,
        hasAlert: false,
        connected: false,
        cwd: '/root'
      };

      tabs[tabId] = tabObj;

      setupTabEvents(tabObj);
      connectTabWebSocket(tabObj);
      switchTab(tabId);
    }

    function switchTab(tabId) {
      if (!tabs[tabId]) return;
      activeTabId = tabId;
      const activeTab = tabs[tabId];
      activeTab.hasAlert = false;
      renderTabsList();

      Object.keys(tabs).forEach(id => {
        const t = tabs[id];
        if (t && t.mountEl) {
          if (id === tabId) {
            t.mountEl.classList.remove('hidden');
          } else {
            t.mountEl.classList.add('hidden');
          }
        }
      });

      if (activeTab.fitAddon) {
        setTimeout(() => {
          activeTab.fitAddon.fit();
          sendResize(activeTab);
        }, 30);
      }
      if (activeTab.term) {
        activeTab.term.focus();
      }

      const connBadge = document.getElementById('conn-badge');
      if (connBadge) {
        if (activeTab.connected) {
          connBadge.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span> Connected';
          connBadge.className = 'text-[11px] sm:text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 font-mono flex items-center gap-1';
        } else {
          connBadge.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-ping"></span> Connecting...';
          connBadge.className = 'text-[11px] sm:text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 font-mono flex items-center gap-1';
        }
      }

      updateCwd();
    }

    function closeTab(tabId) {
      const tabKeys = Object.keys(tabs);
      if (tabKeys.length <= 1) {
        showToast('Cannot close the last open tab');
        return;
      }
      const tab = tabs[tabId];
      if (!tab) return;

      if (tab.pingTimer) clearInterval(tab.pingTimer);
      if (tab.reconnectTimer) clearTimeout(tab.reconnectTimer);
      if (tab.socket) {
        try { tab.socket.close(); } catch(e) {}
      }

      fetch(`/api/tab_close?tab=${encodeURIComponent(tabId)}`, { method: 'POST' }).catch(() => {});

      if (tab.mountEl && tab.mountEl.parentNode) {
        tab.mountEl.parentNode.removeChild(tab.mountEl);
      }
      if (tab.term) {
        try { tab.term.dispose(); } catch(e) {}
      }

      delete tabs[tabId];

      if (activeTabId === tabId) {
        const remaining = Object.keys(tabs);
        switchTab(remaining[remaining.length - 1]);
      } else {
        renderTabsList();
      }
    }

    function closeCurrentTab() {
      if (activeTabId) closeTab(activeTabId);
    }

    function renderTabsList() {
      const listEl = document.getElementById('tabs-list');
      if (!listEl) return;
      const tabKeys = Object.keys(tabs);
      if (tabKeys.length === 0) return;

      listEl.innerHTML = tabKeys.map((tabId, idx) => {
        const tab = tabs[tabId];
        tab.index = idx + 1;
        const isActive = tabId === activeTabId;
        const statusDot = tab.connected ? 'bg-emerald-400' : 'bg-amber-400';
        const alertBadge = tab.hasAlert ? '<span class="animate-bounce text-xs">🔔</span>' : '';
        const closeBtn = tabKeys.length > 1 ? `
          <button onclick="event.stopPropagation(); closeTab('${tabId}')" title="Close Tab (Alt+W)" class="opacity-40 group-hover:opacity-100 hover:text-rose-400 hover:bg-slate-800/80 p-0.5 rounded transition ml-0.5">
            <svg viewBox="0 0 24 24" width="10" height="10" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>` : '';

        return `
          <div onclick="switchTab('${tabId}')" class="group flex items-center gap-1.5 px-3 py-1 rounded-t-lg text-xs font-mono cursor-pointer transition select-none border-t-2 ${
            isActive
              ? 'bg-slate-900 text-white border-orange-500 shadow-md font-semibold'
              : 'bg-slate-950/70 text-slate-400 border-transparent hover:bg-slate-900/60 hover:text-slate-200'
          }">
            <span class="w-1.5 h-1.5 rounded-full ${statusDot} shrink-0"></span>
            ${alertBadge}
            <span class="truncate max-w-[100px] sm:max-w-[140px]">${tab.index}: ${tab.title || 'bash'}</span>
            ${closeBtn}
          </div>
        `;
      }).join('');
    }

    function setupTabEvents(tab) {
      const t = tab.term;

      // Terminal Bell
      t.onBell(() => {
        const isBg = tab.id !== activeTabId;
        if (isBg) { tab.hasAlert = true; renderTabsList(); }
        triggerTaskAlert(
          isBg ? `[Tab ${tab.index}: ${tab.title}] Bell` : 'Terminal Bell',
          'Process requested attention',
          'bell'
        );
      });

      // OSC 9 & 777
      if (t.parser && t.parser.registerOscHandler) {
        t.parser.registerOscHandler(9, (data) => {
          const isBg = tab.id !== activeTabId;
          if (isBg) { tab.hasAlert = true; renderTabsList(); }
          triggerTaskAlert(isBg ? `[Tab ${tab.index}] Notification` : 'Antigravity Notification', data, 'osc9');
          return true;
        });
        t.parser.registerOscHandler(777, (data) => {
          const isBg = tab.id !== activeTabId;
          if (isBg) { tab.hasAlert = true; renderTabsList(); }
          const parts = data.split(';');
          if (parts[0] === 'notify') {
            const title = parts[1] || 'Antigravity Notification';
            const msg = parts.slice(2).join(';') || 'Task finished';
            triggerTaskAlert(isBg ? `[Tab ${tab.index}] ${title}` : title, msg, 'osc777');
          }
          return true;
        });
      }

      // Mouse & contextmenu on mountEl
      tab.mountEl.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        showContextMenu(e.clientX, e.clientY);
      });

      tab.mountEl.addEventListener('auxclick', (e) => {
        if (e.button === 1) {
          e.preventDefault();
          pasteFromClipboard(false, true);
        }
      });

      // Custom key event handler
      t.attachCustomKeyEventHandler((e) => {
        if (e.type === 'keydown') {
          const isCtrlOrMeta = e.ctrlKey || e.metaKey;

          // Copy
          if ((isCtrlOrMeta && (e.key === 'c' || e.key === 'C')) || (isCtrlOrMeta && e.key === 'Insert')) {
            if (t.hasSelection()) {
              copySelectionToClipboard(true);
              return false;
            }
            if (e.metaKey && !e.ctrlKey) return false;
            if (e.shiftKey) return false;
            sendInterrupt();
            return false;
          }

          // Paste (handled by native document paste listener for Ctrl+V / Cmd+V; handle Shift+Insert / Paste key)
          if (e.shiftKey && (e.key === 'Insert' || e.key === 'Paste')) {
            pasteFromClipboard(true, true);
            return false;
          }

          // Select All
          if (((e.metaKey && !e.ctrlKey) || (e.ctrlKey && e.shiftKey)) && (e.key === 'a' || e.key === 'A')) {
            selectAllTerm();
            return false;
          }

          // Clear
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
            if (tab.socket && tab.socket.readyState === WebSocket.OPEN) {
              tab.socket.send(JSON.stringify({ type: 'input', data: '\x0c' }));
            }
            return false;
          }

          // Ctrl+W / Alt+W
          if (e.altKey && (e.key === 'w' || e.key === 'W')) {
            const shells = ['bash', 'sh', 'zsh', 'fish', 'dash', 'ash'];
            if (Object.keys(tabs).length > 1 && shells.includes(tab.title)) {
              e.preventDefault();
              closeTab(tab.id);
              return false;
            }
            e.preventDefault();
            sendCtrlW();
            return false;
          }
          if (e.ctrlKey && (e.key === 'w' || e.key === 'W')) {
            e.preventDefault();
            sendCtrlW();
            return false;
          }

          // Alt+T: New Tab
          if (e.altKey && (e.key === 't' || e.key === 'T')) {
            e.preventDefault();
            createNewTab();
            return false;
          }

          // Alt+1 .. Alt+9: Switch Tab
          if (e.altKey && e.key >= '1' && e.key <= '9') {
            e.preventDefault();
            const targetIdx = parseInt(e.key, 10) - 1;
            const tabKeys = Object.keys(tabs);
            if (targetIdx < tabKeys.length) {
              switchTab(tabKeys[targetIdx]);
            }
            return false;
          }

        }
        return true;
      });

      // Terminal Data handler
      if (!window.IS_READONLY) {
        t.onData(data => {
          if (tab.socket && tab.socket.readyState === WebSocket.OPEN) {
            tab.socket.send(JSON.stringify({ type: 'input', data }));
          }
        });
      }
    }

    function connectTabWebSocket(tab) {
      if (tab.reconnectTimer) clearTimeout(tab.reconnectTimer);
      if (tab.pingTimer) clearInterval(tab.pingTimer);

      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = window.IS_READONLY
        ? `${proto}//${window.location.host}/ws?share=${encodeURIComponent(window.SHARE_TOKEN || '')}&tab=${encodeURIComponent(tab.id)}`
        : `${proto}//${window.location.host}/ws?token=${encodeURIComponent(sessionToken)}&tab=${encodeURIComponent(tab.id)}`;

      tab.socket = new WebSocket(wsUrl);
      tab.socket.binaryType = 'arraybuffer';

      tab.socket.onopen = () => {
        tab.connected = true;
        renderTabsList();

        if (tab.id === activeTabId) {
          const connBadge = document.getElementById('conn-badge');
          if (connBadge) {
            connBadge.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span> Connected';
            connBadge.className = 'text-[11px] sm:text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 font-mono flex items-center gap-1';
          }
          if (tab.fitAddon) tab.fitAddon.fit();
          if (tab.term) tab.term.focus();
          if (!window.IS_READONLY) {
            sendResize(tab);
          }
        }

        tab.pingTimer = setInterval(() => {
          if (tab.socket && tab.socket.readyState === WebSocket.OPEN) {
            tab.socket.send(JSON.stringify({ type: 'ping' }));
          }
        }, 15000);

        if (tab.id === activeTabId) {
          setTimeout(measureLatency, 1000);
          if (!window.IS_READONLY) {
            setTimeout(updateCwd, 500);
          }
        }
      };

      tab.socket.onmessage = (event) => {
        if (typeof event.data === 'string') {
          try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'output') {
              renderTabOutput(tab, msg.data);
            } else if (msg.type === 'pong') {
              // pong
            } else if (msg.type === 'process_name') {
              if (msg.name && tab.title !== msg.name) {
                tab.title = msg.name;
                renderTabsList();
              }
            } else if (msg.type === 'task_alert') {
              const isBg = tab.id !== activeTabId;
              if (isBg) {
                tab.hasAlert = true;
                renderTabsList();
              }
              triggerTaskAlert(
                isBg ? `[Tab ${tab.index}: ${tab.title}] ${msg.command} finished` : `Fire SSH: ${msg.command} finished`,
                `Completed in ${msg.duration}s`,
                'process'
              );
            } else if (msg.type === 'latency_pong') {
              clientServerLatency = performance.now() - msg.timestamp;
              updateLatencyDisplay();
            } else if (msg.type === 'latency_terminal_result') {
              serverTerminalLatency = msg.latency;
              updateLatencyDisplay();
            }
          } catch(e) {
            renderTabOutput(tab, event.data);
          }
        } else {
          const uint8 = new Uint8Array(event.data);
          renderTabOutput(tab, uint8);
        }
      };

      tab.socket.onclose = () => {
        tab.connected = false;
        renderTabsList();
        if (tab.id === activeTabId) {
          const connBadge = document.getElementById('conn-badge');
          if (connBadge) {
            connBadge.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-ping"></span> Reconnecting...';
            connBadge.className = 'text-[11px] sm:text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 font-mono flex items-center gap-1';
          }
        }
        tab.reconnectTimer = setTimeout(() => {
          if (!document.getElementById('terminal-view').classList.contains('hidden')) {
            connectTabWebSocket(tab);
          }
        }, 1500);
      };

      tab.socket.onerror = (err) => {
        console.error('WebSocket Error:', err);
      };
    }

    function renderTabOutput(tab, data) {
      if (tab && tab.term) {
        tab.term.write(data);
      }
    }

    function sendResize(tab) {
      if (tab && tab.socket && tab.socket.readyState === WebSocket.OPEN && tab.term) {
        tab.socket.send(JSON.stringify({ type: 'resize', cols: tab.term.cols, rows: tab.term.rows }));
      }
    }

    function termFit() {
      const cur = getActiveTab();
      if (cur && cur.fitAddon && cur.term) {
        cur.fitAddon.fit();
        sendResize(cur);
      }
    }

    function initGlobalShortcuts() {
      window.addEventListener('resize', () => termFit());

      document.addEventListener('copy', (e) => {
        const cur = getActiveTab();
        if (cur && cur.term && cur.term.hasSelection()) {
          const text = cur.term.getSelection();
          if (text && e.clipboardData) {
            e.clipboardData.setData('text/plain', text);
            e.preventDefault();
            showToast('Copied to clipboard');
          }
        }
      });

      document.addEventListener('paste', (e) => {
        if (window.IS_READONLY) return;
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

        // Alt+T or Ctrl+Shift+T: New Tab
        if ((e.altKey && (e.key === 't' || e.key === 'T')) ||
            (e.ctrlKey && e.shiftKey && (e.key === 't' || e.key === 'T'))) {
          if (window.IS_READONLY) return;
          e.preventDefault();
          createNewTab();
          return;
        }

        // Alt+W: Close current tab
        if (e.altKey && (e.key === 'w' || e.key === 'W')) {
          if (window.IS_READONLY) return;
          e.preventDefault();
          closeCurrentTab();
          return;
        }

        // Alt+1 .. Alt+9: Switch to tab
        if (e.altKey && e.key >= '1' && e.key <= '9') {
          e.preventDefault();
          const targetIdx = parseInt(e.key, 10) - 1;
          const tabKeys = Object.keys(tabs);
          if (targetIdx < tabKeys.length) {
            switchTab(tabKeys[targetIdx]);
          }
          return;
        }

        // Alt+Left / Alt+Right: Cycle tabs
        if (e.altKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
          e.preventDefault();
          const tabKeys = Object.keys(tabs);
          if (tabKeys.length > 1) {
            const curIdx = tabKeys.indexOf(activeTabId);
            if (e.key === 'ArrowLeft') {
              const prev = (curIdx - 1 + tabKeys.length) % tabKeys.length;
              switchTab(tabKeys[prev]);
            } else {
              const next = (curIdx + 1) % tabKeys.length;
              switchTab(tabKeys[next]);
            }
          }
          return;
        }
      });
    }

    let isLoggingOut = false;
    window.addEventListener('beforeunload', (e) => {
      if (!isLoggingOut) {
        const cur = getActiveTab();
        if (cur && cur.socket && cur.socket.readyState === WebSocket.OPEN) {
          e.preventDefault();
          e.returnValue = '';
        }
      }
    });

    async function handleLogout() {
      isLoggingOut = true;
      Object.keys(tabs).forEach(id => {
        const t = tabs[id];
        if (t.pingTimer) clearInterval(t.pingTimer);
        if (t.reconnectTimer) clearTimeout(t.reconnectTimer);
        if (t.socket) {
          try { t.socket.close(); } catch(e) {}
        }
      });
      if (latencyInterval) { clearInterval(latencyInterval); latencyInterval = null; }
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.plain_password = None
        self.salt_hex = None
        self.hash_hex = None
        self.target_shell = '/bin/bash'
        self.rate_limiter = RateLimiter()
        self.sessions = SessionManager()
        self.terminals = TerminalSessionManager()
        self.shares = ShareTokenManager()


class FireSSHServerHandler(BaseHTTPRequestHandler):
    def get_client_ip(self) -> str:
        client_ip = self.client_address[0]
        # Only trust reverse-proxy headers if connection originated from local loopback
        if client_ip in ('127.0.0.1', '::1', 'localhost') or client_ip.startswith('127.'):
            forwarded = self.headers.get('CF-Connecting-IP') or self.headers.get('X-Forwarded-For')
            if forwarded:
                return forwarded.split(',')[0].strip()
        return client_ip

    def get_cookie_token(self) -> str:
        cookie_header = self.headers.get('Cookie', '')
        for part in cookie_header.split(';'):
            part = part.strip()
            if part.startswith('fire_ssh_session='):
                return part.split('=', 1)[1]
        return None

    def get_auth_token(self) -> str:
        token = self.get_cookie_token()
        if token:
            return token
        parsed = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(parsed.query)
        if 'token' in q and q['token']:
            return q['token'][0]
        auth_header = self.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            return auth_header[7:].strip()
        if 'X-Session-Token' in self.headers:
            return self.headers.get('X-Session-Token')
        return None

    def is_authenticated(self) -> bool:
        token = self.get_auth_token()
        if token and self.server.sessions.is_valid(token, self.get_client_ip()):
            return True
        return False

    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/api/download':
            if not self.is_authenticated():
                self.send_error(401, "Unauthorized")
                return
            token = self.get_auth_token()
            query = urllib.parse.parse_qs(parsed.query)
            tab_id = query.get('tab', [None])[0]
            session = self.server.terminals.get(token, tab_id)
            cwd = session.get_cwd() if session else os.environ.get("HOME", "/root")
            file_param = query.get('file', [None])[0] or query.get('path', [None])[0]
            if not file_param:
                self.send_error(400, "Missing file parameter")
                return
            target_path = os.path.realpath(file_param) if os.path.isabs(file_param) else os.path.realpath(os.path.join(cwd, file_param))
            if not os.path.exists(target_path) or not os.path.isfile(target_path):
                self.send_error(404, "File not found or is not a regular file")
                return
            try:
                file_size = os.path.getsize(target_path)
                content_type = mimetypes.guess_type(target_path)[0] or "application/octet-stream"
                filename = os.path.basename(target_path)
                safe_name = urllib.parse.quote(filename)
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(file_size))
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"; filename*=UTF-8\'\'{safe_name}')
                self.end_headers()
            except Exception:
                self.send_error(500, "Error reading file")
            return

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
            origin = self.headers.get('Origin')
            if origin:
                origin_host = urllib.parse.urlparse(origin).netloc.lower().split(':')[0]
                host_header = self.headers.get('X-Forwarded-Host') or self.headers.get('Host', '')
                expected_host = host_header.split(':')[0].lower()
                is_loopback_origin = origin_host in ('localhost', '127.0.0.1')
                is_loopback_host = expected_host in ('localhost', '127.0.0.1', '')
                if not (origin_host == expected_host or (is_loopback_origin and is_loopback_host)):
                    self.send_error(403, "Cross-Origin WebSocket Forbidden")
                    return

            query = urllib.parse.parse_qs(parsed.query)
            token = query.get('token', [None])[0] or self.get_cookie_token()
            tab_id = query.get('tab', [None])[0]
            share_token = query.get('share', [None])[0]

            is_readonly = False
            target_token = token

            if share_token:
                share_info = self.server.shares.validate(share_token)
                if not share_info:
                    self.send_error(403, "Invalid or Expired Share Token")
                    return
                is_readonly = True
                target_token = share_info["session_token"]
            else:
                if not self.server.sessions.is_valid(token, ip):
                    self.send_error(401, "Unauthorized")
                    return

            ws_key = self.headers.get('Sec-WebSocket-Key')
            if not ws_key:
                self.send_error(400, "Bad WebSocket Request")
                return

            self.wfile.write(ws_handshake_response(ws_key))
            self.wfile.flush()
            if is_readonly:
                self.handle_readonly_websocket(target_token, share_token=share_token, tab_id=tab_id)
            else:
                self.handle_websocket(target_token, tab_id=tab_id)
            return

        elif parsed.path == '/api/status':
            query = urllib.parse.parse_qs(parsed.query)
            share_token = query.get('share', [None])[0]
            if share_token:
                share_info = self.server.shares.validate(share_token)
                if share_info:
                    self.send_json({"authenticated": True, "readonly": True, "label": share_info.get("label", "Shared Session")})
                    return
                else:
                    self.send_json({"authenticated": False, "readonly": True, "error": "Expired or invalid share link"}, status=403)
                    return
            auth = self.is_authenticated()
            locked, rem = self.server.rate_limiter.is_locked(ip)
            data = {"authenticated": auth, "locked": locked, "lockout_remaining": rem}
            self.send_json(data)
            return

        elif parsed.path == '/api/share/list':
            if not self.is_authenticated():
                self.send_error(401, "Unauthorized")
                return
            token = self.get_auth_token()
            shares = self.server.shares.list_shares(token)
            self.send_json({"success": True, "shares": shares})
            return

        elif parsed.path == '/api/cwd':
            if not self.is_authenticated():
                self.send_error(401, "Unauthorized")
                return
            token = self.get_auth_token()
            query = urllib.parse.parse_qs(parsed.query)
            tab_id = query.get('tab', [None])[0]
            session = self.server.terminals.get(token, tab_id)
            cwd = session.get_cwd() if session else os.environ.get("HOME", "/root")
            self.send_json({"success": True, "cwd": cwd})
            return

        elif parsed.path == '/api/download':
            if not self.is_authenticated():
                self.send_error(401, "Unauthorized")
                return

            token = self.get_auth_token()
            query = urllib.parse.parse_qs(parsed.query)
            tab_id = query.get('tab', [None])[0]
            session = self.server.terminals.get(token, tab_id)
            cwd = session.get_cwd() if session else os.environ.get("HOME", "/root")

            file_param = query.get('file', [None])[0] or query.get('path', [None])[0]

            if not file_param:
                self.send_json({"success": False, "error": "Missing file parameter"}, status=400)
                return

            target_path = os.path.realpath(file_param) if os.path.isabs(file_param) else os.path.realpath(os.path.join(cwd, file_param))

            if not os.path.exists(target_path):
                self.send_json({"success": False, "error": f"File not found: {file_param}"}, status=404)
                return

            if not os.path.isfile(target_path) or os.path.isdir(target_path):
                self.send_json({"success": False, "error": f"Target is not a regular file: {file_param}. Only regular files can be downloaded."}, status=400)
                return

            try:
                file_size = os.path.getsize(target_path)
                filename = os.path.basename(target_path)
                content_type = mimetypes.guess_type(target_path)[0] or "application/octet-stream"

                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(file_size))
                safe_name = urllib.parse.quote(filename)
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"; filename*=UTF-8\'\'{safe_name}')
                self.end_headers()

                with open(target_path, 'rb') as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            except Exception as e:
                pass
            return

        elif parsed.path == '/health':
            self.send_json({"status": "ok", "service": "fire-ssh"})
            return

        elif parsed.path == '/' or parsed.path == '/index.html':
            query = urllib.parse.parse_qs(parsed.query)
            share_token = query.get('share', [None])[0]
            rendered_html = HTML_TEMPLATE
            if share_token:
                share_info = self.server.shares.validate(share_token)
                if not share_info:
                    self.send_response(403)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    expired_html = """<!DOCTYPE html><html><head><title>Fire PM - Share Expired</title><script src="https://cdn.tailwindcss.com"></script></head><body class="bg-slate-950 text-slate-100 flex items-center justify-center min-h-screen"><div class="bg-slate-900 border border-red-500/40 rounded-2xl p-8 max-w-md text-center shadow-2xl"><div class="text-4xl mb-4">🔒</div><h1 class="text-xl font-bold text-red-400 mb-2">Share Link Expired or Invalid</h1><p class="text-sm text-slate-400 mb-6">This read-only session sharing link has expired or was revoked by the host.</p><a href="/" class="px-4 py-2 bg-orange-600 hover:bg-orange-500 text-white rounded-lg text-sm font-semibold transition">Back to Terminal</a></div></body></html>"""
                    self.wfile.write(expired_html.encode('utf-8'))
                    return
                inject_script = f"<script>window.IS_READONLY = true; window.SHARE_TOKEN = {json.dumps(share_token)}; window.SHARE_LABEL = {json.dumps(share_info.get('label', 'Shared Session'))};</script>"
                rendered_html = rendered_html.replace('</head>', f'{inject_script}\n</head>', 1)

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(rendered_html.encode('utf-8'))
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
                
                proto = self.headers.get('X-Forwarded-Proto', '').lower()
                is_https = proto == 'https' or 'https' in self.headers.get('CF-Visitor', '')
                secure_attr = "; Secure" if is_https else ""
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Set-Cookie", f"fire_ssh_session={token}; Path=/; HttpOnly; SameSite=Lax{secure_attr}; Max-Age={SESSION_EXPIRY_SECONDS}")
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

        elif parsed.path == '/api/upload':
            if not self.is_authenticated():
                self.send_error(401, "Unauthorized")
                return

            token = self.get_auth_token()
            query = urllib.parse.parse_qs(parsed.query)
            tab_id = query.get('tab', [None])[0]
            session = self.server.terminals.get(token, tab_id)
            cwd = session.get_cwd() if session else os.environ.get("HOME", "/root")

            filename = query.get('name', [None])[0] or self.headers.get('X-Filename')
            dest = query.get('dest', [None])[0]
            content_type = self.headers.get('Content-Type', '')
            content_len = int(self.headers.get('Content-Length', 0))

            if content_len > MAX_UPLOAD_BYTES:
                self.send_json({"success": False, "error": f"Upload exceeds maximum allowed size ({MAX_UPLOAD_BYTES // (1024*1024)} MB)"}, status=413)
                return

            target_dir = cwd
            if dest:
                target_dir = os.path.realpath(dest) if os.path.isabs(dest) else os.path.realpath(os.path.join(cwd, dest))

            if not os.path.isdir(target_dir):
                try:
                    os.makedirs(target_dir, exist_ok=True)
                except Exception as e:
                    self.send_json({"success": False, "error": f"Cannot create target directory: {e}"}, status=400)
                    return

            # Support multipart/form-data
            if 'multipart/form-data' in content_type:
                try:
                    import email
                    raw_body = self.rfile.read(content_len)
                    fake_msg = email.message_from_bytes(f"Content-Type: {content_type}\r\n\r\n".encode() + raw_body)
                    saved_files = []
                    for part in fake_msg.get_payload():
                        p_filename = part.get_filename()
                        if p_filename:
                            p_filename = os.path.basename(p_filename).strip()
                            if p_filename:
                                p_path = os.path.join(target_dir, p_filename)
                                p_data = part.get_payload(decode=True)
                                with open(p_path, 'wb') as pf:
                                    pf.write(p_data)
                                saved_files.append({"filename": p_filename, "path": p_path, "bytes": len(p_data)})
                    self.send_json({"success": True, "files": saved_files, "dest": target_dir})
                    return
                except Exception as e:
                    self.send_json({"success": False, "error": f"Multipart upload failed: {e}"}, status=500)
                    return

            # Raw binary stream upload
            if not filename:
                self.send_json({"success": False, "error": "Missing filename parameter (?name=... or X-Filename)"}, status=400)
                return

            filename = os.path.basename(filename).strip()
            if not filename:
                self.send_json({"success": False, "error": "Invalid filename"}, status=400)
                return

            target_path = os.path.join(target_dir, filename)

            try:
                bytes_written = 0
                rem = content_len
                with open(target_path, 'wb') as f:
                    while rem > 0:
                        chunk_size = min(rem, 65536)
                        chunk = self.rfile.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        bytes_written += len(chunk)
                        rem -= len(chunk)

                self.send_json({
                    "success": True,
                    "filename": filename,
                    "path": target_path,
                    "bytes": bytes_written
                })
            except Exception as e:
                self.send_json({"success": False, "error": f"Failed writing file: {e}"}, status=500)
            return

        elif parsed.path == '/api/tab_close':
            if not self.is_authenticated():
                self.send_error(401, "Unauthorized")
                return
            token = self.get_auth_token()
            query = urllib.parse.parse_qs(parsed.query)
            tab_id = query.get('tab', [None])[0]
            if tab_id:
                self.server.terminals.remove(token, tab_id)
            self.send_json({"success": True})
            return

        elif parsed.path == '/api/share/create':
            if not self.is_authenticated():
                self.send_error(401, "Unauthorized")
                return
            token = self.get_auth_token()
            content_len = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_len).decode('utf-8', errors='ignore') if content_len > 0 else '{}'
            data = {}
            try:
                data = json.loads(body)
            except Exception:
                pass
            raw_exp = data.get('expires_in', 3600)
            try:
                expires_in = float(raw_exp) if raw_exp is not None and float(raw_exp) > 0 else None
            except Exception:
                expires_in = 3600.0
            label = str(data.get('label', '')).strip() or "Shared Session"
            share_token = self.server.shares.create_share(token, expires_in_seconds=expires_in, label=label)
            self.send_json({
                "success": True,
                "share_token": share_token,
                "share_url": f"/?share={share_token}"
            })
            return

        elif parsed.path == '/api/share/revoke':
            if not self.is_authenticated():
                self.send_error(401, "Unauthorized")
                return
            token = self.get_auth_token()
            content_len = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_len).decode('utf-8', errors='ignore') if content_len > 0 else '{}'
            data = {}
            try:
                data = json.loads(body)
            except Exception:
                pass
            share_token = data.get('share_token')
            if not share_token:
                self.send_json({"success": False, "error": "Missing share_token"}, status=400)
                return
            info = self.server.shares.validate(share_token)
            if info and info["session_token"] == token:
                self.server.shares.revoke(share_token)
                self.send_json({"success": True})
            else:
                self.send_json({"success": False, "error": "Invalid share token or unauthorized"}, status=403)
            return

        elif parsed.path == '/api/logout':
            token = self.get_auth_token() or self.get_cookie_token()
            if token:
                self.server.shares.revoke_by_session(token)
                self.server.sessions.revoke(token)
                self.server.terminals.remove(token)
            proto = self.headers.get('X-Forwarded-Proto', '').lower()
            is_https = proto == 'https' or 'https' in self.headers.get('CF-Visitor', '')
            secure_attr = "; Secure" if is_https else ""
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", f"fire_ssh_session=; Path=/; HttpOnly; SameSite=Lax{secure_attr}; Max-Age=0")
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

    def handle_websocket(self, token: str, tab_id: str = None):
        """Bridges WebSocket client with a persistent TerminalSession."""
        sock = self.connection
        sock.setblocking(True)

        target_shell = getattr(self.server, 'target_shell', None)
        session = self.server.terminals.get_or_create(token, tab_id, target_shell)
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

    def handle_readonly_websocket(self, token: str, share_token: str, tab_id: str = None):
        """Bridges a read-only viewer WebSocket with a TerminalSession."""
        sock = self.connection
        sock.setblocking(True)

        session = self.server.terminals.get(token, tab_id)
        if not session:
            session = self.server.terminals.get(token, None)
        if not session:
            try:
                sock.close()
            except Exception:
                pass
            return

        self.server.shares.register_socket(share_token, sock)
        session.attach_readonly_socket(sock)

        last_ping_sent = time.time()

        try:
            while session.is_alive() and self.server.shares.validate(share_token):
                rlist, _, _ = select.select([sock], [], [], 5.0)

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
                        if mtype == 'ping':
                            sock.sendall(ws_make_frame(json.dumps({"type": "pong"}), opcode=1))
                        elif mtype == 'latency_ping':
                            ts = msg.get('timestamp', 0)
                            sock.sendall(ws_make_frame(json.dumps({"type": "latency_pong", "timestamp": ts}), opcode=1))
                        # Note: resize, input, signals are strictly ignored for read-only viewers
                    except Exception:
                        pass
                elif opcode == 2:
                    # STRICTLY IGNORED: Binary terminal input rejected for read-only viewers
                    pass

        finally:
            self.server.shares.unregister_socket(share_token, sock)
            session.detach_readonly_socket(sock)
            try:
                sock.close()
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
    server.terminals = TerminalSessionManager()
    server.shares = ShareTokenManager()

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
