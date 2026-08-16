"use client";

import React from "react";
import { Header } from "@/components/Header";
import { ProcessTable } from "@/components/ProcessTable";
import { SystemHealth } from "@/components/SystemHealth";
import { useProcesses } from "@/hooks/useProcesses";
import { useSystemInfo } from "@/hooks/useSystemInfo";
import { useTunnels } from "@/hooks/useTunnels";
import { 
  Stack, 
  CheckCircle, 
  Warning, 
  HardDrives, 
  Plugs, 
  Pulse, 
  Cpu 
} from "@phosphor-icons/react";

export default function DashboardPage() {
  const { processes, total, online, stopped, isLoading: isProcsLoading, refresh: refreshProcs } = useProcesses();
  const { info, health, isLoading: isSysLoading } = useSystemInfo();
  const { tunnels } = useTunnels();

  const handleRefresh = () => {
    refreshProcs();
  };

  const erroredCount = processes.filter(
    (p) => p.status === "errored" || p.status === "failed"
  ).length;

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <Header
        title="Command Center"
        subtitle="Real-time Linux daemon orchestration & telemetry"
        onRefresh={handleRefresh}
        isRefreshing={isProcsLoading}
      />

      <main className="p-5 sm:p-6 md:p-8 space-y-6 max-w-7xl w-full mx-auto">
        {/* Double-Bezel KPI Cards Grid */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3.5 sm:gap-4">
          {/* Total Services */}
          <div className="double-bezel">
            <div className="double-bezel-inner p-4 flex items-center justify-between">
              <div>
                <div className="text-[10px] font-mono font-bold uppercase tracking-[0.15em] text-slate-400">
                  Total Services
                </div>
                <div className="text-2xl font-bold font-mono text-slate-100 mt-1">
                  {total}
                </div>
              </div>
              <div className="p-2.5 rounded-xl bg-white/[0.04] text-slate-300 border border-white/[0.06]">
                <Stack weight="bold" className="w-5 h-5 text-[#ff5500]" />
              </div>
            </div>
          </div>

          {/* Online Services */}
          <div className="double-bezel">
            <div className="double-bezel-inner p-4 flex items-center justify-between">
              <div>
                <div className="text-[10px] font-mono font-bold uppercase tracking-[0.15em] text-slate-400">
                  Online Active
                </div>
                <div className="text-2xl font-bold font-mono text-emerald-400 mt-1">
                  {online}
                </div>
              </div>
              <div className="p-2.5 rounded-xl bg-emerald-950/40 text-emerald-400 border border-emerald-500/25">
                <CheckCircle weight="fill" className="w-5 h-5" />
              </div>
            </div>
          </div>

          {/* Stopped / Errored */}
          <div className="double-bezel">
            <div className="double-bezel-inner p-4 flex items-center justify-between">
              <div>
                <div className="text-[10px] font-mono font-bold uppercase tracking-[0.15em] text-slate-400">
                  Stopped / Failed
                </div>
                <div
                  className={`text-2xl font-bold font-mono mt-1 ${
                    erroredCount > 0 ? "text-rose-400" : "text-slate-400"
                  }`}
                >
                  {stopped}
                </div>
              </div>
              <div
                className={`p-2.5 rounded-xl ${
                  erroredCount > 0
                    ? "bg-rose-950/50 text-rose-400 border border-rose-500/30"
                    : "bg-white/[0.04] text-slate-400 border border-white/[0.06]"
                }`}
              >
                <Warning weight="bold" className="w-5 h-5" />
              </div>
            </div>
          </div>

          {/* Active Tunnels */}
          <div className="double-bezel">
            <div className="double-bezel-inner p-4 flex items-center justify-between">
              <div>
                <div className="text-[10px] font-mono font-bold uppercase tracking-[0.15em] text-slate-400">
                  Live Tunnels
                </div>
                <div className="text-2xl font-bold font-mono text-amber-400 mt-1">
                  {tunnels.length}
                </div>
              </div>
              <div className="p-2.5 rounded-xl bg-amber-950/40 text-amber-400 border border-amber-500/25">
                <Plugs weight="bold" className="w-5 h-5" />
              </div>
            </div>
          </div>
        </div>

        {/* Process Management Table */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-[#ff5500] telemetry-pulse" />
              <h2 className="text-sm font-bold text-slate-100 tracking-tight font-sans">
                Managed Daemons & Processes
              </h2>
            </div>
            <span className="text-[10px] text-slate-500 font-mono">
              Auto-polled (3s)
            </span>
          </div>

          <ProcessTable
            processes={processes}
            isLoading={isProcsLoading}
            onRefresh={refreshProcs}
          />
        </div>

        {/* Diagnostics & Host Storage */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 pt-2">
          <div className="lg:col-span-2">
            <SystemHealth health={health} isLoading={isSysLoading} />
          </div>

          {info && (
            <div className="double-bezel">
              <div className="double-bezel-inner p-5 flex flex-col justify-between h-full">
                <div>
                  <div className="flex items-center gap-2.5 pb-4 mb-4 border-b border-white/[0.05]">
                    <div className="p-2 rounded-xl bg-sky-500/10 border border-sky-500/20 text-sky-400">
                      <HardDrives weight="bold" className="w-4 h-4" />
                    </div>
                    <div>
                      <h3 className="text-sm font-bold text-slate-100 font-sans tracking-tight">Host Storage & Load</h3>
                      <p className="text-[11px] text-slate-400 font-mono">Kernel hardware resource utilization</p>
                    </div>
                  </div>

                  <div className="space-y-4 text-xs font-mono">
                    <div>
                      <div className="flex justify-between text-slate-300 mb-1.5">
                        <span className="text-slate-400 font-medium">Disk Usage (/)</span>
                        <span className="font-bold text-slate-100">{info.diskUsedPercent}%</span>
                      </div>
                      <div className="w-full bg-white/[0.04] rounded-full h-2 overflow-hidden border border-white/[0.04]">
                        <div
                          className={`h-full rounded-full ${
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
                      <div className="flex justify-between text-slate-300 mb-1.5">
                        <span className="text-slate-400 font-medium">RAM Utilization</span>
                        <span className="font-bold text-slate-100">{info.memUsedPercent}%</span>
                      </div>
                      <div className="w-full bg-white/[0.04] rounded-full h-2 overflow-hidden border border-white/[0.04]">
                        <div
                          className={`h-full rounded-full ${
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

                <div className="pt-4 mt-4 border-t border-white/[0.05] flex items-center justify-between text-[11px] text-slate-400 font-mono">
                  <span>Load Avg:</span>
                  <span className="text-slate-200 font-bold">{info.loadAvg.join(", ")}</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
