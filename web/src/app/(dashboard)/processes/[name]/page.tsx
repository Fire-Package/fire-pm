"use client";

import React, { useState, useEffect, use } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  RotateCw,
  Square,
  Play,
  Sliders,
  Trash2,
  Terminal,
  FileCode,
  Check,
  AlertCircle,
  Clock,
  HardDrive,
  Cpu,
  User,
  Folder,
  Command,
} from "lucide-react";
import { Header } from "@/components/Header";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
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
      if (data.unitContent) {
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
        showToast(`Restarted process "${params.name}"`, "success");
      } else if (action === "stop") {
        await ProcessApi.stop(params.name);
        showToast(`Stopped process "${params.name}"`, "info");
      } else if (action === "start") {
        await ProcessApi.start(params.name);
        showToast(`Started process "${params.name}"`, "success");
      } else if (action === "delete") {
        await ProcessApi.delete(params.name);
        showToast(`Deleted process "${params.name}"`, "info");
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
      showToast(`Watchdog restart policy set to "${res.watch}"`, "success");
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
      showToast("Systemd unit file updated and reloaded", "success");
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
        title={`Process: ${detail?.name || params.name}`}
        subtitle={detail?.service}
        onRefresh={loadData}
        isRefreshing={isLoading}
      />

      <main className="p-6 md:p-8 space-y-6 max-w-7xl w-full mx-auto">
        {/* Navigation & Action Bar */}
        <div className="flex flex-wrap items-center justify-between gap-4">
          <Link
            href="/processes"
            className="flex items-center gap-1.5 text-xs font-semibold text-slate-400 hover:text-slate-200 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" /> Back to Process List
          </Link>

          {/* Quick Actions */}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setConfirmAction("restart")}
              disabled={isActing}
            >
              <RotateCw className="w-3.5 h-3.5" /> Restart
            </Button>

            {isOnline ? (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => setConfirmAction("stop")}
                disabled={isActing}
              >
                <Square className="w-3.5 h-3.5 text-rose-400" /> Stop
              </Button>
            ) : (
              <Button
                size="sm"
                variant="primary"
                onClick={() => setConfirmAction("start")}
                disabled={isActing}
              >
                <Play className="w-3.5 h-3.5" /> Start
              </Button>
            )}

            <Button
              size="sm"
              variant="secondary"
              onClick={() => setIsLimitsOpen(true)}
            >
              <Sliders className="w-3.5 h-3.5 text-amber-400" /> Limits
            </Button>

            <Button
              size="sm"
              variant="danger"
              onClick={() => setConfirmAction("delete")}
              disabled={isActing}
            >
              <Trash2 className="w-3.5 h-3.5" /> Delete
            </Button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center gap-2 border-b border-[#1c2230] pb-2">
          <button
            onClick={() => setActiveTab("overview")}
            className={`px-4 py-2 rounded-md text-xs font-semibold transition-all cursor-pointer ${
              activeTab === "overview"
                ? "bg-[#ff5500]/15 text-[#ff5500] border border-[#ff5500]/30"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            Overview & Metrics
          </button>

          <button
            onClick={() => setActiveTab("logs")}
            className={`flex items-center gap-1.5 px-4 py-2 rounded-md text-xs font-semibold transition-all cursor-pointer ${
              activeTab === "logs"
                ? "bg-[#ff5500]/15 text-[#ff5500] border border-[#ff5500]/30"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Terminal className="w-3.5 h-3.5" />
            Live Logs
          </button>

          <button
            onClick={() => setActiveTab("unit")}
            className={`flex items-center gap-1.5 px-4 py-2 rounded-md text-xs font-semibold transition-all cursor-pointer ${
              activeTab === "unit"
                ? "bg-[#ff5500]/15 text-[#ff5500] border border-[#ff5500]/30"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <FileCode className="w-3.5 h-3.5" />
            Systemd Unit File
          </button>
        </div>

        {/* Tab 1: Overview */}
        {activeTab === "overview" && detail && (
          <div className="space-y-6">
            {/* Top Cards */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <div className="bg-[#12151e] border border-[#202634] rounded-lg p-4">
                <div className="text-xs text-slate-400 font-semibold uppercase">Status</div>
                <div className="mt-1.5">
                  <StatusBadge status={detail.status} />
                </div>
              </div>

              <div className="bg-[#12151e] border border-[#202634] rounded-lg p-4">
                <div className="text-xs text-slate-400 font-semibold uppercase">RAM Usage</div>
                <div className="text-xl font-bold font-mono text-slate-100 mt-1">
                  {detail.mem}
                </div>
              </div>

              <div className="bg-[#12151e] border border-[#202634] rounded-lg p-4">
                <div className="text-xs text-slate-400 font-semibold uppercase">CPU Usage</div>
                <div className="text-xl font-bold font-mono text-slate-100 mt-1">
                  {detail.cpu}
                </div>
              </div>

              <div className="bg-[#12151e] border border-[#202634] rounded-lg p-4">
                <div className="text-xs text-slate-400 font-semibold uppercase">Uptime</div>
                <div className="text-xl font-bold font-mono text-emerald-400 mt-1">
                  {detail.uptime}
                </div>
              </div>
            </div>

            {/* Detailed Properties Grid */}
            <Card title="Process Configuration & Properties">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-y-4 gap-x-8 text-xs font-mono">
                <div className="flex items-start gap-3">
                  <Command className="w-4 h-4 text-slate-500 shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <span className="text-slate-400 block text-[11px] uppercase tracking-wider">Interpreter</span>
                    <span className="text-slate-200 break-all">{detail.interpreter}</span>
                  </div>
                </div>

                <div className="flex items-start gap-3">
                  <FileCode className="w-4 h-4 text-slate-500 shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <span className="text-slate-400 block text-[11px] uppercase tracking-wider">Script File</span>
                    <span className="text-slate-200 break-all">{detail.script}</span>
                  </div>
                </div>

                <div className="flex items-start gap-3">
                  <Folder className="w-4 h-4 text-slate-500 shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <span className="text-slate-400 block text-[11px] uppercase tracking-wider">Working Directory</span>
                    <span className="text-slate-200 break-all">{detail.workingDirectory}</span>
                  </div>
                </div>

                <div className="flex items-start gap-3">
                  <User className="w-4 h-4 text-slate-500 shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <span className="text-slate-400 block text-[11px] uppercase tracking-wider">Run User</span>
                    <span className="text-slate-200">{detail.user}</span>
                  </div>
                </div>

                <div className="flex items-start gap-3">
                  <Clock className="w-4 h-4 text-slate-500 shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <span className="text-slate-400 block text-[11px] uppercase tracking-wider">Restarts Count</span>
                    <span className="text-slate-200">{detail.restarts} times</span>
                  </div>
                </div>

                <div className="flex items-start gap-3">
                  <Terminal className="w-4 h-4 text-slate-500 shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <span className="text-slate-400 block text-[11px] uppercase tracking-wider">Log Source</span>
                    <span className="text-slate-200">{detail.logPath}</span>
                  </div>
                </div>
              </div>

              {/* Toggles (Watchdog & Reload) */}
              <div className="mt-6 pt-5 border-t border-[#1c2230] flex flex-wrap items-center gap-4">
                <Button size="sm" variant="secondary" onClick={handleToggleWatch}>
                  Toggle Watchdog (Restart=always)
                </Button>
                <Button size="sm" variant="secondary" onClick={handleToggleReload}>
                  Toggle Hot-Reload (.path unit)
                </Button>
              </div>
            </Card>

            {/* Inline live log snippet */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-200">Recent Output Logs</h3>
                <button
                  onClick={() => setActiveTab("logs")}
                  className="text-xs text-[#ff5500] hover:underline"
                >
                  View Full Terminal &rarr;
                </button>
              </div>
              <LogViewer
                logs={logs.slice(-30)}
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
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-200">
                Live Journalctl Log Stream
              </h3>
              <Link
                href={`/processes/${encodeURIComponent(params.name)}/logs`}
                className="text-xs text-sky-400 hover:underline"
              >
                Open Fullscreen View &rarr;
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
          <Card
            title={`Systemd Unit Configuration (${detail?.service})`}
            subtitle="Directly edit the service unit file and reload the systemd daemon."
            action={
              <Button
                size="sm"
                variant="primary"
                onClick={handleSaveUnit}
                isLoading={isSavingUnit}
              >
                <Check className="w-4 h-4" /> Save & Reload Daemon
              </Button>
            }
          >
            <div className="space-y-4">
              <textarea
                value={unitContent}
                onChange={(e) => setUnitContent(e.target.value)}
                rows={16}
                className="w-full bg-[#0b0d13] border border-[#232a3b] rounded-lg p-4 font-mono text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#ff5500] leading-relaxed"
                spellCheck={false}
              />
              <p className="text-xs text-slate-500">
                Tip: Saving this unit file executes <code className="text-slate-400 font-mono">systemctl daemon-reload</code> automatically.
              </p>
            </div>
          </Card>
        )}
      </main>

      {/* Confirmation Dialog */}
      <ConfirmDialog
        isOpen={confirmAction !== null}
        title={`Confirm ${confirmAction?.toUpperCase()}`}
        message={`Are you sure you want to ${confirmAction} process "${params.name}"?`}
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
