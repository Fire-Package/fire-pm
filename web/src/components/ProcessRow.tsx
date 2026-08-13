"use client";

import React, { useState } from "react";
import Link from "next/link";
import { RotateCw, Square, Play, Sliders, FileCode, Trash2, Terminal, Eye } from "lucide-react";
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

  return (
    <>
      <tr className="border-b border-[#1c2230] hover:bg-[#151926]/70 transition-colors text-sm font-normal">
        {/* Name & PID */}
        <td className="py-3.5 px-4">
          <div className="flex items-center gap-2">
            <Link
              href={`/processes/${encodeURIComponent(process.name)}`}
              className="font-semibold text-slate-100 hover:text-[#ff5500] transition-colors"
            >
              {process.name}
            </Link>
            {process.pid && (
              <span className="text-[11px] font-mono text-slate-500 bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
                PID {process.pid}
              </span>
            )}
          </div>
        </td>

        {/* Status */}
        <td className="py-3.5 px-4">
          <StatusBadge status={process.status} />
        </td>

        {/* Port */}
        <td className="py-3.5 px-4 font-mono text-xs text-slate-300">
          {process.port !== "-" ? (
            <span className="text-amber-400 font-semibold bg-amber-950/40 border border-amber-800/40 px-1.5 py-0.5 rounded">
              :{process.port}
            </span>
          ) : (
            <span className="text-slate-600">-</span>
          )}
        </td>

        {/* Memory & Mem Limit */}
        <td className="py-3.5 px-4 font-mono text-xs">
          <div className="text-slate-200 font-medium">{process.mem}</div>
          {process.memLimit !== "-" && (
            <div className="text-[10px] text-slate-500">max {process.memLimit}</div>
          )}
        </td>

        {/* CPU & CPU Limit */}
        <td className="py-3.5 px-4 font-mono text-xs">
          <div className="text-slate-200 font-medium">{process.cpu}</div>
          {process.cpuLimit !== "-" && (
            <div className="text-[10px] text-slate-500">max {process.cpuLimit}</div>
          )}
        </td>

        {/* Uptime */}
        <td className="py-3.5 px-4 font-mono text-xs text-slate-400">
          {process.uptime}
        </td>

        {/* Restarts */}
        <td className="py-3.5 px-4 font-mono text-xs text-slate-400">
          {process.restarts}
        </td>

        {/* Action Controls */}
        <td className="py-3.5 px-4 text-right">
          <div className="flex items-center justify-end gap-1">
            {/* Live details button */}
            <Link
              href={`/processes/${encodeURIComponent(process.name)}`}
              className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-[#202738] rounded transition-colors"
              title="Process Details"
            >
              <Eye className="w-4 h-4" />
            </Link>

            {/* Logs button */}
            <Link
              href={`/processes/${encodeURIComponent(process.name)}/logs`}
              className="p-1.5 text-slate-400 hover:text-sky-400 hover:bg-[#202738] rounded transition-colors"
              title="Live Logs"
            >
              <Terminal className="w-4 h-4" />
            </Link>

            {/* Restart button */}
            <button
              onClick={() => setConfirmAction("restart")}
              disabled={isActing}
              className="p-1.5 text-slate-400 hover:text-[#ff5500] hover:bg-[#202738] rounded transition-colors cursor-pointer"
              title="Restart"
            >
              <RotateCw className={`w-4 h-4 ${isActing ? "animate-spin" : ""}`} />
            </button>

            {/* Stop/Start toggle */}
            {isOnline ? (
              <button
                onClick={() => setConfirmAction("stop")}
                disabled={isActing}
                className="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-[#202738] rounded transition-colors cursor-pointer"
                title="Stop"
              >
                <Square className="w-4 h-4" />
              </button>
            ) : (
              <button
                onClick={() => setConfirmAction("start")}
                disabled={isActing}
                className="p-1.5 text-slate-400 hover:text-emerald-400 hover:bg-[#202738] rounded transition-colors cursor-pointer"
                title="Start"
              >
                <Play className="w-4 h-4" />
              </button>
            )}

            {/* Resource limits */}
            <button
              onClick={() => setIsLimitsOpen(true)}
              className="p-1.5 text-slate-400 hover:text-amber-400 hover:bg-[#202738] rounded transition-colors cursor-pointer"
              title="Resource Limits"
            >
              <Sliders className="w-4 h-4" />
            </button>

            {/* Delete button */}
            <button
              onClick={() => setConfirmAction("delete")}
              disabled={isActing}
              className="p-1.5 text-slate-400 hover:text-rose-500 hover:bg-rose-950/30 rounded transition-colors cursor-pointer"
              title="Delete Service"
            >
              <Trash2 className="w-4 h-4" />
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
