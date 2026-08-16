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
  Eye 
} from "@phosphor-icons/react";
import { ProcessItem } from "@/lib/types";
import { StatusBadge } from "./StatusBadge";
import { ConfirmDialog } from "./ConfirmDialog";
import { ResourceLimitsModal } from "./ResourceLimitsModal";
import { useToast } from "./ui/Toast";
import { ProcessApi } from "@/lib/api/processes";

export interface ProcessRowProps {
  process: ProcessItem;
  onRefresh: () => void;
}

export const ProcessRow: React.FC<ProcessRowProps> = ({ process, onRefresh }) => {
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
        showToast(`Restarted process "${process.name}"`, "success");
      } else if (action === "stop") {
        await ProcessApi.stop(process.name);
        showToast(`Stopped process "${process.name}"`, "info");
      } else if (action === "start") {
        await ProcessApi.start(process.name);
        showToast(`Started process "${process.name}"`, "success");
      } else if (action === "delete") {
        await ProcessApi.delete(process.name);
        showToast(`Deleted process "${process.name}"`, "info");
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
      <tr className="border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors text-xs font-normal group">
        {/* Name & PID */}
        <td className="py-3 px-4">
          <div className="flex items-center gap-2">
            <Link
              href={`/processes/${encodeURIComponent(process.name)}`}
              className="font-bold text-slate-100 hover:text-[#ff5500] transition-colors font-sans tracking-tight"
            >
              {process.name}
            </Link>
            {process.pid && (
              <span className="text-[9px] font-mono text-slate-400 bg-white/[0.03] px-1.5 py-0.5 rounded-md border border-white/[0.06]">
                PID {process.pid}
              </span>
            )}
          </div>
        </td>

        {/* Status */}
        <td className="py-3 px-4">
          <StatusBadge status={process.status} size="sm" />
        </td>

        {/* Port */}
        <td className="py-3 px-4 font-mono text-xs text-slate-300">
          {process.port !== "-" ? (
            <span className="text-amber-400 font-semibold bg-amber-950/40 border border-amber-500/30 px-1.5 py-0.5 rounded-md">
              :{process.port}
            </span>
          ) : (
            <span className="text-slate-600">-</span>
          )}
        </td>

        {/* Memory & Mem Limit */}
        <td className="py-3 px-4 font-mono text-xs">
          <div className="flex items-center gap-2">
            <span className="text-slate-200 font-medium">{process.mem}</span>
            <div className="w-12 h-1.5 bg-white/[0.05] rounded-full overflow-hidden hidden sm:block border border-white/[0.04]">
              <div
                className="h-full bg-sky-500 rounded-full"
                style={{ width: `${Math.min((memNum / 1024) * 100, 100)}%` }}
              />
            </div>
          </div>
          {process.memLimit !== "-" && (
            <div className="text-[10px] text-slate-500 mt-0.5 font-mono">max {process.memLimit}</div>
          )}
        </td>

        {/* CPU & CPU Limit */}
        <td className="py-3 px-4 font-mono text-xs">
          <div className="flex items-center gap-2">
            <span className="text-slate-200 font-medium">{process.cpu}</span>
            <div className="w-12 h-1.5 bg-white/[0.05] rounded-full overflow-hidden hidden sm:block border border-white/[0.04]">
              <div
                className={`h-full rounded-full ${cpuNum > 80 ? "bg-rose-500" : "bg-[#ff5500]"}`}
                style={{ width: `${Math.min(cpuNum, 100)}%` }}
              />
            </div>
          </div>
          {process.cpuLimit !== "-" && (
            <div className="text-[10px] text-slate-500 mt-0.5 font-mono">max {process.cpuLimit}</div>
          )}
        </td>

        {/* Uptime */}
        <td className="py-3 px-4 font-mono text-xs text-slate-400">
          {process.uptime}
        </td>

        {/* Restarts */}
        <td className="py-3 px-4 font-mono text-xs text-slate-400">
          {process.restarts}
        </td>

        {/* Action Controls */}
        <td className="py-3 px-4 text-right">
          <div className="flex items-center justify-end gap-1">
            {/* Live details button */}
            <Link
              href={`/processes/${encodeURIComponent(process.name)}`}
              className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-white/[0.05] rounded-lg transition-colors haptic-btn"
              title="Process Details"
            >
              <Eye weight="bold" className="w-3.5 h-3.5" />
            </Link>

            {/* Logs button */}
            <Link
              href={`/processes/${encodeURIComponent(process.name)}/logs`}
              className="p-1.5 text-slate-400 hover:text-sky-400 hover:bg-white/[0.05] rounded-lg transition-colors haptic-btn"
              title="Live Logs"
            >
              <TerminalWindow weight="bold" className="w-3.5 h-3.5" />
            </Link>

            {/* Restart button */}
            <button
              onClick={() => setConfirmAction("restart")}
              disabled={isActing}
              className="p-1.5 text-slate-400 hover:text-[#ff5500] hover:bg-white/[0.05] rounded-lg transition-colors cursor-pointer haptic-btn"
              title="Restart"
            >
              <ArrowsClockwise weight="bold" className={`w-3.5 h-3.5 ${isActing ? "animate-spin" : ""}`} />
            </button>

            {/* Stop/Start toggle */}
            {isOnline ? (
              <button
                onClick={() => setConfirmAction("stop")}
                disabled={isActing}
                className="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-white/[0.05] rounded-lg transition-colors cursor-pointer haptic-btn"
                title="Stop"
              >
                <Stop weight="fill" className="w-3.5 h-3.5" />
              </button>
            ) : (
              <button
                onClick={() => setConfirmAction("start")}
                disabled={isActing}
                className="p-1.5 text-slate-400 hover:text-emerald-400 hover:bg-white/[0.05] rounded-lg transition-colors cursor-pointer haptic-btn"
                title="Start"
              >
                <Play weight="fill" className="w-3.5 h-3.5" />
              </button>
            )}

            {/* Resource limits */}
            <button
              onClick={() => setIsLimitsOpen(true)}
              className="p-1.5 text-slate-400 hover:text-amber-400 hover:bg-white/[0.05] rounded-lg transition-colors cursor-pointer haptic-btn"
              title="Resource Limits"
            >
              <SlidersHorizontal weight="bold" className="w-3.5 h-3.5" />
            </button>

            {/* Delete button */}
            <button
              onClick={() => setConfirmAction("delete")}
              disabled={isActing}
              className="p-1.5 text-slate-400 hover:text-rose-500 hover:bg-rose-950/30 rounded-lg transition-colors cursor-pointer haptic-btn"
              title="Delete Service"
            >
              <Trash weight="bold" className="w-3.5 h-3.5" />
            </button>
          </div>
        </td>
      </tr>

      {/* Confirmation Dialog */}
      <ConfirmDialog
        isOpen={confirmAction !== null}
        title={`Confirm ${confirmAction?.toUpperCase()}`}
        message={`Are you sure you want to ${confirmAction} process "${process.name}"?`}
        confirmText={confirmAction ? confirmAction.charAt(0).toUpperCase() + confirmAction.slice(1) : "Confirm"}
        variant={confirmAction === "delete" || confirmAction === "stop" ? "danger" : "primary"}
        isLoading={isActing}
        onConfirm={() => confirmAction && handleAction(confirmAction)}
        onCancel={() => setConfirmAction(null)}
      />

      {/* Resource Limits Modal */}
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
