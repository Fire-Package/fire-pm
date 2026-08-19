"use client";

import React, { useState } from "react";
import { Button } from "./ui/Button";
import { Input } from "./ui/Input";
import { SlidersHorizontal, X } from "@phosphor-icons/react";

export interface ResourceLimitsModalProps {
  isOpen: boolean;
  serviceName: string;
  currentMemLimit?: string;
  currentCpuLimit?: string;
  onClose: () => void;
  onSave: (mem?: string | null, cpu?: string | null) => Promise<void>;
}

export const ResourceLimitsModal: React.FC<ResourceLimitsModalProps> = ({
  isOpen,
  serviceName,
  currentMemLimit = "",
  currentCpuLimit = "",
  onClose,
  onSave,
}) => {
  const [mem, setMem] = useState(currentMemLimit === "-" ? "" : currentMemLimit);
  const [cpu, setCpu] = useState(currentCpuLimit === "-" ? "" : currentCpuLimit);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);
    try {
      await onSave(mem.trim() || null, cpu.trim() || null);
      onClose();
    } catch (err: any) {
      setError(err.message || "Failed to save resource limits");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md animate-in fade-in select-none">
      <div className="telemetry-panel max-w-md w-full p-6 shadow-2xl animate-in zoom-in-95 border-white/[0.1]">
        <div className="flex items-center justify-between pb-3.5 mb-4 border-b border-white/[0.05]">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/20">
              <SlidersHorizontal weight="bold" className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-100 font-sans tracking-tight">Resource Quotas</h3>
              <p className="text-[10px] text-slate-400 font-mono">{serviceName}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-200 transition-colors p-1 cursor-pointer tactile-btn"
          >
            <X weight="bold" className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3.5 text-xs font-mono">
          <Input
            label="Memory Limit (e.g. 500M, 1G, or empty for none)"
            placeholder="e.g. 500M"
            value={mem}
            onChange={(e) => setMem(e.target.value)}
            helperText="Directly bounds cgroup MemoryMax"
          />

          <Input
            label="CPU Quota (e.g. 50%, 100%, or empty for none)"
            placeholder="e.g. 50%"
            value={cpu}
            onChange={(e) => setCpu(e.target.value)}
            helperText="Directly bounds cgroup CPUQuota"
          />

          {error && <div className="text-xs text-rose-400 bg-rose-950/40 p-2.5 rounded-lg border border-rose-900/60 font-mono">{error}</div>}

          <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-white/[0.05]">
            <Button variant="secondary" type="button" onClick={onClose} disabled={isLoading}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" isLoading={isLoading}>
              Save Limits
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};
