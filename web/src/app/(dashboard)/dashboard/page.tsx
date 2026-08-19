"use client";

import React, { useState } from "react";
import { Header } from "@/components/Header";
import { ProcessTable } from "@/components/ProcessTable";
import { SystemHealth } from "@/components/SystemHealth";
import { StartProcessModal } from "@/components/StartProcessModal";
import { useProcesses } from "@/hooks/useProcesses";
import { useSystemInfo } from "@/hooks/useSystemInfo";
import { useTunnels } from "@/hooks/useTunnels";
import { 
  Stack, 
  CheckCircle, 
  Warning, 
  HardDrives, 
  Plugs, 
  Cpu,
  Activity,
  Plus
} from "@phosphor-icons/react";

export default function DashboardPage() {
  const { processes, total, online, stopped, isLoading: isProcsLoading, refresh: refreshProcs } = useProcesses();
  const { info, health, isLoading: isSysLoading } = useSystemInfo();
  const { tunnels } = useTunnels();
  const [isLaunchModalOpen, setIsLaunchModalOpen] = useState(false);

  const handleRefresh = () => {
    refreshProcs();
  };

  const erroredCount = processes.filter(
    (p) => p.status === "errored" || p.status === "failed"
  ).length;

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <Header
        title="Telemetry Command Console"
        subtitle="Linux kernel systemd process supervisor & resource monitor"
        onRefresh={handleRefresh}
        isRefreshing={isProcsLoading}
        onNewProcess={() => setIsLaunchModalOpen(true)}
      />

      <main className="p-4 sm:p-6 md:p-7 space-y-5 max-w-7xl w-full mx-auto">
        {/* KPI Telemetry Cards Grid */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {/* Total Daemons */}
          <div className="telemetry-panel p-3.5 flex items-center justify-between">
            <div>
              <div className="text-[9px] font-mono font-bold uppercase tracking-[0.15em] text-slate-400">
                Total Daemons
              </div>
              <div className="text-xl sm:text-2xl font-bold font-mono text-slate-100 mt-0.5">
                {total}
              </div>
            </div>
            <div className="p-2 rounded-lg bg-white/[0.03] text-[#ff5500] border border-white/[0.06]">
              <Stack weight="bold" className="w-4 h-4" />
            </div>
          </div>

          {/* Online Active */}
          <div className="telemetry-panel p-3.5 flex items-center justify-between">
            <div>
              <div className="text-[9px] font-mono font-bold uppercase tracking-[0.15em] text-slate-400">
                Online Active
              </div>
              <div className="text-xl sm:text-2xl font-bold font-mono text-emerald-400 mt-0.5">
                {online}
              </div>
            </div>
            <div className="p-2 rounded-lg bg-emerald-950/40 text-emerald-400 border border-emerald-500/20">
              <CheckCircle weight="fill" className="w-4 h-4" />
            </div>
          </div>

          {/* Stopped / Failed */}
          <div className="telemetry-panel p-3.5 flex items-center justify-between">
            <div>
              <div className="text-[9px] font-mono font-bold uppercase tracking-[0.15em] text-slate-400">
                Stopped / Failed
              </div>
              <div
                className={`text-xl sm:text-2xl font-bold font-mono mt-0.5 ${
                  erroredCount > 0 ? "text-rose-400" : "text-slate-400"
                }`}
              >
                {stopped}
              </div>
            </div>
            <div
              className={`p-2 rounded-lg ${
                erroredCount > 0
                  ? "bg-rose-950/50 text-rose-400 border border-rose-500/30"
                  : "bg-white/[0.03] text-slate-400 border border-white/[0.06]"
              }`}
            >
              <Warning weight="bold" className="w-4 h-4" />
            </div>
          </div>

          {/* Live Tunnels */}
          <div className="telemetry-panel p-3.5 flex items-center justify-between">
            <div>
              <div className="text-[9px] font-mono font-bold uppercase tracking-[0.15em] text-slate-400">
                Active Tunnels
              </div>
              <div className="text-xl sm:text-2xl font-bold font-mono text-amber-400 mt-0.5">
                {tunnels.length}
              </div>
            </div>
            <div className="p-2 rounded-lg bg-amber-950/40 text-amber-400 border border-amber-500/20">
              <Plugs weight="bold" className="w-4 h-4" />
            </div>
          </div>
        </div>

        {/* Process Management Section */}
        <div className="space-y-2.5">
          <div className="flex items-center justify-between px-0.5">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-[#ff5500] pulse-glow-orange" />
              <h2 className="text-xs sm:text-sm font-bold text-slate-100 tracking-tight font-sans">
                Active Process Registry
              </h2>
            </div>
            <span className="text-[10px] text-slate-500 font-mono">
              Live Polling (3s)
            </span>
          </div>

          <ProcessTable
            processes={processes}
            isLoading={isProcsLoading}
            onRefresh={refreshProcs}
            onNewProcess={() => setIsLaunchModalOpen(true)}
          />
        </div>

        {/* System Diagnostics & Host Resource Usage */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 pt-1">
          <div className="lg:col-span-2">
            <SystemHealth health={health} isLoading={isSysLoading} />
          </div>

          {info && (
            <div className="telemetry-panel p-5 flex flex-col justify-between h-full">
              <div>
                <div className="flex items-center gap-2.5 pb-3.5 mb-3.5 border-b border-white/[0.05]">
                  <div className="p-2 rounded-lg bg-sky-500/10 border border-sky-500/20 text-sky-400">
                    <HardDrives weight="bold" className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-slate-100 font-sans tracking-tight">Kernel Host Utilization</h3>
                    <p className="text-[10px] text-slate-400 font-mono">Storage & Memory quotas</p>
                  </div>
                </div>

                <div className="space-y-3.5 text-xs font-mono">
                  <div>
                    <div className="flex justify-between text-slate-300 mb-1">
                      <span className="text-slate-400">Root Disk (/)</span>
                      <span className="font-bold text-slate-100">{info.diskUsedPercent}%</span>
                    </div>
                    <div className="w-full bg-white/[0.04] rounded-full h-1.5 overflow-hidden border border-white/[0.04]">
                      <div
                        className={`h-full rounded-full transition-all ${
                          info.diskUsedPercent > 85 ? "bg-rose-500" : "bg-sky-500"
                        }`}
                        style={{ width: `${Math.min(info.diskUsedPercent, 100)}%` }}
                      />
                    </div>
                    <div className="text-[10px] text-slate-500 mt-1">
                      {info.diskUsed} of {info.diskTotal} used
                    </div>
                  </div>

                  <div>
                    <div className="flex justify-between text-slate-300 mb-1">
                      <span className="text-slate-400">RAM Allocation</span>
                      <span className="font-bold text-slate-100">{info.memUsedPercent}%</span>
                    </div>
                    <div className="w-full bg-white/[0.04] rounded-full h-1.5 overflow-hidden border border-white/[0.04]">
                      <div
                        className={`h-full rounded-full transition-all ${
                          info.memUsedPercent > 85 ? "bg-rose-500" : "bg-[#ff5500]"
                        }`}
                        style={{ width: `${Math.min(info.memUsedPercent, 100)}%` }}
                      />
                    </div>
                    <div className="text-[10px] text-slate-500 mt-1">
                      {info.memFree} free / {info.memTotal} total
                    </div>
                  </div>
                </div>
              </div>

              <div className="pt-3.5 mt-3.5 border-t border-white/[0.05] flex items-center justify-between text-[11px] text-slate-400 font-mono">
                <span>Kernel Load Avg:</span>
                <span className="text-slate-200 font-bold">{info.loadAvg.join(", ")}</span>
              </div>
            </div>
          )}
        </div>
      </main>

      {/* Start Process Modal */}
      <StartProcessModal
        isOpen={isLaunchModalOpen}
        onClose={() => setIsLaunchModalOpen(false)}
        onSuccess={refreshProcs}
      />
    </div>
  );
}
