# 🔥 Fire PM

> **The lightweight, Linux-native process & application management platform.**  
> Fast CLI &bull; Rich Terminal UI (TUI) &bull; Developer Web Dashboard &bull; Wildcard Reverse-Proxy Tunnels

---

## ⚡ Quick Start (1-Command Install)

Clone the repository and run the automated installer:

```bash
git clone https://github.com/Fire-Package/fire-pm.git
cd fire-pm
sudo ./install.sh
```

This installs:
* `fire` CLI binary to `/usr/local/bin/fire`
* Interactive Python TUI dashboard to `/usr/local/bin/fire_tui.py`
* Systemd auto-reload units
* Pre-built developer Web UI

---

## 🖥️ Usage Modes

### 1. Interactive Terminal Mode (TUI / CLI)
Run `fire` with no arguments to launch the full-screen terminal dashboard:
```bash
fire
```

### 2. Command Line Interface (CLI)
```bash
# Start a Python, Node.js, or Shell script as a persistent service
fire start app.py --name my-api --env PORT=8080

# List all managed services with CPU, memory, and port statistics
fire list

# View live system health diagnostics
fire doctor

# Tail live output logs
fire logs my-api

# Stop, restart, or delete processes
fire stop my-api
fire restart my-api
fire delete my-api

# Set Memory and CPU limits
fire limit my-api 500M 50%
```

### 3. Public HTTPS Tunnels (Reverse Proxy)
Expose any local port over a secure HTTPS subdomain mapped via Nginx:
```bash
# Open a tunnel for port 3000
fire tunnel open 3000
# Output: https://a1b2c3d4-tunnel.yourdomain.com

# List active tunnels
fire tunnel list

# Close a tunnel
fire tunnel close 3000
```

### 4. Developer Web Dashboard & API
Start the Web UI as a managed service:
```bash
fire start $(pwd)/web/start.sh --name fire-web --env PORT=3000
```
Open `http://localhost:3000` in your browser. On your first visit, set your master password to access:
* Real-time process metrics table with 3-second live updates
* Live Journalctl log streaming with auto-scroll and search filters
* In-browser systemd unit file editor with instant daemon reload
* Dynamic Memory & CPU resource limiter
* Tunnel management console

---

## 📁 Repository Structure

```text
fire-pm/
├── app/                  # Core process manager Bash engine (fire)
├── web/                  # Full-stack Next.js Web UI & REST/SSE API
├── tui/                  # Python Textual interactive terminal dashboard
├── shared/               # Shared systemd templates, Nginx configs, examples
├── install.sh            # Automated Linux installer
├── AGENT.md              # Architecture reference for AI coding agents
└── README.md             # Documentation & guide
```

---

## 🔒 Security Architecture

* **Argument-Based Execution:** All system calls utilize strict argument arrays without shell evaluation.
* **Strict Validation:** Service names and ports are strictly sanitized against alphanumeric regexes.
* **Session Protection:** Signed JWT tokens stored in `httpOnly`, `Secure`, `SameSite=Strict` cookies.
* **Double-Submit CSRF:** Mutating endpoints require matching CSRF header tokens.
* **Zero External Database:** All state is derived directly from `systemd` and local flat files.

---

## 📄 License
MIT License. Created by [Fire Package](https://github.com/Fire-Package).
