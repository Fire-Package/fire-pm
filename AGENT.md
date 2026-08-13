# Fire PM (`Fire-Package/fire-pm`)

Fire PM is a Linux-native process and application management platform providing a fast CLI, an interactive Terminal UI (TUI), and a modern developer Web Dashboard.

## Repository Architecture

```text
fire-pm/
├── app/                  # Core Bash Process Manager & CLI
│   ├── fire              # Main executable CLI engine
│   └── ff-service        # Service status helper
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
├── shared/               # Shared templates and configurations
│   ├── units/            # Systemd templates (e.g. fire-reload@.service)
│   ├── nginx/            # Nginx map & tunnel virtualhost configuration
│   └── config.example.json
│
├── install.sh            # Automated installer for Linux systems
└── README.md             # Complete user guide & setup instructions
```

## Architectural Conventions & Rules

1. **Source of Truth:** All process management is backed by `systemd`. The CLI (`app/fire`), TUI (`tui/fire_tui.py`), and Web backend (`web/src/lib/services/`) never maintain duplicate state machines — they query `systemd` and `fire list --json`.
2. **Safe Subprocesses:** The Web backend must execute system commands using argument-based `child_process.execFile` and `spawn` (never string evaluation or shell interpolation).
3. **Authentication:** Web UI access is protected by bcrypt master passwords and signed JWT tokens in `httpOnly` secure cookies with double-submit CSRF protection.
4. **Zero Database:** Config lives in `/etc/fire-pm/config.json`, unit files in `/etc/systemd/system/fire-*.service`, and active tunnel state in `/tmp/fire-tunnels/`.

## Key Development Commands

* **Install Whole Ecosystem:** `sudo ./install.sh`
* **Run CLI:** `fire list` / `fire doctor` / `fire tunnel list`
* **Run TUI:** `python3 tui/fire_tui.py`
* **Web UI Dev:** `cd web && pnpm dev`
* **Web UI Build:** `cd web && pnpm build`
* **Web UI Production Start:** `cd web && ./start.sh`
