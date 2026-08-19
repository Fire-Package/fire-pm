"use client";

import React, { useState } from "react";
import { 
  X, 
  Play, 
  TerminalWindow, 
  SlidersHorizontal, 
  Cpu, 
  HardDrives,
  Plus,
  Trash
} from "@phosphor-icons/react";
import { Button } from "./ui/Button";
import { Input } from "./ui/Input";
import { ProcessApi } from "@/lib/api/processes";
import { useToast } from "./ui/Toast";

export interface StartProcessModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export const StartProcessModal: React.FC<StartProcessModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
}) => {
  const { showToast } = useToast();
  const [script, setScript] = useState("");
  const [name, setName] = useState("");
  const [interpreter, setInterpreter] = useState("auto");
  const [customInterpreter, setCustomInterpreter] = useState("");
  const [memLimit, setMemLimit] = useState("");
  const [cpuLimit, setCpuLimit] = useState("");
  const [watch, setWatch] = useState(true);
  const [reload, setReload] = useState(false);
  const [envPairs, setEnvPairs] = useState<{ key: string; value: string }[]>([
    { key: "", value: "" },
  ]);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleAddEnv = () => {
    setEnvPairs([...envPairs, { key: "", value: "" }]);
  };

  const handleRemoveEnv = (idx: number) => {
    setEnvPairs(envPairs.filter((_, i) => i !== idx));
  };

  const handleEnvChange = (idx: number, field: "key" | "value", val: string) => {
    const next = [...envPairs];
    next[idx][field] = val;
    setEnvPairs(next);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!script.trim()) {
      showToast("Script file path is required", "error");
      return;
    }

    const envList = envPairs
      .filter((p) => p.key.trim() && p.value.trim())
      .map((p) => `${p.key.trim()}=${p.value.trim()}`);

    const selectedInterpreter =
      interpreter === "auto"
        ? undefined
        : interpreter === "custom"
        ? customInterpreter.trim() || undefined
        : interpreter;

    setIsSubmitting(true);
    try {
      await ProcessApi.create({
        script: script.trim(),
        name: name.trim() || undefined,
        interpreter: selectedInterpreter,
        env: envList.length > 0 ? envList : undefined,
        watch,
        reload,
        mem: memLimit.trim() || undefined,
        cpu: cpuLimit.trim() || undefined,
      });

      showToast(`Supervised daemon "${name.trim() || script.trim()}" started!`, "success");
      onSuccess();
      onClose();
    } catch (err: any) {
      showToast(err.message || "Failed to start process", "error");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md animate-in fade-in select-none">
      <div className="telemetry-panel max-w-xl w-full p-6 shadow-2xl animate-in zoom-in-95 border-white/[0.1] max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between pb-4 mb-5 border-b border-white/[0.06]">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-[#ff5500]/10 border border-[#ff5500]/25 text-[#ff5500]">
              <Play weight="fill" className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-100 font-sans tracking-tight">
                Launch & Supervise Process
              </h3>
              <p className="text-[11px] text-slate-400 font-mono">
                Deploy application script as a persistent Linux systemd service
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-slate-100 hover:bg-white/[0.05] rounded-lg transition-colors cursor-pointer tactile-btn"
          >
            <X weight="bold" className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 text-xs font-mono">
          {/* Script path & App Name */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
            <div>
              <label className="block text-[10px] font-bold text-slate-300 uppercase tracking-wider mb-1.5">
                Script / Binary Path <span className="text-[#ff5500]">*</span>
              </label>
              <input
                type="text"
                placeholder="/var/www/app.js or main.py"
                value={script}
                onChange={(e) => setScript(e.target.value)}
                className="w-full bg-[#06080d] border border-white/[0.08] rounded-lg px-3 py-2 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#ff5500] text-xs font-mono"
                required
                autoFocus
              />
            </div>

            <div>
              <label className="block text-[10px] font-bold text-slate-300 uppercase tracking-wider mb-1.5">
                Service Name (Optional)
              </label>
              <input
                type="text"
                placeholder="e.g. my-api (defaults to file)"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full bg-[#06080d] border border-white/[0.08] rounded-lg px-3 py-2 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#ff5500] text-xs font-mono"
              />
            </div>
          </div>

          {/* Interpreter */}
          <div>
            <label className="block text-[10px] font-bold text-slate-300 uppercase tracking-wider mb-1.5">
              Interpreter Engine
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {[
                { id: "auto", label: "Auto Detect" },
                { id: "node", label: "Node.js" },
                { id: "python3", label: "Python 3" },
                { id: "bash", label: "Bash / Shell" },
              ].map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setInterpreter(item.id)}
                  className={`px-3 py-2 rounded-lg text-xs font-semibold text-center border transition-all cursor-pointer tactile-btn ${
                    interpreter === item.id
                      ? "bg-[#ff5500]/15 text-white border-[#ff5500]/50 font-bold"
                      : "bg-[#06080d] text-slate-400 border-white/[0.06] hover:text-slate-200"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>

          {/* Resource Limits */}
          <div className="p-3.5 rounded-xl bg-white/[0.015] border border-white/[0.05] space-y-3">
            <div className="flex items-center gap-1.5 text-slate-300 text-xs font-bold font-sans">
              <SlidersHorizontal weight="bold" className="w-3.5 h-3.5 text-amber-400" />
              <span>Resource Quotas (cgroups v2)</span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-[10px] text-slate-400 uppercase tracking-wider mb-1">
                  RAM Cap (e.g. 500M, 1G)
                </label>
                <input
                  type="text"
                  placeholder="Unlimited"
                  value={memLimit}
                  onChange={(e) => setMemLimit(e.target.value)}
                  className="w-full bg-[#06080d] border border-white/[0.06] rounded-lg px-2.5 py-1.5 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-[#ff5500] text-xs font-mono"
                />
              </div>

              <div>
                <label className="block text-[10px] text-slate-400 uppercase tracking-wider mb-1">
                  CPU Quota (e.g. 50%, 100%)
                </label>
                <input
                  type="text"
                  placeholder="Unlimited"
                  value={cpuLimit}
                  onChange={(e) => setCpuLimit(e.target.value)}
                  className="w-full bg-[#06080d] border border-white/[0.06] rounded-lg px-2.5 py-1.5 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-[#ff5500] text-xs font-mono"
                />
              </div>
            </div>
          </div>

          {/* Toggles */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
            <label className="flex items-center gap-2.5 p-2.5 rounded-lg bg-white/[0.02] border border-white/[0.05] cursor-pointer hover:border-white/[0.1] transition-colors">
              <input
                type="checkbox"
                checked={watch}
                onChange={(e) => setWatch(e.target.checked)}
                className="rounded border-slate-700 text-[#ff5500] focus:ring-[#ff5500]"
              />
              <span className="text-xs text-slate-300 font-sans">
                Watchdog Auto-Restart (`Restart=always`)
              </span>
            </label>

            <label className="flex items-center gap-2.5 p-2.5 rounded-lg bg-white/[0.02] border border-white/[0.05] cursor-pointer hover:border-white/[0.1] transition-colors">
              <input
                type="checkbox"
                checked={reload}
                onChange={(e) => setReload(e.target.checked)}
                className="rounded border-slate-700 text-[#ff5500] focus:ring-[#ff5500]"
              />
              <span className="text-xs text-slate-300 font-sans">
                Hot-Reload on File Change (`.path` unit)
              </span>
            </label>
          </div>

          {/* Environment Variables */}
          <div className="space-y-2 pt-1">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold text-slate-300 uppercase tracking-wider">
                Environment Variables
              </span>
              <button
                type="button"
                onClick={handleAddEnv}
                className="flex items-center gap-1 text-[11px] text-[#ff5500] hover:underline cursor-pointer"
              >
                <Plus weight="bold" className="w-3 h-3" /> Add Var
              </button>
            </div>

            {envPairs.map((pair, idx) => (
              <div key={idx} className="flex items-center gap-2">
                <input
                  type="text"
                  placeholder="KEY (e.g. PORT)"
                  value={pair.key}
                  onChange={(e) => handleEnvChange(idx, "key", e.target.value)}
                  className="flex-1 bg-[#06080d] border border-white/[0.06] rounded-lg px-2.5 py-1.5 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-[#ff5500] text-xs font-mono"
                />
                <span className="text-slate-500">=</span>
                <input
                  type="text"
                  placeholder="VALUE (e.g. 8080)"
                  value={pair.value}
                  onChange={(e) => handleEnvChange(idx, "value", e.target.value)}
                  className="flex-1 bg-[#06080d] border border-white/[0.06] rounded-lg px-2.5 py-1.5 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-[#ff5500] text-xs font-mono"
                />
                {envPairs.length > 1 && (
                  <button
                    type="button"
                    onClick={() => handleRemoveEnv(idx)}
                    className="p-1.5 text-slate-500 hover:text-rose-400 rounded transition-colors"
                  >
                    <Trash weight="bold" className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            ))}
          </div>

          {/* Actions */}
          <div className="flex items-center justify-end gap-2.5 pt-4 border-t border-white/[0.06]">
            <Button type="button" variant="secondary" onClick={onClose} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" isLoading={isSubmitting}>
              <Play weight="fill" className="w-3.5 h-3.5" /> Launch Daemon
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};
