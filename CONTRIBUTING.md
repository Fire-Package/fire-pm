# Contributing to Fire PM

Thank you for your interest in contributing to Fire PM! This document provides guidelines and instructions for setting up your development environment, submitting bug reports, proposing features, and opening pull requests.

---

## Code of Conduct

We are committed to providing a welcoming, inclusive, and harassment-free environment for everyone. Please be respectful and constructive in all interactions across issues, discussions, and pull requests.

---

## Project Overview & Architecture

Fire PM is a Linux-native process and application management ecosystem composed of three interfaces over a shared systemd backend:

- **CLI Engine (`app/fire`)**: Bash-based process supervisor interfacing directly with systemd user/system units.
- **Web Dashboard (`web/`)**: Full-stack Next.js (App Router, React 19, TypeScript, Tailwind CSS v4) providing real-time metrics, SSE log streaming, resource limiting, and tunnel management.
- **Terminal UI (`tui/fire_tui.py`)**: Interactive full-screen terminal dashboard built with Python Textual.
- **Shared Templates (`shared/`)**: Systemd unit templates and Nginx configuration templates.

### Core Architectural Principles

1. **systemd is the Single Source of Truth**: The CLI, TUI, and Web backend do not maintain independent state machines. State is queried directly from systemd and `fire list --json`.
2. **Safe Subprocesses**: The Web backend must execute system commands using argument-based `child_process.execFile` and `spawn` (never string interpolation or raw shell evaluation).
3. **Zero External Database**: Global configuration resides in `/etc/fire-pm/config.json`, unit files in `/etc/systemd/system/fire-*.service`, and active tunnel mappings in `/tmp/fire-tunnels/`.

---

## Getting Started

### Prerequisites

- **OS**: Linux with `systemd` (Ubuntu 22.04+, Debian 12+, Fedora, Arch, etc.)
- **Node.js**: v22 LTS or newer
- **Package Manager**: [`pnpm`](https://pnpm.io/)
- **Python**: Python 3.10+ with `pip`
- **Core Utilities**: `procps`, `iproute2`, `curl`

### Repository Setup

1. Fork the repository on GitHub.
2. Clone your fork locally:
   ```bash
   git clone https://github.com/<your-username>/fire-pm.git
   cd fire-pm
   ```
3. Set up the upstream remote:
   ```bash
   git remote add upstream https://github.com/Fire-Package/fire-pm.git
   ```

---

## Development Workflows

### 1. Web Dashboard (`web/`)

```bash
cd web

# Install dependencies using pnpm
pnpm install

# Start development server
pnpm dev

# Lint code
pnpm lint

# Build for production
pnpm build
```

> **Note**: Always use `pnpm` to manage dependencies. Do not modify lockfiles manually.

### 2. Terminal UI (`tui/`)

```bash
# Install Python dependencies
pip install -r tui/requirements.txt

# Run the TUI dashboard
python3 tui/fire_tui.py
```

### 3. CLI Engine (`app/`)

Test CLI scripts directly or link them locally:
```bash
./app/fire --help
./app/fire list
```

---

## Making Changes

1. **Create a branch**:
   ```bash
   git checkout -b fix/issue-description
   # or
   git checkout -b feat/feature-name
   ```
2. **Follow existing coding style**:
   - Keep functions focused and readable.
   - Use descriptive variable and function names.
   - Avoid introducing unnecessary external dependencies.
   - Maintain type safety in TypeScript files.
3. **Verify your changes**:
   - For Web changes: run `pnpm lint` and `pnpm build`.
   - For CLI/TUI changes: test execution with sample processes.
4. **Commit your changes**:
   - Use clear, concise commit messages (e.g. `feat(web): ...`, `fix(cli): ...`, `docs: ...`).

---

## Submitting a Pull Request

1. Push your branch to your fork:
   ```bash
   git push origin feat/feature-name
   ```
2. Open a Pull Request against the `main` branch of `Fire-Package/fire-pm`.
3. In the PR description:
   - Reference any relevant issues (e.g. `Fixes #123`).
   - Clearly explain what changed and why.
   - Describe how the changes were verified/tested.

---

## Reporting Issues

- Search existing issues and PRs before creating a new issue.
- Provide a clear, descriptive title.
- Include your operating system, Node.js version, and steps to reproduce when reporting bugs.
