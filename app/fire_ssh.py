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
import html
import mimetypes
import urllib.parse
import zipfile
import tempfile
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
            # Allow client roaming across network changes while keeping IP recorded
            if ip and info.get("ip") != ip:
                info["ip"] = ip
            return True

    def revoke(self, token: str):
        with self.lock:
            self.sessions.pop(token, None)


class SecurityEventManager:
    """Maintains an in-memory buffer of recent security events for monitoring and SSE streaming."""
    def __init__(self, max_events: int = 200):
        self.lock = threading.Lock()
        self.max_events = max_events
        self.events = []

    def record_event(self, event_type: str, severity: str, source_ip: str, details: str):
        evt = {
            "id": secrets.token_hex(8),
            "type": event_type,
            "severity": severity,
            "source_ip": source_ip,
            "details": details,
            "timestamp": time.time()
        }
        with self.lock:
            self.events.append(evt)
            if len(self.events) > self.max_events:
                self.events.pop(0)
        return evt

    def get_recent_events(self, limit: int = 50) -> list:
        with self.lock:
            return list(reversed(self.events[-limit:]))


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

    # RFC 6455: Client-to-Server frames must be masked
    if not masked:
        return None, b""

    if payload_len == 126:
        ext = sock.recv(2)
        if len(ext) < 2: return None, b""
        payload_len = struct.unpack(">H", ext)[0]
    elif payload_len == 127:
        ext = sock.recv(8)
        if len(ext) < 8: return None, b""
        payload_len = struct.unpack(">Q", ext)[0]

    MAX_WS_PAYLOAD = 10 * 1024 * 1024
    if payload_len > MAX_WS_PAYLOAD:
        return None, b""

    mask = sock.recv(4)
    if len(mask) < 4: return None, b""

    data = bytearray()
    while len(data) < payload_len:
        chunk = sock.recv(min(8192, payload_len - len(data)))
        if not chunk:
            break
        data.extend(chunk)

    if not data:
        return opcode, b""
    if len(data) < 32:
        unmasked = bytes(b ^ mask[i & 3] for i, b in enumerate(data))
    else:
        m0, m1, m2, m3 = mask[0], mask[1], mask[2], mask[3]
        data[0::4] = bytes(b ^ m0 for b in data[0::4])
        data[1::4] = bytes(b ^ m1 for b in data[1::4])
        data[2::4] = bytes(b ^ m2 for b in data[2::4])
        data[3::4] = bytes(b ^ m3 for b in data[3::4])
        unmasked = bytes(data)
    return opcode, unmasked


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


def resolve_fs_path(base_dir: str, target: str) -> str:
    """Safely resolves an absolute or relative path, expanding ~ and handling path normalization."""
    if not base_dir:
        base_dir = os.environ.get("HOME", "/root")
    if not target or not str(target).strip():
        return os.path.realpath(os.path.expanduser(base_dir))
    target = str(target).strip()
    expanded = os.path.expanduser(target)
    if os.path.isabs(expanded):
        return os.path.realpath(expanded)
    return os.path.realpath(os.path.join(base_dir, expanded))


# ==================== PERSISTENT TERMINAL ENGINE ====================

