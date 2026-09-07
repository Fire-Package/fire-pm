# Changelog

All notable changes to the Fire PM project are documented in this file.

Format: `[YYYY-MM-DD]{HH:mm:ss} Title: Description #optional extra notes` (Timestamps in Asia/Kolkata)

---

## [Unreleased]

- `[2026-09-07]{14:07:31} Web Terminal: Remove predictive echo mode and command bar for standard, deterministic PTY stream I/O #Issue 44`
- `[2026-09-07]{01:28:45} Documentation: Overhaul README.md with sanitized high-resolution screenshots, multi-tab terminal showcase, session sharing & alerts documentation, and Mermaid system architecture diagram`
- `[2026-09-07]{00:28:30} Security Hardening: Add WebSocket Origin validation, restrict forwarded IP trust to loopback, verify regular files on download, cap uploads at 500MB, add dynamic Secure cookies, relocate cloudflared binary, secure tunnel directory permissions (755/644), and isolate TUI IPC #Issue 41`
- `[2026-09-06]{23:59:00} Web Terminal: Add read-only live session sharing links with configurable expiration and instant revocation #Issue 39`
- `[2026-09-06]{23:38:00} Web Terminal: In-terminal multi-tab sessions with process-aware badges, keyboard shortcuts, background bell alerts, and independent PTY multiplexing #Issue 37`
- `[2026-09-06]{23:12:00} Web Terminal: Add drag-and-drop file upload to $PWD, toolbar upload/download buttons, and streaming file transfer endpoints #Issue 35`
- `[2026-09-06]{22:45:00} Web Terminal: Add background task alerts with desktop notifications, audio chime, and Antigravity bell/OSC integration #Issue 33`
- `[2026-09-06]{21:54:00} Web Terminal: Add window capture-phase keydown listener and fullscreenchange lock for Ctrl+W and Alt+W support #Issue 31`
- `[2026-09-06]{21:49:00} Web Terminal: Implement stream buffer reconciliation and instant local newline for 0ms typing on high-latency connections #Issue 31`
- `[2026-09-06]{21:28:00} Web Terminal: Add direct in-terminal 0ms typing echo with server echo cancellation for interactive shells like bash and antigravity #Issue 31`
- `[2026-09-06]{21:08:00} Web Terminal: Add local command input buffer (line mode) for 0ms typing lag on high latency / 2000ms ping connections #Issue 31`
- `[2026-09-06]{20:44:00} Web Terminal: Add Ctrl+W support with keyboard lock, Alt+W safe alias, context menu, and fullscreen mode for editors like nano #Issue 31`
- `[2026-09-04]{12:44:00} CLI: Fix fire ssh immediately closing in foreground mode and add Ctrl+B detach shortcut #PR 30`
- `[2026-09-04]{12:22:00} Web Terminal: Extend detached session TTL to 3 days and support session reattachment on re-login #PR 28`
- `[2026-09-04]{12:13:00} Web Terminal: Fix clipboard copy on Ctrl+C and native copy events in web terminal #PR 27`
- `[2026-09-02]{20:25:00} Documentation Refresh: Overhaul README.md with comprehensive guides, feature comparisons, TUI keybindings, CLI references, and architecture breakdown`

---

## [Release History]

