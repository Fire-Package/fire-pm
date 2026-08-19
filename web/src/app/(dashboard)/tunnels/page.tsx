"use client";

import React, { useState } from "react";
import { Header } from "@/components/Header";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";
import { useTunnels } from "@/hooks/useTunnels";
import { TunnelApi } from "@/lib/api/tunnels";
import { 
  Plugs, 
  Plus, 
  Copy, 
  Check, 
  Trash, 
  ArrowSquareOut, 
  ShieldCheck 
} from "@phosphor-icons/react";

export default function TunnelsPage() {
  const { tunnels, total, online, pending, isLoading, refresh } = useTunnels();
  const { showToast } = useToast();

  const [isOpenModal, setIsOpenModal] = useState(false);
  const [portInput, setPortInput] = useState("");
  const [isOpening, setIsOpening] = useState(false);
  const [closingPort, setClosingPort] = useState<number | null>(null);
  const [copiedHash, setCopiedHash] = useState<string | null>(null);

  const handleOpenTunnel = async (e: React.FormEvent) => {
    e.preventDefault();
    const portNum = parseInt(portInput, 10);
    if (isNaN(portNum) || portNum <= 0 || portNum > 65535) {
      showToast("Please enter a valid port number between 1 and 65535", "error");
      return;
    }

    setIsOpening(true);
    try {
      const res = await TunnelApi.open(portNum);
      showToast(`Tunnel opened for localhost:${res.port}`, "success");
      setPortInput("");
      setIsOpenModal(false);
      refresh();
    } catch (err: any) {
      showToast(err.message || "Failed to open tunnel", "error");
    } finally {
      setIsOpening(false);
    }
  };

  const handleCloseTunnel = async () => {
    if (!closingPort) return;
    try {
      await TunnelApi.close(closingPort);
      showToast(`Closed tunnel on port ${closingPort}`, "info");
      refresh();
    } catch (err: any) {
      showToast(err.message || "Failed to close tunnel", "error");
    } finally {
      setClosingPort(null);
    }
  };

  const handleCopy = (url: string, hash: string) => {
    navigator.clipboard.writeText(url);
    setCopiedHash(hash);
    setTimeout(() => setCopiedHash(null), 2000);
    showToast("Tunnel URL copied to clipboard", "success");
  };

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <Header
        title="Public Reverse-Proxy Tunnels"
        subtitle="Expose local listening ports securely via Nginx wildcard routing"
        onRefresh={refresh}
        isRefreshing={isLoading}
      />

      <main className="p-4 sm:p-6 md:p-8 space-y-5 max-w-7xl w-full mx-auto">
        {/* Top Summary & Action */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-lg bg-amber-950/50 text-amber-400 border border-amber-500/25">
              <Plugs weight="bold" className="w-5 h-5" />
            </div>
            <div>
              <div className="text-sm font-bold text-slate-100 font-sans">
                {total} Active {total === 1 ? "Reverse-Proxy Tunnel" : "Reverse-Proxy Tunnels"}
              </div>
              <div className="text-xs text-slate-400 font-mono">
                {online} Online &bull; {pending} Pending Configuration
              </div>
            </div>
          </div>

          <Button variant="primary" onClick={() => setIsOpenModal(true)}>
            <Plus weight="bold" className="w-4 h-4" /> Open New Tunnel
          </Button>
        </div>

        {/* Tunnels Table */}
        <div className="telemetry-panel overflow-hidden flex flex-col">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-white/[0.04] bg-white/[0.01] text-[10px] font-mono font-bold uppercase tracking-[0.15em] text-slate-400 select-none">
                  <th className="py-2.5 px-3.5">Local Port</th>
                  <th className="py-2.5 px-3.5">Service</th>
                  <th className="py-2.5 px-3.5">Status</th>
                  <th className="py-2.5 px-3.5">Age</th>
                  <th className="py-2.5 px-3.5">Public HTTPS Endpoint</th>
                  <th className="py-2.5 px-3.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="text-xs">
                {isLoading && tunnels.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-slate-500 font-mono text-xs">
                      Inspecting dynamic Nginx tunnel sockets...
                    </td>
                  </tr>
                ) : tunnels.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-slate-500 font-mono text-xs">
                      No active tunnels. Click "Open New Tunnel" to expose any local listening port.
                    </td>
                  </tr>
                ) : (
                  tunnels.map((t) => (
                    <tr key={t.port} className="border-b border-white/[0.04] hover:bg-white/[0.025] transition-colors">
                      <td className="py-2.5 px-3.5 font-mono font-semibold text-amber-400">
                        :{t.port}
                      </td>
                      <td className="py-2.5 px-3.5 font-sans font-medium text-slate-200">
                        {t.name}
                      </td>
                      <td className="py-2.5 px-3.5">
                        <span
                          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full font-mono text-[10px] font-semibold ${
                            t.status === "ONLINE"
                              ? "bg-emerald-950/50 border border-emerald-500/30 text-emerald-400"
                              : "bg-amber-950/50 border border-amber-500/30 text-amber-400"
                          }`}
                        >
                          <span
                            className={`w-1.5 h-1.5 rounded-full ${
                              t.status === "ONLINE" ? "bg-emerald-400 animate-pulse" : "bg-amber-400"
                            }`}
                          />
                          {t.status}
                        </span>
                      </td>
                      <td className="py-2.5 px-3.5 font-mono text-xs text-slate-400">
                        {t.age}
                      </td>
                      <td className="py-2.5 px-3.5 font-mono text-xs">
                        {t.url ? (
                          <div className="flex items-center gap-2">
                            <a
                              href={t.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-sky-400 hover:underline flex items-center gap-1 font-semibold"
                            >
                              {t.url} <ArrowSquareOut weight="bold" className="w-3 h-3" />
                            </a>
                            <button
                              onClick={() => handleCopy(t.url, t.hash || t.url)}
                              className="p-1 text-slate-400 hover:text-slate-200 rounded transition-colors cursor-pointer"
                              title="Copy URL"
                            >
                              {copiedHash === (t.hash || t.url) ? (
                                <Check weight="bold" className="w-3.5 h-3.5 text-emerald-400" />
                              ) : (
                                <Copy weight="bold" className="w-3.5 h-3.5" />
                              )}
                            </button>
                          </div>
                        ) : (
                          <span className="text-slate-500 italic">configuring...</span>
                        )}
                      </td>
                      <td className="py-2.5 px-3.5 text-right">
                        <Button
                          size="sm"
                          variant="danger"
                          onClick={() => setClosingPort(t.port)}
                        >
                          <Trash weight="bold" className="w-3.5 h-3.5" /> Close
                        </Button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Nginx Info Banner */}
        <div className="telemetry-panel p-4 text-xs text-slate-400 flex items-start gap-3">
          <ShieldCheck weight="fill" className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
          <div>
            <div className="font-semibold text-slate-200 font-sans">Dynamic Nginx Reverse-Proxy Architecture</div>
            <p className="mt-0.5 text-slate-400 leading-relaxed font-mono text-[11px]">
              Tunnels map random hex subdomains to local service ports via dynamic Nginx map configuration (<code>/etc/nginx/tunnels.map</code>) and automated zero-downtime daemon reloading.
            </p>
          </div>
        </div>
      </main>

      {/* Open Tunnel Modal */}
      {isOpenModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md animate-in fade-in select-none">
          <div className="telemetry-panel max-w-md w-full p-6 shadow-2xl animate-in zoom-in-95 border-white/[0.1]">
            <h3 className="text-sm font-bold text-slate-100 mb-1 font-sans">Open Reverse-Proxy Tunnel</h3>
            <p className="text-[11px] text-slate-400 mb-4 font-mono">
              Enter the local port you want to expose through a secure public HTTPS subdomain.
            </p>

            <form onSubmit={handleOpenTunnel} className="space-y-4">
              <Input
                label="Local Target Port"
                type="number"
                placeholder="e.g. 3000, 8080, 5000"
                value={portInput}
                onChange={(e) => setPortInput(e.target.value)}
                autoFocus
              />

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
                  Establish Tunnel
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Close Confirmation */}
      <ConfirmDialog
        isOpen={closingPort !== null}
        title="Confirm Tunnel Close"
        message={`Are you sure you want to close the tunnel for localhost:${closingPort}? Incoming traffic to this subdomain will be disconnected immediately.`}
        confirmText="Close Tunnel"
        variant="danger"
        onConfirm={handleCloseTunnel}
        onCancel={() => setClosingPort(null)}
      />
    </div>
  );
}
