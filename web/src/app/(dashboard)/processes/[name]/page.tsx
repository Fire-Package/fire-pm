"use client";

import React, { useState, useEffect, use } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowsClockwise,
  Stop,
  Play,
  SlidersHorizontal,
  Trash,
  TerminalWindow,
  FileCode,
  Check,
  Clock,
  User,
  Folder,
  Command,
  Pulse,
  Eye,
  Activity
} from "@phosphor-icons/react";
import { Header } from "@/components/Header";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/StatusBadge";
import { LogViewer } from "@/components/LogViewer";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ResourceLimitsModal } from "@/components/ResourceLimitsModal";
import { useToast } from "@/components/ui/Toast";
import { useLogs } from "@/hooks/useLogs";
import { ProcessApi } from "@/lib/api/processes";
import { ProcessDetail } from "@/lib/types";

export default function ProcessDetailPage(props: { params: Promise<{ name: string }> }) {
  const params = use(props.params);
  const router = useRouter();
  const { showToast } = useToast();

  const [detail, setDetail] = useState<ProcessDetail | null>(null);
  const [unitContent, setUnitContent] = useState("");
  const [activeTab, setActiveTab] = useState<"overview" | "logs" | "unit">("overview");
  const [isLoading, setIsLoading] = useState(true);
  const [isActing, setIsActing] = useState(false);
  const [confirmAction, setConfirmAction] = useState<"restart" | "stop" | "start" | "delete" | null>(null);
  const [isLimitsOpen, setIsLimitsOpen] = useState(false);
  const [isSavingUnit, setIsSavingUnit] = useState(false);

  const { logs, isConnected, clearLogs } = useLogs(params.name);

  const loadData = async () => {
    try {
      const data = await ProcessApi.getDetail(params.name);
      setDetail(data);
      if (data?.unitContent) {
        setUnitContent(data.unitContent);
      }
    } catch (e: any) {
      showToast(e.message || "Failed to load process details", "error");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 4000);
    return () => clearInterval(interval);
  }, [params.name]);

  const handleAction = async (action: "restart" | "stop" | "start" | "delete") => {
    setIsActing(true);
    try {
      if (action === "restart") {
        await ProcessApi.restart(params.name);
        showToast(`Restarted daemon "${params.name}"`, "success");
      } else if (action === "stop") {
        await ProcessApi.stop(params.name);
        showToast(`Stopped daemon "${params.name}"`, "info");
      } else if (action === "start") {
        await ProcessApi.start(params.name);
        showToast(`Started daemon "${params.name}"`, "success");
      } else if (action === "delete") {
        await ProcessApi.delete(params.name);
        showToast(`Deleted daemon "${params.name}"`, "info");
        router.push("/processes");
        return;
      }
      await loadData();
    } catch (err: any) {
      showToast(err.message || `Failed to ${action} process`, "error");
    } finally {
      setIsActing(false);
      setConfirmAction(null);
    }
  };

  const handleSaveLimits = async (mem?: string | null, cpu?: string | null) => {
    await ProcessApi.setLimits(params.name, mem, cpu);
    showToast(`Updated resource limits for "${params.name}"`, "success");
    await loadData();
  };

  const handleToggleWatch = async () => {
    try {
      const res = await ProcessApi.toggleWatch(params.name);
      showToast(`Watchdog policy set to "${res.watch}"`, "success");
      await loadData();
    } catch (e: any) {
      showToast(e.message || "Failed to toggle watchdog", "error");
    }
  };

  const handleToggleReload = async () => {
    try {
      const res = await ProcessApi.toggleReload(params.name);
      showToast(`Auto-reload is now ${res.reload}`, "success");
      await loadData();
    } catch (e: any) {
      showToast(e.message || "Failed to toggle auto-reload", "error");
    }
  };

  const handleSaveUnit = async () => {
    setIsSavingUnit(true);
    try {
      await ProcessApi.updateUnitContent(params.name, unitContent);
      showToast("Systemd unit file updated and daemon reloaded", "success");
      await loadData();
    } catch (e: any) {
      showToast(e.message || "Failed to update unit file", "error");
    } finally {
      setIsSavingUnit(false);
    }
  };

  const isOnline = detail?.status === "online" || detail?.status === "active";

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <Header
        title={`Daemon: ${detail?.name || params.name}`}
        subtitle={detail?.service}
        onRefresh={loadData}
        isRefreshing={isLoading}
      />

      <main className="p-4 sm:p-6 md:p-8 space-y-5 max-w-7xl w-full mx-auto">
        {/* Navigation & Action Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Link
            href="/processes"
            className="flex items-center gap-1.5 text-xs font-semibold text-slate-400 hover:text-slate-200 transition-colors tactile-btn font-mono"
          >
            <ArrowLeft weight="bold" className="w-3.5 h-3.5" /> Back to registry
          </Link>

          {/* Quick Actions */}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setConfirmAction("restart")}
              disabled={isActing}
            >
              <ArrowsClockwise weight="bold" className={`w-3.5 h-3.5 ${isActing ? "animate-spin" : ""}`} /> Restart
            </Button>

            {isOnline ? (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => setConfirmAction("stop")}
                disabled={isActing}
              >
                <Stop weight="fill" className="w-3.5 h-3.5 text-rose-400" /> Stop
              </Button>
            ) : (
              <Button
                size="sm"
                variant="primary"
                onClick={() => setConfirmAction("start")}
                disabled={isActing}
              >
                <Play weight="fill" className="w-3.5 h-3.5" /> Start
              </Button>
            )}

            <Button
              size="sm"
              variant="secondary"
              onClick={() => setIsLimitsOpen(true)}
            >
              <SlidersHorizontal weight="bold" className="w-3.5 h-3.5 text-amber-400" /> Limits
            </Button>

            <Button
              size="sm"
              variant="danger"
              onClick={() => setConfirmAction("delete")}
              disabled={isActing}
            >
              <Trash weight="bold" className="w-3.5 h-3.5" /> Delete
            </Button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center gap-2 border-b border-white/[0.05] pb-2">
          <button
            onClick={() => setActiveTab("overview")}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer tactile-btn ${
              activeTab === "overview"
                ? "bg-[#ff5500]/15 text-[#ff5500] border border-[#ff5500]/30 font-bold"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            Overview & Metrics
          </button>

          <button
            onClick={() => setActiveTab("logs")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer tactile-btn ${
              activeTab === "logs"
                ? "bg-[#ff5500]/15 text-[#ff5500] border border-[#ff5500]/30 font-bold"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <TerminalWindow weight="bold" className="w-3.5 h-3.5" />
            Live Logs
          </button>

          <button
            onClick={() => setActiveTab("unit")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer tactile-btn ${
              activeTab === "unit"
                ? "bg-[#ff5500]/15 text-[#ff5500] border border-[#ff5500]/30 font-bold"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <FileCode weight="bold" className="w-3.5 h-3.5" />
            Systemd Unit File
          </button>
        </div>

        {/* Tab 1: Overview */}
        {activeTab === "overview" && detail && (
          <div className="space-y-5">
            {/* Top Cards */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="telemetry-panel p-3.5">
                <div className="text-[9px] font-mono text-slate-400 font-bold uppercase tracking-wider">Status</div>
                <div className="mt-1.5">
                  <StatusBadge status={detail.status} size="sm" />
                </div>
              </div>

              <div className="telemetry-panel p-3.5">
                <div className="text-[9px] font-mono text-slate-400 font-bold uppercase tracking-wider">RAM Usage</div>
                <div className="text-lg font-bold font-mono text-slate-100 mt-1">
                  {detail.mem}
                </div>
              </div>

              <div className="telemetry-panel p-3.5">
                <div className="text-[9px] font-mono text-slate-400 font-bold uppercase tracking-wider">CPU Load</div>
                <div className="text-lg font-bold font-mono text-slate-100 mt-1">
                  {detail.cpu}
                </div>
              </div>

              <div className="telemetry-panel p-3.5">
                <div className="text-[9px] font-mono text-slate-400 font-bold uppercase tracking-wider">Uptime</div>
                <div className="text-lg font-bold font-mono text-emerald-400 mt-1">
                  {detail.uptime}
                </div>
              </div>
            </div>

            {/* Detailed Properties Grid */}
            <div className="telemetry-panel p-5">
              <div className="pb-3.5 mb-3.5 border-b border-white/[0.05]">
                <h3 className="text-sm font-bold text-slate-100 font-sans tracking-tight">Process Runtime Parameters</h3>
                <p className="text-[10px] text-slate-400 font-mono">Kernel cgroup directives & execution context</p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs font-mono">
                <div className="flex items-start gap-2.5 p-3 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                  <Command weight="bold" className="w-4 h-4 text-[#ff5500] shrink-0 mt-0.5" />
                  <div className="flex-1 min-w-0">
                    <span className="text-slate-400 block text-[9px] uppercase tracking-wider font-bold">Interpreter</span>
                    <span className="text-slate-200 break-all">{detail.interpreter}</span>
                  </div>
                </div>

                <div className="flex items-start gap-2.5 p-3 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                  <FileCode weight="bold" className="w-4 h-4 text-sky-400 shrink-0 mt-0.5" />
                  <div className="flex-1 min-w-0">
                    <span className="text-slate-400 block text-[9px] uppercase tracking-wider font-bold">Script Path</span>
                    <span className="text-slate-200 break-all">{detail.script}</span>
                  </div>
                </div>

                <div className="flex items-start gap-2.5 p-3 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                  <Folder weight="bold" className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                  <div className="flex-1 min-w-0">
                    <span className="text-slate-400 block text-[9px] uppercase tracking-wider font-bold">Working Directory</span>
                    <span className="text-slate-200 break-all">{detail.workingDirectory}</span>
                  </div>
                </div>

                <div className="flex items-start gap-2.5 p-3 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                  <User weight="bold" className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                  <div className="flex-1 min-w-0">
                    <span className="text-slate-400 block text-[9px] uppercase tracking-wider font-bold">Run User</span>
                    <span className="text-slate-200">{detail.user}</span>
                  </div>
                </div>

                <div className="flex items-start gap-2.5 p-3 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                  <Clock weight="bold" className="w-4 h-4 text-purple-400 shrink-0 mt-0.5" />
                  <div className="flex-1 min-w-0">
                    <span className="text-slate-400 block text-[9px] uppercase tracking-wider font-bold">Restarts Counter</span>
                    <span className="text-slate-200">{detail.restarts} times</span>
                  </div>
                </div>

                <div className="flex items-start gap-2.5 p-3 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                  <TerminalWindow weight="bold" className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                  <div className="flex-1 min-w-0">
                    <span className="text-slate-400 block text-[9px] uppercase tracking-wider font-bold">Journalctl Stream</span>
                    <span className="text-slate-200 truncate">{detail.logPath}</span>
                  </div>
                </div>
              </div>

              {/* Toggles */}
              <div className="mt-5 pt-4 border-t border-white/[0.05] flex flex-wrap items-center gap-2.5">
                <Button size="sm" variant="secondary" onClick={handleToggleWatch}>
                  Toggle Watchdog (Restart=always)
                </Button>
                <Button size="sm" variant="secondary" onClick={handleToggleReload}>
                  Toggle Hot-Reload (.path unit)
                </Button>
              </div>
            </div>

            {/* Inline live log snippet */}
            <div className="space-y-2">
              <div className="flex items-center justify-between px-0.5">
                <h3 className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-300">Live Telemetry Stream</h3>
                <button
                  onClick={() => setActiveTab("logs")}
                  className="text-xs text-[#ff5500] hover:underline font-semibold font-mono cursor-pointer"
                >
                  View Full Terminal &rarr;
                </button>
              </div>
              <LogViewer
                logs={logs.slice(-35)}
                isConnected={isConnected}
                serviceName={params.name}
                onClear={clearLogs}
              />
            </div>
          </div>
        )}

        {/* Tab 2: Logs */}
        {activeTab === "logs" && (
          <div className="space-y-3">
            <div className="flex items-center justify-between px-0.5">
              <h3 className="text-xs font-semibold text-slate-300 font-mono">
                Full Journalctl Daemon Logs
              </h3>
              <Link
                href={`/processes/${encodeURIComponent(params.name)}/logs`}
                className="text-xs text-sky-400 hover:underline font-semibold font-mono"
              >
                Fullscreen View &rarr;
              </Link>
            </div>
            <LogViewer
              logs={logs}
              isConnected={isConnected}
              serviceName={params.name}
              onClear={clearLogs}
            />
          </div>
        )}

        {/* Tab 3: Systemd Unit Editor */}
        {activeTab === "unit" && (
          <div className="telemetry-panel p-5 space-y-4">
            <div className="flex items-center justify-between pb-3.5 border-b border-white/[0.05]">
              <div>
                <h3 className="text-sm font-bold text-slate-100 font-sans tracking-tight">Systemd Unit Configuration ({detail?.service})</h3>
                <p className="text-[10px] text-slate-400 font-mono">Direct daemon configuration file with instant daemon-reload</p>
              </div>
              <Button
                size="sm"
                variant="primary"
                onClick={handleSaveUnit}
                isLoading={isSavingUnit}
              >
                <Check weight="bold" className="w-3.5 h-3.5" /> Save & Reload Daemon
              </Button>
            </div>
            <textarea
              value={unitContent}
              onChange={(e) => setUnitContent(e.target.value)}
              rows={16}
              className="w-full bg-[#05070c] border border-white/[0.06] rounded-lg p-4 font-mono text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#ff5500]/70 leading-relaxed"
              spellCheck={false}
            />
            <p className="text-[11px] text-slate-500 font-mono">
              Note: Saving this file automatically triggers <code className="text-slate-300 font-mono">systemctl daemon-reload</code>.
            </p>
          </div>
        )}
      </main>

      {/* Confirmation Dialog */}
      <ConfirmDialog
        isOpen={confirmAction !== null}
        title={`Confirm ${confirmAction?.toUpperCase()}`}
        message={`Are you sure you want to ${confirmAction} daemon "${params.name}"?`}
        confirmText={confirmAction ? confirmAction.charAt(0).toUpperCase() + confirmAction.slice(1) : "Confirm"}
        variant={confirmAction === "delete" || confirmAction === "stop" ? "danger" : "primary"}
        isLoading={isActing}
        onConfirm={() => confirmAction && handleAction(confirmAction)}
        onCancel={() => setConfirmAction(null)}
      />

      {/* Limits Modal */}
      <ResourceLimitsModal
        isOpen={isLimitsOpen}
        serviceName={params.name}
        currentMemLimit={detail?.memLimit}
        currentCpuLimit={detail?.cpuLimit}
        onClose={() => setIsLimitsOpen(false)}
        onSave={handleSaveLimits}
      />
    </div>
  );
}
