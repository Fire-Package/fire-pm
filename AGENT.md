# Fire PM (`Fire-Package/fire-pm`)

Fire PM is a lightweight, Linux-native process and application management platform providing a fast CLI, an interactive Terminal UI (TUI), a modern developer Web Dashboard, encrypted public HTTPS tunnels, and a persistent browser-based remote Web Terminal (`fire ssh`).

## Repository Architecture

```text
fire-pm/
├── app/                  # Core Bash Process Manager & CLI
│   ├── fire              # Main executable CLI engine
│   ├── ff-service        # Service status helper
│   └── fire_ssh.py       # Remote Web Terminal (PTY/WebSocket) persistent engine
│
├── web/                  # Full-stack Next.js Web UI & REST/SSE API
│   ├── src/              # React 19 UI, Next.js 15 App Router, Tailwind v4
│   │   ├── app/          # App routes, pages & API endpoints (/api/*)
│   │   ├── components/   # UI components (ProcessTable, LogViewer, etc.)
│   │   ├── hooks/        # SWR live polling and SSE log streaming hooks
│   │   └── lib/          # Services (Process, Log, Tunnel, System, Config, Auth)
│   ├── package.json
│   └── start.sh          # Standalone production runner
│
├── tui/                  # Python Textual Interactive Terminal Dashboard
│   ├── fire_tui.py       # Full-screen terminal dashboard
│   └── requirements.txt  # Python dependencies (textual)
│
├── assets/               # Screenshots and visual documentation assets
├── tools/                # Developer utilities (upload_assets.py, etc.)
├── shared/               # Shared templates and configurations
│   ├── units/            # Systemd templates (e.g. fire-reload@.service)
│   ├── nginx/            # Nginx map & tunnel virtualhost configuration
│   └── config.example.json
│
├── install.sh            # Automated installer for Linux systems
└── README.md             # Complete user guide & visual showcase
```

## Core Subsystems & Components

### 1. Process Management (`app/fire`, `systemd`)
- **Source of Truth:** All process state is managed directly by Linux `systemd`. The CLI, TUI, and Web backend never maintain duplicate state machines.
- **Unit Files:** Automatically generated and placed in `/etc/systemd/system/fire-<name>.service`.
- **Interpreters:** Built-in automatic runtime detection for Python (`venv` aware), Node.js, and Shell scripts.

### 2. Remote Web Terminal (`app/fire_ssh.py`)
- **Persistent PTY Engine:** PTY lifecycle is decoupled from WebSocket connections via `TerminalSession` and `TerminalSessionManager`. Disconnecting or refreshing the browser retains the active shell and replays the last 128 KB of scrollback buffer upon reattachment.
- **Signal Dispatching:** Fast loop / process interrupts (`Ctrl+C`, `Ctrl+Z`, `Ctrl+D`) resolve the active foreground process group via `os.tcgetpgrp` and dispatch direct kernel signals (`os.killpg`) to instantly break infinite stdout loops (e.g. `yes`).
- **Authentication & Security:** Salted PBKDF2-HMAC-SHA256 password hashing, brute-force IP rate limiting (5 attempts / 5-min lockout), 24-hour cryptographically signed session tokens, and Xterm.js emulation.
- **Tunnel Routing:** Automatically routes through custom Nginx domain tunnels when configured, or falls back to Cloudflare tunnels.

### 3. Public HTTPS Tunnels
- **Quick Tunnels:** Zero-configuration public URLs powered by `cloudflared` forced with `--protocol http2` over TCP port 443 to eliminate UDP QUIC packet loss and `ERR_QUIC_PROTOCOL_ERROR`.
- **Custom Domain Tunnels:** Self-hosted reverse proxy using Nginx dynamic port maps (`/etc/nginx/tunnels.map`) and wildcard virtualhosts (`*.yourdomain.com`).
- **Domain Normalization & Priority:** Fire PM automatically gives highest precedence to custom domains found in `/etc/fire-pm/config.json`, stripping duplicate sub-level prefixes.

### 4. Developer Web UI (`web/`)
- **Stack:** Next.js 15.5 App Router, React 19, Tailwind CSS v4.
- **API & Streaming:** REST endpoints for mutation, Server-Sent Events (SSE) for live Journalctl log streaming and process metrics polling.
- **Authentication:** Bcrypt password verification with JWT cookies (`httpOnly`, `Secure`, `SameSite=Strict`) and double-submit CSRF tokens.

## Key Development Commands

* **Run CLI:** `/usr/local/bin/fire list` / `fire doctor` / `fire tunnel list`
* **Remote Web Terminal:** `fire ssh` / `fire ssh --daemon` / `fire ssh close`
* **Run TUI:** `python3 tui/fire_tui.py`
* **Web UI Dev:** `cd web && pnpm dev`
* **Web UI Build:** `cd web && pnpm build`
* **Web UI Production Start:** `fire start /opt/fire-pm/web/start.sh --name fire-web --env PORT=3000`
* **Update Fire PM:** `fire update` / `fire update --force`