class TerminalSession:
    """Manages a persistent PTY process that survives network disconnects and page reloads."""
    def __init__(self, session_id: str, shell: str = None):
        self.session_id = session_id
        self.shell = shell or '/bin/bash'
        self.master_fd = None
        self.pid = None
        self.interactive_socks = set()
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

    @property
    def sock(self):
        with self.sock_lock:
            return next(iter(self.interactive_socks), None)

    @sock.setter
    def sock(self, value):
        with self.sock_lock:
            if value is None:
                self.interactive_socks.clear()
            else:
                self.interactive_socks.add(value)

    def start(self):
        master_fd, slave_fd = pty.openpty()
        self.master_fd = master_fd

        winsize = struct.pack("HHHH", self.rows, self.cols, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)

        # Validate and sanitize shell path to prevent command injection
        raw_shell = (self.shell or '/bin/bash').strip()
        allowed_shells = {'/bin/bash', '/usr/bin/bash', '/bin/sh', '/usr/bin/sh', '/bin/dash', '/usr/bin/dash', '/bin/zsh', '/usr/bin/zsh'}
        resolved_shell = os.path.realpath(raw_shell)
        if resolved_shell in allowed_shells and os.path.exists(resolved_shell) and os.access(resolved_shell, os.X_OK):
            shell = resolved_shell
        elif os.path.exists('/bin/bash') and os.access('/bin/bash', os.X_OK):
            shell = '/bin/bash'
        else:
            shell = '/bin/sh'
        self.shell = shell

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
        dead_interactive = []
        for s in list(self.interactive_socks):
            try:
                s.sendall(frame)
            except Exception:
                dead_interactive.append(s)
        for s in dead_interactive:
            self.interactive_socks.discard(s)

        dead_ro = []
        for ro in list(self.readonly_socks):
            try:
                ro.sendall(frame)
            except Exception:
                dead_ro.append(ro)
        for ro in dead_ro:
            self.readonly_socks.discard(ro)

    def send_ws_json(self, data: dict):
        with self.sock_lock:
            payload = json.dumps(data).encode('utf-8')
            frame = ws_make_frame(payload, opcode=1)
            self._broadcast_frame_unlocked(frame)

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
        last_proc_check = 0.0
        while not self.closed:
            try:
                if self.pid:
                    try:
                        pid_res, _ = os.waitpid(self.pid, os.WNOHANG)
                        if pid_res != 0:
                            self.closed = True
                            break
                    except (ChildProcessError, ProcessLookupError):
                        self.closed = True
                        break

                rlist, _, _ = select.select([self.master_fd], [], [], 0.5)
                now = time.time()
                if now - last_proc_check >= 0.5:
                    self._check_fg_process()
                    last_proc_check = now

                if not rlist:
                    continue

                data = os.read(self.master_fd, 16384)
                if not data:
                    self.closed = True
                    break

                # Drain any immediate burst chunks from PTY buffer without re-selecting
                burst_chunks = [data]
                while True:
                    try:
                        extra = os.read(self.master_fd, 65536)
                        if not extra:
                            break
                        burst_chunks.append(extra)
                    except (BlockingIOError, InterruptedError):
                        break

                total_data = b"".join(burst_chunks) if len(burst_chunks) > 1 else data

                with self.buffer_lock:
                    self.output_buffer.extend(total_data)
                    if len(self.output_buffer) > SCROLLBACK_BUFFER_SIZE:
                        self.output_buffer = self.output_buffer[-SCROLLBACK_BUFFER_SIZE:]

                with self.sock_lock:
                    frame = ws_make_frame(total_data, opcode=2)
                    self._broadcast_frame_unlocked(frame)
            except (BlockingIOError, InterruptedError):
                continue
            except Exception:
                break

        self.close()

    def attach_socket(self, sock):
        with self.sock_lock:
            self.interactive_socks.add(sock)
            self.last_seen = time.time()
            with self.buffer_lock:
                if self.output_buffer:
                    try:
                        frame = ws_make_frame(bytes(self.output_buffer), opcode=2)
                        sock.sendall(frame)
                    except Exception:
                        self.interactive_socks.discard(sock)

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
            if sock:
                self.interactive_socks.discard(sock)
            elif sock is None:
                self.interactive_socks.clear()
            self.last_seen = time.time()

    @staticmethod
    def is_terminal_query_response(data: bytes) -> bool:
        """True for auto-generated terminal replies (DA1/DA2, DSR, kitty keyboard, OSC colors) that arrive late and would be echoed as junk at the prompt."""
        if not data or data[:1] != b'\x1b':
            return False
        if data[:3] in (b'\x1b[>', b'\x1b[?') and data.endswith((b'c', b'u')):
            return True
        if data in (b'\x1b[0n', b'\x1b[3n'):
            return True
        return data.startswith((b'\x1b]10;', b'\x1b]11;', b'\x1b]12;', b'\x1b]4;'))

    def write_input(self, data: bytes):
        if self.is_terminal_query_response(data):
            return
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
        except (ChildProcessError, ProcessLookupError):
            return False
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
            exit_frame = ws_make_frame(struct.pack("!H", 1000) + b"Process exited", opcode=8)
            for s in list(self.interactive_socks):
                try:
                    s.sendall(exit_frame)
                    s.close()
                except Exception:
                    pass
            self.interactive_socks.clear()
            for ro in list(self.readonly_socks):
                try:
                    ro.sendall(exit_frame)
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

    def _make_key(self, token: str = None, tab_id: str = None) -> str:
        if tab_id:
            if ":" in tab_id:
                return tab_id.split(":")[-1]
            return tab_id
        return "tab-1"

    def get(self, token: str = None, tab_id: str = None):
        key = self._make_key(token, tab_id)
        with self.lock:
            sess = self.sessions.get(key)
            if sess and sess.is_alive():
                return sess
            # Fallback to any alive session if specific tab wasn't found or has terminated
            for s in self.sessions.values():
                if s.is_alive():
                    return s
            return None

    def get_or_create(self, token: str = None, tab_id: str = None, shell: str = None) -> TerminalSession:
        key = self._make_key(token, tab_id)
        created_new = False
        with self.lock:
            session = self.sessions.get(key)
            if session and session.is_alive():
                return session
            if session:
                session.close()
            session = TerminalSession(key, shell)
            self.sessions[key] = session
            created_new = True

        if created_new:
            self.broadcast_all({"type": "tabs_changed", "created": key})
        return session

    def remove(self, token: str = None, tab_id: str = None):
        removed_key = None
        with self.lock:
            if tab_id:
                key = self._make_key(token, tab_id)
                session = self.sessions.pop(key, None)
                if not session and tab_id == "tab-1":
                    session = self.sessions.pop(token, None)
                if session:
                    session.close()
                    removed_key = key
            else:
                for k in list(self.sessions.keys()):
                    sess = self.sessions.pop(k, None)
                    if sess:
                        sess.close()
                removed_key = "all"

        if removed_key:
            self.broadcast_all({"type": "tabs_changed", "removed": removed_key})

    def list_all(self) -> list:
        with self.lock:
            return [s for s in self.sessions.values() if s.is_alive()]

    def list_tabs(self, token: str = None) -> list:
        with self.lock:
            results = []
            for tab_id, sess in self.sessions.items():
                if not sess.is_alive():
                    continue
                clean_id = tab_id.split(":")[-1] if ":" in tab_id else tab_id
                results.append({
                    "id": clean_id,
                    "title": sess.active_cmd_name or sess.last_reported_comm or "bash",
                    "cwd": sess.get_cwd()
                })

            def tab_sort_key(item):
                tid = item.get("id", "")
                if tid.startswith("tab-"):
                    try:
                        return (0, int(tid[4:]))
                    except ValueError:
                        pass
                return (1, tid)

            results.sort(key=tab_sort_key)
            return results

    def broadcast_all(self, data: dict):
        try:
            payload = json.dumps(data).encode("utf-8")
            frame = ws_make_frame(payload, opcode=1)
            with self.lock:
                for sess in self.sessions.values():
                    sess._broadcast_frame_unlocked(frame)
        except Exception:
            pass

    def migrate_token(self, old_token: str, new_token: str):
        pass

    def _reaper_loop(self):
        while True:
            time.sleep(5)
            while True:
                try:
                    rpid, _ = os.waitpid(-1, os.WNOHANG)
                    if rpid <= 0:
                        break
                except (ChildProcessError, OSError):
                    break

            now = time.time()
            with self.lock:
                to_delete = []
                for token, session in self.sessions.items():
                    if not session.is_alive():
                        to_delete.append(token)
                    elif len(session.interactive_socks) == 0 and len(session.readonly_socks) == 0 and (now - session.last_seen > DETACHED_SESSION_TTL):
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
  <script src="https://cdn.jsdelivr.net/npm/xterm-addon-webgl@0.16.0/lib/xterm-addon-webgl.js"></script>
  <style>
    .xterm { height: 100%; padding: 4px; }
    .xterm-viewport { background-color: #020617 !important; -webkit-overflow-scrolling: touch; }
    .xterm-screen { touch-action: pan-y; }
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #020617; }
    ::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #334155; }
    .scrollbar-none::-webkit-scrollbar { display: none; }
    .scrollbar-none { -ms-overflow-style: none; scrollbar-width: none; }
    .mobile-key {
      -webkit-touch-callout: none;
      -webkit-user-select: none;
      user-select: none;
      touch-action: pan-x;
    }
    #mobile-keys-list {
      -webkit-overflow-scrolling: touch;
      touch-action: pan-x;
      scroll-behavior: smooth;
    }
    /* Drag and drop tab reordering styles */
    .tab-item {
      cursor: pointer;
      user-select: none;
      -webkit-user-select: none;
      transition: background-color 0.15s ease, border-color 0.15s ease, opacity 0.15s ease;
    }
    .tab-item.tab-dragging {
      opacity: 0.45;
      transform: scale(0.97);
    }
    .tab-item.tab-drag-over-left {
      border-left: 2px solid #f97316 !important;
    }
    .tab-item.tab-drag-over-right {
      border-right: 2px solid #f97316 !important;
    }
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
          <p id="login-card-subtitle" class="text-xs text-slate-400">Persistent Remote Terminal</p>
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
    <header class="h-12 bg-slate-900 border-b border-slate-800 px-2 sm:px-4 flex items-center justify-between select-none">
      <div class="flex items-center space-x-1.5 sm:space-x-3 min-w-0">
        <span class="text-lg shrink-0">🔥</span>
        <button id="brand-header-btn" onclick="promptUpdateTitle()" class="flex items-center gap-1 group/title text-left bg-transparent border-0 p-0 cursor-pointer min-w-0" title="Click to rename session title">
          <span id="brand-header-title" class="text-xs sm:text-sm font-semibold text-white truncate max-w-[140px] sm:max-w-xs group-hover/title:text-orange-300 transition">Fire PM</span>
          <svg class="w-3 h-3 text-slate-400 opacity-0 group-hover/title:opacity-100 transition shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
        </button>
        <span id="conn-badge" class="text-[10px] sm:text-xs px-1.5 sm:px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 font-mono flex items-center gap-1 shrink-0">
          <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
          Connected
        </span>
      </div>

      <!-- Quick Control Action Toolbar -->
      <div class="flex items-center space-x-1 sm:space-x-2 shrink-0">
        <button onclick="sendInterrupt()" title="Break / Interrupt (Ctrl+C)" class="px-2 sm:px-2.5 py-1 text-xs bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/30 rounded-lg transition font-mono font-bold flex items-center gap-1">
          <span>⎋</span>
          <span>Ctrl+C</span>
        </button>
        <button onclick="sendSuspend()" title="Suspend Foreground Job (Ctrl+Z)" class="hidden sm:inline-flex px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono">^Z</button>
        <button onclick="sendEOF()" title="EOF / Exit (Ctrl+D)" class="hidden sm:inline-flex px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono">^D</button>
        <button onclick="sendCtrlW()" title="Send Ctrl+W (Where Is in nano / erase word in bash)" class="hidden sm:inline-flex px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono">^W</button>
        <button onclick="clearTerm()" title="Clear Terminal Output" class="hidden sm:inline-flex px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition">Clear</button>
        <button onclick="termFit()" title="Fit Terminal Window" class="hidden sm:inline-flex px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition">⛶ Fit</button>
        <button onclick="toggleFullscreen()" title="Fullscreen mode (locks Ctrl+W from closing tab)" class="hidden sm:inline-flex px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition">⛶ Fullscreen</button>
        <div class="relative hidden sm:inline-block">
          <button id="split-btn" onclick="toggleSplitMenu()" title="Split View: Dual Interactive Tabs (Alt+V / Alt+H)" class="px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono flex items-center gap-1">
            <span id="split-icon">◫</span>
            <span id="split-label">Split</span>
          </button>
          <div id="split-menu" class="hidden absolute left-0 top-full mt-1.5 w-44 bg-slate-900 border border-slate-700/80 rounded-xl shadow-2xl p-1.5 z-50 text-xs font-sans space-y-1">
            <button onclick="setSplitMode('none'); closeSplitMenu();" class="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-slate-800 text-slate-200 flex items-center justify-between">
              <span>⬛ Single Tab</span>
              <span class="text-[10px] text-slate-500 font-mono">Alt+S</span>
            </button>
            <button onclick="setSplitMode('vertical'); closeSplitMenu();" class="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-slate-800 text-slate-200 flex items-center justify-between">
              <span>◫ Side-by-Side</span>
              <span class="text-[10px] text-slate-500 font-mono">Alt+V</span>
            </button>
            <button onclick="setSplitMode('horizontal'); closeSplitMenu();" class="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-slate-800 text-slate-200 flex items-center justify-between">
              <span>⬒ Top & Bottom</span>
              <span class="text-[10px] text-slate-500 font-mono">Alt+H</span>
            </button>
            <button onclick="setSplitMode('triple-left'); closeSplitMenu();" class="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-slate-800 text-slate-200 flex items-center justify-between">
              <span>⚿ 1 Left / 2 Right (3 Panes)</span>
              <span class="text-[10px] text-slate-500 font-mono">Alt+3</span>
            </button>
            <button onclick="setSplitMode('triple-col'); closeSplitMenu();" class="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-slate-800 text-slate-200 flex items-center justify-between">
              <span>||| 3 Columns</span>
              <span class="text-[10px] text-slate-500 font-mono">Alt+C</span>
            </button>
            <button onclick="setSplitMode('grid'); closeSplitMenu();" class="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-slate-800 text-slate-200 flex items-center justify-between">
              <span>⊞ 2x2 Quad Grid (4 Panes)</span>
              <span class="text-[10px] text-slate-500 font-mono">Alt+G</span>
            </button>
          </div>
        </div>
        <button id="record-btn" onclick="toggleSessionRecording()" title="Record session to Asciinema (.cast) file" class="hidden sm:inline-flex px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono items-center gap-1">
          <span id="record-dot" class="w-2 h-2 rounded-full bg-rose-500"></span>
          <span id="record-text">Rec</span>
        </button>
        <button onclick="copySelectionToClipboard(true)" title="Copy Selected Text (Ctrl+C / Cmd+C)" class="hidden sm:inline-flex px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono flex items-center gap-1">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-slate-400">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
          </svg>
          <span>Copy</span>
        </button>
        <button onclick="pasteFromClipboard(true, true)" title="Paste from Clipboard (Ctrl+V / Cmd+V)" class="hidden sm:inline-flex px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono flex items-center gap-1">
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
        <button id="share-btn" onclick="openShareModal()" title="Share Live Terminal (Read-Only)" class="hidden sm:inline-flex px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-slate-400">
            <circle cx="18" cy="5" r="3"></circle>
            <circle cx="6" cy="12" r="3"></circle>
            <circle cx="18" cy="19" r="3"></circle>
            <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"></line>
            <line x1="15.41" y1="6.51" x2="8.59" y2="10.49"></line>
          </svg>
          <span class="hidden md:inline">Share</span>
        </button>
        <button id="upload-btn" onclick="triggerFileInput()" title="Upload File to Terminal Directory" class="hidden sm:inline-flex px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-slate-400">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="17 8 12 3 7 8"/>
            <line x1="12" y1="3" x2="12" y2="15"/>
          </svg>
          <span class="hidden md:inline">Upload</span>
        </button>
        <input id="file-upload-input" type="file" multiple class="hidden" onchange="handleFileSelect(event)">
        <button id="download-btn" onclick="openDownloadModal()" title="Download File from Remote Server" class="hidden sm:inline-flex px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-slate-400">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          <span class="hidden md:inline">Download</span>
        </button>
        <button id="logout-btn" onclick="handleLogout()" class="hidden sm:inline-flex px-2.5 py-1 text-xs bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 rounded-lg transition">Disconnect</button>

        <!-- Mobile Actions Menu Button -->
        <div class="relative sm:hidden">
          <button id="mobile-actions-btn" onclick="toggleMobileActionsMenu()" title="Actions Menu" class="px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 active:bg-slate-600 text-slate-200 border border-slate-700 rounded-lg transition font-mono flex items-center gap-1">
            <span>⚙️</span>
            <span>Menu</span>
          </button>
          <div id="mobile-actions-menu" class="hidden absolute right-0 top-full mt-1.5 w-56 bg-slate-900/98 backdrop-blur-md border border-slate-700/90 rounded-xl shadow-2xl shadow-black/80 p-2 z-50 text-xs font-sans space-y-1">
            <div class="px-2 py-1 text-[10px] font-semibold text-slate-400 uppercase tracking-wider border-b border-slate-800 flex items-center justify-between">
              <span>Terminal Actions</span>
              <span class="text-slate-500 font-mono">Mobile</span>
            </div>
            
            <button onclick="copySelectionToClipboard(true); closeMobileActionsMenu()" class="w-full px-2.5 py-1.5 text-left text-slate-200 hover:bg-slate-800 rounded-lg flex items-center gap-2 transition">
              <span>📋</span> <span>Copy Selection</span>
            </button>
            <button onclick="pasteFromClipboard(true, true); closeMobileActionsMenu()" class="w-full px-2.5 py-1.5 text-left text-slate-200 hover:bg-slate-800 rounded-lg flex items-center gap-2 transition">
              <span>📥</span> <span>Paste Clipboard</span>
            </button>
            <button onclick="clearTerm(); closeMobileActionsMenu()" class="w-full px-2.5 py-1.5 text-left text-slate-200 hover:bg-slate-800 rounded-lg flex items-center gap-2 transition">
              <span>🧹</span> <span>Clear Terminal</span>
            </button>
            <button onclick="termFit(); closeMobileActionsMenu()" class="w-full px-2.5 py-1.5 text-left text-slate-200 hover:bg-slate-800 rounded-lg flex items-center gap-2 transition">
              <span>⛶</span> <span>Fit Window</span>
            </button>

            <div class="flex items-center justify-between px-2.5 py-1.5 text-slate-300 border-t border-slate-800">
              <span class="flex items-center gap-1.5"><span>🔤</span> Font Size</span>
              <div class="flex items-center space-x-1">
                <button onclick="adjustFontSize(-1)" class="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded border border-slate-700 font-mono font-bold">A-</button>
                <button onclick="adjustFontSize(1)" class="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded border border-slate-700 font-mono font-bold">A+</button>
              </div>
            </div>

            <button onclick="toggleMobileBarVisibility(); closeMobileActionsMenu()" class="w-full px-2.5 py-1.5 text-left text-slate-200 hover:bg-slate-800 rounded-lg flex items-center justify-between transition border-t border-slate-800">
              <span class="flex items-center gap-2"><span>⌨️</span> Keypad Bar</span>
              <span id="mobile-bar-status-text" class="text-[10px] font-mono text-emerald-400">Active</span>
            </button>

            <div class="border-t border-slate-800 pt-1">
              <div class="flex items-center justify-between px-2.5 py-1.5 text-slate-300">
                <span class="flex items-center gap-1.5"><span>📑</span> Move Tab</span>
                <div class="flex items-center space-x-1.5">
                  <button onclick="if(activeTabId) moveTab(activeTabId, -1)" class="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded border border-slate-700 font-mono text-[11px]" title="Move Tab Left">◀ Left</button>
                  <button onclick="if(activeTabId) moveTab(activeTabId, 1)" class="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded border border-slate-700 font-mono text-[11px]" title="Move Tab Right">Right ▶</button>
                </div>
              </div>
              <button onclick="promptUpdateTitle(); closeMobileActionsMenu()" class="w-full px-2.5 py-1.5 text-left text-slate-200 hover:bg-slate-800 rounded-lg flex items-center gap-2 transition">
                <span>🏷️</span> <span>Rename Session</span>
              </button>
              <button onclick="promptRenameTab(activeTabId); closeMobileActionsMenu()" class="w-full px-2.5 py-1.5 text-left text-slate-200 hover:bg-slate-800 rounded-lg flex items-center gap-2 transition">
                <span>✏️</span> <span>Rename Active Tab</span>
              </button>
              <button onclick="openShareModal(); closeMobileActionsMenu()" class="w-full px-2.5 py-1.5 text-left text-slate-200 hover:bg-slate-800 rounded-lg flex items-center gap-2 transition">
                <span>🔗</span> <span>Share Session</span>
              </button>
              <button onclick="triggerFileInput(); closeMobileActionsMenu()" class="w-full px-2.5 py-1.5 text-left text-slate-200 hover:bg-slate-800 rounded-lg flex items-center gap-2 transition">
                <span>⬆️</span> <span>Upload File</span>
              </button>
              <button onclick="openDownloadModal(); closeMobileActionsMenu()" class="w-full px-2.5 py-1.5 text-left text-slate-200 hover:bg-slate-800 rounded-lg flex items-center gap-2 transition">
                <span>⬇️</span> <span>Download File</span>
              </button>
            </div>

            <div class="border-t border-slate-800 pt-1">
              <button onclick="handleLogout()" class="w-full px-2.5 py-1.5 text-left text-rose-400 hover:bg-rose-500/10 rounded-lg flex items-center gap-2 transition">
                <span>🚪</span> <span>Disconnect</span>
              </button>
            </div>
          </div>
        </div>
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

    <!-- MOBILE ACCESSORY KEYPAD BAR -->
    <div id="mobile-accessory-bar" class="hidden w-full bg-slate-900 border-t border-slate-800 select-none z-30 shrink-0 transition-all duration-150">
      <div class="flex items-center justify-between px-1.5 py-1 bg-slate-950/80 border-b border-slate-800/80">
        <div id="mobile-keys-list" class="flex items-center space-x-1 overflow-x-auto scrollbar-none py-0.5 touch-pan-x flex-1 scroll-smooth" ontouchmove="handleMobileKeyTouchMove(event)" ontouchcancel="handleMobileKeyTouchCancel(event)">
          <!-- Essential terminal keys -->
          <button type="button" ontouchstart="handleMobileKeyTouchStart(event, 'esc')" ontouchend="handleMobileKeyTouchEnd(event, 'esc')" onclick="handleMobileKeyClick('esc')" class="mobile-key px-2 py-1 text-xs font-mono font-bold bg-slate-800 active:bg-orange-600 text-slate-200 active:text-white rounded-md border border-slate-700 shadow-sm shrink-0 transition select-none">ESC</button>
          <button type="button" ontouchstart="handleMobileKeyTouchStart(event, 'tab')" ontouchend="handleMobileKeyTouchEnd(event, 'tab')" onclick="handleMobileKeyClick('tab')" class="mobile-key px-2 py-1 text-xs font-mono font-bold bg-slate-800 active:bg-orange-600 text-slate-200 active:text-white rounded-md border border-slate-700 shadow-sm shrink-0 transition select-none">TAB</button>
          <button type="button" id="mobile-key-ctrl" ontouchstart="handleMobileKeyTouchStart(event, 'ctrl')" ontouchend="handleMobileKeyTouchEnd(event, 'ctrl')" onclick="handleMobileKeyClick('ctrl')" class="mobile-key px-2 py-1 text-xs font-mono font-bold bg-slate-800 text-slate-200 rounded-md border border-slate-700 shadow-sm shrink-0 transition select-none">CTRL</button>
          <button type="button" id="mobile-key-alt" ontouchstart="handleMobileKeyTouchStart(event, 'alt')" ontouchend="handleMobileKeyTouchEnd(event, 'alt')" onclick="handleMobileKeyClick('alt')" class="mobile-key px-2 py-1 text-xs font-mono font-bold bg-slate-800 text-slate-200 rounded-md border border-slate-700 shadow-sm shrink-0 transition select-none">ALT</button>
          <button type="button" id="mobile-key-shift" ontouchstart="handleMobileKeyTouchStart(event, 'shift')" ontouchend="handleMobileKeyTouchEnd(event, 'shift')" onclick="handleMobileKeyClick('shift')" class="mobile-key px-2 py-1 text-xs font-mono font-bold bg-slate-800 text-slate-200 rounded-md border border-slate-700 shadow-sm shrink-0 transition select-none">SHIFT</button>
          <button type="button" ontouchstart="handleMobileKeyTouchStart(event, 'enter')" ontouchend="handleMobileKeyTouchEnd(event, 'enter')" onclick="handleMobileKeyClick('enter')" class="mobile-key px-2 py-1 text-xs font-mono font-bold bg-slate-800 active:bg-orange-600 text-slate-200 active:text-white rounded-md border border-slate-700 shadow-sm shrink-0 select-none" title="Enter / Return">RET</button>
          
          <div class="h-4 w-[1px] bg-slate-700/80 shrink-0 mx-0.5"></div>

          <!-- Arrows -->
          <button type="button" ontouchstart="handleMobileKeyTouchStart(event, 'up')" ontouchend="handleMobileKeyTouchEnd(event, 'up')" onmousedown="handleMobileKeyMouseDown(event, 'up')" onmouseup="handleMobileKeyMouseUp(event, 'up')" onmouseleave="handleMobileKeyMouseLeave(event)" onclick="handleMobileKeyClick('up')" title="Up Arrow (Previous Command)" class="mobile-key px-2 py-1 text-xs font-mono font-bold bg-slate-800 active:bg-orange-600 text-slate-200 active:text-white rounded-md border border-slate-700 shadow-sm shrink-0 transition select-none">▲</button>
          <button type="button" ontouchstart="handleMobileKeyTouchStart(event, 'down')" ontouchend="handleMobileKeyTouchEnd(event, 'down')" onmousedown="handleMobileKeyMouseDown(event, 'down')" onmouseup="handleMobileKeyMouseUp(event, 'down')" onmouseleave="handleMobileKeyMouseLeave(event)" onclick="handleMobileKeyClick('down')" title="Down Arrow (Next Command)" class="mobile-key px-2 py-1 text-xs font-mono font-bold bg-slate-800 active:bg-orange-600 text-slate-200 active:text-white rounded-md border border-slate-700 shadow-sm shrink-0 transition select-none">▼</button>
          <button type="button" ontouchstart="handleMobileKeyTouchStart(event, 'left')" ontouchend="handleMobileKeyTouchEnd(event, 'left')" onmousedown="handleMobileKeyMouseDown(event, 'left')" onmouseup="handleMobileKeyMouseUp(event, 'left')" onmouseleave="handleMobileKeyMouseLeave(event)" onclick="handleMobileKeyClick('left')" title="Left Arrow" class="mobile-key px-2 py-1 text-xs font-mono font-bold bg-slate-800 active:bg-orange-600 text-slate-200 active:text-white rounded-md border border-slate-700 shadow-sm shrink-0 transition select-none">◀</button>
          <button type="button" ontouchstart="handleMobileKeyTouchStart(event, 'right')" ontouchend="handleMobileKeyTouchEnd(event, 'right')" onmousedown="handleMobileKeyMouseDown(event, 'right')" onmouseup="handleMobileKeyMouseUp(event, 'right')" onmouseleave="handleMobileKeyMouseLeave(event)" onclick="handleMobileKeyClick('right')" title="Right Arrow" class="mobile-key px-2 py-1 text-xs font-mono font-bold bg-slate-800 active:bg-orange-600 text-slate-200 active:text-white rounded-md border border-slate-700 shadow-sm shrink-0 transition select-none">▶</button>

          <div class="h-4 w-[1px] bg-slate-700/80 shrink-0 mx-0.5"></div>

          <!-- Shell Symbols -->
          <button type="button" ontouchstart="handleMobileKeyTouchStart(event, 'char', '|')" ontouchend="handleMobileKeyTouchEnd(event, 'char', '|')" onclick="handleMobileKeyClick('char', '|')" class="mobile-key px-2 py-1 text-xs font-mono bg-slate-800/90 active:bg-orange-600 text-slate-300 active:text-white rounded-md border border-slate-700/80 shadow-sm shrink-0 select-none">|</button>
          <button type="button" ontouchstart="handleMobileKeyTouchStart(event, 'char', '~')" ontouchend="handleMobileKeyTouchEnd(event, 'char', '~')" onclick="handleMobileKeyClick('char', '~')" class="mobile-key px-2 py-1 text-xs font-mono bg-slate-800/90 active:bg-orange-600 text-slate-300 active:text-white rounded-md border border-slate-700/80 shadow-sm shrink-0 select-none">~</button>
          <button type="button" ontouchstart="handleMobileKeyTouchStart(event, 'char', '/')" ontouchend="handleMobileKeyTouchEnd(event, 'char', '/')" onclick="handleMobileKeyClick('char', '/')" class="mobile-key px-2 py-1 text-xs font-mono bg-slate-800/90 active:bg-orange-600 text-slate-300 active:text-white rounded-md border border-slate-700/80 shadow-sm shrink-0 select-none">/</button>
          <button type="button" ontouchstart="handleMobileKeyTouchStart(event, 'char', '-')" ontouchend="handleMobileKeyTouchEnd(event, 'char', '-')" onclick="handleMobileKeyClick('char', '-')" class="mobile-key px-2 py-1 text-xs font-mono bg-slate-800/90 active:bg-orange-600 text-slate-300 active:text-white rounded-md border border-slate-700/80 shadow-sm shrink-0 select-none">-</button>
          <button type="button" ontouchstart="handleMobileKeyTouchStart(event, 'char', '_')" ontouchend="handleMobileKeyTouchEnd(event, 'char', '_')" onclick="handleMobileKeyClick('char', '_')" class="mobile-key px-2 py-1 text-xs font-mono bg-slate-800/90 active:bg-orange-600 text-slate-300 active:text-white rounded-md border border-slate-700/80 shadow-sm shrink-0 select-none">_</button>
          <button type="button" ontouchstart="handleMobileKeyTouchStart(event, 'char', '$')" ontouchend="handleMobileKeyTouchEnd(event, 'char', '$')" onclick="handleMobileKeyClick('char', '$')" class="mobile-key px-2 py-1 text-xs font-mono bg-slate-800/90 active:bg-orange-600 text-slate-300 active:text-white rounded-md border border-slate-700/80 shadow-sm shrink-0 select-none">$</button>

          <div class="h-4 w-[1px] bg-slate-700/80 shrink-0 mx-0.5"></div>

          <!-- Fast Signals -->
          <button type="button" ontouchstart="handleMobileKeyTouchStart(event, 'sigint')" ontouchend="handleMobileKeyTouchEnd(event, 'sigint')" onclick="handleMobileKeyClick('sigint')" class="mobile-key px-2 py-1 text-xs font-mono font-bold bg-rose-500/20 active:bg-rose-600 text-rose-300 active:text-white rounded-md border border-rose-500/30 shadow-sm shrink-0 select-none">^C</button>
          <button type="button" ontouchstart="handleMobileKeyTouchStart(event, 'eof')" ontouchend="handleMobileKeyTouchEnd(event, 'eof')" onclick="handleMobileKeyClick('eof')" class="mobile-key px-2 py-1 text-xs font-mono font-bold bg-slate-800/90 active:bg-orange-600 text-slate-300 active:text-white rounded-md border border-slate-700/80 shadow-sm shrink-0 select-none">^D</button>
          <button type="button" ontouchstart="handleMobileKeyTouchStart(event, 'clear')" ontouchend="handleMobileKeyTouchEnd(event, 'clear')" onclick="handleMobileKeyClick('clear')" class="mobile-key px-2 py-1 text-xs font-mono font-bold bg-slate-800/90 active:bg-orange-600 text-slate-300 active:text-white rounded-md border border-slate-700/80 shadow-sm shrink-0 select-none">^L</button>
        </div>

        <!-- Utility toggles with scroll buttons -->
        <div class="flex items-center space-x-1 pl-1 shrink-0">
          <button type="button" onclick="scrollMobileKeys(-120)" title="Scroll Left" class="px-1.5 py-1 text-xs bg-slate-800 active:bg-slate-700 text-slate-400 hover:text-white rounded-md border border-slate-700 shrink-0 select-none font-bold">‹</button>
          <button type="button" onclick="scrollMobileKeys(120)" title="Scroll Right" class="px-1.5 py-1 text-xs bg-slate-800 active:bg-slate-700 text-slate-400 hover:text-white rounded-md border border-slate-700 shrink-0 select-none font-bold">›</button>
          <button type="button" ontouchstart="handleMobileKeyTouchStart(event, 'toggle-kbd')" ontouchend="handleMobileKeyTouchEnd(event, 'toggle-kbd')" onclick="handleMobileKeyClick('toggle-kbd')" title="Toggle Keyboard" class="px-2 py-1 text-xs bg-slate-800 active:bg-slate-700 text-slate-300 hover:text-white rounded-md border border-slate-700 shrink-0 select-none">⌨️</button>
          <button type="button" ontouchstart="handleMobileKeyTouchStart(event, 'collapse-bar')" ontouchend="handleMobileKeyTouchEnd(event, 'collapse-bar')" onclick="handleMobileKeyClick('collapse-bar')" id="mobile-collapse-btn" title="Collapse / Expand Key Bar" class="px-1.5 py-1 text-xs bg-slate-800 active:bg-slate-700 text-slate-400 hover:text-white rounded-md border border-slate-700 shrink-0 select-none font-bold">⌄</button>
        </div>
      </div>
    </div>

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

    <!-- Download Modal Dialog with Autocomplete -->
    <div id="download-modal" class="hidden fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div class="bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl p-5 w-full max-w-lg text-left font-sans">
        <div class="flex items-center justify-between mb-3 pb-2 border-b border-slate-800">
          <div class="flex items-center gap-2">
            <span class="text-base">📥</span>
            <span class="font-semibold text-sm text-white">Download Remote File</span>
          </div>
          <button type="button" onclick="closeDownloadModal()" class="text-slate-400 hover:text-slate-200 text-sm p-1">✕</button>
        </div>
        <form onsubmit="handleDownloadSubmit(event)" class="space-y-3.5">
          <div class="relative">
            <label class="block text-xs font-medium text-slate-300 mb-1">File Path to Download</label>
            <div class="text-[11px] text-slate-400 mb-1.5 font-mono truncate">
              Working directory: <span id="download-cwd-hint" class="text-orange-300">/root</span>
            </div>
            <div class="relative">
              <input type="text" id="download-path-input" required autocomplete="off" spellcheck="false"
                     placeholder="Type or select a file/directory..."
                     class="w-full bg-slate-950 border border-slate-700 rounded-xl px-3.5 py-2.5 text-xs text-white font-mono placeholder:text-slate-600 focus:outline-none focus:border-orange-500 focus:ring-1 focus:ring-orange-500 pr-8">
              <div id="download-spinner" class="hidden absolute right-2.5 top-2.5 text-slate-400 animate-spin text-xs">⟳</div>
            </div>
            <!-- Download Autocomplete Dropdown -->
            <div id="download-suggestions" class="hidden absolute left-0 right-0 top-full mt-1.5 z-50 bg-slate-950/95 border border-slate-700 rounded-xl shadow-2xl max-h-56 overflow-y-auto font-mono text-xs backdrop-blur-sm divide-y divide-slate-800/60">
            </div>
            <p class="text-[10px] text-slate-500 mt-1 flex items-center justify-between">
              <span>Use <kbd class="px-1 py-0.5 bg-slate-800 rounded text-slate-300">Tab</kbd> or <kbd class="px-1 py-0.5 bg-slate-800 rounded text-slate-300">↑↓</kbd> to complete suggestions.</span>
              <span id="download-count-badge" class="text-slate-400"></span>
            </p>
          </div>

          <!-- Download Folder Information Hint -->
          <div class="pt-0.5 pb-0.5">
            <div class="flex items-center gap-2 p-2.5 bg-slate-950/60 border border-slate-800 rounded-xl text-slate-400 text-xs">
              <span class="text-sm">📦</span>
              <span class="text-[11px] leading-tight">Folders are automatically packaged as <code class="text-orange-300 font-mono">.zip</code> archives. Files are downloaded directly.</span>
            </div>
          </div>

          <!-- Error Alert Banner -->
          <div id="download-error-banner" class="hidden p-2.5 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-xs flex items-start gap-2">
            <span class="shrink-0 text-sm">⚠️</span>
            <span id="download-error-msg" class="flex-1"></span>
          </div>

          <div class="flex items-center justify-end gap-2 pt-1">
            <button type="button" onclick="closeDownloadModal()" class="px-3 py-1.5 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl transition">Cancel</button>
            <button type="submit" id="download-submit-btn" class="px-3.5 py-1.5 text-xs bg-orange-500 hover:bg-orange-600 text-white font-semibold rounded-xl transition flex items-center gap-1.5 shadow-lg shadow-orange-500/20">
              <span id="download-submit-label">Download</span>
              <span class="text-[10px]">↓</span>
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Upload Modal Dialog with Destination Autocomplete -->
    <div id="upload-modal" class="hidden fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div class="bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl p-5 w-full max-w-lg text-left font-sans">
        <div class="flex items-center justify-between mb-3 pb-2 border-b border-slate-800">
          <div class="flex items-center gap-2">
            <span class="text-base">📤</span>
            <div>
              <span class="font-semibold text-sm text-white block">Upload Files</span>
              <span class="text-[11px] text-slate-400">Choose destination directory and files to upload</span>
            </div>
          </div>
          <button type="button" onclick="closeUploadModal()" class="text-slate-400 hover:text-slate-200 text-sm p-1">✕</button>
        </div>
        <form onsubmit="handleUploadSubmit(event)" class="space-y-3.5">
          <!-- Destination Directory Field -->
          <div class="relative">
            <label class="block text-xs font-medium text-slate-300 mb-1">Destination Directory</label>
            <div class="relative">
              <input type="text" id="upload-dest-input" required autocomplete="off" spellcheck="false"
                     placeholder="/root or relative path..."
                     class="w-full bg-slate-950 border border-slate-700 rounded-xl px-3.5 py-2.5 text-xs text-white font-mono placeholder:text-slate-600 focus:outline-none focus:border-orange-500 focus:ring-1 focus:ring-orange-500 pr-8">
              <div id="upload-dest-spinner" class="hidden absolute right-2.5 top-2.5 text-slate-400 animate-spin text-xs">⟳</div>
            </div>
            <!-- Upload Destination Dropdown -->
            <div id="upload-dest-suggestions" class="hidden absolute left-0 right-0 top-full mt-1.5 z-50 bg-slate-950/95 border border-slate-700 rounded-xl shadow-2xl max-h-52 overflow-y-auto font-mono text-xs backdrop-blur-sm divide-y divide-slate-800/60">
            </div>
            <p class="text-[10px] text-slate-500 mt-1">Files will be saved into this directory on the remote server.</p>
          </div>

          <!-- Selected Files Display / File Picker -->
          <div>
            <div class="flex items-center justify-between mb-1">
              <label class="block text-xs font-medium text-slate-300">Files to Upload</label>
              <button type="button" onclick="document.getElementById('upload-modal-file-input').click()" class="text-[11px] text-orange-400 hover:text-orange-300 transition">
                + Select More
              </button>
            </div>
            <input id="upload-modal-file-input" type="file" multiple class="hidden" onchange="handleModalFileSelect(event)">
            <div id="upload-files-list" class="bg-slate-950 border border-slate-800 rounded-xl p-2.5 max-h-36 overflow-y-auto space-y-1 text-xs font-mono">
              <div class="text-slate-500 text-[11px] text-center py-3">No files selected. Drag & drop files here or click "+ Select More".</div>
            </div>
          </div>

          <div class="flex items-center justify-end gap-2 pt-2">
            <button type="button" onclick="closeUploadModal()" class="px-3 py-1.5 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl transition">Cancel</button>
            <button type="submit" id="start-upload-btn" class="px-3.5 py-1.5 text-xs bg-orange-500 hover:bg-orange-600 text-white font-semibold rounded-xl transition flex items-center gap-1.5 shadow-lg shadow-orange-500/20 disabled:opacity-50 disabled:cursor-not-allowed">
              <span>Start Upload</span>
              <span class="text-[10px]">↑</span>
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

    <!-- Session Closed Modal Dialog -->
    <div id="session-closed-modal" class="hidden fixed inset-0 z-50 bg-slate-950/85 backdrop-blur-sm flex items-center justify-center p-4">
      <div class="bg-slate-900 border border-slate-700/80 rounded-2xl shadow-2xl p-6 w-full max-w-md text-center font-sans space-y-4">
        <div class="w-14 h-14 mx-auto rounded-2xl bg-amber-500/10 border border-amber-500/20 text-amber-400 flex items-center justify-center text-3xl">
          🔌
        </div>
        <div>
          <h2 class="text-base sm:text-lg font-bold text-white tracking-tight">SSH Session Closed</h2>
          <p id="session-closed-msg" class="text-xs text-slate-300 mt-2 leading-relaxed">
            This remote web terminal session was closed (<code class="px-1.5 py-0.5 rounded bg-slate-950 text-orange-400 font-mono text-[11px]">fire ssh close</code>).
          </p>
        </div>
        <div class="p-3.5 rounded-xl bg-slate-950/80 border border-slate-800 text-[11px] text-slate-400 text-left font-mono space-y-1.5">
          <div class="text-slate-500 text-[10px] uppercase font-bold tracking-wider">To start a new session:</div>
          <div class="text-slate-300"># On your server terminal:</div>
          <div class="text-orange-400 font-bold">$ fire ssh</div>
        </div>
        <div class="flex items-center justify-center gap-2 pt-1">
          <button type="button" onclick="handleSessionClosedReload()" class="w-full py-2.5 px-4 text-xs bg-orange-500 hover:bg-orange-600 active:bg-orange-700 text-white font-semibold rounded-xl transition shadow-lg shadow-orange-500/20 flex items-center justify-center gap-2">
            <span>🔄 Reconnect / Login</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Terminal File & Image Hover Quick Actions Menu -->
    <div id="file-hover-menu" class="hidden fixed z-50 p-2.5 bg-slate-950/95 border border-slate-700/80 rounded-2xl shadow-2xl backdrop-blur-md transition-opacity duration-150 font-sans max-w-sm select-none">
      <!-- File Info Header -->
      <div class="flex items-center gap-2.5 px-1 pb-2 border-b border-slate-800/80 mb-2">
        <div id="file-hover-icon-box" class="w-8 h-8 rounded-lg bg-slate-900 border border-slate-800 flex items-center justify-center shrink-0 overflow-hidden">
          <span id="file-hover-icon" class="text-base">📄</span>
          <img id="file-hover-thumb" class="hidden max-w-full max-h-full object-contain" alt="Thumb">
        </div>
        <div class="min-w-0 flex-1">
          <div id="file-hover-name" class="text-xs font-semibold text-white font-mono truncate">file.txt</div>
          <div id="file-hover-path" class="text-[10px] text-slate-400 font-mono truncate" title="Full Path">/path/to/file.txt</div>
        </div>
        <span id="file-hover-badge" class="hidden text-[9px] uppercase px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-mono font-medium"></span>
      </div>

      <!-- Quick Action Buttons -->
      <div class="flex items-center gap-1.5 flex-wrap">
        <button type="button" id="file-hover-btn-cat" class="px-2.5 py-1 text-xs bg-slate-800/90 hover:bg-slate-700 text-slate-200 hover:text-white rounded-xl transition flex items-center gap-1.5 font-medium border border-slate-700/60 shadow-sm" title="View content in modal">
          <span>👁️</span> <span id="file-hover-btn-cat-text">View File</span>
        </button>

        <button type="button" id="file-hover-btn-edit" class="px-2.5 py-1 text-xs bg-orange-500/20 hover:bg-orange-500/30 text-orange-300 hover:text-orange-200 rounded-xl transition flex items-center gap-1.5 font-medium border border-orange-500/30 shadow-sm" title="Edit with nano in a new tab">
          <span>✏️</span> <span>Edit</span>
        </button>

        <button type="button" id="file-hover-btn-dir" class="hidden px-2.5 py-1 text-xs bg-sky-500/20 hover:bg-sky-500/30 text-sky-300 hover:text-sky-200 rounded-xl transition flex items-center gap-1.5 font-medium border border-sky-500/30 shadow-sm" title="Open directory in new tab (cd)">
          <span>📁</span> <span>Open in Tab</span>
        </button>

        <button type="button" id="file-hover-btn-img" class="hidden px-2.5 py-1 text-xs bg-sky-500/20 hover:bg-sky-500/30 text-sky-300 hover:text-sky-200 rounded-xl transition flex items-center gap-1.5 font-medium border border-sky-500/30 shadow-sm" title="Preview image in Lightbox viewer">
          <span>🖼️</span> <span>View Image</span>
        </button>

        <button type="button" id="file-hover-btn-copy" class="px-2 py-1 text-xs bg-slate-800/90 hover:bg-slate-700 text-slate-300 hover:text-white rounded-xl transition flex items-center gap-1 border border-slate-700/60" title="Copy path to clipboard">
          <span>📋</span> <span>Copy</span>
        </button>

        <button type="button" id="file-hover-btn-dl" class="px-2 py-1 text-xs bg-slate-800/90 hover:bg-slate-700 text-slate-300 hover:text-white rounded-xl transition flex items-center gap-1 border border-slate-700/60" title="Download">
          <span>↓</span> <span>Download</span>
        </button>
      </div>
    </div>

    <!-- Terminal Image Output Detected Toast Chip -->
    <div id="image-output-chip" class="hidden fixed bottom-6 right-6 z-40 max-w-sm bg-slate-900/95 border border-orange-500/40 rounded-2xl shadow-2xl backdrop-blur-md p-3 flex items-center gap-3 transition-all duration-300 transform translate-y-2 select-none">
      <div class="relative w-12 h-12 rounded-xl bg-slate-950 border border-slate-800 overflow-hidden shrink-0 flex items-center justify-center cursor-pointer hover:opacity-80 transition" id="image-chip-thumb-container" title="Click to inspect image">
        <img id="image-chip-img" class="max-w-full max-h-full object-contain" alt="Thumb">
      </div>
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-1.5 text-[10px] font-semibold text-orange-400 uppercase tracking-wider">
          <span>🖼️</span> Image Generated
        </div>
        <div id="image-chip-name" class="text-xs font-mono text-white truncate font-medium mt-0.5"></div>
        <div class="text-[10px] text-slate-400 font-mono" id="image-chip-dims"></div>
      </div>
      <div class="flex items-center gap-1 shrink-0">
        <button type="button" id="image-chip-view-btn" class="px-2.5 py-1 text-xs bg-orange-500 hover:bg-orange-600 text-white font-medium rounded-lg transition shadow">View</button>
        <button type="button" onclick="dismissImageOutputChip()" class="p-1 text-slate-400 hover:text-white text-xs rounded-lg transition">✕</button>
      </div>
    </div>

    <!-- Image Preview Lightbox Modal -->
    <div id="image-preview-modal" class="hidden fixed inset-0 z-50 bg-black/85 backdrop-blur-md flex flex-col justify-between font-sans select-none">
      <!-- Top Bar -->
      <div class="flex items-center justify-between px-4 py-3 bg-slate-950/80 border-b border-slate-800/80 shrink-0">
        <div class="flex items-center gap-3 min-w-0">
          <span class="text-lg">🖼️</span>
          <div class="min-w-0">
            <div id="image-modal-title" class="text-sm font-semibold text-white truncate font-mono">image.png</div>
            <div id="image-modal-path" class="text-[11px] text-slate-400 font-mono truncate max-w-lg cursor-pointer hover:text-orange-300 transition" title="Click to copy path" onclick="copyModalImagePath()"></div>
          </div>
        </div>

        <!-- Controls Toolbar -->
        <div class="flex items-center gap-1.5 shrink-0">
          <div class="flex items-center bg-slate-900/90 border border-slate-700/80 rounded-xl px-1.5 py-1 text-xs mr-2 font-mono text-slate-300">
            <button type="button" onclick="zoomImagePreview(-0.25)" class="px-2 py-0.5 hover:bg-slate-800 rounded transition text-slate-200" title="Zoom Out (-)">−</button>
            <span id="image-modal-zoom" class="px-2 min-w-[50px] text-center text-[11px] font-semibold text-orange-400">100%</span>
            <button type="button" onclick="zoomImagePreview(0.25)" class="px-2 py-0.5 hover:bg-slate-800 rounded transition text-slate-200" title="Zoom In (+)">+</button>
            <button type="button" onclick="resetImagePreviewZoom()" class="px-2 py-0.5 hover:bg-slate-800 rounded transition text-slate-400 hover:text-white" title="Reset Zoom (0)">1:1</button>
            <button type="button" onclick="fitImagePreviewToScreen()" class="px-2 py-0.5 hover:bg-slate-800 rounded transition text-slate-400 hover:text-white" title="Fit to Screen">⊡</button>
          </div>

          <button type="button" onclick="copyModalImagePath()" class="px-2.5 py-1.5 bg-slate-900 hover:bg-slate-800 border border-slate-700 rounded-xl text-xs text-slate-300 hover:text-white transition flex items-center gap-1" title="Copy Path">
            <span>📋</span> <span class="hidden sm:inline">Copy Path</span>
          </button>
          <button type="button" onclick="downloadModalImage()" class="px-2.5 py-1.5 bg-slate-900 hover:bg-slate-800 border border-slate-700 rounded-xl text-xs text-slate-300 hover:text-white transition flex items-center gap-1" title="Download">
            <span>↓</span> <span class="hidden sm:inline">Download</span>
          </button>
          <button type="button" onclick="openModalImageInNewTab()" class="px-2.5 py-1.5 bg-slate-900 hover:bg-slate-800 border border-slate-700 rounded-xl text-xs text-slate-300 hover:text-white transition flex items-center gap-1" title="Open In New Tab">
            <span>↗</span>
          </button>
          <button type="button" onclick="closeImagePreviewModal()" class="ml-2 p-1.5 px-2 bg-slate-800 hover:bg-red-500/20 hover:text-red-400 rounded-xl text-slate-400 hover:border-red-500/30 border border-slate-700 text-sm transition" title="Close (Escape)">✕</button>
        </div>
      </div>

      <!-- Main Viewer Viewport -->
      <div id="image-modal-viewport" class="flex-1 relative overflow-hidden flex items-center justify-center p-4 cursor-grab active:cursor-grabbing bg-slate-950/50" style="background-image: radial-gradient(#1e293b 1px, transparent 1px); background-size: 24px 24px;">
        <div id="image-modal-spinner" class="hidden absolute inset-0 flex items-center justify-center bg-slate-950/60 z-10 text-orange-400 text-sm">
          <div class="flex items-center gap-2 bg-slate-900 border border-slate-800 p-3 rounded-2xl shadow-xl">
            <span class="animate-spin text-base">⟳</span>
            <span>Loading image...</span>
          </div>
        </div>
        <div id="image-modal-error" class="hidden absolute inset-0 flex items-center justify-center bg-slate-950/80 z-10 text-red-400 text-xs">
          <div class="bg-slate-900 border border-red-500/30 p-4 rounded-2xl shadow-xl max-w-sm text-center">
            <div class="text-2xl mb-1">⚠️</div>
            <div id="image-modal-error-msg" class="text-slate-300">Unable to load image preview</div>
          </div>
        </div>
        <img id="image-modal-img" class="max-w-none transition-transform duration-75 select-none rounded shadow-2xl" alt="Preview" draggable="false">
      </div>

      <!-- Bottom Status Bar -->
      <div class="px-4 py-2 bg-slate-950/90 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400 font-mono shrink-0">
        <div class="flex items-center gap-4">
          <span id="image-modal-meta-dims">Dimensions: --</span>
          <span id="image-modal-meta-size">Size: --</span>
          <span id="image-modal-meta-type">Type: --</span>
        </div>
        <div class="text-[11px] text-slate-500 hidden md:block">
          Use mouse wheel to zoom, drag to pan, <kbd class="px-1 py-0.5 bg-slate-800 rounded text-slate-400">Esc</kbd> to exit
        </div>
      </div>
    </div>

    <!-- File Content In-Tab Preview Modal (< 2000 lines) -->
    <div id="file-content-modal" class="hidden fixed inset-0 z-50 bg-black/85 backdrop-blur-md flex flex-col justify-between font-sans select-none">
      <!-- Top Bar -->
      <div class="flex items-center justify-between px-4 py-3 bg-slate-950/80 border-b border-slate-800/80 shrink-0">
        <div class="flex items-center gap-3 min-w-0">
          <span id="file-modal-icon" class="text-lg">📄</span>
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <span id="file-modal-title" class="text-sm font-semibold text-white truncate font-mono">file.txt</span>
              <span id="file-modal-line-badge" class="px-2 py-0.5 rounded-full text-[10px] font-mono bg-sky-500/20 text-sky-300 border border-sky-500/30">0 lines</span>
              <span id="file-modal-size-badge" class="px-2 py-0.5 rounded-full text-[10px] font-mono bg-slate-800 text-slate-300">0 B</span>
            </div>
            <div id="file-modal-path" class="text-[11px] text-slate-400 font-mono truncate max-w-xl cursor-pointer hover:text-orange-300 transition" title="Click to copy path" onclick="copyModalFilePath()"></div>
          </div>
        </div>

        <!-- Controls Toolbar -->
        <div class="flex items-center gap-1.5 shrink-0">
          <button type="button" id="file-modal-edit-btn" onclick="editModalFileInNewTab()" class="px-2.5 py-1.5 bg-orange-500/20 hover:bg-orange-500/30 border border-orange-500/30 rounded-xl text-xs text-orange-300 hover:text-orange-200 transition flex items-center gap-1 font-medium" title="Edit file with nano in a new tab">
            <span>✏️</span> <span class="hidden sm:inline">Edit (nano)</span>
          </button>
          <button type="button" onclick="copyModalFileContent()" class="px-2.5 py-1.5 bg-slate-900 hover:bg-slate-800 border border-slate-700 rounded-xl text-xs text-slate-300 hover:text-white transition flex items-center gap-1" title="Copy file content to clipboard">
            <span>📋</span> <span id="file-modal-copy-label" class="hidden sm:inline">Copy Content</span>
          </button>
          <button type="button" onclick="downloadModalFile()" class="px-2.5 py-1.5 bg-slate-900 hover:bg-slate-800 border border-slate-700 rounded-xl text-xs text-slate-300 hover:text-white transition flex items-center gap-1" title="Download file">
            <span>↓</span> <span class="hidden sm:inline">Download</span>
          </button>
          <button type="button" onclick="closeFileContentModal()" class="ml-2 p-1.5 px-2 bg-slate-800 hover:bg-red-500/20 hover:text-red-400 rounded-xl text-slate-400 hover:border-red-500/30 border border-slate-700 text-sm transition" title="Close (Escape)">✕</button>
        </div>
      </div>

      <!-- Main Code Viewport -->
      <div id="file-modal-viewport" class="flex-1 relative overflow-auto p-4 bg-slate-950 font-mono text-xs sm:text-sm select-text text-slate-200">
        <div id="file-modal-spinner" class="hidden absolute inset-0 flex items-center justify-center bg-slate-950/70 z-10 text-orange-400 text-sm select-none">
          <div class="flex items-center gap-2 bg-slate-900 border border-slate-800 p-3.5 rounded-2xl shadow-xl">
            <span class="animate-spin text-base">⟳</span>
            <span>Loading content...</span>
          </div>
        </div>
        <div id="file-modal-error" class="hidden absolute inset-0 flex items-center justify-center bg-slate-950/80 z-10 text-red-400 text-xs select-none">
          <div class="bg-slate-900 border border-red-500/30 p-4 rounded-2xl shadow-xl max-w-sm text-center">
            <div class="text-2xl mb-1">⚠️</div>
            <div id="file-modal-error-msg" class="text-slate-300">Unable to load file content</div>
          </div>
        </div>

        <!-- Code Container with line numbers and text -->
        <div id="file-modal-code-wrap" class="min-w-full inline-flex font-mono text-xs sm:text-sm leading-6">
          <div id="file-modal-line-numbers" class="select-none text-right pr-4 text-slate-500 font-mono shrink-0 border-r border-slate-800/80 whitespace-pre leading-6 min-w-[3.5rem] sticky left-0 bg-slate-950 z-10"></div>
          <pre id="file-modal-code-text" class="flex-1 pl-4 m-0 whitespace-pre font-mono text-slate-200 select-text outline-none leading-6"></pre>
        </div>
      </div>

      <!-- Bottom Status Bar -->
      <div class="px-4 py-2 bg-slate-950/90 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400 font-mono shrink-0 select-none">
        <div class="flex items-center gap-4">
          <span id="file-modal-meta-lines">Lines: --</span>
          <span id="file-modal-meta-size">Size: --</span>
          <span id="file-modal-meta-encoding">Encoding: UTF-8</span>
        </div>
        <div class="text-[11px] text-slate-500 hidden md:block">
          Press <kbd class="px-1.5 py-0.5 bg-slate-800 border border-slate-700 rounded text-slate-300">Esc</kbd> to close
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
      <button onclick="promptRenameTab(activeTabId); hideContextMenu();" class="w-full text-left px-3 py-1.5 text-slate-300 hover:bg-slate-800 hover:text-white flex items-center justify-between">
        <span class="flex items-center gap-2">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 20h16M4 4h16M9 4v16M15 4v16"/></svg>
          <span>Rename Active Tab...</span>
        </span>
      </button>
      <button onclick="promptUpdateTitle(); hideContextMenu();" class="w-full text-left px-3 py-1.5 text-slate-300 hover:bg-slate-800 hover:text-white flex items-center justify-between">
        <span class="flex items-center gap-2">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
          <span>Rename Session Title...</span>
        </span>
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
    function escapeHtml(str) {
      if (str === null || str === undefined) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    let sessionToken = '';
    let latencyPingSent = 0, clientServerLatency = -1, serverTerminalLatency = -1, latencyInterval = null;
    let tabs = {}; // tabId -> tabObj
    let activeTabId = null;
    let secondaryTabId = null; // for dual split view
    let dualTabIds = []; // [pane1, pane2] for dual split view (left/right or top/bottom)
    let gridTabIds = []; // [topLeft, topRight, bottomLeft, bottomRight] for 2x2 grid
    let tripleTabIds = []; // [left/main, topRight, bottomRight] or [col1, col2, col3]
    let splitMode = 'none'; // 'none' | 'vertical' | 'horizontal' | 'triple-left' | 'triple-col' | 'grid'
    let splitRatio = 0.5; // for dual split (50%)
    let splitRatioX = 0.5; // for grid & triple-left split (50% horizontal)
    let splitRatioY = 0.5; // for grid & triple-left split (50% vertical)
    let splitRatio3Col1 = 0.3333; // for 3-column split (first divider)
    let splitRatio3Col2 = 0.6667; // for 3-column split (second divider)
    let isDraggingDivider = false;
    let dragMode = null; // 'dual' | 'grid-v' | 'grid-h' | 'grid-cross' | 'triple-v' | 'triple-h' | 'col1' | 'col2'
    let tabSequence = 0;

    function getActiveTab() {
      return activeTabId ? tabs[activeTabId] : null;
    }

    function getSecondaryTab() {
      const id = (dualTabIds && dualTabIds.length > 1) ? dualTabIds[1] : secondaryTabId;
      return id ? tabs[id] : null;
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
          showTerminal(data.tabs);
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
        if (data.title && !window.SESSION_TITLE) {
          window.SESSION_TITLE = data.title;
        }
        applySessionTitle();
        if (data.authenticated) {
          if (data.token) {
            sessionToken = data.token;
          }
          showTerminal(data.tabs);
        }
      } catch (e) {
        applySessionTitle();
      }
    }

    function showTerminal(knownTabs) {
      document.getElementById('login-view').classList.add('hidden');
      document.getElementById('terminal-view').classList.remove('hidden');
      updateMobileBarVisibility();
      applySessionTitle();
      if (window.IS_READONLY) {
        applyReadonlyUI();
      }
      initTerminal(knownTabs);
    }

    function sendInterrupt() {
      const cur = getActiveTab();
      const s = cur && cur.socket ? cur.socket : socket;
      if (s && s.readyState === WebSocket.OPEN) {
        s.send(JSON.stringify({ type: 'signal', signal: 'SIGINT' }));
        s.send(JSON.stringify({ type: 'input', data: '\x03' }));
      }
      if (term && !isTouchDevice) term.focus();
    }

    function sendSuspend() {
      const cur = getActiveTab();
      const s = cur && cur.socket ? cur.socket : socket;
      if (s && s.readyState === WebSocket.OPEN) {
        s.send(JSON.stringify({ type: 'signal', signal: 'SIGTSTP' }));
        s.send(JSON.stringify({ type: 'input', data: '\x1a' }));
      }
      if (term && !isTouchDevice) term.focus();
    }

    function sendEOF() {
      const cur = getActiveTab();
      const s = cur && cur.socket ? cur.socket : socket;
      if (s && s.readyState === WebSocket.OPEN) {
        s.send(JSON.stringify({ type: 'input', data: '\x04' }));
      }
      if (term && !isTouchDevice) term.focus();
    }

    function sendCtrlW() {
      const cur = getActiveTab();
      const s = cur && cur.socket ? cur.socket : socket;
      if (s && s.readyState === WebSocket.OPEN) {
        s.send(JSON.stringify({ type: 'input', data: '\x17' }));
      }
      if (term && !isTouchDevice) term.focus();
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
      if (e.key === 'F11' || e.keyCode === 122) {
        e.preventDefault();
        e.stopPropagation();
        toggleFullscreen();
        return false;
      }
    }, { capture: true });

    // ==================== MOBILE TERMINAL COMPATIBILITY ====================
    let isTouchDevice = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0) || (window.innerWidth < 768);
    let mobileBarVisible = isTouchDevice;
    let mobileBarCollapsed = false;
    let ctrlSticky = false;
    let altSticky = false;
    let shiftSticky = false;
    let currentFontSize = window.innerWidth < 480 ? 12 : (window.innerWidth < 768 ? 13 : 14);
    let lastMobileTouchTime = 0;

    function sendTerminalData(data) {
      if (window.IS_READONLY) return;
      const cur = getActiveTab();
      const s = cur && cur.socket ? cur.socket : socket;
      if (s && s.readyState === WebSocket.OPEN) {
        if (typeof data === 'string') {
          s.send(new TextEncoder().encode(data));
        } else {
          s.send(data);
        }
      }
    }

    let touchStartX = 0;
    let touchStartY = 0;
    let touchMoved = false;
    let pendingMobileKey = null;
    let keyRepeatTimeout = null;
    let keyRepeatInterval = null;
    let hasRepeated = false;
    let mouseRepeatTimeout = null;
    let mouseRepeatInterval = null;
    let mouseRepeated = false;

    const KEY_REPEAT_INITIAL_DELAY_MS = 350;
    const KEY_REPEAT_INTERVAL_MS = 100;

    function isRepeatableKey(keyType) {
      return keyType === 'up' || keyType === 'down' || keyType === 'left' || keyType === 'right';
    }

    function clearKeyRepeat() {
      if (keyRepeatTimeout) {
        clearTimeout(keyRepeatTimeout);
        keyRepeatTimeout = null;
      }
      if (keyRepeatInterval) {
        clearInterval(keyRepeatInterval);
        keyRepeatInterval = null;
      }
    }

    function clearMouseRepeat() {
      if (mouseRepeatTimeout) {
        clearTimeout(mouseRepeatTimeout);
        mouseRepeatTimeout = null;
      }
      if (mouseRepeatInterval) {
        clearInterval(mouseRepeatInterval);
        mouseRepeatInterval = null;
      }
    }

    function handleMobileKeyTouchStart(e, keyType, val) {
      clearKeyRepeat();
      hasRepeated = false;
      if (!e.touches || e.touches.length === 0) return;
      touchStartX = e.touches[0].clientX;
      touchStartY = e.touches[0].clientY;
      touchMoved = false;
      pendingMobileKey = { keyType, val };

      if (isRepeatableKey(keyType)) {
        keyRepeatTimeout = setTimeout(() => {
          if (!touchMoved && pendingMobileKey) {
            hasRepeated = true;
            lastMobileTouchTime = Date.now();
            executeMobileKey(pendingMobileKey.keyType, pendingMobileKey.val);
            keyRepeatInterval = setInterval(() => {
              if (!touchMoved && pendingMobileKey) {
                executeMobileKey(pendingMobileKey.keyType, pendingMobileKey.val);
              } else {
                clearKeyRepeat();
              }
            }, KEY_REPEAT_INTERVAL_MS);
          }
        }, KEY_REPEAT_INITIAL_DELAY_MS);
      }
    }

    function handleMobileKeyTouchMove(e) {
      if (!pendingMobileKey || !e.touches || e.touches.length === 0) return;
      const dx = Math.abs(e.touches[0].clientX - touchStartX);
      const dy = Math.abs(e.touches[0].clientY - touchStartY);

      if (hasRepeated) {
        if (e.cancelable) e.preventDefault();
        const touch = e.touches[0];
        const el = document.elementFromPoint(touch.clientX, touch.clientY);
        if (!el || !el.closest('.mobile-key') || dx > 35 || dy > 35) {
          clearKeyRepeat();
          pendingMobileKey = null;
          touchMoved = true;
        }
      } else {
        if (dx > 6 || dy > 6) {
          touchMoved = true;
          clearKeyRepeat();
          pendingMobileKey = null;
        }
      }
    }

    function handleMobileKeyTouchEnd(e, keyType, val) {
      clearKeyRepeat();
      if (e && !touchMoved && pendingMobileKey) {
        e.preventDefault();
        e.stopPropagation();
      }
      if (!touchMoved && pendingMobileKey && !hasRepeated) {
        lastMobileTouchTime = Date.now();
        executeMobileKey(pendingMobileKey.keyType, pendingMobileKey.val);
      }
      pendingMobileKey = null;
      touchMoved = false;
      hasRepeated = false;
    }

    function handleMobileKeyTouchCancel() {
      clearKeyRepeat();
      pendingMobileKey = null;
      touchMoved = false;
      hasRepeated = false;
    }

    function handleMobileKeyMouseDown(e, keyType, val) {
      if (Date.now() - lastMobileTouchTime < 450) return;
      if (e.button !== 0) return;
      if (!isRepeatableKey(keyType)) return;

      clearMouseRepeat();
      mouseRepeated = false;

      mouseRepeatTimeout = setTimeout(() => {
        mouseRepeated = true;
        executeMobileKey(keyType, val);
        mouseRepeatInterval = setInterval(() => {
          executeMobileKey(keyType, val);
        }, KEY_REPEAT_INTERVAL_MS);
      }, KEY_REPEAT_INITIAL_DELAY_MS);
    }

    function handleMobileKeyMouseUp(e, keyType, val) {
      clearMouseRepeat();
    }

    function handleMobileKeyMouseLeave(e) {
      clearMouseRepeat();
    }

    // Retain handleMobileKeyTouch for backward compatibility
    function handleMobileKeyTouch(e, keyType, val) {
      if (e) {
        e.preventDefault();
        e.stopPropagation();
      }
      lastMobileTouchTime = Date.now();
      executeMobileKey(keyType, val);
    }

    let isListMouseDragging = false;
    function handleMobileKeyClick(keyType, val) {
      if (Date.now() - lastMobileTouchTime < 450) return;
      if (isListMouseDragging) return;
      if (mouseRepeated) {
        mouseRepeated = false;
        return;
      }
      executeMobileKey(keyType, val);
    }

    function scrollMobileKeys(amount) {
      const list = document.getElementById('mobile-keys-list');
      if (list) {
        list.scrollBy({ left: amount, behavior: 'smooth' });
      }
    }

    function executeMobileKey(keyType, val) {
      if (window.IS_READONLY) {
        showToast('Read-only mode: terminal input disabled');
        return;
      }
      const cur = getActiveTab();

      switch (keyType) {
        case 'esc':
          sendTerminalData('\x1b');
          if (ctrlSticky || altSticky || shiftSticky) {
            ctrlSticky = false;
            altSticky = false;
            shiftSticky = false;
            updateModifierUI();
          }
          break;
        case 'tab':
          if (shiftSticky) {
            sendTerminalData('\x1b[Z'); // ANSI Backtab (Shift+Tab)
            shiftSticky = false;
            updateModifierUI();
          } else if (altSticky) {
            sendTerminalData('\x1b\t');
            altSticky = false;
            updateModifierUI();
          } else {
            sendTerminalData('\t');
          }
          break;
        case 'ctrl':
          toggleCtrlSticky();
          break;
        case 'alt':
          toggleAltSticky();
          break;
        case 'shift':
          toggleShiftSticky();
          break;
        case 'enter':
          if (altSticky) {
            sendTerminalData('\x1b\r');
            altSticky = false;
            updateModifierUI();
          } else {
            sendTerminalData('\r');
            if (shiftSticky || ctrlSticky) {
              shiftSticky = false;
              ctrlSticky = false;
              updateModifierUI();
            }
          }
          break;
        case 'up':
          if (shiftSticky) {
            sendTerminalData('\x1b[1;2A');
            shiftSticky = false;
            updateModifierUI();
          } else if (ctrlSticky) {
            sendTerminalData('\x1b[1;5A');
            ctrlSticky = false;
            updateModifierUI();
          } else if (altSticky) {
            sendTerminalData('\x1b[1;3A');
            altSticky = false;
            updateModifierUI();
          } else {
            sendTerminalData('\x1b[A');
          }
          break;
        case 'down':
          if (shiftSticky) {
            sendTerminalData('\x1b[1;2B');
            shiftSticky = false;
            updateModifierUI();
          } else if (ctrlSticky) {
            sendTerminalData('\x1b[1;5B');
            ctrlSticky = false;
            updateModifierUI();
          } else if (altSticky) {
            sendTerminalData('\x1b[1;3B');
            altSticky = false;
            updateModifierUI();
          } else {
            sendTerminalData('\x1b[B');
          }
          break;
        case 'left':
          if (shiftSticky) {
            sendTerminalData('\x1b[1;2D');
            shiftSticky = false;
            updateModifierUI();
          } else if (ctrlSticky) {
            sendTerminalData('\x1b[1;5D');
            ctrlSticky = false;
            updateModifierUI();
          } else if (altSticky) {
            sendTerminalData('\x1bb');
            altSticky = false;
            updateModifierUI();
          } else {
            sendTerminalData('\x1b[D');
          }
          break;
        case 'right':
          if (shiftSticky) {
            sendTerminalData('\x1b[1;2C');
            shiftSticky = false;
            updateModifierUI();
          } else if (ctrlSticky) {
            sendTerminalData('\x1b[1;5C');
            ctrlSticky = false;
            updateModifierUI();
          } else if (altSticky) {
            sendTerminalData('\x1bf');
            altSticky = false;
            updateModifierUI();
          } else {
            sendTerminalData('\x1b[C');
          }
          break;
        case 'char':
          if (val) {
            if (ctrlSticky) {
              sendCtrlChar(val);
            } else if (altSticky) {
              sendTerminalData('\x1b' + val);
              altSticky = false;
              updateModifierUI();
            } else if (shiftSticky) {
              sendShiftChar(val);
            } else {
              sendTerminalData(val);
            }
          }
          break;
        case 'sigint':
          sendInterrupt();
          break;
        case 'eof':
          sendEOF();
          break;
        case 'clear':
          sendTerminalData('\x0c');
          break;
        case 'toggle-kbd':
          toggleMobileKeyboard();
          break;
        case 'collapse-bar':
          toggleMobileBarCollapse();
          break;
        default:
          break;
      }
    }

    function toggleCtrlSticky() {
      ctrlSticky = !ctrlSticky;
      if (ctrlSticky) {
        altSticky = false;
        shiftSticky = false;
        const cur = getActiveTab();
        if (cur && cur.term) cur.term.focus();
      }
      updateModifierUI();
    }

    function toggleAltSticky() {
      altSticky = !altSticky;
      if (altSticky) {
        ctrlSticky = false;
        shiftSticky = false;
        const cur = getActiveTab();
        if (cur && cur.term) cur.term.focus();
      }
      updateModifierUI();
    }

    function toggleShiftSticky() {
      shiftSticky = !shiftSticky;
      if (shiftSticky) {
        ctrlSticky = false;
        altSticky = false;
        const cur = getActiveTab();
        if (cur && cur.term) cur.term.focus();
      }
      updateModifierUI();
    }

    function updateModifierUI() {
      const ctrlBtn = document.getElementById('mobile-key-ctrl');
      if (ctrlBtn) {
        if (ctrlSticky) {
          ctrlBtn.className = 'mobile-key px-2.5 py-1 text-xs font-mono font-bold bg-orange-500 text-white rounded-md border border-orange-400 shadow-sm shrink-0 transition select-none ring-2 ring-orange-500/50';
        } else {
          ctrlBtn.className = 'mobile-key px-2.5 py-1 text-xs font-mono font-bold bg-slate-800 text-slate-200 rounded-md border border-slate-700 shadow-sm shrink-0 transition select-none';
        }
      }

      const altBtn = document.getElementById('mobile-key-alt');
      if (altBtn) {
        if (altSticky) {
          altBtn.className = 'mobile-key px-2.5 py-1 text-xs font-mono font-bold bg-orange-500 text-white rounded-md border border-orange-400 shadow-sm shrink-0 transition select-none ring-2 ring-orange-500/50';
        } else {
          altBtn.className = 'mobile-key px-2.5 py-1 text-xs font-mono font-bold bg-slate-800 text-slate-200 rounded-md border border-slate-700 shadow-sm shrink-0 transition select-none';
        }
      }

      const shiftBtn = document.getElementById('mobile-key-shift');
      if (shiftBtn) {
        if (shiftSticky) {
          shiftBtn.className = 'mobile-key px-2.5 py-1 text-xs font-mono font-bold bg-orange-500 text-white rounded-md border border-orange-400 shadow-sm shrink-0 transition select-none ring-2 ring-orange-500/50';
        } else {
          shiftBtn.className = 'mobile-key px-2.5 py-1 text-xs font-mono font-bold bg-slate-800 text-slate-200 rounded-md border border-slate-700 shadow-sm shrink-0 transition select-none';
        }
      }
    }

    const SHIFT_MAP = {
      '1': '!', '2': '@', '3': '#', '4': '$', '5': '%',
      '6': '^', '7': '&', '8': '*', '9': '(', '0': ')',
      '`': '~', '-': '_', '=': '+', '[': '{', ']': '}',
      '\\': '|', ';': ':', "'": '"', ',': '<', '.': '>',
      '/': '?'
    };

    function sendShiftChar(str) {
      if (!str) return;
      let out = '';
      for (let i = 0; i < str.length; i++) {
        const c = str[i];
        if (SHIFT_MAP[c]) {
          out += SHIFT_MAP[c];
        } else if (c >= 'a' && c <= 'z') {
          out += c.toUpperCase();
        } else {
          out += c;
        }
      }
      sendTerminalData(out);
      shiftSticky = false;
      updateModifierUI();
    }

    function sendCtrlChar(char) {
      let code = char.charCodeAt(0);
      let ctrlCode;
      if (code >= 97 && code <= 122) { // a-z
        ctrlCode = String.fromCharCode(code - 96);
      } else if (code >= 65 && code <= 90) { // A-Z
        ctrlCode = String.fromCharCode(code - 64);
      } else if (char === '@' || char === ' ') {
        ctrlCode = '\x00';
      } else if (char === '[') {
        ctrlCode = '\x1b';
      } else if (char === '\\') {
        ctrlCode = '\x1c';
      } else if (char === ']') {
        ctrlCode = '\x1d';
      } else if (char === '^') {
        ctrlCode = '\x1e';
      } else if (char === '_') {
        ctrlCode = '\x1f';
      } else {
        ctrlCode = char;
      }
      sendTerminalData(ctrlCode);
      ctrlSticky = false;
      updateModifierUI();
    }

    function toggleMobileKeyboard() {
      const cur = getActiveTab();
      if (!cur || !cur.term) return;
      const textarea = cur.term.textarea;
      if (!textarea) return;

      if (document.activeElement === textarea) {
        textarea.blur();
        showToast('Keyboard hidden');
      } else {
        textarea.focus();
        cur.term.focus();
        showToast('Keyboard focused');
      }
    }

    function toggleMobileBarCollapse() {
      const keysList = document.getElementById('mobile-keys-list');
      const collapseBtn = document.getElementById('mobile-collapse-btn');
      if (!keysList || !collapseBtn) return;

      mobileBarCollapsed = !mobileBarCollapsed;
      if (mobileBarCollapsed) {
        keysList.classList.add('hidden');
        collapseBtn.textContent = '⌃';
        collapseBtn.title = 'Expand Key Bar';
      } else {
        keysList.classList.remove('hidden');
        collapseBtn.textContent = '⌄';
        collapseBtn.title = 'Collapse Key Bar';
      }
      termFit();
    }

    let userToggledMobileBar = false;

    function updateMobileBarVisibility() {
      if (userToggledMobileBar) return;
      const bar = document.getElementById('mobile-accessory-bar');
      if (!bar) return;
      const isFinePointer = window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches;
      const isDesktop = isFinePointer || (!isTouchDevice && window.innerWidth >= 768);
      if (isDesktop) {
        bar.classList.add('hidden');
        mobileBarVisible = false;
      } else {
        bar.classList.remove('hidden');
        mobileBarVisible = true;
      }
      const statusText = document.getElementById('mobile-bar-status-text');
      if (statusText) {
        statusText.textContent = mobileBarVisible ? 'Active' : 'Hidden';
        statusText.className = mobileBarVisible ? 'text-[10px] font-mono text-emerald-400' : 'text-[10px] font-mono text-slate-500';
      }
    }

    function toggleMobileBarVisibility() {
      userToggledMobileBar = true;
      mobileBarVisible = !mobileBarVisible;
      const bar = document.getElementById('mobile-accessory-bar');
      const statusText = document.getElementById('mobile-bar-status-text');
      if (bar) {
        if (mobileBarVisible) {
          bar.classList.remove('hidden');
          if (statusText) {
            statusText.textContent = 'Active';
            statusText.className = 'text-[10px] font-mono text-emerald-400';
          }
        } else {
          bar.classList.add('hidden');
          if (statusText) {
            statusText.textContent = 'Hidden';
            statusText.className = 'text-[10px] font-mono text-slate-500';
          }
        }
      }
      termFit();
    }

    function toggleMobileActionsMenu() {
      const m = document.getElementById('mobile-actions-menu');
      if (!m) return;
      m.classList.toggle('hidden');
    }

    function closeMobileActionsMenu() {
      const m = document.getElementById('mobile-actions-menu');
      if (m) m.classList.add('hidden');
    }

    function adjustFontSize(delta) {
      const newSize = Math.max(9, Math.min(24, currentFontSize + delta));
      if (newSize === currentFontSize) return;
      currentFontSize = newSize;
      Object.values(tabs).forEach(tab => {
        if (tab && tab.term) {
          tab.term.options.fontSize = currentFontSize;
          if (tab.fitAddon) tab.fitAddon.fit();
          sendResize(tab);
        }
      });
      showToast(`Font Size: ${currentFontSize}px`);
    }

    function updateViewportLayout() {
      const termView = document.getElementById('terminal-view');
      if (!termView) return;

      updateMobileBarVisibility();

      if (window.visualViewport) {
        const vv = window.visualViewport;
        if (window.innerWidth <= 768 || ('ontouchstart' in window) || navigator.maxTouchPoints > 0) {
          termView.style.height = `${vv.height}px`;
          window.scrollTo(0, 0);
        } else {
          termView.style.height = '';
        }
      }
      termFit();
    }

    let originalDocTitle = (window.SESSION_TITLE || document.title || 'Fire SSH');
    let titleBlinkInterval = null;

    function applySessionTitle(newTitle) {
      if (typeof newTitle === 'string') {
        window.SESSION_TITLE = newTitle;
      }
      const titleToApply = window.SESSION_TITLE || 'Fire PM';
      document.title = titleToApply;
      originalDocTitle = titleToApply;

      const brandEl = document.getElementById('brand-header-title');
      if (brandEl) {
        brandEl.textContent = titleToApply;
        brandEl.title = titleToApply + (window.IS_READONLY ? '' : ' (Click to rename)');
      }
      const loginSubtitle = document.getElementById('login-card-subtitle');
      if (loginSubtitle) {
        loginSubtitle.textContent = titleToApply;
      }
    }

    async function promptUpdateTitle() {
      if (window.IS_READONLY) return;
      const current = window.SESSION_TITLE || '';
      const newTitle = prompt('Enter session title (browser tab & header):', current);
      if (newTitle === null) return;
      const clean = newTitle.trim();
      try {
        const res = await fetch('/api/title', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: clean })
        });
        const data = await res.json();
        if (res.ok && data.success) {
          applySessionTitle(data.title);
          showToast(`Session title updated to "${data.title || 'Fire PM'}"`);
        } else {
          showToast(data.error || 'Failed to update title');
        }
      } catch (e) {
        showToast('Error updating session title');
      }
    }

    function promptRenameTab(tabId) {
      if (window.IS_READONLY) return;
      const targetId = tabId || activeTabId;
      const tab = tabs[targetId];
      if (!tab) return;
      const newName = prompt(`Rename Tab ${tab.index}:`, tab.title || '');
      if (newName === null) return;
      tab.title = newName.trim() || 'bash';
      renderTabsList();
      saveTabsState();
      showToast(`Tab ${tab.index} renamed to "${tab.title}"`);
    }

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

    window.addEventListener('blur', () => {
      clearKeyRepeat();
      clearMouseRepeat();
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
    let pendingUploadFiles = [];

    // ==================== FAST 0-LATENCY DIRECTORY AUTOCOMPLETE ====================
    // Caches directory listings so keystrokes filter instantly in-memory without network calls
    const fsDirCache = new Map(); // dirPath -> { items: [], ts: Date.now() }
    const FS_CACHE_TTL = 30000; // 30 seconds cache

    async function fetchDirListing(dirPath, filterType = 'all', forceRefresh = false) {
      const cacheKey = `${filterType}:${dirPath}`;
      const cached = fsDirCache.get(cacheKey);
      if (!forceRefresh && cached && (Date.now() - cached.ts < FS_CACHE_TTL)) {
        return cached.items;
      }

      try {
        const tabParam = activeTabId ? `tab=${encodeURIComponent(activeTabId)}` : '';
        const tokenParam = sessionToken ? `token=${encodeURIComponent(sessionToken)}` : '';
        const dirParam = `dir=${encodeURIComponent(dirPath)}`;
        const typeParam = `type=${encodeURIComponent(filterType)}`;
        const qs = [dirParam, typeParam, tabParam, tokenParam].filter(Boolean).join('&');
        const res = await fetch(`/api/suggest?${qs}`);
        if (res.ok) {
          const data = await res.json();
          if (data && data.success && Array.isArray(data.items)) {
            fsDirCache.set(cacheKey, { items: data.items, ts: Date.now() });
            return data.items;
          }
        }
      } catch(e) {}
      return cached ? cached.items : [];
    }

    class PathAutocomplete {
      constructor(options) {
        this.inputEl = options.inputEl;
        this.dropdownEl = options.dropdownEl;
        this.spinnerEl = options.spinnerEl;
        this.countBadgeEl = options.countBadgeEl;
        this.filterType = options.filterType || 'all'; // 'all' or 'dir_only'
        this.onSelect = options.onSelect || null;
        this.items = [];
        this.selectedIndex = -1;
        this.debounceTimer = null;
        this.isFetching = false;

        this.init();
      }

      init() {
        if (!this.inputEl || !this.dropdownEl) return;

        this.inputEl.addEventListener('input', () => this.handleInput());
        this.inputEl.addEventListener('focus', () => this.handleFocus());
        this.inputEl.addEventListener('keydown', (e) => this.handleKeyDown(e));

        document.addEventListener('click', (e) => {
          if (!this.inputEl.contains(e.target) && !this.dropdownEl.contains(e.target)) {
            this.hide();
          }
        });
      }

      parseInputPath(val) {
        const raw = val.trim();
        if (!raw) {
          return { parentDir: currentCwd, baseName: '', isAbsolute: false };
        }
        const isAbs = raw.startsWith('/') || raw.startsWith('~');
        if (raw === '/' || raw === '~') {
          return { parentDir: raw, baseName: '', isAbsolute: true };
        }
        if (raw.endsWith('/')) {
          return { parentDir: raw.slice(0, -1) || '/', baseName: '', isAbsolute: isAbs };
        }
        const lastSlash = raw.lastIndexOf('/');
        if (lastSlash === -1) {
          return { parentDir: currentCwd, baseName: raw, isAbsolute: false };
        }
        const parent = raw.slice(0, lastSlash) || '/';
        const base = raw.slice(lastSlash + 1);
        return { parentDir: parent, baseName: base, isAbsolute: isAbs };
      }

      async handleFocus() {
        await this.refreshSuggestions();
      }

      handleInput() {
        clearTimeout(this.debounceTimer);
        // Instant local filter if we already have items from the parent directory
        const { parentDir, baseName } = this.parseInputPath(this.inputEl.value);
        const cacheKey = `${this.filterType}:${parentDir}`;
        const cached = fsDirCache.get(cacheKey);

        if (cached) {
          this.renderList(cached.items, baseName, parentDir);
        }

        // Slight debounce for fetching new directory if not in cache
        this.debounceTimer = setTimeout(() => {
          this.refreshSuggestions();
        }, 120);
      }

      async refreshSuggestions(force = false) {
        const { parentDir, baseName } = this.parseInputPath(this.inputEl.value);
        if (this.spinnerEl) this.spinnerEl.classList.remove('hidden');

        const items = await fetchDirListing(parentDir, this.filterType, force);
        if (this.spinnerEl) this.spinnerEl.classList.add('hidden');

        this.renderList(items, baseName, parentDir);
      }

      renderList(items, query, parentDir) {
        if (!items || !items.length) {
          this.dropdownEl.innerHTML = '<div class="px-3 py-2 text-[11px] text-slate-500 italic">No matching files or directories</div>';
          this.dropdownEl.classList.remove('hidden');
          if (this.countBadgeEl) this.countBadgeEl.textContent = '';
          this.items = [];
          this.selectedIndex = -1;
          return;
        }

        const q = (query || '').toLowerCase();
        // Instant matching: prefix matches first, then substring matches
        let matches = items.filter(item => {
          const name = item.name.toLowerCase();
          return !q || name.includes(q);
        });

        // Sort exact prefix matches first
        matches.sort((a, b) => {
          const aName = a.name.toLowerCase();
          const bName = b.name.toLowerCase();
          const aPrefix = aName.startsWith(q);
          const bPrefix = bName.startsWith(q);
          if (aPrefix && !bPrefix) return -1;
          if (!aPrefix && bPrefix) return 1;
          if (a.is_dir && !b.is_dir) return -1;
          if (!a.is_dir && b.is_dir) return 1;
          return aName.localeCompare(bName);
        });

        // Limit dropdown items to 40 for DOM performance
        matches = matches.slice(0, 40);
        this.items = matches;
        this.selectedIndex = matches.length > 0 ? 0 : -1;

        if (matches.length === 0) {
          this.dropdownEl.innerHTML = `<div class="px-3 py-2 text-[11px] text-slate-500 italic">No files matching "${query}"</div>`;
          this.dropdownEl.classList.remove('hidden');
          if (this.countBadgeEl) this.countBadgeEl.textContent = '0 items';
          return;
        }

        if (this.countBadgeEl) {
          this.countBadgeEl.textContent = `${matches.length} item${matches.length === 1 ? '' : 's'}`;
        }

        this.dropdownEl.innerHTML = matches.map((item, idx) => {
          const icon = item.is_dir ? '📁' : '📄';
          const sizeStr = item.is_dir ? '' : `<span class="text-[10px] text-slate-500 font-mono">${formatBytes(item.size || 0)}</span>`;
          const isSelected = idx === this.selectedIndex;
          const activeClass = isSelected ? 'bg-orange-500/20 text-orange-200 border-l-2 border-orange-500' : 'text-slate-300 hover:bg-slate-900 border-l-2 border-transparent';
          const safeName = escapeHtml(item.name || '');

          return `
            <div data-idx="${idx}" class="suggestion-item px-3 py-1.5 cursor-pointer flex items-center justify-between transition text-xs font-mono select-none ${activeClass}">
              <div class="flex items-center gap-2 truncate">
                <span>${icon}</span>
                <span class="truncate ${item.is_dir ? 'font-medium text-white' : ''}">${safeName}${item.is_dir ? '/' : ''}</span>
              </div>
              ${sizeStr}
            </div>
          `;
        }).join('');

        this.dropdownEl.querySelectorAll('.suggestion-item').forEach(el => {
          el.addEventListener('mousedown', (e) => {
            e.preventDefault(); // keep input focused
            const idx = parseInt(el.getAttribute('data-idx'), 10);
            this.selectItem(idx);
          });
        });

        this.dropdownEl.classList.remove('hidden');
        this.scrollSelectedIntoView();
      }

      scrollSelectedIntoView() {
        const active = this.dropdownEl.querySelector(`.suggestion-item[data-idx="${this.selectedIndex}"]`);
        if (active) {
          active.scrollIntoView({ block: 'nearest' });
        }
      }

      updateSelectionUI() {
        const items = this.dropdownEl.querySelectorAll('.suggestion-item');
        items.forEach((el, idx) => {
          if (idx === this.selectedIndex) {
            el.className = 'suggestion-item px-3 py-1.5 cursor-pointer flex items-center justify-between transition text-xs font-mono select-none bg-orange-500/20 text-orange-200 border-l-2 border-orange-500';
          } else {
            el.className = 'suggestion-item px-3 py-1.5 cursor-pointer flex items-center justify-between transition text-xs font-mono select-none text-slate-300 hover:bg-slate-900 border-l-2 border-transparent';
          }
        });
        this.scrollSelectedIntoView();
      }

      selectItem(idx) {
        if (idx < 0 || idx >= this.items.length) return;
        const item = this.items[idx];
        const val = this.inputEl.value.trim();
        const lastSlash = val.lastIndexOf('/');

        let newPath = '';
        if (lastSlash === -1) {
          newPath = item.name;
        } else {
          newPath = val.slice(0, lastSlash + 1) + item.name;
        }

        if (item.is_dir) {
          newPath += '/';
        }

        this.inputEl.value = newPath;

        if (item.is_dir) {
          // Immediately prefetch directory contents for the next stage
          this.refreshSuggestions(false);
        } else {
          this.hide();
        }

        if (this.onSelect) this.onSelect(item, newPath);
      }

      handleKeyDown(e) {
        const isVisible = !this.dropdownEl.classList.contains('hidden');

        if (e.key === 'ArrowDown') {
          if (!isVisible) {
            this.refreshSuggestions();
            return;
          }
          e.preventDefault();
          if (this.items.length > 0) {
            this.selectedIndex = (this.selectedIndex + 1) % this.items.length;
            this.updateSelectionUI();
          }
        } else if (e.key === 'ArrowUp') {
          if (!isVisible) return;
          e.preventDefault();
          if (this.items.length > 0) {
            this.selectedIndex = (this.selectedIndex - 1 + this.items.length) % this.items.length;
            this.updateSelectionUI();
          }
        } else if (e.key === 'Tab') {
          if (isVisible && this.items.length > 0) {
            e.preventDefault();
            this.selectItem(this.selectedIndex >= 0 ? this.selectedIndex : 0);
          }
        } else if (e.key === 'Enter') {
          if (isVisible && this.selectedIndex >= 0 && this.items.length > 0) {
            const item = this.items[this.selectedIndex];
            if (item.is_dir) {
              const currentVal = this.inputEl.value.trim().replace(/\/+$/, '');
              if (currentVal.endsWith(item.name) && this.filterType === 'dir_only') {
                this.hide();
                return;
              }
              e.preventDefault();
              this.selectItem(this.selectedIndex);
              return;
            }
          }
          this.hide();
        } else if (e.key === 'Escape') {
          if (isVisible) {
            e.preventDefault();
            this.hide();
          }
        }
      }

      hide() {
        this.dropdownEl.classList.add('hidden');
        if (this.countBadgeEl) this.countBadgeEl.textContent = '';
      }
    }

    let downloadAutoComp = null;
    let uploadDestAutoComp = null;

    async function updateCwd() {
      try {
        const tabParam = activeTabId ? `tab=${encodeURIComponent(activeTabId)}` : '';
        const tokenParam = sessionToken ? `token=${encodeURIComponent(sessionToken)}` : '';
        const qs = [tabParam, tokenParam].filter(Boolean).join('&');
        const res = await fetch(`/api/cwd${qs ? '?' + qs : ''}`);
        if (res.ok) {
          const data = await res.json();
          if (data && data.cwd) {
            currentCwd = data.cwd;
            const dropDirEl = document.getElementById('drop-target-dir');
            if (dropDirEl) dropDirEl.textContent = currentCwd;
            const dlHintEl = document.getElementById('download-cwd-hint');
            if (dlHintEl) dlHintEl.textContent = currentCwd;
            const upDestInput = document.getElementById('upload-dest-input');
            if (upDestInput && !upDestInput.value) upDestInput.value = currentCwd;
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

    // Drag and Drop Event Listeners
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

    window.addEventListener('dragenter', (e) => {
      if (window.IS_READONLY) return;
      if (!isFileDragEvent(e)) return;
      e.preventDefault();
      dragCounter++;
      if (dragCounter === 1) {
        updateCwd();
        const overlay = document.getElementById('drop-overlay');
        if (overlay) overlay.classList.remove('hidden');
      }
    });

    window.addEventListener('dragover', (e) => {
      if (window.IS_READONLY) return;
      if (!isFileDragEvent(e)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
    });

    window.addEventListener('dragleave', (e) => {
      if (window.IS_READONLY) return;
      if (!isFileDragEvent(e)) return;
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
      if (!isFileDragEvent(e)) {
        dragCounter = 0;
        const overlay = document.getElementById('drop-overlay');
        if (overlay) overlay.classList.add('hidden');
        return;
      }
      e.preventDefault();
      dragCounter = 0;
      const overlay = document.getElementById('drop-overlay');
      if (overlay) overlay.classList.add('hidden');

      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        // Drop into upload modal to allow choosing/verifying target directory
        openUploadModal(e.dataTransfer.files);
      }
    });

    function triggerFileInput() {
      openUploadModal();
    }

    function handleFileSelect(e) {
      if (e.target && e.target.files && e.target.files.length > 0) {
        openUploadModal(e.target.files);
      }
    }

    // ==================== UPLOAD MODAL & DESTINATION SELECTION ====================
    async function openUploadModal(initialFiles = null) {
      if (window.IS_READONLY) return;
      await updateCwd();

      const modal = document.getElementById('upload-modal');
      const destInput = document.getElementById('upload-dest-input');

      if (modal) modal.classList.remove('hidden');
      if (destInput) {
        destInput.value = currentCwd;
      }

      if (!uploadDestAutoComp) {
        uploadDestAutoComp = new PathAutocomplete({
          inputEl: document.getElementById('upload-dest-input'),
          dropdownEl: document.getElementById('upload-dest-suggestions'),
          spinnerEl: document.getElementById('upload-dest-spinner'),
          filterType: 'dir_only'
        });
      }

      if (initialFiles && initialFiles.length > 0) {
        pendingUploadFiles = Array.from(initialFiles);
      } else {
        pendingUploadFiles = [];
      }
      renderUploadFilesList();

      setTimeout(() => {
        if (destInput) destInput.focus();
        if (uploadDestAutoComp) uploadDestAutoComp.refreshSuggestions();
      }, 50);
    }

    function closeUploadModal() {
      const modal = document.getElementById('upload-modal');
      if (modal) modal.classList.add('hidden');
      if (uploadDestAutoComp) uploadDestAutoComp.hide();
      pendingUploadFiles = [];
    }

    function handleModalFileSelect(e) {
      if (e.target && e.target.files && e.target.files.length > 0) {
        for (let i = 0; i < e.target.files.length; i++) {
          pendingUploadFiles.push(e.target.files[i]);
        }
        renderUploadFilesList();
      }
    }

    function removePendingFile(idx) {
      if (idx >= 0 && idx < pendingUploadFiles.length) {
        pendingUploadFiles.splice(idx, 1);
        renderUploadFilesList();
      }
    }

    function renderUploadFilesList() {
      const listEl = document.getElementById('upload-files-list');
      const startBtn = document.getElementById('start-upload-btn');
      if (!listEl) return;

      if (!pendingUploadFiles.length) {
        listEl.innerHTML = '<div class="text-slate-500 text-[11px] text-center py-3">No files selected. Drag & drop files here or click "+ Select More".</div>';
        if (startBtn) startBtn.disabled = true;
        return;
      }

      if (startBtn) startBtn.disabled = false;
      let totalSize = 0;
      listEl.innerHTML = pendingUploadFiles.map((file, idx) => {
        totalSize += file.size || 0;
        const safeName = escapeHtml(file.name || 'unnamed');
        return `
          <div class="flex items-center justify-between px-2 py-1 bg-slate-900 rounded-lg text-slate-300">
            <span class="truncate max-w-[280px]">${safeName}</span>
            <div class="flex items-center gap-2 shrink-0">
              <span class="text-[10px] text-slate-500">${formatBytes(file.size || 0)}</span>
              <button type="button" onclick="removePendingFile(${idx})" class="text-slate-400 hover:text-red-400 transition text-xs">✕</button>
            </div>
          </div>
        `;
      }).join('');
    }

    async function handleUploadSubmit(e) {
      e.preventDefault();
      if (!pendingUploadFiles || !pendingUploadFiles.length) {
        showToast('Please select at least one file to upload');
        return;
      }

      const destInput = document.getElementById('upload-dest-input');
      const targetDest = (destInput && destInput.value.trim()) ? destInput.value.trim() : currentCwd;
      const filesToUpload = [...pendingUploadFiles];

      closeUploadModal();
      await executeFileUpload(filesToUpload, targetDest);
    }

    async function executeFileUpload(files, destDirectory) {
      if (!files || files.length === 0) return;

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
            const tabParam = activeTabId ? `tab=${encodeURIComponent(activeTabId)}` : '';
            const tokenParam = sessionToken ? `token=${encodeURIComponent(sessionToken)}` : '';
            const nameParam = `name=${encodeURIComponent(file.name)}`;
            const destParam = `dest=${encodeURIComponent(destDirectory)}`;
            const qs = [nameParam, destParam, tabParam, tokenParam].filter(Boolean).join('&');
            const url = `/api/upload?${qs}`;
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
                showToast(`Uploaded ${file.name} to ${destDirectory}`);
                resolve();
              } else {
                let errMsg = `Upload failed (${xhr.status})`;
                try {
                  const res = JSON.parse(xhr.responseText);
                  if (res && res.error) errMsg = res.error;
                } catch(e) {
                  const titleMatch = xhr.responseText.match(/<title>(.*?)<\/title>/i);
                  if (titleMatch && titleMatch[1]) errMsg = titleMatch[1];
                  else if (xhr.responseText.length > 0 && xhr.responseText.length < 150) errMsg = xhr.responseText.trim();
                }
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
            body: `Uploaded ${successCount} file(s) to ${destDirectory}`
          });
        }
      }
    }

    // ==================== DOWNLOAD MODAL & FILE AUTOCOMPLETE ====================
    async function openDownloadModal() {
      await updateCwd();
      const modal = document.getElementById('download-modal');
      const input = document.getElementById('download-path-input');
      const errorBanner = document.getElementById('download-error-banner');
      if (modal) modal.classList.remove('hidden');
      if (errorBanner) errorBanner.classList.add('hidden');

      if (!downloadAutoComp) {
        downloadAutoComp = new PathAutocomplete({
          inputEl: document.getElementById('download-path-input'),
          dropdownEl: document.getElementById('download-suggestions'),
          spinnerEl: document.getElementById('download-spinner'),
          countBadgeEl: document.getElementById('download-count-badge'),
          filterType: 'all',
          onSelect: () => {
            const errorBanner = document.getElementById('download-error-banner');
            if (errorBanner) errorBanner.classList.add('hidden');
          }
        });
      }

      if (input) {
        input.value = '';
        setTimeout(() => {
          input.focus();
          if (downloadAutoComp) downloadAutoComp.refreshSuggestions();
        }, 50);
      }
    }

    function closeDownloadModal() {
      const modal = document.getElementById('download-modal');
      const errorBanner = document.getElementById('download-error-banner');
      if (modal) modal.classList.add('hidden');
      if (errorBanner) errorBanner.classList.add('hidden');
      if (downloadAutoComp) downloadAutoComp.hide();
    }

    function showDownloadModalError(msg) {
      const errorBanner = document.getElementById('download-error-banner');
      const errorMsgEl = document.getElementById('download-error-msg');
      if (errorBanner && errorMsgEl) {
        errorMsgEl.textContent = msg;
        errorBanner.classList.remove('hidden');
      }
      showToast(msg);
    }

    async function handleDownloadSubmit(e) {
      e.preventDefault();
      const input = document.getElementById('download-path-input');
      const submitBtn = document.getElementById('download-submit-btn');
      const errorBanner = document.getElementById('download-error-banner');
      if (!input) return;
      const val = input.value.trim();
      if (!val) return;

      if (errorBanner) errorBanner.classList.add('hidden');
      const tabParam = activeTabId ? `tab=${encodeURIComponent(activeTabId)}` : '';
      const tokenParam = sessionToken ? `token=${encodeURIComponent(sessionToken)}` : '';
      const fileParam = `file=${encodeURIComponent(val)}`;
      const qs = [fileParam, tabParam, tokenParam].filter(Boolean).join('&');
      const dlUrl = `/api/download?${qs}`;

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.classList.add('opacity-75');
      }

      try {
        // Fast preflight check (~10ms) to ensure file/directory exists and auth is valid
        const res = await fetch(dlUrl, { method: 'HEAD' });

        if (!res.ok) {
          let errMsg = `Download failed (HTTP ${res.status})`;
          try {
            const errRes = await fetch(dlUrl, { method: 'GET' });
            const data = await errRes.json();
            if (data && data.error) errMsg = data.error;
          } catch(e) {}
          showDownloadModalError(errMsg);
          return;
        }

        // Verified valid: close modal immediately and trigger native browser streaming
        closeDownloadModal();
        const a = document.createElement('a');
        a.href = dlUrl;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        showToast('Download started');
      } catch(err) {
        showDownloadModalError(`Download error: ${err.message || 'connection failed'}`);
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.classList.remove('opacity-75');
        }
      }
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
          const safeLabel = escapeHtml(s.label || 'Shared Session');
          return `
            <div class="flex items-center justify-between p-2.5 rounded-lg bg-slate-950/60 border border-slate-800 gap-2 font-mono">
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <span class="font-semibold text-slate-200 truncate">${safeLabel}</span>
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
        'settings-btn', 'new-tab-btn', 'mobile-accessory-bar'
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

    // ==================== TERMINAL FILE HOVER QUICK ACTIONS & IMAGE LIGHTBOX ====================
    let currentPreviewPath = '';
    let currentPreviewTabId = '';
    let imageZoom = 1.0;
    let imagePanX = 0;
    let imagePanY = 0;
    let isPanningImage = false;
    let panStartX = 0;
    let panStartY = 0;
    let fileMenuHideTimer = null;
    let imageChipTimer = null;
    const recentDetectedImages = new Set();

    const BLOCKED_EXTENSIONS = new Set([
      'exe', 'bin', 'dll', 'so', 'dylib', 'o', 'a', 'obj', 'pyc', 'pyo', 'class', 'wasm',
      'zip', 'tar', 'gz', 'tgz', 'bz2', 'xz', '7z', 'rar', 'zst', 'iso', 'dmg', 'deb', 'rpm', 'apk', 'msi',
      'mp4', 'mkv', 'avi', 'mov', 'webm', 'flv', 'wmv', 'mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a',
      'pdf', 'docx', 'xlsx', 'pptx', 'sqlite', 'db', 'sqlite3'
    ]);

    const IMAGE_EXTENSIONS = new Set([
      'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico', 'tiff'
    ]);

    const KNOWN_SPECIAL_FILES = new Set(['dockerfile', 'makefile', 'license', 'procfile', 'gemfile']);

    function cleanCandidatePath(p) {
      if (!p) return '';
      let s = p.trim();
      s = s.replace(/^["'`]+|["'`]+$/g, '');
      s = s.replace(/["'`]/g, '');
      return s;
    }

    function isPathValidCandidate(candidate) {
      if (!candidate || candidate.length < 2) return false;
      const s = cleanCandidatePath(candidate);
      if (s.startsWith('http://') || s.startsWith('https://') || s.startsWith('ftp://') || s.startsWith('git@')) return false;
      if (s.startsWith('-')) return false;
      if (/^[0-9.]+$/.test(s)) return false;
      if (s.includes(':') && !/^[a-zA-Z]:[/\\]/.test(s)) return false;

      const hasSlash = s.includes('/') || s.startsWith('~');
      const base = s.split('/').pop();
      if (hasSlash) return true;
      if (base.startsWith('.') && base.length > 2) return true;
      if (KNOWN_SPECIAL_FILES.has(base.toLowerCase())) return true;
      if (base.includes('.')) {
        const ext = base.split('.').pop().toLowerCase();
        if (/^[a-z0-9_+-]{1,12}$/.test(ext) && !/^\d+$/.test(ext)) return true;
      }
      return false;
    }

    const pathStatCache = new Map();

    async function fetchPathStat(path, tabId) {
      const clean = cleanCandidatePath(path);
      if (!clean) return null;
      const cacheKey = `${tabId || activeTabId || 'default'}:${clean}`;
      if (pathStatCache.has(cacheKey)) {
        const cached = pathStatCache.get(cacheKey);
        if (cached && (Date.now() - cached.ts < 15000)) {
          return cached.data;
        }
        pathStatCache.delete(cacheKey);
      }
      try {
        const fileParam = encodeURIComponent(clean);
        const tabParam = (tabId || activeTabId) ? `tab=${encodeURIComponent(tabId || activeTabId)}` : '';
        const tokenParam = sessionToken ? `token=${encodeURIComponent(sessionToken)}` : '';
        const qs = [fileParam ? `file=${fileParam}` : '', tabParam, tokenParam].filter(Boolean).join('&');
        const res = await fetch(`/api/stat?${qs}`);
        if (res.ok) {
          const data = await res.json();
          pathStatCache.set(cacheKey, { data, ts: Date.now() });
          return data;
        }
      } catch (err) {
        console.debug('fetchPathStat error', err);
      }
      return null;
    }

    function getFileCategory(path) {
      const base = path.split('/').pop() || path;
      const parts = base.split('.');
      const ext = (parts.length > 1 ? parts.pop() : '').toLowerCase();

      if (IMAGE_EXTENSIONS.has(ext)) {
        return { type: 'image', ext: ext, canEdit: false, canCat: false, isImage: true };
      }
      if (BLOCKED_EXTENSIONS.has(ext)) {
        let badge = 'BINARY';
        if (['zip', 'tar', 'gz', 'tgz', 'bz2', 'xz', '7z', 'rar', 'zst', 'iso', 'dmg', 'deb', 'rpm', 'apk', 'msi'].includes(ext)) badge = 'ARCHIVE';
        else if (['mp4', 'mkv', 'avi', 'mov', 'webm', 'flv', 'wmv'].includes(ext)) badge = 'VIDEO';
        else if (['mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a'].includes(ext)) badge = 'AUDIO';
        return { type: 'blocked', ext: ext, badge: badge, canEdit: false, canCat: false, isImage: false };
      }
      return { type: 'text', ext: ext, canEdit: true, canCat: true, isImage: false };
    }

    function quoteShellArg(arg) {
      if (!arg) return '""';
      if (arg.startsWith('~/')) {
        return '~/"' + arg.slice(2).replace(/"/g, '\\"') + '"';
      }
      return '"' + arg.replace(/"/g, '\\"') + '"';
    }

    function openTabWithCommand(title, command) {
      if (window.IS_READONLY) {
        showToast('Cannot run command in read-only mode');
        return;
      }
      const newTab = createNewTab(title, null, true);
      if (!newTab) return;

      let executed = false;
      const sendCmd = () => {
        if (executed) return;
        if (newTab.socket && newTab.socket.readyState === WebSocket.OPEN) {
          executed = true;
          newTab.socket.send(new TextEncoder().encode(command + '\r'));
        } else {
          setTimeout(sendCmd, 80);
        }
      };

      setTimeout(sendCmd, 350);
    }

    function buildImageUrl(path, tabId, isDownload = false) {
      const endpoint = isDownload ? '/api/download' : '/api/preview';
      const fileParam = `file=${encodeURIComponent(path)}`;
      const tabParam = (tabId || activeTabId) ? `tab=${encodeURIComponent(tabId || activeTabId)}` : '';
      const tokenParam = sessionToken ? `token=${encodeURIComponent(sessionToken)}` : '';
      const qs = [fileParam, tabParam, tokenParam].filter(Boolean).join('&');
      return `${endpoint}?${qs}`;
    }

    function registerFileLinkProvider(term, tabId) {
      if (!term || typeof term.registerLinkProvider !== 'function') return;

      term.registerLinkProvider({
        async provideLinks(bufferLineNumber, callback) {
          const line = term.buffer.active.getLine(bufferLineNumber - 1);
          if (!line) {
            callback(undefined);
            return;
          }
          const lineText = line.translateToString(true);
          if (!lineText) {
            callback(undefined);
            return;
          }

          const rawRegex = /(?:^|[\s"'`(\[<])((?:[~.A-Za-z0-9_-]*\/)?(?:[A-Za-z0-9_.-]+\/)*[A-Za-z0-9_.-]+(?:\.[A-Za-z0-9_+-]+)?)(?=[\s"'`()\[\]<>{},;:!?.]|$)/gi;
          const candidates = [];
          let match;

          while ((match = rawRegex.exec(lineText)) !== null) {
            const fullMatch = match[0];
            const candidate = match[1];
            if (!isPathValidCandidate(candidate)) continue;

            const startOffset = match.index + fullMatch.indexOf(candidate);
            const endOffset = startOffset + candidate.length;
            candidates.push({ candidate, startOffset, endOffset });
          }

          if (candidates.length === 0) {
            callback(undefined);
            return;
          }

          const validLinks = [];
          await Promise.all(candidates.map(async ({ candidate, startOffset, endOffset }) => {
            const clean = cleanCandidatePath(candidate);
            const stat = await fetchPathStat(clean, tabId);
            if (!stat || stat.exists === false) {
              return;
            }

            validLinks.push({
              range: {
                start: { x: startOffset + 1, y: bufferLineNumber },
                end: { x: endOffset, y: bufferLineNumber }
              },
              text: candidate,
              activate: async (e, text) => {
                const targetClean = cleanCandidatePath(text);
                const targetStat = await fetchPathStat(targetClean, tabId);
                if (targetStat && targetStat.is_dir) {
                  openTabWithCommand(`cd ${targetStat.name || targetClean.split('/').pop() || targetClean}`, `cd ${quoteShellArg(targetStat.path || targetClean)}`);
                  return;
                }
                const cat = getFileCategory(targetClean);
                if (cat.isImage) {
                  openImagePreviewModal(targetClean, tabId);
                } else if (cat.canCat || (targetStat && targetStat.is_file)) {
                  openFileContentModal(targetStat ? (targetStat.path || targetClean) : targetClean, tabId, targetStat);
                } else {
                  showFileHoverMenu(e, text, tabId, targetStat);
                }
              },
              hover: (e, text) => {
                showFileHoverMenu(e, text, tabId, stat);
              },
              leave: () => {
                hideFileHoverMenu();
              }
            });
          }));

          validLinks.sort((a, b) => a.range.start.x - b.range.start.x);
          callback(validLinks.length > 0 ? validLinks : undefined);
        }
      });
    }

    const registerImageLinkProvider = registerFileLinkProvider;

    function showFileHoverMenu(event, rawPath, tabId, prefetchedStat) {
      clearTimeout(fileMenuHideTimer);
      const menu = document.getElementById('file-hover-menu');
      if (!menu) return;

      const path = cleanCandidatePath(rawPath);
      const fileName = path.split('/').pop() || path;
      const cat = getFileCategory(path);

      const nameEl = document.getElementById('file-hover-name');
      const pathEl = document.getElementById('file-hover-path');
      const iconEl = document.getElementById('file-hover-icon');
      const thumbEl = document.getElementById('file-hover-thumb');
      const badgeEl = document.getElementById('file-hover-badge');
      const btnCat = document.getElementById('file-hover-btn-cat');
      const btnCatText = document.getElementById('file-hover-btn-cat-text');
      const btnEdit = document.getElementById('file-hover-btn-edit');
      const btnDir = document.getElementById('file-hover-btn-dir');
      const btnImg = document.getElementById('file-hover-btn-img');
      const btnCopy = document.getElementById('file-hover-btn-copy');
      const btnDl = document.getElementById('file-hover-btn-dl');

      if (nameEl) nameEl.textContent = fileName;
      if (pathEl) pathEl.textContent = path;
      if (btnDir) btnDir.classList.add('hidden');

      // Icon & thumbnail
      if (cat.isImage) {
        if (iconEl) iconEl.classList.add('hidden');
        if (thumbEl) {
          thumbEl.src = buildImageUrl(path, tabId);
          thumbEl.classList.remove('hidden');
        }
      } else {
        if (thumbEl) { thumbEl.classList.add('hidden'); thumbEl.src = ''; }
        if (iconEl) {
          iconEl.classList.remove('hidden');
          if (cat.badge === 'ARCHIVE') iconEl.textContent = '📦';
          else if (cat.badge === 'VIDEO') iconEl.textContent = '🎬';
          else if (cat.badge === 'AUDIO') iconEl.textContent = '🎵';
          else if (cat.badge === 'BINARY') iconEl.textContent = '⚙️';
          else iconEl.textContent = '📄';
        }
      }

      // Badge
      if (badgeEl) {
        if (cat.badge) {
          badgeEl.textContent = cat.badge;
          badgeEl.classList.remove('hidden');
        } else {
          badgeEl.classList.add('hidden');
        }
      }

      // View File (in-tab modal)
      if (btnCat) {
        if (cat.canCat) {
          btnCat.classList.remove('hidden');
          if (btnCatText) btnCatText.textContent = 'View File';
          btnCat.title = 'View file content in modal';
          btnCat.onclick = (e) => {
            e.stopPropagation();
            hideFileHoverMenu();
            openFileContentModal(path, tabId);
          };
        } else {
          btnCat.classList.add('hidden');
        }
      }

      // Edit (nano)
      if (btnEdit) {
        if (cat.canEdit) {
          btnEdit.classList.remove('hidden');
          btnEdit.onclick = (e) => {
            e.stopPropagation();
            hideFileHoverMenu();
            openTabWithCommand(`edit ${fileName}`, `nano ${quoteShellArg(path)}`);
          };
        } else {
          btnEdit.classList.add('hidden');
        }
      }

      // View Image (for images)
      if (btnImg) {
        if (cat.isImage) {
          btnImg.classList.remove('hidden');
          btnImg.onclick = (e) => {
            e.stopPropagation();
            hideFileHoverMenu();
            openImagePreviewModal(path, tabId);
          };
        } else {
          btnImg.classList.add('hidden');
        }
      }

      // Copy Path
      if (btnCopy) {
        btnCopy.onclick = (e) => {
          e.stopPropagation();
          hideFileHoverMenu();
          navigator.clipboard.writeText(path).then(() => {
            showToast('Path copied to clipboard!');
          }).catch(() => {
            showToast(path);
          });
        };
      }

      // Download
      if (btnDl) {
        btnDl.onclick = (e) => {
          e.stopPropagation();
          hideFileHoverMenu();
          const dlUrl = buildImageUrl(path, tabId, true);
          const a = document.createElement('a');
          a.href = dlUrl;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          showToast(`Downloading ${fileName}...`);
        };
      }

      // Position
      const posX = Math.min(event.clientX + 10, window.innerWidth - 340);
      let posY = event.clientY + 14;
      if (posY + 140 > window.innerHeight) {
        posY = Math.max(10, event.clientY - 95);
      }
      menu.style.left = `${posX}px`;
      menu.style.top = `${posY}px`;
      menu.classList.remove('hidden');

      menu.onmouseenter = () => clearTimeout(fileMenuHideTimer);
      menu.onmouseleave = () => {
        fileMenuHideTimer = setTimeout(hideFileHoverMenu, 250);
      };

      function applyStat(stat) {
        if (!stat || menu.classList.contains('hidden')) return;
        if (stat.exists === false) {
          hideFileHoverMenu();
          return;
        }

        if (stat.is_dir) {
          if (nameEl) nameEl.textContent = (stat.name || fileName) + '/';
          if (pathEl) pathEl.textContent = stat.path || path;
          if (iconEl) {
            iconEl.classList.remove('hidden');
            iconEl.textContent = '📁';
          }
          if (thumbEl) thumbEl.classList.add('hidden');
          if (badgeEl) {
            badgeEl.textContent = 'DIR';
            badgeEl.classList.remove('hidden');
          }
          if (btnCat) btnCat.classList.add('hidden');
          if (btnEdit) btnEdit.classList.add('hidden');
          if (btnImg) btnImg.classList.add('hidden');
          if (btnDir) {
            btnDir.classList.remove('hidden');
            btnDir.onclick = (e) => {
              e.stopPropagation();
              hideFileHoverMenu();
              openTabWithCommand(`cd ${stat.name || fileName}`, `cd ${quoteShellArg(stat.path || path)}`);
            };
          }
        } else if (stat.is_file) {
          if (btnDir) btnDir.classList.add('hidden');
          if (!cat.isImage && !cat.badge) {
            if (btnCat) {
              btnCat.classList.remove('hidden');
              if (btnCatText) btnCatText.textContent = 'View File';
              btnCat.title = `View file content in modal${stat.lines !== null ? ` (${stat.lines} lines)` : ''}`;
              btnCat.onclick = (e) => {
                e.stopPropagation();
                hideFileHoverMenu();
                openFileContentModal(stat.path || path, tabId, stat);
              };
            }
            if (badgeEl && stat.lines !== null) {
              badgeEl.textContent = `${stat.lines}L`;
              badgeEl.classList.remove('hidden');
            }
          }
        }
      }

      if (prefetchedStat) {
        applyStat(prefetchedStat);
      } else {
        fetchPathStat(path, tabId).then(applyStat).catch(() => {});
      }
    }

    function hideFileHoverMenu() {
      fileMenuHideTimer = setTimeout(() => {
        const menu = document.getElementById('file-hover-menu');
        if (menu) menu.classList.add('hidden');
      }, 150);
    }

    let currentModalFilePath = '';
    let currentModalFileTabId = '';
    let currentModalFileContent = '';

    async function openFileContentModal(path, tabId, statData) {
      if (!path) return;
      hideFileHoverMenu();
      closeImagePreviewModal();
      currentModalFilePath = path;
      currentModalFileTabId = tabId || activeTabId;

      const modal = document.getElementById('file-content-modal');
      const titleEl = document.getElementById('file-modal-title');
      const pathEl = document.getElementById('file-modal-path');
      const lineBadge = document.getElementById('file-modal-line-badge');
      const sizeBadge = document.getElementById('file-modal-size-badge');
      const spinner = document.getElementById('file-modal-spinner');
      const errorEl = document.getElementById('file-modal-error');
      const errorMsg = document.getElementById('file-modal-error-msg');
      const lineNumEl = document.getElementById('file-modal-line-numbers');
      const codeTextEl = document.getElementById('file-modal-code-text');
      const metaLines = document.getElementById('file-modal-meta-lines');
      const metaSize = document.getElementById('file-modal-meta-size');

      const fileName = path.split('/').pop() || path;
      if (titleEl) titleEl.textContent = fileName;
      if (pathEl) pathEl.textContent = path;
      if (modal) modal.classList.remove('hidden');

      if (spinner) spinner.classList.remove('hidden');
      if (errorEl) errorEl.classList.add('hidden');
      if (lineNumEl) lineNumEl.textContent = '';
      if (codeTextEl) codeTextEl.textContent = '';

      try {
        const fileParam = encodeURIComponent(path);
        const tabParam = (tabId || activeTabId) ? `tab=${encodeURIComponent(tabId || activeTabId)}` : '';
        const tokenParam = sessionToken ? `token=${encodeURIComponent(sessionToken)}` : '';
        const qs = [fileParam ? `file=${fileParam}` : '', tabParam, tokenParam, 'inline=1'].filter(Boolean).join('&');
        const res = await fetch(`/api/view?${qs}`);
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}: Failed to read file`);
        }
        const text = await res.text();
        currentModalFileContent = text;

        const normalized = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
        const rawLines = normalized.split('\n');
        const hasTrailingNewline = normalized.endsWith('\n');
        const contentLines = (hasTrailingNewline && rawLines.length > 1) ? rawLines.slice(0, -1) : rawLines;
        const lineCount = normalized.length === 0 ? 0 : contentLines.length;
        const byteSize = new Blob([text]).size;

        if (lineBadge) lineBadge.textContent = `${lineCount} line${lineCount === 1 ? '' : 's'}`;
        if (sizeBadge) sizeBadge.textContent = formatBytes(byteSize);
        if (metaLines) metaLines.textContent = `Lines: ${lineCount}`;
        if (metaSize) metaSize.textContent = `Size: ${formatBytes(byteSize)}`;

        let lineNums = '';
        for (let i = 1; i <= lineCount; i++) {
          lineNums += (i === 1 ? '' : '\n') + i;
        }
        if (lineNumEl) lineNumEl.textContent = lineNums;
        if (codeTextEl) {
          codeTextEl.textContent = (hasTrailingNewline && rawLines.length > 1) ? normalized.slice(0, -1) : normalized;
        }
      } catch (err) {
        if (errorEl) errorEl.classList.remove('hidden');
        if (errorMsg) errorMsg.textContent = err.message || 'Unable to load file content';
      } finally {
        if (spinner) spinner.classList.add('hidden');
      }
    }

    function closeFileContentModal() {
      const modal = document.getElementById('file-content-modal');
      if (modal) modal.classList.add('hidden');
      currentModalFileContent = '';
      currentModalFilePath = '';
    }

    function copyModalFilePath() {
      if (!currentModalFilePath) return;
      navigator.clipboard.writeText(currentModalFilePath).then(() => {
        showToast('Path copied to clipboard!');
      }).catch(() => {
        showToast(currentModalFilePath);
      });
    }

    function copyModalFileContent() {
      if (currentModalFileContent === undefined || currentModalFileContent === null) return;
      navigator.clipboard.writeText(currentModalFileContent).then(() => {
        const copyLabel = document.getElementById('file-modal-copy-label');
        if (copyLabel) {
          const orig = copyLabel.textContent;
          copyLabel.textContent = 'Copied!';
          setTimeout(() => { copyLabel.textContent = orig; }, 1500);
        }
        showToast('File content copied to clipboard!');
      }).catch(() => {
        showToast('Failed to copy content');
      });
    }

    function editModalFileInNewTab() {
      if (!currentModalFilePath) return;
      const p = currentModalFilePath;
      const fileName = p.split('/').pop() || p;
      closeFileContentModal();
      openTabWithCommand(`edit ${fileName}`, `nano ${quoteShellArg(p)}`);
    }

    function downloadModalFile() {
      if (!currentModalFilePath) return;
      const dlUrl = buildImageUrl(currentModalFilePath, currentModalFileTabId, true);
      const a = document.createElement('a');
      a.href = dlUrl;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      showToast(`Downloading ${currentModalFilePath.split('/').pop()}...`);
    }

    function openImagePreviewModal(path, tabId) {
      if (!path) return;
      hideFileHoverMenu();
      dismissImageOutputChip();

      currentPreviewPath = path;
      currentPreviewTabId = tabId || activeTabId;

      const modal = document.getElementById('image-preview-modal');
      const img = document.getElementById('image-modal-img');
      const spinner = document.getElementById('image-modal-spinner');
      const errBox = document.getElementById('image-modal-error');
      const titleEl = document.getElementById('image-modal-title');
      const pathEl = document.getElementById('image-modal-path');
      const metaDims = document.getElementById('image-modal-meta-dims');
      const metaSize = document.getElementById('image-modal-meta-size');
      const metaType = document.getElementById('image-modal-meta-type');

      const fileName = path.split('/').pop() || path;
      const ext = fileName.split('.').pop() || 'image';

      if (titleEl) titleEl.textContent = fileName;
      if (pathEl) pathEl.textContent = path;
      if (metaType) metaType.textContent = `Type: ${ext.toUpperCase()}`;
      if (metaDims) metaDims.textContent = 'Dimensions: loading...';
      if (metaSize) metaSize.textContent = 'Size: ...';

      imageZoom = 1.0;
      imagePanX = 0;
      imagePanY = 0;
      updateImageTransform();

      if (errBox) errBox.classList.add('hidden');
      if (spinner) spinner.classList.remove('hidden');
      if (modal) modal.classList.remove('hidden');

      const previewUrl = buildImageUrl(path, currentPreviewTabId);

      fetch(previewUrl, { method: 'HEAD' }).then(r => {
        if (r.ok) {
          const len = r.headers.get('content-length');
          if (len && metaSize) {
            metaSize.textContent = `Size: ${formatBytes(parseInt(len, 10))}`;
          }
        }
      }).catch(() => {});

      img.onload = () => {
        if (spinner) spinner.classList.add('hidden');
        if (metaDims) {
          metaDims.textContent = `Dimensions: ${img.naturalWidth} × ${img.naturalHeight}px`;
        }
        const vp = document.getElementById('image-modal-viewport');
        if (vp && (img.naturalWidth > vp.clientWidth * 0.9 || img.naturalHeight > vp.clientHeight * 0.9)) {
          fitImagePreviewToScreen();
        }
      };

      img.onerror = () => {
        if (spinner) spinner.classList.add('hidden');
        if (errBox) {
          const errMsg = document.getElementById('image-modal-error-msg');
          if (errMsg) errMsg.textContent = `Could not load image: "${path}" (file not found or access denied)`;
          errBox.classList.remove('hidden');
        }
      };

      img.src = previewUrl;
    }

    function closeImagePreviewModal() {
      const modal = document.getElementById('image-preview-modal');
      const img = document.getElementById('image-modal-img');
      if (modal) modal.classList.add('hidden');
      if (img) img.src = '';
      currentPreviewPath = '';
    }

    function updateImageTransform() {
      const img = document.getElementById('image-modal-img');
      const zoomEl = document.getElementById('image-modal-zoom');
      if (img) {
        img.style.transform = `translate(${imagePanX}px, ${imagePanY}px) scale(${imageZoom})`;
      }
      if (zoomEl) {
        zoomEl.textContent = `${Math.round(imageZoom * 100)}%`;
      }
    }

    function zoomImagePreview(delta) {
      imageZoom = Math.min(8.0, Math.max(0.1, imageZoom + delta));
      updateImageTransform();
    }

    function resetImagePreviewZoom() {
      imageZoom = 1.0;
      imagePanX = 0;
      imagePanY = 0;
      updateImageTransform();
    }

    function fitImagePreviewToScreen() {
      const vp = document.getElementById('image-modal-viewport');
      const img = document.getElementById('image-modal-img');
      if (!vp || !img || !img.naturalWidth || !img.naturalHeight) return;
      const pad = 48;
      const scaleX = (vp.clientWidth - pad) / img.naturalWidth;
      const scaleY = (vp.clientHeight - pad) / img.naturalHeight;
      imageZoom = Math.min(1.0, Math.min(scaleX, scaleY));
      imagePanX = 0;
      imagePanY = 0;
      updateImageTransform();
    }

    function copyModalImagePath() {
      if (!currentPreviewPath) return;
      navigator.clipboard.writeText(currentPreviewPath).then(() => {
        showToast('Path copied to clipboard!');
      }).catch(() => {
        showToast(currentPreviewPath);
      });
    }

    function downloadModalImage() {
      if (!currentPreviewPath) return;
      const dlUrl = buildImageUrl(currentPreviewPath, currentPreviewTabId, true);
      const a = document.createElement('a');
      a.href = dlUrl;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      showToast('Download started');
    }

    function openModalImageInNewTab() {
      if (!currentPreviewPath) return;
      const previewUrl = buildImageUrl(currentPreviewPath, currentPreviewTabId, false);
      window.open(previewUrl, '_blank');
    }

    function showImageOutputChip(path, tabId) {
      const chip = document.getElementById('image-output-chip');
      const img = document.getElementById('image-chip-img');
      const nameEl = document.getElementById('image-chip-name');
      const dimsEl = document.getElementById('image-chip-dims');
      const viewBtn = document.getElementById('image-chip-view-btn');
      const thumbBox = document.getElementById('image-chip-thumb-container');
      if (!chip || !img) return;

      clearTimeout(imageChipTimer);

      const fileName = path.split('/').pop() || path;
      if (nameEl) nameEl.textContent = fileName;
      if (dimsEl) dimsEl.textContent = 'Image output detected';

      const previewUrl = buildImageUrl(path, tabId);
      img.onload = () => {
        if (dimsEl) dimsEl.textContent = `${img.naturalWidth} × ${img.naturalHeight}px`;
      };
      img.onerror = () => {
        chip.classList.add('hidden');
      };
      img.src = previewUrl;

      const openAction = () => openImagePreviewModal(path, tabId);
      if (viewBtn) viewBtn.onclick = openAction;
      if (thumbBox) thumbBox.onclick = openAction;

      chip.classList.remove('hidden');
      imageChipTimer = setTimeout(() => {
        dismissImageOutputChip();
      }, 8000);
    }

    function dismissImageOutputChip() {
      clearTimeout(imageChipTimer);
      const chip = document.getElementById('image-output-chip');
      if (chip) chip.classList.add('hidden');
    }

    function detectImageOutputInChunk(tab, data) {
      if (!data) return;
      let text = '';
      if (typeof data === 'string') {
        text = data;
      } else if (data instanceof ArrayBuffer || ArrayBuffer.isView(data)) {
        try {
          text = new TextDecoder().decode(data);
        } catch(e) { return; }
      }
      if (!text || text.length < 5) return;
      const clean = text.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, '');
      const regex = /(?:^|[\s"'`(\[<])((?:[~.A-Za-z0-9_-]*\/)?(?:[A-Za-z0-9_.-]+\/)*[A-Za-z0-9_.-]+\.(?:png|jpe?g|gif|webp|svg|bmp|ico))(?=[\s"'`()\[\]<>{},;:!?.]|$)/gi;
      let match;
      while ((match = regex.exec(clean)) !== null) {
        const imgPath = match[1];
        if (recentDetectedImages.has(imgPath)) continue;
        recentDetectedImages.add(imgPath);
        if (recentDetectedImages.size > 100) {
          const first = recentDetectedImages.values().next().value;
          recentDetectedImages.delete(first);
        }
        showImageOutputChip(imgPath, tab ? tab.id : activeTabId);
        break;
      }
    }

    function setupImageViewerInteractions() {
      const vp = document.getElementById('image-modal-viewport');
      if (!vp) return;

      vp.addEventListener('mousedown', (e) => {
        if (e.target.closest('button')) return;
        isPanningImage = true;
        panStartX = e.clientX - imagePanX;
        panStartY = e.clientY - imagePanY;
        vp.classList.add('cursor-grabbing');
        vp.classList.remove('cursor-grab');
      });

      window.addEventListener('mousemove', (e) => {
        if (!isPanningImage) return;
        imagePanX = e.clientX - panStartX;
        imagePanY = e.clientY - panStartY;
        updateImageTransform();
      });

      window.addEventListener('mouseup', () => {
        if (isPanningImage) {
          isPanningImage = false;
          if (vp) {
            vp.classList.remove('cursor-grabbing');
            vp.classList.add('cursor-grab');
          }
        }
      });

      vp.addEventListener('wheel', (e) => {
        e.preventDefault();
        const factor = e.deltaY < 0 ? 1.15 : 0.85;
        imageZoom = Math.min(8.0, Math.max(0.1, imageZoom * factor));
        updateImageTransform();
      }, { passive: false });

      window.addEventListener('keydown', (e) => {
        const modal = document.getElementById('image-preview-modal');
        if (modal && !modal.classList.contains('hidden')) {
          if (e.key === 'Escape') {
            e.preventDefault();
            closeImagePreviewModal();
            return;
          } else if (e.key === '+' || e.key === '=') {
            e.preventDefault();
            zoomImagePreview(0.25);
            return;
          } else if (e.key === '-' || e.key === '_') {
            e.preventDefault();
            zoomImagePreview(-0.25);
            return;
          } else if (e.key === '0') {
            e.preventDefault();
            resetImagePreviewZoom();
            return;
          }
        }

        const fileModal = document.getElementById('file-content-modal');
        if (fileModal && !fileModal.classList.contains('hidden')) {
          if (e.key === 'Escape') {
            e.preventDefault();
            closeFileContentModal();
            return;
          }
        }
      });
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

    function saveTabsState() {
      if (window.IS_READONLY) return;
      try {
        const tabList = Object.keys(tabs).map(id => ({
          id: id,
          title: tabs[id].title || 'bash'
        }));
        localStorage.setItem('fire_ssh_open_tabs', JSON.stringify(tabList));
        if (activeTabId) {
          localStorage.setItem('fire_ssh_active_tab', activeTabId);
        }
      } catch (e) {}
    }

    async function initTerminal(knownServerTabs) {
      if (Object.keys(tabs).length > 0) {
        initGlobalShortcuts();
        return;
      }

      let tabsToRestore = [];
      let savedActiveTab = null;

      // 1. Server-reported tabs (passed from checkAuth/handleLogin or fetched via /api/tabs)
      let serverTabs = [];
      if (Array.isArray(knownServerTabs) && knownServerTabs.length > 0) {
        serverTabs = knownServerTabs.map(t => ({ id: t.id, title: t.title || 'bash' }));
      } else if (!window.IS_READONLY) {
        try {
          const res = await fetch('/api/tabs');
          if (res.ok) {
            const data = await res.json();
            if (data && Array.isArray(data.tabs) && data.tabs.length > 0) {
              serverTabs = data.tabs.map(t => ({ id: t.id, title: t.title || 'bash' }));
            }
          }
        } catch (e) {}
      }

      // 2. Read client localStorage state
      let storedList = [];
      if (!window.IS_READONLY) {
        try {
          savedActiveTab = localStorage.getItem('fire_ssh_active_tab');
          const stored = localStorage.getItem('fire_ssh_open_tabs');
          if (stored) {
            const parsed = JSON.parse(stored);
            if (Array.isArray(parsed) && parsed.length > 0) {
              storedList = parsed;
            }
          }
        } catch (e) {}
      }

      // 3. Resolve tabs to restore:
      if (serverTabs.length > 0) {
        // Active server session: Server is the single source of truth for alive sessions.
        // We preserve user-reordered tab sequence and custom renamed titles from storedList,
        // but strictly drop any closed or dead tabs not currently reported by the server.
        const serverTabMap = new Map();
        serverTabs.forEach(t => serverTabMap.set(t.id, t));

        if (storedList.length > 0) {
          storedList.forEach(t => {
            if (t && t.id && serverTabMap.has(t.id)) {
              const sTab = serverTabMap.get(t.id);
              tabsToRestore.push({
                id: t.id,
                title: t.title || sTab.title || 'bash'
              });
              serverTabMap.delete(t.id);
            }
          });
        }
        // Append any live server tabs that were not in storedList
        serverTabMap.forEach(sTab => {
          tabsToRestore.push(sTab);
        });
      } else if (!window.IS_READONLY && storedList.length > 0) {
        // Fallback for daemon restart / cold start: restore previously saved tab layout
        tabsToRestore = storedList;
      }

      // 4. Fallback: single tab if nothing to restore
      if (tabsToRestore.length === 0) {
        createNewTab('bash');
      } else {
        // Determine target active tab
        let targetActiveId = savedActiveTab;
        if (!targetActiveId || !tabsToRestore.some(t => t.id === targetActiveId)) {
          targetActiveId = tabsToRestore[0].id;
        }

        tabsToRestore.forEach(tabInfo => {
          if (!tabs[tabInfo.id]) {
            const isTarget = tabInfo.id === targetActiveId;
            createNewTab(tabInfo.title || 'bash', tabInfo.id, isTarget);
          }
        });

        if (targetActiveId && tabs[targetActiveId]) {
          switchTab(targetActiveId);
        }
      }

      initGlobalShortcuts();
      saveTabsState();
      if (!window.tabSyncTimer && !window.IS_READONLY) {
        window.tabSyncTimer = setInterval(syncServerTabs, 10000);
      }
    }

    let isSyncingTabs = false;
    async function syncServerTabs() {
      if (window.IS_READONLY || isSyncingTabs) return;
      isSyncingTabs = true;
      try {
        const res = await fetch('/api/tabs');
        if (!res.ok) return;
        const data = await res.json();
        if (!data || !Array.isArray(data.tabs)) return;

        const serverTabs = data.tabs;
        const serverTabIds = new Set(serverTabs.map(t => t.id));
        const localTabIds = Object.keys(tabs);

        // 1. Add any tabs that exist on the server but not locally
        serverTabs.forEach(sTab => {
          if (!tabs[sTab.id]) {
            createNewTab(sTab.title || 'bash', sTab.id, false);
          } else {
            if (sTab.title && tabs[sTab.id].title !== sTab.title) {
              tabs[sTab.id].title = sTab.title;
            }
          }
        });

        // 2. Remove any local tabs that no longer exist on the server
        const now = Date.now();
        localTabIds.forEach(localId => {
          if (!serverTabIds.has(localId)) {
            const localTab = tabs[localId];
            if (localTab && localTab.createdAt && (now - localTab.createdAt < 4000)) {
              return;
            }
            closeTab(localId, true);
          }
        });

        if (Object.keys(tabs).length === 0) {
          createNewTab('bash', 'tab-1', true);
        } else {
          renderTabsList();
          saveTabsState();
        }
      } catch (e) {
      } finally {
        isSyncingTabs = false;
      }
    }

    function createNewTab(initialTitle, explicitTabId, shouldSwitch = true) {
      let tabId;
      if (explicitTabId) {
        tabId = explicitTabId;
        const match = tabId.match(/^tab-(\d+)$/);
        if (match) {
          const num = parseInt(match[1], 10);
          if (num > tabSequence) tabSequence = num;
        }
      } else {
        tabSequence++;
        tabId = 'tab-' + tabSequence;
      }

      if (tabs[tabId]) {
        if (shouldSwitch) switchTab(tabId);
        return tabs[tabId];
      }
      const tabIndex = Object.keys(tabs).length + 1;
      const title = initialTitle || (window.SESSION_TITLE && tabIndex === 1 ? window.SESSION_TITLE : 'bash');

      const container = document.getElementById('terminal-container');
      if (!container) return;

      const mountEl = document.createElement('div');
      mountEl.id = `term-mount-${tabId}`;
      mountEl.className = 'w-full h-full' + (shouldSwitch ? '' : ' hidden');
      container.appendChild(mountEl);

      const isReadOnly = !!window.IS_READONLY;
      const t = new Terminal({
        cursorBlink: !isReadOnly,
        disableStdin: isReadOnly,
        cursorStyle: isReadOnly ? 'underline' : 'bar',
        fontSize: currentFontSize,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
        scrollback: 10000,
        fastScrollModifier: 'alt',
        smoothScrollDuration: 0,
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
      if (typeof registerFileLinkProvider === 'function') {
        registerFileLinkProvider(t, tabId);
      }

      // Hardware accelerated GPU rendering (with automatic canvas fallback)
      if (typeof WebglAddon !== 'undefined' && WebglAddon.WebglAddon) {
        try {
          const webgl = new WebglAddon.WebglAddon();
          webgl.onContextLoss(() => {
            try { webgl.dispose(); } catch(e) {}
          });
          t.loadAddon(webgl);
        } catch(e) {
          // Fallback seamlessly to standard canvas renderer if WebGL unavailable
        }
      }

      mountEl.addEventListener('mousedown', () => {
        if (splitMode !== 'none' && activeTabId !== tabId) {
          activeTabId = tabId;
          applySplitLayout();
          renderTabsList();
        }
        if (!window.IS_READONLY && t.textarea) {
          t.focus();
        }
      });

      mountEl.addEventListener('pointerdown', () => {
        if (!window.IS_READONLY && t && fa) {
          fa.fit();
          sendResize(tabObj);
        }
      });

      mountEl.addEventListener('touchend', () => {
        if (!window.IS_READONLY && t.textarea) {
          if (document.activeElement !== t.textarea) {
            t.focus();
          }
        }
      });

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
        cwd: '/root',
        createdAt: Date.now(),
        lastSentCols: null,
        lastSentRows: null
      };

      tabs[tabId] = tabObj;

      setupTabEvents(tabObj);
      connectTabWebSocket(tabObj);
      if (shouldSwitch) {
        switchTab(tabId);
      } else {
        renderTabsList();
      }
      saveTabsState();
      return tabObj;
    }

    function toggleSplitMenu() {
      const menu = document.getElementById('split-menu');
      if (menu) menu.classList.toggle('hidden');
    }

    function closeSplitMenu() {
      const menu = document.getElementById('split-menu');
      if (menu) menu.classList.add('hidden');
    }

    function setSplitMode(mode) {
      let tabKeys = Object.keys(tabs);
      if (mode === 'grid') {
        // Ensure at least 4 tabs exist for Quad Grid mode
        while (Object.keys(tabs).length < 4) {
          const nextIndex = Object.keys(tabs).length + 1;
          createNewTab(`pane-${nextIndex}`, null, false);
        }
        tabKeys = Object.keys(tabs);
      } else if (mode === 'triple-left' || mode === 'triple-col') {
        // Ensure at least 3 tabs exist for 3-pane split modes
        while (Object.keys(tabs).length < 3) {
          const nextIndex = Object.keys(tabs).length + 1;
          createNewTab(`pane-${nextIndex}`, null, false);
        }
        tabKeys = Object.keys(tabs);
      } else if (mode !== 'none' && tabKeys.length < 2) {
        // Automatically create a second tab if user enters dual split mode with only 1 tab
        createNewTab('split-2', null, false);
        tabKeys = Object.keys(tabs);
      }

      splitMode = mode;
      const splitIcon = document.getElementById('split-icon');
      const splitBtn = document.getElementById('split-btn');
      
      if (splitMode === 'grid') {
        if (splitIcon) splitIcon.textContent = '⊞';
        if (splitBtn) splitBtn.className = 'px-2 py-1 text-xs bg-orange-600/30 text-orange-300 border border-orange-500/50 rounded-lg transition font-mono flex items-center gap-1';
        const others = tabKeys.filter(id => id !== activeTabId);
        gridTabIds = [activeTabId, others[0], others[1], others[2]].filter(Boolean);
        tripleTabIds = [];
        dualTabIds = [];
        secondaryTabId = null;
      } else if (splitMode === 'triple-left') {
        if (splitIcon) splitIcon.textContent = '⚿';
        if (splitBtn) splitBtn.className = 'px-2 py-1 text-xs bg-orange-600/30 text-orange-300 border border-orange-500/50 rounded-lg transition font-mono flex items-center gap-1';
        const others = tabKeys.filter(id => id !== activeTabId);
        tripleTabIds = [activeTabId, others[0], others[1]].filter(Boolean);
        gridTabIds = [];
        dualTabIds = [];
        secondaryTabId = null;
      } else if (splitMode === 'triple-col') {
        if (splitIcon) splitIcon.textContent = '|||';
        if (splitBtn) splitBtn.className = 'px-2 py-1 text-xs bg-orange-600/30 text-orange-300 border border-orange-500/50 rounded-lg transition font-mono flex items-center gap-1';
        const others = tabKeys.filter(id => id !== activeTabId);
        tripleTabIds = [activeTabId, others[0], others[1]].filter(Boolean);
        gridTabIds = [];
        dualTabIds = [];
        secondaryTabId = null;
      } else if (splitMode === 'vertical' || splitMode === 'horizontal') {
        if (splitIcon) splitIcon.textContent = splitMode === 'vertical' ? '◫' : '⬒';
        if (splitBtn) splitBtn.className = 'px-2 py-1 text-xs bg-orange-600/30 text-orange-300 border border-orange-500/50 rounded-lg transition font-mono flex items-center gap-1';
        if (!dualTabIds || dualTabIds.length < 2 || !tabs[dualTabIds[0]] || !tabs[dualTabIds[1]]) {
          const remaining = tabKeys.filter(id => id !== activeTabId);
          dualTabIds = [activeTabId, remaining[0] || null].filter(Boolean);
        }
        secondaryTabId = dualTabIds[1] || null;
        gridTabIds = [];
        tripleTabIds = [];
      } else {
        if (splitIcon) splitIcon.textContent = '◫';
        if (splitBtn) splitBtn.className = 'px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition font-mono flex items-center gap-1';
        dualTabIds = [];
        secondaryTabId = null;
        gridTabIds = [];
        tripleTabIds = [];
      }

      applySplitLayout();
      renderTabsList();
    }

    function cycleSplitFocus() {
      if (splitMode === 'grid' && gridTabIds.length > 0) {
        const curIdx = gridTabIds.indexOf(activeTabId);
        const nextIdx = (curIdx + 1) % gridTabIds.length;
        activeTabId = gridTabIds[nextIdx];
        applySplitLayout();
        renderTabsList();
        const cur = getActiveTab();
        if (cur && cur.term) cur.term.focus();
        return;
      }
      if ((splitMode === 'triple-left' || splitMode === 'triple-col') && tripleTabIds.length > 0) {
        const curIdx = tripleTabIds.indexOf(activeTabId);
        const nextIdx = (curIdx + 1) % tripleTabIds.length;
        activeTabId = tripleTabIds[nextIdx];
        applySplitLayout();
        renderTabsList();
        const cur = getActiveTab();
        if (cur && cur.term) cur.term.focus();
        return;
      }
      if ((splitMode === 'vertical' || splitMode === 'horizontal') && dualTabIds.length >= 2) {
        const curIdx = dualTabIds.indexOf(activeTabId);
        const nextIdx = curIdx === 0 ? 1 : 0;
        activeTabId = dualTabIds[nextIdx];
        applySplitLayout();
        renderTabsList();
        const cur = getActiveTab();
        if (cur && cur.term) cur.term.focus();
        return;
      }
    }

    function removeSplitDividers() {
      [
        'split-divider',
        'grid-divider-v', 'grid-divider-h', 'grid-divider-cross',
        'triple-divider-v', 'triple-divider-h',
        'triple-col-divider-1', 'triple-col-divider-2'
      ].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.remove();
      });
    }

    function applySplitLayout() {
      const container = document.getElementById('terminal-container');
      if (!container) return;

      if (splitMode === 'grid') {
        if (!gridTabIds || gridTabIds.length < 4 || gridTabIds.some(id => !tabs[id])) {
          const tabKeys = Object.keys(tabs);
          const others = tabKeys.filter(id => id !== activeTabId);
          gridTabIds = [activeTabId, others[0], others[1], others[2]].filter(Boolean);
        }

        removeSplitDividers();
        container.style.display = 'block';
        container.style.position = 'relative';
        container.style.overflow = 'hidden';

        const pctX = (splitRatioX * 100).toFixed(2);
        const pctY = (splitRatioY * 100).toFixed(2);
        const invPctX = ((1 - splitRatioX) * 100).toFixed(2);
        const invPctY = ((1 - splitRatioY) * 100).toFixed(2);

        Object.keys(tabs).forEach(id => {
          const t = tabs[id];
          if (!t || !t.mountEl) return;
          const isGridPane = gridTabIds.includes(id);
          if (!isGridPane) {
            t.mountEl.classList.add('hidden');
            t.mountEl.style.border = '';
            t.mountEl.style.position = '';
            return;
          }

          t.mountEl.classList.remove('hidden');
          t.mountEl.style.position = 'absolute';
          t.mountEl.style.boxSizing = 'border-box';
          t.mountEl.style.overflow = 'hidden';

          const isActive = (id === activeTabId);
          t.mountEl.style.border = isActive
            ? '2px solid rgba(249, 115, 22, 0.7)'
            : '2px solid rgba(51, 65, 85, 0.4)';

          if (id === gridTabIds[0]) {
            // Top Left
            t.mountEl.style.top = '0px';
            t.mountEl.style.left = '0px';
            t.mountEl.style.width = `calc(${pctX}% - 3px)`;
            t.mountEl.style.height = `calc(${pctY}% - 3px)`;
            t.mountEl.style.right = '';
            t.mountEl.style.bottom = '';
          } else if (id === gridTabIds[1]) {
            // Top Right
            t.mountEl.style.top = '0px';
            t.mountEl.style.left = `calc(${pctX}% + 3px)`;
            t.mountEl.style.width = `calc(${invPctX}% - 3px)`;
            t.mountEl.style.height = `calc(${pctY}% - 3px)`;
            t.mountEl.style.right = '';
            t.mountEl.style.bottom = '';
          } else if (id === gridTabIds[2]) {
            // Bottom Left
            t.mountEl.style.top = `calc(${pctY}% + 3px)`;
            t.mountEl.style.left = '0px';
            t.mountEl.style.width = `calc(${pctX}% - 3px)`;
            t.mountEl.style.height = `calc(${invPctY}% - 3px)`;
            t.mountEl.style.right = '';
            t.mountEl.style.bottom = '';
          } else if (id === gridTabIds[3]) {
            // Bottom Right
            t.mountEl.style.top = `calc(${pctY}% + 3px)`;
            t.mountEl.style.left = `calc(${pctX}% + 3px)`;
            t.mountEl.style.width = `calc(${invPctX}% - 3px)`;
            t.mountEl.style.height = `calc(${invPctY}% - 3px)`;
            t.mountEl.style.right = '';
            t.mountEl.style.bottom = '';
          }
        });

        // Create Grid Dividers: Vertical bar, Horizontal bar, and Center Crosshair Knot
        const divV = document.createElement('div');
        divV.id = 'grid-divider-v';
        divV.className = 'absolute top-0 bottom-0 w-1.5 bg-slate-800 hover:bg-orange-500 cursor-col-resize z-30 transition-colors select-none';
        divV.style.left = `calc(${pctX}% - 3px)`;
        container.appendChild(divV);

        const divH = document.createElement('div');
        divH.id = 'grid-divider-h';
        divH.className = 'absolute left-0 right-0 h-1.5 bg-slate-800 hover:bg-orange-500 cursor-row-resize z-30 transition-colors select-none';
        divH.style.top = `calc(${pctY}% - 3px)`;
        container.appendChild(divH);

        const divCross = document.createElement('div');
        divCross.id = 'grid-divider-cross';
        divCross.className = 'absolute w-4 h-4 -ml-2 -mt-2 bg-slate-700 hover:bg-orange-500 border-2 border-slate-900 rounded-full cursor-move z-40 transition-colors select-none flex items-center justify-center shadow-lg';
        divCross.title = 'Drag to resize all 4 panes in 2D';
        divCross.style.left = `${pctX}%`;
        divCross.style.top = `${pctY}%`;
        divCross.innerHTML = '<div class="w-1 h-1 bg-white rounded-full"></div>';
        container.appendChild(divCross);

        initGridDividerDragging(divV, divH, divCross);

        setTimeout(() => {
          gridTabIds.forEach(id => {
            const t = tabs[id];
            if (t && t.fitAddon) { t.fitAddon.fit(); sendResize(t); }
          });
          const cur = getActiveTab();
          if (cur && cur.term) cur.term.focus();
        }, 50);
        return;
      }

      // Triple Split: 1 Left (Full height) / 2 Right (Top & Bottom)
      if (splitMode === 'triple-left') {
        if (!tripleTabIds || tripleTabIds.length < 3 || tripleTabIds.some(id => !tabs[id])) {
          const tabKeys = Object.keys(tabs);
          const others = tabKeys.filter(id => id !== activeTabId);
          tripleTabIds = [activeTabId, others[0], others[1]].filter(Boolean);
        }

        removeSplitDividers();
        container.style.display = 'block';
        container.style.position = 'relative';
        container.style.overflow = 'hidden';

        const pctX = (splitRatioX * 100).toFixed(2);
        const pctY = (splitRatioY * 100).toFixed(2);
        const invPctX = ((1 - splitRatioX) * 100).toFixed(2);
        const invPctY = ((1 - splitRatioY) * 100).toFixed(2);

        Object.keys(tabs).forEach(id => {
          const t = tabs[id];
          if (!t || !t.mountEl) return;
          const isTriplePane = tripleTabIds.includes(id);
          if (!isTriplePane) {
            t.mountEl.classList.add('hidden');
            t.mountEl.style.border = '';
            t.mountEl.style.position = '';
            return;
          }

          t.mountEl.classList.remove('hidden');
          t.mountEl.style.position = 'absolute';
          t.mountEl.style.boxSizing = 'border-box';
          t.mountEl.style.overflow = 'hidden';

          const isActive = (id === activeTabId);
          t.mountEl.style.border = isActive
            ? '2px solid rgba(249, 115, 22, 0.7)'
            : '2px solid rgba(51, 65, 85, 0.4)';

          if (id === tripleTabIds[0]) {
            // Pane 1: Left column (full height)
            t.mountEl.style.top = '0px';
            t.mountEl.style.left = '0px';
            t.mountEl.style.width = `calc(${pctX}% - 3px)`;
            t.mountEl.style.height = '100%';
            t.mountEl.style.right = '';
            t.mountEl.style.bottom = '';
          } else if (id === tripleTabIds[1]) {
            // Pane 2: Right Top
            t.mountEl.style.top = '0px';
            t.mountEl.style.left = `calc(${pctX}% + 3px)`;
            t.mountEl.style.width = `calc(${invPctX}% - 3px)`;
            t.mountEl.style.height = `calc(${pctY}% - 3px)`;
            t.mountEl.style.right = '';
            t.mountEl.style.bottom = '';
          } else if (id === tripleTabIds[2]) {
            // Pane 3: Right Bottom
            t.mountEl.style.top = `calc(${pctY}% + 3px)`;
            t.mountEl.style.left = `calc(${pctX}% + 3px)`;
            t.mountEl.style.width = `calc(${invPctX}% - 3px)`;
            t.mountEl.style.height = `calc(${invPctY}% - 3px)`;
            t.mountEl.style.right = '';
            t.mountEl.style.bottom = '';
          }
        });

        // Vertical divider between left pane and right panes
        const divV = document.createElement('div');
        divV.id = 'triple-divider-v';
        divV.className = 'absolute top-0 bottom-0 w-1.5 bg-slate-800 hover:bg-orange-500 cursor-col-resize z-30 transition-colors select-none';
        divV.style.left = `calc(${pctX}% - 3px)`;
        container.appendChild(divV);

        // Horizontal divider between top-right and bottom-right panes
        const divH = document.createElement('div');
        divH.id = 'triple-divider-h';
        divH.className = 'absolute right-0 h-1.5 bg-slate-800 hover:bg-orange-500 cursor-row-resize z-30 transition-colors select-none';
        divH.style.left = `calc(${pctX}% + 3px)`;
        divH.style.top = `calc(${pctY}% - 3px)`;
        container.appendChild(divH);

        initTripleLeftDragging(divV, divH);

        setTimeout(() => {
          tripleTabIds.forEach(id => {
            const t = tabs[id];
            if (t && t.fitAddon) { t.fitAddon.fit(); sendResize(t); }
          });
          const cur = getActiveTab();
          if (cur && cur.term) cur.term.focus();
        }, 50);
        return;
      }

      // Triple Split: 3 Equal/Resizable Columns (|||)
      if (splitMode === 'triple-col') {
        if (!tripleTabIds || tripleTabIds.length < 3 || tripleTabIds.some(id => !tabs[id])) {
          const tabKeys = Object.keys(tabs);
          const others = tabKeys.filter(id => id !== activeTabId);
          tripleTabIds = [activeTabId, others[0], others[1]].filter(Boolean);
        }

        removeSplitDividers();
        container.style.display = 'block';
        container.style.position = 'relative';
        container.style.overflow = 'hidden';

        const c1Pct = (splitRatio3Col1 * 100).toFixed(2);
        const c2Pct = (splitRatio3Col2 * 100).toFixed(2);
        const w1 = `calc(${c1Pct}% - 3px)`;
        const w2 = `calc(${c2Pct - c1Pct}% - 6px)`;
        const w3 = `calc(${(100 - c2Pct).toFixed(2)}% - 3px)`;

        Object.keys(tabs).forEach(id => {
          const t = tabs[id];
          if (!t || !t.mountEl) return;
          const isTriplePane = tripleTabIds.includes(id);
          if (!isTriplePane) {
            t.mountEl.classList.add('hidden');
            t.mountEl.style.border = '';
            t.mountEl.style.position = '';
            return;
          }

          t.mountEl.classList.remove('hidden');
          t.mountEl.style.position = 'absolute';
          t.mountEl.style.boxSizing = 'border-box';
          t.mountEl.style.overflow = 'hidden';
          t.mountEl.style.top = '0px';
          t.mountEl.style.height = '100%';

          const isActive = (id === activeTabId);
          t.mountEl.style.border = isActive
            ? '2px solid rgba(249, 115, 22, 0.7)'
            : '2px solid rgba(51, 65, 85, 0.4)';

          if (id === tripleTabIds[0]) {
            t.mountEl.style.left = '0px';
            t.mountEl.style.width = w1;
          } else if (id === tripleTabIds[1]) {
            t.mountEl.style.left = `calc(${c1Pct}% + 3px)`;
            t.mountEl.style.width = w2;
          } else if (id === tripleTabIds[2]) {
            t.mountEl.style.left = `calc(${c2Pct}% + 3px)`;
            t.mountEl.style.width = w3;
          }
        });

        // 2 Vertical dividers between the 3 columns
        const div1 = document.createElement('div');
        div1.id = 'triple-col-divider-1';
        div1.className = 'absolute top-0 bottom-0 w-1.5 bg-slate-800 hover:bg-orange-500 cursor-col-resize z-30 transition-colors select-none';
        div1.style.left = `calc(${c1Pct}% - 3px)`;
        container.appendChild(div1);

        const div2 = document.createElement('div');
        div2.id = 'triple-col-divider-2';
        div2.className = 'absolute top-0 bottom-0 w-1.5 bg-slate-800 hover:bg-orange-500 cursor-col-resize z-30 transition-colors select-none';
        div2.style.left = `calc(${c2Pct}% - 3px)`;
        container.appendChild(div2);

        initTripleColDragging(div1, div2);

        setTimeout(() => {
          tripleTabIds.forEach(id => {
            const t = tabs[id];
            if (t && t.fitAddon) { t.fitAddon.fit(); sendResize(t); }
          });
          const cur = getActiveTab();
          if (cur && cur.term) cur.term.focus();
        }, 50);
        return;
      }

      // Single mode or dual split mode
      removeSplitDividers();

      if (splitMode === 'vertical' || splitMode === 'horizontal') {
        const tabKeys = Object.keys(tabs);
        if (tabKeys.length >= 2) {
          dualTabIds = (dualTabIds || []).filter(id => tabs[id]);
          if (dualTabIds.length < 2) {
            if (!dualTabIds.includes(activeTabId) && tabs[activeTabId]) {
              dualTabIds.unshift(activeTabId);
            }
            const others = tabKeys.filter(id => !dualTabIds.includes(id));
            dualTabIds = [...dualTabIds, ...others].slice(0, 2);
          }
          secondaryTabId = dualTabIds[1] || null;
        }
      }

      if (splitMode === 'none' || dualTabIds.length < 2 || !tabs[dualTabIds[0]] || !tabs[dualTabIds[1]]) {
        container.style.display = 'block';
        container.style.position = '';
        container.style.overflow = '';
        container.style.flexDirection = '';

        Object.keys(tabs).forEach(id => {
          const t = tabs[id];
          if (t && t.mountEl) {
            t.mountEl.style.width = '100%';
            t.mountEl.style.height = '100%';
            t.mountEl.style.position = '';
            t.mountEl.style.flex = '';
            t.mountEl.style.border = '';
            t.mountEl.style.top = '';
            t.mountEl.style.left = '';
            t.mountEl.style.right = '';
            t.mountEl.style.bottom = '';
            if (id === activeTabId) {
              t.mountEl.classList.remove('hidden');
              setTimeout(() => {
                if (t.fitAddon) t.fitAddon.fit();
                sendResize(t);
                if (t.term) t.term.focus();
              }, 40);
            } else {
              t.mountEl.classList.add('hidden');
            }
          }
        });
        return;
      }

      // Dual Split Mode Active
      const primaryTab = tabs[dualTabIds[0]];
      const secondaryTab = tabs[dualTabIds[1]];
      if (!primaryTab || !secondaryTab) return;

      container.style.display = 'flex';
      container.style.position = '';
      container.style.overflow = '';
      container.style.flexDirection = splitMode === 'vertical' ? 'row' : 'column';

      let divider = document.getElementById('split-divider');
      if (!divider) {
        divider = document.createElement('div');
        divider.id = 'split-divider';
        container.appendChild(divider);
        initSplitDividerDragging(divider);
      }

      if (splitMode === 'vertical') {
        divider.className = 'w-1.5 h-full bg-slate-800 hover:bg-orange-500 cursor-col-resize shrink-0 transition-colors select-none z-20 flex items-center justify-center';
        divider.innerHTML = '<div class="w-0.5 h-8 bg-slate-600 rounded"></div>';
        divider.style.cursor = 'col-resize';
      } else {
        divider.className = 'w-full h-1.5 bg-slate-800 hover:bg-orange-500 cursor-row-resize shrink-0 transition-colors select-none z-20 flex items-center justify-center';
        divider.innerHTML = '<div class="h-0.5 w-8 bg-slate-600 rounded"></div>';
        divider.style.cursor = 'row-resize';
      }

      // Position primary and secondary panes
      Object.keys(tabs).forEach(id => {
        const t = tabs[id];
        if (!t || !t.mountEl) return;
        t.mountEl.style.position = '';
        t.mountEl.style.top = '';
        t.mountEl.style.left = '';
        t.mountEl.style.right = '';
        t.mountEl.style.bottom = '';

        if (id === dualTabIds[0]) {
          t.mountEl.classList.remove('hidden');
          const isFocused = id === activeTabId;
          t.mountEl.style.border = isFocused ? '2px solid rgba(249, 115, 22, 0.4)' : '2px solid rgba(51, 65, 85, 0.4)';
          if (splitMode === 'vertical') {
            t.mountEl.style.width = `calc(${splitRatio * 100}% - 3px)`;
            t.mountEl.style.height = '100%';
          } else {
            t.mountEl.style.width = '100%';
            t.mountEl.style.height = `calc(${splitRatio * 100}% - 3px)`;
          }
          container.insertBefore(t.mountEl, divider);
        } else if (id === dualTabIds[1]) {
          t.mountEl.classList.remove('hidden');
          const isFocused = id === activeTabId;
          t.mountEl.style.border = isFocused ? '2px solid rgba(249, 115, 22, 0.4)' : '2px solid rgba(51, 65, 85, 0.4)';
          if (splitMode === 'vertical') {
            t.mountEl.style.width = `calc(${(1 - splitRatio) * 100}% - 3px)`;
            t.mountEl.style.height = '100%';
          } else {
            t.mountEl.style.width = '100%';
            t.mountEl.style.height = `calc(${(1 - splitRatio) * 100}% - 3px)`;
          }
          if (divider.nextSibling !== t.mountEl) {
            container.appendChild(t.mountEl);
          }
        } else {
          t.mountEl.classList.add('hidden');
          t.mountEl.style.border = '';
        }
      });

      setTimeout(() => {
        if (primaryTab.fitAddon) { primaryTab.fitAddon.fit(); sendResize(primaryTab); }
        if (secondaryTab.fitAddon) { secondaryTab.fitAddon.fit(); sendResize(secondaryTab); }
        const cur = getActiveTab();
        if (cur && cur.term) cur.term.focus();
      }, 50);
    }

    function initSplitDividerDragging(divider) {
      divider.addEventListener('mousedown', (e) => {
        e.preventDefault();
        isDraggingDivider = true;
        dragMode = 'dual';
        document.body.style.cursor = splitMode === 'vertical' ? 'col-resize' : 'row-resize';
        document.body.style.userSelect = 'none';

        const onMouseMove = (moveEvent) => {
          if (!isDraggingDivider) return;
          const container = document.getElementById('terminal-container');
          if (!container) return;
          const rect = container.getBoundingClientRect();

          let ratio = 0.5;
          if (splitMode === 'vertical') {
            ratio = (moveEvent.clientX - rect.left) / rect.width;
          } else {
            ratio = (moveEvent.clientY - rect.top) / rect.height;
          }
          splitRatio = Math.max(0.15, Math.min(0.85, ratio));
          applySplitLayout();
        };

        const onMouseUp = () => {
          isDraggingDivider = false;
          dragMode = null;
          document.body.style.cursor = '';
          document.body.style.userSelect = '';
          window.removeEventListener('mousemove', onMouseMove);
          window.removeEventListener('mouseup', onMouseUp);
          const p = getActiveTab();
          const s = getSecondaryTab();
          if (p && p.fitAddon) { p.fitAddon.fit(); sendResize(p); }
          if (s && s.fitAddon) { s.fitAddon.fit(); sendResize(s); }
        };

        window.addEventListener('mousemove', onMouseMove);
        window.addEventListener('mouseup', onMouseUp);
      });
    }

    function initGridDividerDragging(divV, divH, divCross) {
      const startDrag = (e, mode) => {
        e.preventDefault();
        isDraggingDivider = true;
        dragMode = mode;
        if (mode === 'grid-v') document.body.style.cursor = 'col-resize';
        else if (mode === 'grid-h') document.body.style.cursor = 'row-resize';
        else document.body.style.cursor = 'move';
        document.body.style.userSelect = 'none';

        const onMouseMove = (moveEvent) => {
          if (!isDraggingDivider) return;
          const container = document.getElementById('terminal-container');
          if (!container) return;
          const rect = container.getBoundingClientRect();

          if (dragMode === 'grid-v' || dragMode === 'grid-cross') {
            const rx = (moveEvent.clientX - rect.left) / rect.width;
            splitRatioX = Math.max(0.15, Math.min(0.85, rx));
          }
          if (dragMode === 'grid-h' || dragMode === 'grid-cross') {
            const ry = (moveEvent.clientY - rect.top) / rect.height;
            splitRatioY = Math.max(0.15, Math.min(0.85, ry));
          }
          applySplitLayout();
        };

        const onMouseUp = () => {
          isDraggingDivider = false;
          dragMode = null;
          document.body.style.cursor = '';
          document.body.style.userSelect = '';
          window.removeEventListener('mousemove', onMouseMove);
          window.removeEventListener('mouseup', onMouseUp);
          gridTabIds.forEach(id => {
            const t = tabs[id];
            if (t && t.fitAddon) { t.fitAddon.fit(); sendResize(t); }
          });
        };

        window.addEventListener('mousemove', onMouseMove);
        window.addEventListener('mouseup', onMouseUp);
      };

      divV.addEventListener('mousedown', (e) => startDrag(e, 'grid-v'));
      divH.addEventListener('mousedown', (e) => startDrag(e, 'grid-h'));
      divCross.addEventListener('mousedown', (e) => startDrag(e, 'grid-cross'));
    }

    function initTripleLeftDragging(divV, divH) {
      const startDrag = (e, mode) => {
        e.preventDefault();
        isDraggingDivider = true;
        dragMode = mode;
        document.body.style.cursor = mode === 'triple-v' ? 'col-resize' : 'row-resize';
        document.body.style.userSelect = 'none';

        const onMouseMove = (moveEvent) => {
          if (!isDraggingDivider) return;
          const container = document.getElementById('terminal-container');
          if (!container) return;
          const rect = container.getBoundingClientRect();

          if (dragMode === 'triple-v') {
            const rx = (moveEvent.clientX - rect.left) / rect.width;
            splitRatioX = Math.max(0.15, Math.min(0.85, rx));
          } else if (dragMode === 'triple-h') {
            const ry = (moveEvent.clientY - rect.top) / rect.height;
            splitRatioY = Math.max(0.15, Math.min(0.85, ry));
          }
          applySplitLayout();
        };

        const onMouseUp = () => {
          isDraggingDivider = false;
          dragMode = null;
          document.body.style.cursor = '';
          document.body.style.userSelect = '';
          window.removeEventListener('mousemove', onMouseMove);
          window.removeEventListener('mouseup', onMouseUp);
          tripleTabIds.forEach(id => {
            const t = tabs[id];
            if (t && t.fitAddon) { t.fitAddon.fit(); sendResize(t); }
          });
        };

        window.addEventListener('mousemove', onMouseMove);
        window.addEventListener('mouseup', onMouseUp);
      };

      divV.addEventListener('mousedown', (e) => startDrag(e, 'triple-v'));
      divH.addEventListener('mousedown', (e) => startDrag(e, 'triple-h'));
    }

    function initTripleColDragging(div1, div2) {
      const startDrag = (e, mode) => {
        e.preventDefault();
        isDraggingDivider = true;
        dragMode = mode;
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';

        const onMouseMove = (moveEvent) => {
          if (!isDraggingDivider) return;
          const container = document.getElementById('terminal-container');
          if (!container) return;
          const rect = container.getBoundingClientRect();
          const rx = (moveEvent.clientX - rect.left) / rect.width;

          if (dragMode === 'col1') {
            splitRatio3Col1 = Math.max(0.15, Math.min(splitRatio3Col2 - 0.1, rx));
          } else if (dragMode === 'col2') {
            splitRatio3Col2 = Math.max(splitRatio3Col1 + 0.1, Math.min(0.85, rx));
          }
          applySplitLayout();
        };

        const onMouseUp = () => {
          isDraggingDivider = false;
          dragMode = null;
          document.body.style.cursor = '';
          document.body.style.userSelect = '';
          window.removeEventListener('mousemove', onMouseMove);
          window.removeEventListener('mouseup', onMouseUp);
          tripleTabIds.forEach(id => {
            const t = tabs[id];
            if (t && t.fitAddon) { t.fitAddon.fit(); sendResize(t); }
          });
        };

        window.addEventListener('mousemove', onMouseMove);
        window.addEventListener('mouseup', onMouseUp);
      };

      div1.addEventListener('mousedown', (e) => startDrag(e, 'col1'));
      div2.addEventListener('mousedown', (e) => startDrag(e, 'col2'));
    }

    function switchTab(tabId) {
      if (!tabs[tabId]) return;

      if (splitMode === 'grid') {
        if (!gridTabIds.includes(tabId)) {
          // Replace inactive grid pane with this tab
          const idxToReplace = gridTabIds.indexOf(activeTabId);
          if (idxToReplace !== -1) {
            gridTabIds[idxToReplace] = tabId;
          } else {
            gridTabIds[0] = tabId;
          }
        }
        activeTabId = tabId;
        const activeTab = tabs[activeTabId];
        if (activeTab) activeTab.hasAlert = false;
        applySplitLayout();
        renderTabsList();
        saveTabsState();
        if (activeTab && activeTab.term) activeTab.term.focus();
        return;
      }

      if (splitMode === 'triple-left' || splitMode === 'triple-col') {
        if (!tripleTabIds.includes(tabId)) {
          const idxToReplace = tripleTabIds.indexOf(activeTabId);
          if (idxToReplace !== -1) {
            tripleTabIds[idxToReplace] = tabId;
          } else {
            tripleTabIds[0] = tabId;
          }
        }
        activeTabId = tabId;
        const activeTab = tabs[activeTabId];
        if (activeTab) activeTab.hasAlert = false;
        applySplitLayout();
        renderTabsList();
        saveTabsState();
        if (activeTab && activeTab.term) activeTab.term.focus();
        return;
      }

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
        const activeTab = tabs[activeTabId];
        if (activeTab) activeTab.hasAlert = false;
        applySplitLayout();
        renderTabsList();
        saveTabsState();
        if (activeTab && activeTab.term) activeTab.term.focus();
        return;
      }

      activeTabId = tabId;
      const activeTab = tabs[tabId];
      activeTab.hasAlert = false;
      renderTabsList();
      saveTabsState();

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
          activeTab.lastSentCols = null;
          activeTab.lastSentRows = null;
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

    function closeTab(tabId, silent = false) {
      const tabKeys = Object.keys(tabs);
      if (tabKeys.length <= 1 && !silent) {
        showToast('Cannot close the last open tab');
        return;
      }
      const tab = tabs[tabId];
      if (!tab) return;

      tab.isClosed = true;
      if (tab.pingTimer) { clearInterval(tab.pingTimer); tab.pingTimer = null; }
      if (tab.reconnectTimer) { clearTimeout(tab.reconnectTimer); tab.reconnectTimer = null; }
      if (tab.socket) {
        tab.socket.onopen = null;
        tab.socket.onmessage = null;
        tab.socket.onerror = null;
        tab.socket.onclose = null;
        try { tab.socket.close(); } catch(e) {}
        tab.socket = null;
      }

      if (!silent) {
        const closeUrl = `/api/tab_close?tab=${encodeURIComponent(tabId)}&token=${encodeURIComponent(sessionToken || '')}`;
        if (navigator.sendBeacon) {
          try {
            navigator.sendBeacon(closeUrl);
          } catch (e) {
            fetch(closeUrl, { method: 'POST', keepalive: true }).catch(() => {});
          }
        } else {
          fetch(closeUrl, { method: 'POST', keepalive: true }).catch(() => {});
        }
      }

      if (tab.mountEl && tab.mountEl.parentNode) {
        tab.mountEl.parentNode.removeChild(tab.mountEl);
      }
      if (tab.term) {
        try { tab.term.dispose(); } catch(e) {}
      }

      delete tabs[tabId];
      saveTabsState();

      if (splitMode === 'grid') {
        const remainingKeys = Object.keys(tabs);
        if (remainingKeys.length < 4) {
          setSplitMode('triple-left');
          return;
        } else {
          gridTabIds = gridTabIds.filter(id => id !== tabId);
          const unused = remainingKeys.find(id => !gridTabIds.includes(id));
          if (unused) gridTabIds.push(unused);
          if (activeTabId === tabId) {
            activeTabId = gridTabIds[0];
          }
          applySplitLayout();
          renderTabsList();
          return;
        }
      }

      if (splitMode === 'triple-left' || splitMode === 'triple-col') {
        const remainingKeys = Object.keys(tabs);
        if (remainingKeys.length < 3) {
          setSplitMode('vertical');
          return;
        } else {
          tripleTabIds = tripleTabIds.filter(id => id !== tabId);
          const unused = remainingKeys.find(id => !tripleTabIds.includes(id));
          if (unused) tripleTabIds.push(unused);
          if (activeTabId === tabId) {
            activeTabId = tripleTabIds[0];
          }
          applySplitLayout();
          renderTabsList();
          return;
        }
      }

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
          applySplitLayout();
          renderTabsList();
          return;
        }
      }

      if (activeTabId === tabId) {
        const remaining = Object.keys(tabs);
        if (remaining.length > 0) {
          switchTab(remaining[remaining.length - 1]);
        }
      } else {
        renderTabsList();
      }
    }

    function closeCurrentTab() {
      if (activeTabId) closeTab(activeTabId);
    }

    let draggedTabId = null;

    function moveTab(tabId, direction) {
      const keys = Object.keys(tabs);
      const curIdx = keys.indexOf(tabId);
      if (curIdx === -1) return;
      const targetIdx = curIdx + direction;
      if (targetIdx < 0 || targetIdx >= keys.length) return;

      const newOrder = [...keys];
      const [removed] = newOrder.splice(curIdx, 1);
      newOrder.splice(targetIdx, 0, removed);

      const reorderedTabs = {};
      newOrder.forEach(id => {
        reorderedTabs[id] = tabs[id];
      });
      tabs = reorderedTabs;

      renderTabsList();
      saveTabsState();
      showToast(`Tab moved ${direction < 0 ? 'left' : 'right'}`);
    }

    function reorderTabTo(draggedId, targetId, placeAfter) {
      if (!draggedId || !targetId || draggedId === targetId) return;
      const keys = Object.keys(tabs);
      const fromIdx = keys.indexOf(draggedId);
      const toIdx = keys.indexOf(targetId);
      if (fromIdx === -1 || toIdx === -1) return;

      const newOrder = [...keys];
      newOrder.splice(fromIdx, 1);
      const insertIdx = newOrder.indexOf(targetId) + (placeAfter ? 1 : 0);
      newOrder.splice(insertIdx, 0, draggedId);

      const reorderedTabs = {};
      newOrder.forEach(id => {
        reorderedTabs[id] = tabs[id];
      });
      tabs = reorderedTabs;

      renderTabsList();
      saveTabsState();
    }

    function handleTabDragStart(e, tabId) {
      draggedTabId = tabId;
      e.dataTransfer.effectAllowed = 'move';
      try {
        e.dataTransfer.setData('application/x-fire-ssh-tab', tabId);
      } catch (err) {}
      e.dataTransfer.setData('text/plain', tabId);
      const tabEl = e.currentTarget;
      setTimeout(() => {
        if (tabEl) tabEl.classList.add('tab-dragging');
      }, 0);
    }

    function handleTabDragOver(e, tabId) {
      if (!draggedTabId || draggedTabId === tabId) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      const rect = e.currentTarget.getBoundingClientRect();
      const midpoint = rect.left + rect.width / 2;
      e.currentTarget.classList.remove('tab-drag-over-left', 'tab-drag-over-right');
      if (e.clientX < midpoint) {
        e.currentTarget.classList.add('tab-drag-over-left');
      } else {
        e.currentTarget.classList.add('tab-drag-over-right');
      }
    }

    function handleTabDragLeave(e) {
      e.currentTarget.classList.remove('tab-drag-over-left', 'tab-drag-over-right');
    }

    function handleTabDrop(e, targetId) {
      e.currentTarget.classList.remove('tab-drag-over-left', 'tab-drag-over-right');
      if (!draggedTabId) {
        // Not a tab reorder — this is an external file drop over the tab bar!
        // Allow the event to bubble to the window drop handler so the file upload modal opens.
        return;
      }
      e.preventDefault();
      if (draggedTabId === targetId) {
        draggedTabId = null;
        return;
      }
      const rect = e.currentTarget.getBoundingClientRect();
      const placeAfter = e.clientX >= (rect.left + rect.width / 2);
      reorderTabTo(draggedTabId, targetId, placeAfter);
      draggedTabId = null;
    }

    function handleTabDragEnd(e) {
      e.currentTarget.classList.remove('tab-dragging', 'tab-drag-over-left', 'tab-drag-over-right');
      document.querySelectorAll('.tab-item').forEach(el => {
        el.classList.remove('tab-dragging', 'tab-drag-over-left', 'tab-drag-over-right');
      });
      draggedTabId = null;
      dragCounter = 0;
      const overlay = document.getElementById('drop-overlay');
      if (overlay) overlay.classList.add('hidden');
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
        const isDual = splitMode === 'vertical' || splitMode === 'horizontal';
        const dualPaneIdx = isDual ? dualTabIds.indexOf(tabId) : -1;
        const gridPaneIdx = splitMode === 'grid' ? gridTabIds.indexOf(tabId) : -1;
        const isTripleMode = splitMode === 'triple-left' || splitMode === 'triple-col';
        const triplePaneIdx = isTripleMode ? tripleTabIds.indexOf(tabId) : -1;
        const statusDot = tab.connected ? 'bg-emerald-400' : 'bg-amber-400';
        const alertBadge = tab.hasAlert ? '<span class="animate-bounce text-xs">🔔</span>' : '';
        
        let splitBadge = '';
        if (splitMode === 'grid' && gridPaneIdx !== -1) {
          const badgeClass = isActive
            ? 'bg-orange-950 text-orange-400 border-orange-800'
            : 'bg-slate-800 text-slate-400 border-slate-700';
          splitBadge = `<span class="text-[9px] px-1 py-0.2 rounded font-sans border ${badgeClass}">Pane ${gridPaneIdx + 1}</span>`;
        } else if (isTripleMode && triplePaneIdx !== -1) {
          const badgeClass = isActive
            ? 'bg-orange-950 text-orange-400 border-orange-800'
            : 'bg-slate-800 text-slate-400 border-slate-700';
          splitBadge = `<span class="text-[9px] px-1 py-0.2 rounded font-sans border ${badgeClass}">Pane ${triplePaneIdx + 1}</span>`;
        } else if (isDual && dualPaneIdx !== -1) {
          const badgeClass = isActive
            ? 'bg-orange-950 text-orange-400 border-orange-800'
            : 'bg-slate-800 text-slate-400 border-slate-700';
          splitBadge = `<span class="text-[9px] px-1 py-0.2 rounded font-sans border ${badgeClass}">Pane ${dualPaneIdx + 1}</span>`;
        }

        const closeBtn = tabKeys.length > 1 ? `
          <button onclick="event.stopPropagation(); closeTab('${tabId}')" title="Close Tab (Alt+W)" class="opacity-40 group-hover:opacity-100 hover:text-rose-400 hover:bg-slate-800/80 p-0.5 rounded transition ml-0.5">
            <svg viewBox="0 0 24 24" width="10" height="10" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>` : '';

        const safeTitle = escapeHtml(tab.title || 'bash');
        let borderClass = 'bg-slate-950/70 text-slate-400 border-transparent hover:bg-slate-900/60 hover:text-slate-200';
        if (isActive) {
          borderClass = 'bg-slate-900 text-white border-orange-500 shadow-md font-semibold';
        } else if ((isDual && dualPaneIdx !== -1) || (splitMode === 'grid' && gridPaneIdx !== -1) || (isTripleMode && triplePaneIdx !== -1)) {
          borderClass = 'bg-slate-900/80 text-slate-200 border-slate-600 shadow-sm';
        }

        return `
          <div onclick="switchTab('${tabId}')"
               ondblclick="event.stopPropagation(); promptRenameTab('${tabId}')"
               draggable="true"
               ondragstart="handleTabDragStart(event, '${tabId}')"
               ondragover="handleTabDragOver(event, '${tabId}')"
               ondragleave="handleTabDragLeave(event)"
               ondrop="handleTabDrop(event, '${tabId}')"
               ondragend="handleTabDragEnd(event)"
               data-tab-id="${tabId}"
               title="Click to switch, drag to reorder, double-click to rename (Ctrl+Shift+←/→ to move)"
               class="tab-item group flex items-center gap-1.5 px-3 py-1 rounded-t-lg text-xs font-mono cursor-pointer transition select-none border-t-2 ${borderClass}">
            <span class="w-1.5 h-1.5 rounded-full ${statusDot} shrink-0"></span>
            ${alertBadge}
            <span class="truncate max-w-[100px] sm:max-w-[140px] pointer-events-none">${tab.index}: ${safeTitle}</span>
            ${splitBadge}
            ${closeBtn}
          </div>
        `;
      }).join('');
    }

    function isTerminalQueryResponse(data) {
      if (!data || data.charCodeAt(0) !== 27) return false;
      if ((data.startsWith('\x1b[>') || data.startsWith('\x1b[?')) && /[cu]$/.test(data)) return true;
      if (data === '\x1b[0n' || data === '\x1b[3n') return true;
      return /^\x1b\](4|10|11|12);/.test(data);
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

      if (t.parser && t.parser.registerCsiHandler) {
        t.parser.registerCsiHandler({ prefix: '>', final: 'c' }, () => true);
        t.parser.registerCsiHandler({ prefix: '=', final: 'c' }, () => true);
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

          // Alt+V: Vertical Split
          if (e.altKey && (e.key === 'v' || e.key === 'V')) {
            e.preventDefault();
            setSplitMode(splitMode === 'vertical' ? 'none' : 'vertical');
            return false;
          }

          // Alt+H: Horizontal Split
          if (e.altKey && (e.key === 'h' || e.key === 'H')) {
            e.preventDefault();
            setSplitMode(splitMode === 'horizontal' ? 'none' : 'horizontal');
            return false;
          }

          // Alt+3: Triple Split (1 Left / 2 Right)
          if (e.altKey && e.key === '3') {
            e.preventDefault();
            setSplitMode(splitMode === 'triple-left' ? 'none' : 'triple-left');
            return false;
          }

          // Alt+C: 3 Columns
          if (e.altKey && (e.key === 'c' || e.key === 'C')) {
            e.preventDefault();
            setSplitMode(splitMode === 'triple-col' ? 'none' : 'triple-col');
            return false;
          }

          // Alt+G: 2x2 Quad Grid
          if (e.altKey && (e.key === 'g' || e.key === 'G')) {
            e.preventDefault();
            setSplitMode(splitMode === 'grid' ? 'none' : 'grid');
            return false;
          }

          // Alt+S: Single mode
          if (e.altKey && (e.key === 's' || e.key === 'S')) {
            e.preventDefault();
            setSplitMode('none');
            return false;
          }

          // Alt+O: Cycle split focus
          if (e.altKey && (e.key === 'o' || e.key === 'O')) {
            e.preventDefault();
            cycleSplitFocus();
            return false;
          }

          // Ctrl+Shift+Left / Ctrl+Shift+Right or PageUp / PageDown: Move / Reorder Tab
          if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight' || e.key === 'PageUp' || e.key === 'PageDown' || e.key === 'Left' || e.key === 'Right')) {
            e.preventDefault();
            e.stopPropagation();
            if (activeTabId) {
              const isLeft = (e.key === 'ArrowLeft' || e.key === 'Left' || e.key === 'PageUp');
              moveTab(activeTabId, isLeft ? -1 : 1);
            }
            return false;
          }

          // Shift+Tab: Backtab
          if (e.shiftKey && e.key === 'Tab') {
            e.preventDefault();
            sendTerminalData('\x1b[Z');
            return false;
          }

          // F11: Toggle Fullscreen
          if (e.key === 'F11' || e.keyCode === 122) {
            e.preventDefault();
            e.stopPropagation();
            toggleFullscreen();
            return false;
          }

        }
        return true;
      });

      // Terminal Data handler
      if (!window.IS_READONLY) {
        t.onData(data => {
          if (isTerminalQueryResponse(data)) return;
          if (tab.fitAddon && tab.term) {
            if (tab.lastSentCols !== tab.term.cols || tab.lastSentRows !== tab.term.rows) {
              sendResize(tab);
            }
          }
          if (ctrlSticky && data.length > 0) {
            sendCtrlChar(data[0]);
            if (data.length > 1) {
              sendTerminalData(data.slice(1));
            }
            return;
          }
          if (altSticky && data.length > 0) {
            sendTerminalData('\x1b' + data);
            altSticky = false;
            updateModifierUI();
            return;
          }
          if (shiftSticky && data.length > 0) {
            if (data === '\t') {
              sendTerminalData('\x1b[Z');
              shiftSticky = false;
              updateModifierUI();
              return;
            }
            sendShiftChar(data[0]);
            if (data.length > 1) {
              sendTerminalData(data.slice(1));
            }
            return;
          }
          if (tab.socket && tab.socket.readyState === WebSocket.OPEN) {
            tab.socket.send(new TextEncoder().encode(data));
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
        tab.reconnectAttempts = 0;
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
            } else if (msg.type === 'session_closed') {
              handleSessionClosed(msg.message || msg.reason || "SSH session closed via 'fire ssh close'");
              return;
            } else if (msg.type === 'tabs_changed') {
              if (typeof syncServerTabs === 'function') {
                syncServerTabs();
              }
            } else if (msg.type === 'pty_resize') {
              if (msg.cols && msg.rows && tab.term) {
                if (!document.hasFocus() || document.visibilityState === 'hidden') {
                  tab.lastSentCols = msg.cols;
                  tab.lastSentRows = msg.rows;
                  if (tab.term.cols !== msg.cols || tab.term.rows !== msg.rows) {
                    tab.term.resize(msg.cols, msg.rows);
                  }
                }
              }
            } else if (msg.type === 'pong') {
              // pong
            } else if (msg.type === 'process_name') {
              if (msg.name && tab.title !== msg.name) {
                tab.title = msg.name;
                renderTabsList();
                saveTabsState();
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
            } else if (msg.type === 'title_update') {
              applySessionTitle(msg.title);
            }
          } catch(e) {
            renderTabOutput(tab, event.data);
          }
        } else {
          const uint8 = new Uint8Array(event.data);
          renderTabOutput(tab, uint8);
        }
      };

      tab.socket.onclose = (event) => {
        if (tab.isClosed || !tabs[tab.id]) {
          return;
        }

        tab.connected = false;
        renderTabsList();

        if (sessionClosed) {
          return;
        }

        if (event && event.reason === 'Process exited') {
          if (Object.keys(tabs).length > 1) {
            closeTab(tab.id);
            showToast(`Tab ${tab.index || ''} closed (shell exited)`);
            return;
          } else {
            handleSessionClosed(event.reason);
            return;
          }
        }

        if (event && (event.code === 1000 || event.code === 1001) && event.reason && (event.reason.includes('closed') || event.reason.includes('fire ssh'))) {
          handleSessionClosed(event.reason);
          return;
        }

        if (tab.id === activeTabId) {
          const connBadge = document.getElementById('conn-badge');
          if (connBadge) {
            connBadge.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-ping"></span> Reconnecting...';
            connBadge.className = 'text-[11px] sm:text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 font-mono flex items-center gap-1';
          }
        }

        tab.reconnectAttempts = (tab.reconnectAttempts || 0) + 1;

        if (tab.reconnectAttempts >= 3) {
          fetch('/api/status')
            .then(res => {
              if (!res.ok) throw new Error('status ' + res.status);
            })
            .catch(() => {
              handleSessionClosed("SSH session closed or server unreachable (fire ssh close).");
            });
        }

        if (tab.reconnectAttempts >= 8) {
          handleSessionClosed("Server disconnected. The session was closed or is unreachable.");
          return;
        }

        tab.reconnectTimer = setTimeout(() => {
          if (!sessionClosed && !tab.isClosed && tabs[tab.id] && !document.getElementById('terminal-view').classList.contains('hidden')) {
            connectTabWebSocket(tab);
          }
        }, 1500);
      };

      tab.socket.onerror = (err) => {
        console.error('WebSocket Error:', err);
      };
    }

    // ==================== ASCIINEMA SESSION RECORDER ====================
    let isRecordingSession = false;
    let recordingStartTime = 0;
    let recordedEvents = [];

    function toggleSessionRecording() {
      if (!isRecordingSession) {
        startSessionRecording();
      } else {
        stopSessionRecording();
      }
    }

    function startSessionRecording() {
      const cur = getActiveTab();
      isRecordingSession = true;
      recordingStartTime = performance.now();
      const cols = cur && cur.term ? cur.term.cols : 80;
      const rows = cur && cur.term ? cur.term.rows : 24;

      // Asciinema v2 header
      const header = {
        version: 2,
        width: cols,
        height: rows,
        timestamp: Math.floor(Date.now() / 1000),
        title: "Fire PM Session Recording",
        env: { "TERM": "xterm-256color", "SHELL": "/bin/bash" }
      };
      recordedEvents = [JSON.stringify(header)];

      const btn = document.getElementById('record-btn');
      const dot = document.getElementById('record-dot');
      const text = document.getElementById('record-text');
      if (btn) btn.classList.add('bg-rose-950/80', 'border', 'border-rose-500/50', 'text-rose-200');
      if (dot) dot.classList.add('animate-ping');
      if (text) text.textContent = 'Recording...';
      showToast('Recording started (Asciinema .cast format)');
    }

    function stopSessionRecording() {
      if (!isRecordingSession) return;
      isRecordingSession = false;

      const btn = document.getElementById('record-btn');
      const dot = document.getElementById('record-dot');
      const text = document.getElementById('record-text');
      if (btn) btn.classList.remove('bg-rose-950/80', 'border', 'border-rose-500/50', 'text-rose-200');
      if (dot) dot.classList.remove('animate-ping');
      if (text) text.textContent = 'Rec';

      if (recordedEvents.length <= 1) {
        showToast('No terminal output recorded.');
        return;
      }

      const content = recordedEvents.join('\n') + '\n';
      const blob = new Blob([content], { type: 'application/x-asciicast' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const ts = new Date().toISOString().replace(/[:.]/g, '-');
      a.href = url;
      a.download = `fire-pm-session-${ts}.cast`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast('Recording saved as .cast file!');
    }

    function recordTerminalOutputChunk(data) {
      if (!isRecordingSession) return;
      const timeOffset = Math.max(0, (performance.now() - recordingStartTime) / 1000);
      let textChunk = '';
      if (typeof data === 'string') {
        textChunk = data;
      } else if (data instanceof Uint8Array || data instanceof ArrayBuffer) {
        try {
          textChunk = new TextDecoder('utf-8').decode(data);
        } catch(e) {
          textChunk = String.fromCharCode.apply(null, new Uint8Array(data));
        }
      }
      if (textChunk) {
        recordedEvents.push(JSON.stringify([parseFloat(timeOffset.toFixed(4)), 'o', textChunk]));
      }
    }

    function renderTabOutput(tab, data) {
      if (tab && tab.term) {
        tab.term.write(data);
        recordTerminalOutputChunk(data);
        if (typeof detectImageOutputInChunk === 'function') {
          detectImageOutputInChunk(tab, data);
        }
      }
    }

    function sendResize(tab) {
      if (window.IS_READONLY) return;
      if (document.visibilityState === 'hidden') return;
      if (!tab || !tab.socket || tab.socket.readyState !== WebSocket.OPEN || !tab.term) return;
      if (splitMode === 'none' && activeTabId !== tab.id) return;

      if (tab.lastSentCols === tab.term.cols && tab.lastSentRows === tab.term.rows) return;
      tab.lastSentCols = tab.term.cols;
      tab.lastSentRows = tab.term.rows;

      tab.socket.send(JSON.stringify({ type: 'resize', cols: tab.term.cols, rows: tab.term.rows }));
    }

    function termFit() {
      const cur = getActiveTab();
      if (cur && cur.fitAddon && cur.term) {
        cur.fitAddon.fit();
        sendResize(cur);
      }
    }

    function initGlobalShortcuts() {
      if (typeof setupImageViewerInteractions === 'function') {
        setupImageViewerInteractions();
      }
      window.addEventListener('resize', () => updateViewportLayout());

      if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', () => updateViewportLayout());
        window.visualViewport.addEventListener('scroll', () => updateViewportLayout());
      }

      window.addEventListener('orientationchange', () => {
        setTimeout(() => updateViewportLayout(), 200);
      });

      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && !window.IS_READONLY) {
          if (typeof syncServerTabs === 'function') {
            syncServerTabs();
          }
          const cur = getActiveTab();
          if (cur && cur.fitAddon && cur.term) {
            cur.fitAddon.fit();
            cur.lastSentCols = null;
            cur.lastSentRows = null;
            sendResize(cur);
          }
        }
      });

      window.addEventListener('focus', () => {
        if (!window.IS_READONLY) {
          const cur = getActiveTab();
          if (cur && cur.fitAddon && cur.term) {
            cur.fitAddon.fit();
            cur.lastSentCols = null;
            cur.lastSentRows = null;
            sendResize(cur);
          }
        }
      });

      // Dismiss mobile actions menu when tapping outside
      document.addEventListener('click', (e) => {
        const m = document.getElementById('mobile-actions-menu');
        const btn = document.getElementById('mobile-actions-btn');
        if (m && !m.classList.contains('hidden') && btn && !btn.contains(e.target) && !m.contains(e.target)) {
          m.classList.add('hidden');
        }
      });

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

        // Alt+V: Toggle Vertical Side-by-Side Split
        if (e.altKey && (e.key === 'v' || e.key === 'V')) {
          e.preventDefault();
          setSplitMode(splitMode === 'vertical' ? 'none' : 'vertical');
          return;
        }

        // Alt+H: Toggle Horizontal Top-Bottom Split
        if (e.altKey && (e.key === 'h' || e.key === 'H')) {
          e.preventDefault();
          setSplitMode(splitMode === 'horizontal' ? 'none' : 'horizontal');
          return;
        }

        // Alt+3: Toggle Triple Split (1 Left / 2 Right)
        if (e.altKey && e.key === '3') {
          e.preventDefault();
          setSplitMode(splitMode === 'triple-left' ? 'none' : 'triple-left');
          return;
        }

        // Alt+C: Toggle 3 Columns
        if (e.altKey && (e.key === 'c' || e.key === 'C')) {
          e.preventDefault();
          setSplitMode(splitMode === 'triple-col' ? 'none' : 'triple-col');
          return;
        }

        // Alt+G: Toggle 2x2 Quad Grid
        if (e.altKey && (e.key === 'g' || e.key === 'G')) {
          e.preventDefault();
          setSplitMode(splitMode === 'grid' ? 'none' : 'grid');
          return;
        }

        // Alt+S: Single mode (unsplit)
        if (e.altKey && (e.key === 's' || e.key === 'S')) {
          e.preventDefault();
          setSplitMode('none');
          return;
        }

        // Alt+O: Cycle focus between split panes
        if (e.altKey && (e.key === 'o' || e.key === 'O')) {
          e.preventDefault();
          cycleSplitFocus();
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

        // Ctrl+Shift+Left / Ctrl+Shift+Right or Ctrl+Shift+PageUp / PageDown: Move / Reorder active tab
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight' || e.key === 'PageUp' || e.key === 'PageDown' || e.key === 'Left' || e.key === 'Right')) {
          e.preventDefault();
          if (activeTabId) {
            const isLeft = (e.key === 'ArrowLeft' || e.key === 'Left' || e.key === 'PageUp');
            moveTab(activeTabId, isLeft ? -1 : 1);
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
      try {
        localStorage.removeItem('fire_ssh_open_tabs');
        localStorage.removeItem('fire_ssh_active_tab');
      } catch (e) {}
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

    let sessionClosed = false;

    function handleSessionClosed(message) {
      if (sessionClosed) return;
      sessionClosed = true;

      Object.values(tabs).forEach(t => {
        if (t.reconnectTimer) {
          clearTimeout(t.reconnectTimer);
          t.reconnectTimer = null;
        }
        if (t.pingTimer) {
          clearInterval(t.pingTimer);
          t.pingTimer = null;
        }
        if (t.socket) {
          try { t.socket.close(); } catch(e) {}
        }
        if (t.term) {
          t.term.write('\r\n\x1b[33m[Fire SSH] ' + (message || "Session closed via 'fire ssh close'") + '\x1b[0m\r\n');
        }
      });

      const connBadge = document.getElementById('conn-badge');
      if (connBadge) {
        connBadge.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-rose-500"></span> Closed';
        connBadge.className = 'text-[11px] sm:text-xs px-2 py-0.5 rounded-full bg-rose-500/20 text-rose-400 border border-rose-500/30 font-mono flex items-center gap-1';
      }

      const modal = document.getElementById('session-closed-modal');
      const msgEl = document.getElementById('session-closed-msg');
      if (msgEl && message) {
        msgEl.textContent = message;
      }
      if (modal) {
        modal.classList.remove('hidden');
      }
    }

    function handleSessionClosedReload() {
      try {
        localStorage.removeItem('fire_ssh_open_tabs');
        localStorage.removeItem('fire_ssh_active_tab');
      } catch (e) {}
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
        const mobLat = document.getElementById('mobile-latency-val');
        if (mobLat) mobLat.textContent = ms + 'ms';
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

    function initMobileKeysListScrolling() {
      const list = document.getElementById('mobile-keys-list');
      if (!list) return;

      list.addEventListener('wheel', (e) => {
        if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
          list.scrollLeft += e.deltaY;
          e.preventDefault();
        }
      }, { passive: false });

      let isDown = false;
      let startX = 0;
      let scrollStart = 0;

      list.addEventListener('mousedown', (e) => {
        isDown = true;
        isListMouseDragging = false;
        startX = e.pageX - list.offsetLeft;
        scrollStart = list.scrollLeft;
      });

      window.addEventListener('mouseup', () => {
        if (isDown) {
          isDown = false;
          setTimeout(() => { isListMouseDragging = false; }, 50);
        }
      });

      list.addEventListener('mousemove', (e) => {
        if (!isDown) return;
        const x = e.pageX - list.offsetLeft;
        const dist = x - startX;
        if (Math.abs(dist) > 5) {
          isListMouseDragging = true;
          list.scrollLeft = scrollStart - dist;
        }
      });
    }

    initMobileKeysListScrolling();
    applySessionTitle();
    checkAuth();
  </script>
</body>
</html>
"""

# ==================== HTTP & WEBSOCKET SERVER ====================

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self):
        super().server_bind()
        try:
            self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass

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
        norm_path = parsed.path.rstrip('/') or '/'
        if norm_path in ('/api/download', '/api/preview', '/api/view', '/api/stat'):
            if not self.is_authenticated():
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                return
            token = self.get_auth_token()
            query = urllib.parse.parse_qs(parsed.query)
            tab_id = query.get('tab', [None])[0]
            session = self.server.terminals.get(token, tab_id)
            cwd = session.get_cwd() if session else os.environ.get("HOME", "/root")
            file_param = query.get('file', [None])[0] or query.get('path', [None])[0]
            if not file_param:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                return
            target_path = resolve_fs_path(cwd, file_param)

            if norm_path == '/api/stat':
                self.send_response(200 if os.path.exists(target_path) else 404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                return

            if not os.path.exists(target_path):
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                return

            if os.path.isdir(target_path):
                # Folders are automatically packaged and served as .zip archives
                folder_name = os.path.basename(target_path.rstrip(os.sep)) or "archive"
                clean_name = folder_name.replace('"', '\\"')
                safe_name = urllib.parse.quote(f"{folder_name}.zip")
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Access-Control-Expose-Headers", "Content-Disposition")
                self.send_header("Content-Disposition", f'attachment; filename="{clean_name}.zip"; filename*=UTF-8\'\'{safe_name}')
                self.end_headers()
                return

            if not os.path.isfile(target_path):
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                return

            try:
                file_size = os.path.getsize(target_path)
                content_type = mimetypes.guess_type(target_path)[0] or "application/octet-stream"
                filename = os.path.basename(target_path)
                clean_name = filename.replace('"', '\\"')
                safe_name = urllib.parse.quote(filename)
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(file_size))
                self.send_header("Access-Control-Expose-Headers", "Content-Disposition")
                disposition_type = "inline" if (norm_path in ('/api/preview', '/api/view') or query.get('inline', ['0'])[0] in ('1', 'true', 'yes')) else "attachment"
                self.send_header("Content-Disposition", f'{disposition_type}; filename="{clean_name}"; filename*=UTF-8\'\'{safe_name}')
                self.end_headers()
            except Exception:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
            return

        elif norm_path in ('/', '/index.html'):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            return
        elif norm_path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
            return
        elif norm_path == '/health':
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            return
        else:
            self.send_error(404, "Not Found")
            return

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
            server_title = getattr(self.server, "title", "") or None
            if share_token:
                share_info = self.server.shares.validate(share_token)
                if share_info:
                    self.send_json({"authenticated": True, "readonly": True, "label": share_info.get("label", "Shared Session"), "title": server_title})
                    return
                else:
                    self.send_json({"authenticated": False, "readonly": True, "error": "Expired or invalid share link"}, status=403)
                    return
            auth = self.is_authenticated()
            locked, rem = self.server.rate_limiter.is_locked(ip)
            data = {"authenticated": auth, "locked": locked, "lockout_remaining": rem, "title": server_title}
            if auth:
                token = self.get_auth_token()
                data["tabs"] = self.server.terminals.list_tabs(token)
                data["token"] = token
            self.send_json(data)
            return

        elif parsed.path == '/api/tabs':
            if not self.is_authenticated():
                self.send_error(401, "Unauthorized")
                return
            token = self.get_auth_token()
            tabs = self.server.terminals.list_tabs(token)
            self.send_json({"success": True, "tabs": tabs})
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
                self.send_json({"success": False, "error": "Unauthorized session"}, status=401)
                return
            token = self.get_auth_token()
            query = urllib.parse.parse_qs(parsed.query)
            tab_id = query.get('tab', [None])[0]
            session = self.server.terminals.get(token, tab_id)
            cwd = session.get_cwd() if session else os.environ.get("HOME", "/root")
            self.send_json({"success": True, "cwd": cwd})
            return

        elif parsed.path == '/api/suggest':
            if not self.is_authenticated():
                self.send_json({"success": False, "error": "Unauthorized session"}, status=401)
                return
            token = self.get_auth_token()
            query = urllib.parse.parse_qs(parsed.query)
            tab_id = query.get('tab', [None])[0]
            session = self.server.terminals.get(token, tab_id)
            cwd = session.get_cwd() if session else os.environ.get("HOME", "/root")

            req_dir = query.get('dir', [None])[0]
            filter_type = query.get('type', ['all'])[0]  # 'all' or 'dir_only'
            target_dir = resolve_fs_path(cwd, req_dir) if req_dir else cwd

            if not os.path.exists(target_dir):
                self.send_json({"success": False, "error": "Directory not found", "items": [], "dir": target_dir}, status=404)
                return
            if not os.path.isdir(target_dir):
                self.send_json({"success": False, "error": "Not a directory", "items": [], "dir": target_dir}, status=400)
                return

            items = []
            try:
                with os.scandir(target_dir) as entries:
                    for entry in entries:
                        try:
                            is_dir = entry.is_dir(follow_symlinks=True)
                            if filter_type == 'dir_only' and not is_dir:
                                continue
                            item_info = {
                                "name": entry.name,
                                "is_dir": is_dir
                            }
                            if not is_dir:
                                try:
                                    item_info["size"] = entry.stat(follow_symlinks=True).st_size
                                except Exception:
                                    item_info["size"] = 0
                            items.append(item_info)
                        except (PermissionError, OSError):
                            continue
            except (PermissionError, OSError) as e:
                self.send_json({"success": False, "error": str(e), "items": [], "dir": target_dir}, status=403)
                return

            # Sort directories first, then alphabetically case-insensitive
            items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
            self.send_json({"success": True, "dir": target_dir, "cwd": cwd, "items": items[:250]})
            return

        elif parsed.path == '/api/stat':
            if not self.is_authenticated():
                self.send_json({"success": False, "error": "Unauthorized session"}, status=401)
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

            target_path = resolve_fs_path(cwd, file_param)
            exists = os.path.exists(target_path)
            if not exists:
                self.send_json({
                    "success": True,
                    "exists": False,
                    "is_dir": False,
                    "is_file": False,
                    "size": 0,
                    "lines": None,
                    "is_text": False,
                    "path": target_path,
                    "name": os.path.basename(target_path) or file_param
                })
                return

            is_dir = os.path.isdir(target_path)
            is_file = os.path.isfile(target_path)
            size = 0
            lines = None
            is_text = False

            try:
                stat_res = os.stat(target_path)
                size = stat_res.st_size
            except Exception:
                pass

            if is_file:
                ext = (os.path.basename(target_path).split('.').pop() if '.' in os.path.basename(target_path) else '').lower()
                BLOCKED_SET = {'exe', 'bin', 'dll', 'so', 'dylib', 'o', 'a', 'obj', 'pyc', 'pyo', 'class', 'wasm',
                               'zip', 'tar', 'gz', 'tgz', 'bz2', 'xz', '7z', 'rar', 'zst', 'iso', 'dmg', 'deb', 'rpm', 'apk', 'msi',
                               'mp4', 'mkv', 'avi', 'mov', 'webm', 'flv', 'wmv', 'mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a',
                               'pdf', 'docx', 'xlsx', 'pptx', 'sqlite', 'db', 'sqlite3',
                               'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico', 'tiff'}
                if ext not in BLOCKED_SET and size <= 5 * 1024 * 1024:
                    try:
                        with open(target_path, 'rb') as f:
                            sample = f.read(2048)
                            if b'\x00' not in sample:
                                is_text = True
                                f.seek(0)
                                lines = sum(1 for _ in f)
                    except Exception:
                        pass

            self.send_json({
                "success": True,
                "exists": True,
                "is_dir": is_dir,
                "is_file": is_file,
                "size": size,
                "lines": lines,
                "is_text": is_text,
                "path": target_path,
                "name": os.path.basename(target_path) or file_param
            })
            return

        elif parsed.path.rstrip('/') in ('/api/download', '/api/preview', '/api/view'):
            if not self.is_authenticated():
                self.send_json({"success": False, "error": "Unauthorized session"}, status=401)
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

            target_path = resolve_fs_path(cwd, file_param)

            if not os.path.exists(target_path):
                self.send_json({"success": False, "error": f"Path not found: {file_param}"}, status=404)
                return

            if os.path.isdir(target_path):
                tmp_zip_path = None
                try:
                    folder_name = os.path.basename(target_path.rstrip(os.sep)) or "archive"
                    clean_name = folder_name.replace('"', '\\"')
                    safe_name = urllib.parse.quote(f"{folder_name}.zip")
                    
                    # Create temporary zip archive
                    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp_zip:
                        tmp_zip_path = tmp_zip.name

                    EXCLUDE_DIRS = {'.git', 'node_modules', '.venv', '__pycache__', '.pytest_cache', '.next'}
                    MAX_ZIP_FILES = 25000
                    file_count = 0

                    with zipfile.ZipFile(tmp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                        base_parent = os.path.dirname(target_path) if os.path.dirname(target_path) != target_path else target_path
                        for root, dirs, files in os.walk(target_path):
                            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
                            for f in files:
                                file_count += 1
                                if file_count > MAX_ZIP_FILES:
                                    break
                                full_fp = os.path.join(root, f)
                                if os.path.islink(full_fp):
                                    continue
                                rel_fp = os.path.relpath(full_fp, base_parent)
                                try:
                                    zf.write(full_fp, rel_fp)
                                except Exception:
                                    continue
                            if file_count > MAX_ZIP_FILES:
                                break

                    zip_size = os.path.getsize(tmp_zip_path)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Length", str(zip_size))
                    self.send_header("Access-Control-Expose-Headers", "Content-Disposition")
                    self.send_header("Content-Disposition", f'attachment; filename="{clean_name}.zip"; filename*=UTF-8\'\'{safe_name}')
                    self.end_headers()

                    with open(tmp_zip_path, 'rb') as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                except Exception as e:
                    try:
                        self.send_json({"success": False, "error": f"Failed creating zip archive: {e}"}, status=500)
                    except Exception:
                        pass
                finally:
                    if tmp_zip_path and os.path.exists(tmp_zip_path):
                        try:
                            os.remove(tmp_zip_path)
                        except Exception:
                            pass
                return

            if not os.path.isfile(target_path):
                self.send_json({"success": False, "error": f"Target is not a regular file: {file_param}"}, status=400)
                return

            try:
                file_size = os.path.getsize(target_path)
                filename = os.path.basename(target_path)
                clean_name = filename.replace('"', '\\"')
                content_type = mimetypes.guess_type(target_path)[0] or "application/octet-stream"
                disposition_type = "inline" if (parsed.path.rstrip('/') in ('/api/preview', '/api/view') or query.get('inline', ['0'])[0] in ('1', 'true', 'yes')) else "attachment"
                if disposition_type == "inline":
                    if content_type == "application/octet-stream" or content_type.startswith("text/") or content_type in ("application/json", "application/javascript", "application/xml"):
                        content_type = "text/plain; charset=utf-8"

                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(file_size))
                self.send_header("Access-Control-Expose-Headers", "Content-Disposition")
                safe_name = urllib.parse.quote(filename)
                self.send_header("Content-Disposition", f'{disposition_type}; filename="{clean_name}"; filename*=UTF-8\'\'{safe_name}')
                self.end_headers()

                with open(target_path, 'rb') as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            except Exception as e:
                try:
                    self.send_json({"success": False, "error": f"Failed reading file: {e}"}, status=500)
                except Exception:
                    pass
            return

        elif parsed.path == '/health':
            self.send_json({"status": "ok", "service": "fire-ssh"})
            return

        elif parsed.path == '/api/security/events':
            token = self.get_auth_token() or self.get_cookie_token()
            ip = self.get_client_ip()
            if not self.server.sessions.is_valid(token, ip):
                self.send_json({"error": "Unauthorized"}, status=401)
                return
            events = self.server.security_events.get_recent_events(limit=50) if hasattr(self.server, 'security_events') else []
            self.send_json({"events": events, "count": len(events)})
            return

        elif parsed.path == '/' or parsed.path == '/index.html':
            query = urllib.parse.parse_qs(parsed.query)
            share_token = query.get('share', [None])[0]
            rendered_html = HTML_TEMPLATE

            custom_title = getattr(self.server, 'title', '') or query.get('title', [None])[0] or ''
            inject_vars = []

            if custom_title:
                safe_title_esc = html.escape(custom_title)
                rendered_html = rendered_html.replace(
                    '<title>Fire PM — Remote Terminal</title>',
                    f'<title>{safe_title_esc}</title>',
                    1
                )
                safe_title_json = json.dumps(custom_title).replace('</', r'<\/')
                inject_vars.append(f"window.SESSION_TITLE = {safe_title_json};")

            if share_token:
                share_info = self.server.shares.validate(share_token)
                if not share_info:
                    self.send_response(403)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    expired_html = """<!DOCTYPE html><html><head><title>Fire PM - Share Expired</title><script src="https://cdn.tailwindcss.com"></script></head><body class="bg-slate-950 text-slate-100 flex items-center justify-center min-h-screen"><div class="bg-slate-900 border border-red-500/40 rounded-2xl p-8 max-w-md text-center shadow-2xl"><div class="text-4xl mb-4">🔒</div><h1 class="text-xl font-bold text-red-400 mb-2">Share Link Expired or Invalid</h1><p class="text-sm text-slate-400 mb-6">This read-only session sharing link has expired or was revoked by the host.</p><a href="/" class="px-4 py-2 bg-orange-600 hover:bg-orange-500 text-white rounded-lg text-sm font-semibold transition">Back to Terminal</a></div></body></html>"""
                    self.wfile.write(expired_html.encode('utf-8'))
                    return
                safe_token = json.dumps(str(share_token)).replace('</', r'<\/')
                safe_label = json.dumps(str(share_info.get('label', 'Shared Session'))[:64]).replace('</', r'<\/')
                inject_vars.append("window.IS_READONLY = true;")
                inject_vars.append(f"window.SHARE_TOKEN = {safe_token};")
                inject_vars.append(f"window.SHARE_LABEL = {safe_label};")

            if inject_vars:
                inject_script = f"<script>{' '.join(inject_vars)}</script>"
                rendered_html = rendered_html.replace('</head>', f'{inject_script}\n</head>', 1)

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "frame-ancestors 'none';")
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
                if old_token:
                    self.server.terminals.migrate_token(old_token, token)
                    self.server.sessions.revoke(old_token)
                
                tabs = self.server.terminals.list_tabs(token)
                proto = self.headers.get('X-Forwarded-Proto', '').lower()
                is_https = proto == 'https' or 'https' in self.headers.get('CF-Visitor', '')
                secure_attr = "; Secure" if is_https else ""
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Set-Cookie", f"fire_ssh_session={token}; Path=/; HttpOnly; SameSite=Lax{secure_attr}; Max-Age={SESSION_EXPIRY_SECONDS}")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "token": token, "tabs": tabs}).encode('utf-8'))
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

        elif parsed.path.rstrip('/') == '/api/upload':
            if not self.is_authenticated():
                self.send_json({"success": False, "error": "Unauthorized session"}, status=401)
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

            target_dir = resolve_fs_path(cwd, dest) if dest else cwd

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

        elif parsed.path == '/api/title':
            client_ip = self.get_client_ip()
            is_loopback = client_ip in ('127.0.0.1', '::1', 'localhost') or client_ip.startswith('127.')

            if not is_loopback:
                if not self.is_authenticated():
                    self.send_json({"success": False, "error": "Unauthorized"}, status=401)
                    return
                token = self.get_auth_token() or self.get_cookie_token()
                if not token or (hasattr(self.server, 'shares') and self.server.shares.validate(token)):
                    self.send_json({"success": False, "error": "Read-only users cannot modify session title"}, status=403)
                    return

            content_len = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_len).decode('utf-8', errors='ignore') if content_len > 0 else '{}'
            new_title = ""
            try:
                data = json.loads(body)
                new_title = str(data.get('title', '')).strip()
            except Exception:
                pass

            self.server.title = new_title

            try:
                port = self.server.server_address[1]
                state_file = f"/tmp/fire-ssh/{port}.json"
                if os.path.exists(state_file):
                    with open(state_file, 'r', encoding='utf-8') as f:
                        s_data = json.load(f)
                    s_data['title'] = new_title
                    with open(state_file, 'w', encoding='utf-8') as f:
                        json.dump(s_data, f, indent=2)
            except Exception:
                pass

            try:
                msg = {"type": "title_update", "title": new_title}
                for sess in self.server.terminals.list_all():
                    sess.send_ws_json(msg)
            except Exception:
                pass

            self.send_json({"success": True, "title": new_title})
            return

        elif parsed.path == '/api/logout':
            token = self.get_auth_token() or self.get_cookie_token()
            if token:
                self.server.shares.revoke_by_session(token)
                self.server.sessions.revoke(token)
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
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception:
            pass

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
                            session.send_ws_json({"type": "pty_resize", "cols": cols, "rows": rows})
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
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception:
            pass

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


def run_server(port: int, plain_password: str = None, salt_hex: str = None, hash_hex: str = None, shell: str = None, title: str = None):
    def _sigchld_handler(signum, frame):
        while True:
            try:
                rpid, _ = os.waitpid(-1, os.WNOHANG)
                if rpid <= 0:
                    break
            except (ChildProcessError, OSError):
                break

    try:
        signal.signal(signal.SIGCHLD, _sigchld_handler)
    except Exception:
        pass

    if not plain_password and not hash_hex:
        salt_hex, hash_hex = PasswordManager.load_stored_credentials()

    server = ThreadedHTTPServer(('127.0.0.1', port), FireSSHServerHandler)
    server.plain_password = plain_password
    server.salt_hex = salt_hex
    server.hash_hex = hash_hex
    server.target_shell = shell
    server.title = title.strip() if title else ""
    server.rate_limiter = RateLimiter()
    server.sessions = SessionManager()
    server.terminals = TerminalSessionManager()
    server.shares = ShareTokenManager()
    server.security_events = SecurityEventManager()

    def _shutdown_handler(signum, frame):
        try:
            close_data = {
                "type": "session_closed",
                "reason": "SSH session closed via 'fire ssh close'",
                "message": "This remote web terminal session was closed (fire ssh close)."
            }
            payload = json.dumps(close_data).encode('utf-8')
            msg_frame = ws_make_frame(payload, opcode=1)
            close_frame = ws_make_frame(struct.pack("!H", 1000) + b"Session closed", opcode=8)

            with server.terminals.lock:
                for sess in list(server.terminals.sessions.values()):
                    with sess.sock_lock:
                        for s in list(sess.interactive_socks):
                            try:
                                s.sendall(msg_frame)
                                s.sendall(close_frame)
                            except Exception:
                                pass
                        for ro in list(sess.readonly_socks):
                            try:
                                ro.sendall(msg_frame)
                                ro.sendall(close_frame)
                            except Exception:
                                pass
            time.sleep(0.15)
        except Exception:
            pass
        sys.exit(0)

    try:
        signal.signal(signal.SIGTERM, _shutdown_handler)
        signal.signal(signal.SIGINT, _shutdown_handler)
    except Exception:
        pass

    print(json.dumps({
        "status": "ready",
        "port": port,
        "title": server.title,
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
    p_start.add_argument("--pass-stdin", action="store_true", help="Read plaintext password from stdin")
    p_start.add_argument("--salt", type=str, help="Salt hex for PBKDF2 hash")
    p_start.add_argument("--hash", type=str, help="Hash hex for PBKDF2 verification")
    p_start.add_argument("--shell", type=str, help="Target shell executable")
    p_start.add_argument("--title", type=str, default="", help="Web terminal session title")
    p_start.add_argument("--name", "-n", type=str, default="", help="Web terminal session name (alias for title)")

    p_hash = subparsers.add_parser("hash-password", help="Hash password using PBKDF2-HMAC-SHA256")
    p_hash.add_argument("password", type=str, help="Plaintext password to hash")
    p_hash.add_argument("--save", action="store_true", help="Save hashed password to /etc/fire-pm/ssh-auth.json")

    p_check = subparsers.add_parser("check-password", help="Verify password against salt and hash")
    p_check.add_argument("password", type=str, help="Plaintext password")
    p_check.add_argument("salt", type=str, help="Salt hex")
    p_check.add_argument("hash", type=str, help="Hash hex")

    p_title = subparsers.add_parser("title", help="Update web terminal session title")
    p_title.add_argument("new_title", type=str, help="New session title")
    p_title.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port of running session")

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
        plain_pw = args.password
        if getattr(args, "pass_stdin", False):
            try:
                plain_pw = sys.stdin.readline().rstrip('\r\n')
            except Exception:
                plain_pw = None
        session_title = args.title or getattr(args, "name", None) or None
        run_server(args.port, plain_password=plain_pw, salt_hex=args.salt, hash_hex=args.hash, shell=args.shell, title=session_title)

    elif args.command == "title":
        import urllib.request
        url = f"http://127.0.0.1:{args.port}/api/title"
        req = urllib.request.Request(
            url,
            data=json.dumps({"title": args.new_title}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as r:
                res = json.loads(r.read().decode("utf-8"))
                print(json.dumps(res))
        except Exception as e:
            print(json.dumps({"success": False, "error": str(e)}))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
