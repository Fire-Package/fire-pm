"use client";

import React, { useState } from "react";
import { Header } from "@/components/Header";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";
import { useSsh } from "@/hooks/useSsh";
import { SshApi } from "@/lib/api/ssh";
import { 
  TerminalWindow, 
  Plus, 
  Copy, 
  Check, 
  Trash, 
  ArrowSquareOut, 
  ShieldCheck,
  Lock,
  Broadcast
} from "@phosphor-icons/react";

export default function SshSessionsPage() {
  const { sessions, total, online, isLoading, refresh } = useSsh();
  const { showToast } = useToast();

  const [isOpenModal, setIsOpenModal] = useState(false);
  const [portInput, setPortInput] = useState("");
  const [titleInput, setTitleInput] = useState("");
  const [passwordInput, setPasswordInput] = useState("");
  const [providerInput, setProviderInput] = useState<"quick" | "custom">("quick");
  const [isOpening, setIsOpening] = useState(false);

  // Close Session state
  const [closingPort, setClosingPort] = useState<number | null>(null);
  const [isClosingAll, setIsClosingAll] = useState(false);

  // Rename Session Title state
  const [renamingSession, setRenamingSession] = useState<{ port: number; title: string } | null>(null);
  const [newTitleInput, setNewTitleInput] = useState("");
  const [isRenaming, setIsRenaming] = useState(false);

  // Copy feedback
  const [copiedPort, setCopiedPort] = useState<number | null>(null);

  const handleStartSession = async (e: React.FormEvent) => {
    e.preventDefault();
    let portNum: number | undefined = undefined;
    if (portInput.trim()) {
      portNum = parseInt(portInput.trim(), 10);
      if (isNaN(portNum) || portNum <= 0 || portNum > 65535) {
        showToast("Please enter a valid port number between 1 and 65535", "error");
        return;
      }
    }

    setIsOpening(true);
    try {
      const res = await SshApi.create({
        port: portNum,
        title: titleInput.trim() || undefined,
        password: passwordInput || undefined,
        provider: providerInput,
      });
      showToast(`SSH web terminal started on port ${res.port}`, "success");
      setPortInput("");
      setTitleInput("");
      setPasswordInput("");
      setIsOpenModal(false);
      refresh();
    } catch (err: any) {
      showToast(err.message || "Failed to start SSH session", "error");
    } finally {
      setIsOpening(false);
    }
  };

  const handleCloseSession = async () => {
    if (!closingPort) return;
    try {
      await SshApi.close(closingPort);
      showToast(`Closed SSH session on port ${closingPort}`, "info");
      refresh();
    } catch (err: any) {
      showToast(err.message || "Failed to close SSH session", "error");
    } finally {
      setClosingPort(null);
    }
  };

  const handleCloseAllSessions = async () => {
    try {
      await SshApi.close("all");
      showToast("Closed all active SSH sessions", "info");
      refresh();
    } catch (err: any) {
      showToast(err.message || "Failed to close all SSH sessions", "error");
    } finally {
      setIsClosingAll(false);
    }
  };

  const handleRenameTitle = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!renamingSession) return;

    setIsRenaming(true);
    try {
      await SshApi.renameTitle(renamingSession.port, newTitleInput.trim());
      showToast(`Updated title for port ${renamingSession.port}`, "success");
      setRenamingSession(null);
      setNewTitleInput("");
      refresh();
    } catch (err: any) {
      showToast(err.message || "Failed to update session title", "error");
    } finally {
      setIsRenaming(false);
    }
  };

  const handleCopy = (url: string, port: number) => {
    navigator.clipboard.writeText(url);
    setCopiedPort(port);
    setTimeout(() => setCopiedPort(null), 2000);
    showToast("Terminal URL copied to clipboard", "success");
  };

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <Header
        title="Remote Web Terminal (SSH)"
        subtitle="Browser-based persistent remote terminal sessions via secure HTTPS tunnels"
        onRefresh={refresh}
        isRefreshing={isLoading}
      />

      <main className="p-4 sm:p-6 md:p-8 space-y-5 max-w-7xl w-full mx-auto">
        {/* Top Summary & Action */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-lg bg-[#ff5500]/15 text-[#ff5500] border border-[#ff5500]/25 shadow-sm shadow-[#ff5500]/10">
              <TerminalWindow weight="bold" className="w-5 h-5" />
            </div>
            <div>
              <div className="text-sm font-bold text-slate-100 font-sans">
                {total} Active {total === 1 ? "SSH Session" : "SSH Sessions"}
              </div>
              <div className="text-xs text-slate-400 font-mono">
                {online} Online &bull; Password protected with salted PBKDF2
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {sessions.length > 1 && (
              <Button
                variant="secondary"
                size="md"
                onClick={() => setIsClosingAll(true)}
                className="text-rose-400 hover:text-rose-300 hover:bg-rose-950/30 border-rose-500/20"
              >
                <Trash weight="bold" className="w-4 h-4" /> Close All
              </Button>
            )}
            <Button variant="primary" onClick={() => setIsOpenModal(true)}>
              <Plus weight="bold" className="w-4 h-4" /> Start SSH Session
            </Button>
          </div>
        </div>

        {/* Sessions Table */}
        <div className="telemetry-panel overflow-hidden flex flex-col">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-white/[0.04] bg-white/[0.01] text-[10px] font-mono font-bold uppercase tracking-[0.15em] text-slate-400 select-none">
                  <th className="py-2.5 px-3.5">Local Port</th>
                  <th className="py-2.5 px-3.5">Session Title</th>
                  <th className="py-2.5 px-3.5">PID</th>
                  <th className="py-2.5 px-3.5">Status</th>
                  <th className="py-2.5 px-3.5">Uptime</th>
                  <th className="py-2.5 px-3.5">Terminal Access Endpoint</th>
                  <th className="py-2.5 px-3.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="text-xs">
                {isLoading && sessions.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-slate-500 font-mono text-xs">
                      Inspecting active SSH web terminal sessions...
                    </td>
                  </tr>
                ) : sessions.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-slate-500 font-mono text-xs">
                      No active SSH sessions. Click &quot;Start SSH Session&quot; to launch a remote web terminal.
                    </td>
                  </tr>
                ) : (
                  sessions.map((s) => (
                    <tr key={s.port} className="border-b border-white/[0.04] hover:bg-white/[0.025] transition-colors">
                      <td className="py-2.5 px-3.5 font-mono font-semibold text-[#ff5500]">
                        :{s.port}
                      </td>
                      <td className="py-2.5 px-3.5 font-sans font-medium text-slate-200">
                        <div className="flex items-center gap-1.5 group">
                          <span>{s.title || <span className="text-slate-500 italic">Default Shell</span>}</span>
                          <button
                            onClick={() => {
                              setRenamingSession({ port: s.port, title: s.title });
                              setNewTitleInput(s.title || "");
                            }}
                            className="opacity-0 group-hover:opacity-100 text-[10px] text-slate-400 hover:text-slate-200 px-1 py-0.5 rounded bg-white/[0.05] transition-opacity cursor-pointer"
                            title="Rename Title"
                          >
                            edit
                          </button>
                        </div>
                      </td>
                      <td className="py-2.5 px-3.5 font-mono text-slate-400 text-[11px]">
                        {s.pid > 0 ? s.pid : "-"}
                      </td>
                      <td className="py-2.5 px-3.5">
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full font-mono text-[10px] font-semibold bg-emerald-950/50 border border-emerald-500/30 text-emerald-400">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                          {s.status}
                        </span>
                      </td>
                      <td className="py-2.5 px-3.5 font-mono text-xs text-slate-400">
                        {s.age}
                      </td>
                      <td className="py-2.5 px-3.5 font-mono text-xs">
                        {s.url ? (
                          <div className="flex items-center gap-2">
                            <a
                              href={s.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-sky-400 hover:underline flex items-center gap-1 font-semibold truncate max-w-xs"
                              title={s.url}
                            >
                              {s.url} <ArrowSquareOut weight="bold" className="w-3 h-3 shrink-0" />
                            </a>
                            <button
                              onClick={() => handleCopy(s.url, s.port)}
                              className="p-1 text-slate-400 hover:text-slate-200 rounded transition-colors cursor-pointer shrink-0"
                              title="Copy URL"
                            >
                              {copiedPort === s.port ? (
                                <Check weight="bold" className="w-3.5 h-3.5 text-emerald-400" />
                              ) : (
                                <Copy weight="bold" className="w-3.5 h-3.5" />
                              )}
                            </button>
                          </div>
                        ) : (
                          <span className="text-slate-500 italic">configuring tunnel...</span>
                        )}
                      </td>
                      <td className="py-2.5 px-3.5 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <a
                            href={s.url || s.localUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-semibold bg-sky-500/10 text-sky-400 hover:bg-sky-500/20 border border-sky-500/25 transition-colors"
                          >
                            <ArrowSquareOut weight="bold" className="w-3 h-3" /> Connect
                          </a>
                          <Button
                            size="sm"
                            variant="danger"
                            onClick={() => setClosingPort(s.port)}
                          >
                            <Trash weight="bold" className="w-3.5 h-3.5" /> Close
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Security & Features Info Card */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="telemetry-panel p-4 text-xs text-slate-400 flex items-start gap-3">
            <ShieldCheck weight="fill" className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
            <div>
              <div className="font-semibold text-slate-200 font-sans">Hardened Remote Security</div>
              <p className="mt-1 text-slate-400 leading-relaxed font-mono text-[11px]">
                Sessions are locked with PBKDF2-HMAC-SHA256 salted hashes and protected by an automated brute-force rate limiter (5 failed attempts trigger a 5-minute IP lockout).
              </p>
            </div>
          </div>

          <div className="telemetry-panel p-4 text-xs text-slate-400 flex items-start gap-3">
            <Broadcast weight="fill" className="w-5 h-5 text-[#ff5500] shrink-0 mt-0.5" />
            <div>
              <div className="font-semibold text-slate-200 font-sans">Persistent Background PTY</div>
              <p className="mt-1 text-slate-400 leading-relaxed font-mono text-[11px]">
                Terminal sessions run inside persistent background PTY instances that survive browser reloads and network dropouts. Manage from terminal anytime with <code>fire ssh list</code> and <code>fire ssh close</code>.
              </p>
            </div>
          </div>
        </div>
      </main>

      {/* Start SSH Session Modal */}
      {isOpenModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md animate-in fade-in select-none">
          <div className="telemetry-panel max-w-md w-full p-6 shadow-2xl animate-in zoom-in-95 border-white/[0.1]">
            <div className="flex items-center gap-2.5 mb-1.5">
              <div className="p-1.5 rounded bg-[#ff5500]/15 text-[#ff5500] border border-[#ff5500]/30">
                <TerminalWindow weight="bold" className="w-4 h-4" />
              </div>
              <h3 className="text-sm font-bold text-slate-100 font-sans">Start Remote Web Terminal</h3>
            </div>
            <p className="text-[11px] text-slate-400 mb-4 font-mono">
              Creates a secure browser-accessible PTY shell exposed over a public HTTPS tunnel.
            </p>

            <form onSubmit={handleStartSession} className="space-y-4">
              <Input
                label="Session Title (Optional)"
                type="text"
                placeholder="e.g. Production Console, Staging Shell"
                value={titleInput}
                onChange={(e) => setTitleInput(e.target.value)}
                autoFocus
              />

              <Input
                label="Custom Port (Optional)"
                type="number"
                placeholder="Leave blank to auto-assign a free port"
                value={portInput}
                onChange={(e) => setPortInput(e.target.value)}
              />

              <div>
                <label className="block text-[11px] font-mono font-medium text-slate-300 mb-1.5">
                  Access Password (Optional)
                </label>
                <div className="relative">
                  <input
                    type="password"
                    placeholder="Leave empty to use saved default password"
                    value={passwordInput}
                    onChange={(e) => setPasswordInput(e.target.value)}
                    className="w-full px-3 py-2 bg-black/40 border border-white/[0.08] rounded-lg text-xs font-mono text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-[#ff5500]/50 focus:ring-1 focus:ring-[#ff5500]/25 transition-all"
                  />
                  <Lock weight="bold" className="w-3.5 h-3.5 text-slate-500 absolute right-3 top-2.5 pointer-events-none" />
                </div>
                <p className="text-[10px] text-slate-500 font-mono mt-1">
                  Default credentials are saved securely in <code>/etc/fire-pm/ssh-auth.json</code>.
                </p>
              </div>

              <div>
                <label className="block text-[11px] font-mono font-medium text-slate-300 mb-1.5">
                  Tunnel Routing Provider
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setProviderInput("quick")}
                    className={`p-2.5 text-left rounded border transition-colors cursor-pointer ${
                      providerInput === "quick"
                        ? "bg-[#ff5500]/15 border-[#ff5500]/40 text-[#ff5500]"
                        : "bg-white/[0.02] border-white/[0.06] text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <div className="text-xs font-bold font-sans">Quick Tunnel</div>
                    <div className="text-[10px] font-mono text-slate-400 mt-0.5">Zero-config Cloudflare</div>
                  </button>

                  <button
                    type="button"
                    onClick={() => setProviderInput("custom")}
                    className={`p-2.5 text-left rounded border transition-colors cursor-pointer ${
                      providerInput === "custom"
                        ? "bg-[#ff5500]/15 border-[#ff5500]/40 text-[#ff5500]"
                        : "bg-white/[0.02] border-white/[0.06] text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <div className="text-xs font-bold font-sans">Custom Nginx</div>
                    <div className="text-[10px] font-mono text-slate-400 mt-0.5">Self-hosted domain</div>
                  </button>
                </div>
              </div>

              <div className="flex items-center justify-end gap-2.5 pt-2">
                <Button
                  variant="secondary"
                  type="button"
                  onClick={() => setIsOpenModal(false)}
                  disabled={isOpening}
                >
                  Cancel
                </Button>
                <Button variant="primary" type="submit" isLoading={isOpening}>
                  Launch Terminal
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Rename Title Modal */}
      {renamingSession && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md animate-in fade-in select-none">
          <div className="telemetry-panel max-w-sm w-full p-5 shadow-2xl animate-in zoom-in-95 border-white/[0.1]">
            <h3 className="text-sm font-bold text-slate-100 mb-1 font-sans">
              Rename Session :{renamingSession.port}
            </h3>
            <p className="text-[11px] text-slate-400 mb-3 font-mono">
              Update the human-readable label for this active terminal session.
            </p>

            <form onSubmit={handleRenameTitle} className="space-y-3">
              <Input
                label="New Session Title"
                type="text"
                placeholder="e.g. Production Console"
                value={newTitleInput}
                onChange={(e) => setNewTitleInput(e.target.value)}
                autoFocus
              />

              <div className="flex items-center justify-end gap-2 pt-1">
                <Button
                  variant="secondary"
                  size="sm"
                  type="button"
                  onClick={() => setRenamingSession(null)}
                  disabled={isRenaming}
                >
                  Cancel
                </Button>
                <Button variant="primary" size="sm" type="submit" isLoading={isRenaming}>
                  Save Title
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Close Single Session Confirmation */}
      <ConfirmDialog
        isOpen={closingPort !== null}
        title="Confirm Session Termination"
        message={`Are you sure you want to close the SSH web terminal session on port ${closingPort}? Connected clients will be disconnected and the terminal process terminated.`}
        confirmText="Close Session"
        variant="danger"
        onConfirm={handleCloseSession}
        onCancel={() => setClosingPort(null)}
      />

      {/* Close All Sessions Confirmation */}
      <ConfirmDialog
        isOpen={isClosingAll}
        title="Terminate All SSH Sessions"
        message="Are you sure you want to close ALL active remote web terminal sessions? All running shells and tunnel endpoints will be stopped immediately."
        confirmText="Close All Sessions"
        variant="danger"
        onConfirm={handleCloseAllSessions}
        onCancel={() => setIsClosingAll(false)}
      />
    </div>
  );
}