- `[2026-08-30]{02:22:11} System Cleanup: Remove extraneous personal systemd unit files and expand gitignore`
- `[2026-08-29]{12:36:20} Web Terminal: Merge network latency indicator PR #25`
- `[2026-08-29]{12:35:52} Web Terminal: Add live network latency indicator to the remote web terminal interface`
- `[2026-08-28]{02:13:44} Documentation: Update AGENT.md architecture reference with remote terminal and tunneling subsystems`
- `[2026-08-28]{02:10:36} Web Terminal: Add reliable Ctrl+C interrupt handling, process group signal dispatching, and control toolbar`
- `[2026-08-28]{02:01:51} Web Terminal: Implement persistent PTY sessions and keepalive heartbeats for fire ssh`
- `[2026-08-28]{01:43:09} Documentation: Add product screenshot showcase to README.md`
- `[2026-08-28]{01:15:16} Tooling: Add asset screenshot uploader developer web tool`
- `[2026-08-28]{00:29:36} Tunnel Subsystem: Normalize custom domain names and preserve existing working Nginx configurations`
- `[2026-08-28]{00:22:59} Tunnel Subsystem: Force --protocol http2 for cloudflared tunnels to eliminate ERR_QUIC_PROTOCOL_ERROR`
- `[2026-08-28]{00:20:52} Nginx: Fix default_type directive location in Nginx tunnel template`
- `[2026-08-28]{00:18:37} Nginx: Fix Nginx custom domain configuration structure and error reporting`
- `[2026-08-27]{23:27:13} Maintenance: Ignore Playwright test artifacts in repository`
- `[2026-08-27]{23:24:43} Web Terminal: Prefer custom domain tunnels first for fire ssh and wait for active edge connection`
- `[2026-08-27]{23:19:52} CLI: Ensure action_ssh_close returns exit code 0 cleanly`
- `[2026-08-27]{23:17:39} Web Terminal: Fix JavaScript string escaping in web terminal template and ensure synchronous tunnel URL resolution`
- `[2026-08-27]{23:01:53} Web Terminal: Add fire ssh for secure remote web terminal with salted PBKDF2 authentication and rate limiting #PR 24`
- `[2026-08-26]{14:20:39} Self-Update: Support --force flag and automatic recovery from unstaged modifications during update #PR 22`
- `[2026-08-26]{14:12:25} Autocompletion: Make bash completions standalone without external bash-completion library dependency #PR 20`
- `[2026-08-26]{14:08:40} Self-Update: Use atomic binary installation and exec for in-place self-updates`
- `[2026-08-26]{14:06:30} Installer: Improve update and install headless robustness #PR 19`
- `[2026-08-26]{14:03:27} Autocompletion: Add shell auto-completion for Bash, Zsh, and Fish #PR 18`
- `[2026-08-26]{14:00:50} CLI: Add fire flush command for log cleanup and journal vacuuming #PR 16`
- `[2026-08-26]{13:55:34} Boot Persistence: Add fire startup, fire unstartup, and --no-startup for boot persistence control #PR 14`
- `[2026-08-26]{13:50:53} Snapshots: Add fire save and fire restore commands for process snapshot and restoration #PR 12`
- `[2026-08-26]{13:42:27} CLI: Add fire update self-updater and --env-file support #PR 10`
- `[2026-08-26]{13:13:28} Documentation: Add tunnel provider comparison table with time limits to README`
- `[2026-08-25]{21:34:47} Documentation: Update README and SKILL.md with multi-provider tunnel documentation`
- `[2026-08-25]{21:26:23} Tunnel Subsystem: Support zero-config Quick Tunnels and self-hosted Nginx custom domain tunnels #PR 7`
- `[2026-08-25]{20:15:53} CLI: Allow running CLI without manual sudo and auto-escalate mutating actions #PR 5`
- `[2026-08-25]{19:47:44} Installer: Fix TUI Python dependency discovery and make Web UI build optional in installer #PR 3`
- `[2026-08-19]{17:41:41} Web Dashboard: Resolve icon imports and CSRF verification helper for production build`
- `[2026-08-19]{17:33:58} Web Dashboard: Redesign telemetry dashboard with high-density process registry and direct launch modal`
- `[2026-08-19]{17:25:54} Documentation: Add fire-pm workspace skill for AI agents`
- `[2026-08-19]{17:24:10} Documentation: Add contribution guidelines`
- `[2026-08-19]{17:23:28} Licensing: Add MIT license`
- `[2026-08-16]{23:04:55} Security: Add auth rate limiting and cryptographically random fallback secret`
- `[2026-08-16]{23:04:38} Web Dashboard: Redesign dashboard with ethereal hardware theme and phosphor icons`
- `[2026-08-14]{07:47:03} Core: Handle absolute paths in fire start and discover unit files directly in container environments`
- `[2026-08-14]{07:35:42} Installer: Use official Node.js binary tarball instead of distro repos to guarantee v22`
- `[2026-08-14]{07:23:51} Installer: Install Node.js v22 LTS via NodeSource instead of outdated distro packages`
- `[2026-08-14]{07:03:53} Installer: Add 1-liner curl-to-bash support for automated installation`
- `[2026-08-14]{01:38:45} Installer: Add automatic systemd, python, and system dependency installer`
- `[2026-08-14]{01:35:54} Installer: Make installer and start scripts fully location-independent`
- `[2026-08-14]{01:32:02} Initial Commit: Initial release of Fire PM monorepo (app, web, tui, shared, install.sh)`
