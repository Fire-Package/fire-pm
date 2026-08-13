"use client";

import React, { useState } from "react";
import { Button } from "./ui/Button";
import { Input } from "./ui/Input";
import { Sliders, X } from "lucide-react";

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
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in">
      <div className="bg-[#12151e] border border-[#262e40] rounded-xl max-w-md w-full p-6 shadow-2xl animate-in zoom-in-95">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-[#ff5500]/10 text-[#ff5500] border border-[#ff5500]/20">
              <Sliders className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-slate-100">Resource Limits</h3>
              <p className="text-xs text-slate-400 font-mono">{serviceName}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-200 transition-colors p-1"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <Input
            label="Memory Limit (e.g. 256M, 1G, or empty for none)"
            placeholder="e.g. 500M"
            value={mem}
            onChange={(e) => setMem(e.target.value)}
            helperText="Uses systemd MemoryMax with unlimited swap."
          />

          <Input
            label="CPU Quota (e.g. 50%, 100%, or empty for none)"
            placeholder="e.g. 50%"
            value={cpu}
            onChange={(e) => setCpu(e.target.value)}
            helperText="Uses systemd CPUQuota percentage limit."
          />

          {error && <div className="text-xs text-rose-400 bg-rose-950/40 p-2.5 rounded border border-rose-900/60">{error}</div>}

          <div className="flex items-center justify-end gap-3 mt-3">
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
