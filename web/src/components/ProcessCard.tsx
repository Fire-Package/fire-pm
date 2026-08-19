"use client";

import React, { useState } from "react";
import Link from "next/link";
import { 
  ArrowsClockwise, 
  Stop, 
  Play, 
  SlidersHorizontal, 
  Trash, 
  TerminalWindow, 
  Eye,
  Cpu,
  HardDrives,
  Clock,
  ArrowCounterClockwise
} from "@phosphor-icons/react";
import { ProcessItem } from "@/lib/types";
import { StatusBadge } from "./StatusBadge";
import { ConfirmDialog } from "./ConfirmDialog";
import { ResourceLimitsModal } from "./ResourceLimitsModal";
import { useToast } from "./ui/Toast";
import { ProcessApi } from "@/lib/api/processes";

export interface ProcessCardProps {
  process: ProcessItem;
  onRefresh: () => void;
}

export const ProcessCard: React.FC<ProcessCardProps> = ({ process, onRefresh }) => {
  const { showToast } = useToast();
  const [isActing, setIsActing] = useState(false);
  const [confirmAction, setConfirmAction] = useState<"restart" | "stop" | "start" | "delete" | null>(null);
  const [isLimitsOpen, setIsLimitsOpen] = useState(false);

  const isOnline = process.status === "online" || process.status === "active";

  const handleAction = async (action: "restart" | "stop" | "start" | "delete") => {
    setIsActing(true);
    try {
      if (action === "restart") {
        await ProcessApi.restart(process.name);
        showToast(`Restarted daemon "${process.name}"`, "success");
      } else if (action === "stop") {
        await ProcessApi.stop(process.name);
        showToast(`Stopped daemon "${process.name}"`, "info");
      } else if (action === "start") {
        await ProcessApi.start(process.name);
        showToast(`Started daemon "${process.name}"`, "success");
      } else if (action === "delete") {
        await ProcessApi.delete(process.name);
        showToast(`Deleted daemon "${process.name}"`, "info");
      }
      onRefresh();
    } catch (err: any) {
      showToast(err.message || `Failed to ${action} process`, "error");
    } finally {
      setIsActing(false);
      setConfirmAction(null);
    }
  };

  const handleSaveLimits = async (mem?: string | null, cpu?: string | null) => {
    await ProcessApi.setLimits(process.name, mem, cpu);
    showToast(`Updated resource limits for "${process.name}"`, "success");
    onRefresh();
  };

  const cpuNum = parseFloat(process.cpu.replace("%", "")) || 0;
  const memNum = parseFloat(process.mem.replace("MB", "")) || 0;

  return (
    <>
      <div className="telemetry-card p-4 flex flex-col justify-between select-none">
        <div>
          {/* Header row with name and status */}
          <div className="flex items-start justify-between gap-2 mb-3">
            <div className="min-w-0 flex-1">
              <Link
                href={`/processes/${encodeURIComponent(process.name)}`}
                className="font-bold text-sm text-slate-100 hover:text-[#ff5500] transition-colors font-sans tracking-tight truncate block"
              >
                {process.name}
              </Link>
              <div className="flex items-center gap-2 mt-1 text-[10px] font-mono text-slate-400">
                {process.pid && (
                  <span className="bg-white/[0.03] px-1.5 py-0.5 rounded border border-white/[0.05]">
                    PID {process.pid}
                  </span>
                )}
                {process.port !== "-" && (
                  <span className="text-amber-400 font-semibold bg-amber-950/30 border border-amber-500/25 px-1.5 py-0.5 rounded">
                    :{process.port}
                  </span>
                )}
              </div>
            </div>

            <StatusBadge status={process.status} size="sm" />
          </div>

          {/* Metrics Bars */}
          <div className="space-y-2.5 my-3 p-2.5 rounded-lg bg-white/[0.02] border border-white/[0.04]">
            {/* Memory */}
            <div>
              <div className="flex justify-between text-[11px] font-mono text-slate-300 mb-1">
                <span className="flex items-center gap-1 text-slate-400">
                  <HardDrives weight="regular" className="w-3 h-3 text-sky-400" /> RAM
                </span>
                <span className="font-bold text-slate-200">{process.mem}</span>
              </div>
              <div className="w-full bg-white/[0.04] rounded-full h-1.5 overflow-hidden border border-white/[0.03]">
                <div
                  className="h-full bg-sky-500 rounded-full transition-all"
                  style={{ width: `${Math.min((memNum / 1024) * 100, 100)}%` }}
                />
              </div>
            </div>

            {/* CPU */}
            <div>
              <div className="flex justify-between text-[11px] font-mono text-slate-300 mb-1">
                <span className="flex items-center gap-1 text-slate-400">
                  <Cpu weight="regular" className="w-3 h-3 text-amber-400" /> CPU
                </span>
                <span className="font-bold text-slate-200">{process.cpu}</span>
              </div>
              <div className="w-full bg-white/[0.04] rounded-full h-1.5 overflow-hidden border border-white/[0.03]">
                <div
                  className={`h-full rounded-full transition-all ${cpuNum > 75 ? "bg-rose-500" : "bg-[#ff5500]"}`}
                  style={{ width: `${Math.min(cpuNum, 100)}%` }}
                />
              </div>
            </div>
          </div>

          {/* Sub-info: Uptime & Restarts */}
          <div className="flex items-center justify-between text-[10px] font-mono text-slate-400 pt-1">
            <div className="flex items-center gap-1">
              <Clock weight="regular" className="w-3 h-3 text-emerald-400" />
              <span>{process.uptime}</span>
            </div>
            <div className="flex items-center gap-1">
              <ArrowCounterClockwise weight="regular" className="w-3 h-3 text-purple-400" />
              <span>{process.restarts} restarts</span>
            </div>
          </div>
        </div>

        {/* Footer actions */}
        <div className="flex items-center justify-between gap-1 pt-3 mt-3 border-t border-white/[0.05]">
          <div className="flex items-center gap-1">
            <Link
              href={`/processes/${encodeURIComponent(process.name)}`}
              className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-white/[0.05] rounded-lg transition-colors tactile-btn"
              title="Details"
            >
              <Eye weight="bold" className="w-3.5 h-3.5" />
            </Link>

            <Link
              href={`/processes/${encodeURIComponent(process.name)}/logs`}
              className="p-1.5 text-slate-400 hover:text-sky-400 hover:bg-white/[0.05] rounded-lg transition-colors tactile-btn"
              title="Live Stream Logs"
            >
              <TerminalWindow weight="bold" className="w-3.5 h-3.5" />
            </Link>

            <button
              onClick={() => setIsLimitsOpen(true)}
              className="p-1.5 text-slate-400 hover:text-amber-400 hover:bg-white/[0.05] rounded-lg transition-colors cursor-pointer tactile-btn"
              title="Limits"
            >
              <SlidersHorizontal weight="bold" className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="flex items-center gap-1">
            <button
              onClick={() => setConfirmAction("restart")}
              disabled={isActing}
              className="p-1.5 text-slate-400 hover:text-[#ff5500] hover:bg-white/[0.05] rounded-lg transition-colors cursor-pointer tactile-btn"
              title="Restart"
            >
              <ArrowsClockwise weight="bold" className={`w-3.5 h-3.5 ${isActing ? "animate-spin" : ""}`} />
            </button>

            {isOnline ? (
              <button
                onClick={() => setConfirmAction("stop")}
                disabled={isActing}
                className="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-white/[0.05] rounded-lg transition-colors cursor-pointer tactile-btn"
                title="Stop"
              >
                <Stop weight="fill" className="w-3.5 h-3.5" />
              </button>
            ) : (
              <button
                onClick={() => setConfirmAction("start")}
                disabled={isActing}
                className="p-1.5 text-slate-400 hover:text-emerald-400 hover:bg-white/[0.05] rounded-lg transition-colors cursor-pointer tactile-btn"
                title="Start"
              >
                <Play weight="fill" className="w-3.5 h-3.5" />
              </button>
            )}

            <button
              onClick={() => setConfirmAction("delete")}
              disabled={isActing}
              className="p-1.5 text-slate-400 hover:text-rose-500 hover:bg-rose-950/30 rounded-lg transition-colors cursor-pointer tactile-btn"
              title="Delete"
            >
              <Trash weight="bold" className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Confirmation Dialog */}
      <ConfirmDialog
        isOpen={confirmAction !== null}
        title={`Confirm ${confirmAction?.toUpperCase()}`}
        message={`Are you sure you want to ${confirmAction} daemon "${process.name}"?`}
        confirmText={confirmAction ? confirmAction.charAt(0).toUpperCase() + confirmAction.slice(1) : "Confirm"}
        variant={confirmAction === "delete" || confirmAction === "stop" ? "danger" : "primary"}
        isLoading={isActing}
        onConfirm={() => confirmAction && handleAction(confirmAction)}
        onCancel={() => setConfirmAction(null)}
      />

      {/* Limits Modal */}
      <ResourceLimitsModal
        isOpen={isLimitsOpen}
        serviceName={process.name}
        currentMemLimit={process.memLimit}
        currentCpuLimit={process.cpuLimit}
        onClose={() => setIsLimitsOpen(false)}
        onSave={handleSaveLimits}
      />
    </>
  );
};
