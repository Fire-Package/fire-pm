---
name: fire-pm
description: >-
  Comprehensive guide and runbook for developing, operating, and troubleshooting Fire PM.
  Use when managing Linux systemd services, executing Fire PM CLI commands, interacting with the
  Python Textual TUI, developing or building the Next.js Web Dashboard, or configuring reverse proxy tunnels.
---

# Fire PM Skill Guide

Fire PM is a Linux-native process supervisor and application management ecosystem providing a CLI (`app/fire`), a Python Textual Terminal UI (`tui/fire_tui.py`), and a Next.js 15 Web Dashboard (`web/`) with live SSE log streaming and reverse-proxy tunnels.

---

## Architectural Rules & Key Paths

1. **systemd is the Single Source of Truth**:
   - Never introduce secondary state databases or caches.
   - CLI, TUI, and Web UI inspect status by querying `systemd` or `fire list --json`.
2. **Safe Subprocesses**:
   - In the Web backend (`web/src/lib/services/`), use argument arrays with `child_process.execFile` or `spawn`. Never use raw string shell execution.
3. **Core File Locations**:
   - Master configuration: `/etc/fire-pm/config.json`
   - Generated unit files: `/etc/systemd/system/fire-*.service`
   - Active tunnel descriptors: `/tmp/fire-tunnels/`
   - Nginx tunnel map: `/etc/nginx/tunnels.map`

---

## CLI Operations Reference

### Process Lifecycle

```bash
# Start a script or binary as a managed service
fire start <script_or_binary> --name <service_name> [--env KEY=VALUE] [--watch]

# Start with resource limits
fire start app.py --name api --memory 512M --cpu 50%

# List all services with status, CPU, memory, uptime, and port
fire list
fire list --json   # Machine-readable JSON output

# Inspect service details
fire info <service_name>

# View / tail real-time journalctl logs
fire logs <service_name>
fire live <service_name>

# Stop, restart, or delete a service
fire stop <service_name>
fire restart <service_name>
fire delete <service_name>

# Update memory and CPU limits on an existing service
fire limit <service_name> <memory_limit> <cpu_percent>
# Example: fire limit api 1G 80%

# Real-time process monitor
fire monit

# System diagnostics & health check
fire doctor
fire doctor --json
```

### Reverse-Proxy Tunnels

```bash
# Expose a local port through a public HTTPS subdomain via Nginx
fire tunnel open <port>

# List all active tunnels
fire tunnel list
fire tunnel list --json

# Close a tunnel
fire tunnel close <port>
```

---

## Subsystem Development Workflows

### 1. Web Dashboard (`web/`)

- **Tech Stack**: Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS v4, SWR, Phosphor Icons.
- **Commands**:
  ```bash
  cd web
  pnpm install      # Install dependencies (do not use npm/yarn)
  pnpm dev          # Start development server on port 3000
  pnpm lint         # Run ESLint validation
  pnpm build        # Build production bundle
  ./start.sh        # Run standalone production instance
  ```

### 2. Terminal UI (`tui/`)

- **Tech Stack**: Python 3, Textual.
- **Commands**:
  ```bash
  # Install requirements
  pip install -r tui/requirements.txt

  # Launch TUI
  python3 tui/fire_tui.py
  ```

### 3. System Installer (`install.sh`)

- Automated setup for Linux distributions (Debian/Ubuntu/Fedora/CentOS/Arch):
  ```bash
  sudo ./install.sh
  ```

---

## Troubleshooting & Verification

1. **Verify service unit configuration**:
   ```bash
   systemctl status fire-<service_name>.service
   journalctl -u fire-<service_name>.service -n 50 --no-pager
   ```
2. **Reload systemd daemon**:
   ```bash
   sudo systemctl daemon-reload
   ```
3. **Check health score**:
   ```bash
   fire doctor
   ```
