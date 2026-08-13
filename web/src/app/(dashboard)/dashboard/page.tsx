"use client";

import React from "react";
import { Header } from "@/components/Header";
import { ProcessTable } from "@/components/ProcessTable";
import { SystemHealth } from "@/components/SystemHealth";
import { useProcesses } from "@/hooks/useProcesses";
import { useSystemInfo } from "@/hooks/useSystemInfo";
import { useTunnels } from "@/hooks/useTunnels";
import { Layers, CheckCircle2, AlertTriangle, HardDrive, Network } from "lucide-react";

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
        title="Dashboard"
        subtitle="Live status of system services and resources"
        onRefresh={handleRefresh}
        isRefreshing={isProcsLoading}
      />

      <main className="p-6 md:p-8 space-y-6 max-w-7xl w-full mx-auto">
        {/* KPI Cards Grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {/* Total Services */}
          <div className="bg-[#12151e] border border-[#202634] rounded-xl p-4.5 flex items-center justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Total Services
              </div>
              <div className="text-2xl font-bold font-mono text-slate-100 mt-1">
                {total}
              </div>
            </div>
            <div className="p-3 rounded-lg bg-slate-800/60 text-slate-300">
              <Layers className="w-5 h-5" />
            </div>
          </div>

          {/* Online Services */}
          <div className="bg-[#12151e] border border-[#202634] rounded-xl p-4.5 flex items-center justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Online Active
              </div>
              <div className="text-2xl font-bold font-mono text-emerald-400 mt-1">
                {online}
              </div>
            </div>
            <div className="p-3 rounded-lg bg-emerald-950/70 text-emerald-400 border border-emerald-800/50">
              <CheckCircle2 className="w-5 h-5" />
            </div>
          </div>

          {/* Stopped / Errored */}
          <div className="bg-[#12151e] border border-[#202634] rounded-xl p-4.5 flex items-center justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
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
              className={`p-3 rounded-lg ${
                erroredCount > 0
                  ? "bg-rose-950/70 text-rose-400 border border-rose-800/50"
                  : "bg-slate-800/60 text-slate-400"
              }`}
            >
              <AlertTriangle className="w-5 h-5" />
            </div>
          </div>

          {/* Active Tunnels */}
          <div className="bg-[#12151e] border border-[#202634] rounded-xl p-4.5 flex items-center justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Live Tunnels
              </div>
              <div className="text-2xl font-bold font-mono text-amber-400 mt-1">
                {tunnels.length}
              </div>
            </div>
            <div className="p-3 rounded-lg bg-amber-950/70 text-amber-400 border border-amber-800/50">
              <Network className="w-5 h-5" />
            </div>
          </div>
        </div>

        {/* Process Management Table */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-bold text-slate-100 tracking-tight">
              Managed Processes
            </h2>
            <span className="text-xs text-slate-500 font-mono">
              Auto-refreshing (3s)
            </span>
          </div>

          <ProcessTable
            processes={processes}
            isLoading={isProcsLoading}
            onRefresh={refreshProcs}
          />
        </div>

        {/* System Doctor Diagnostics Widget */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pt-2">
          <div className="md:col-span-2">
            <SystemHealth health={health} isLoading={isSysLoading} />
          </div>

          {info && (
            <div className="bg-[#12151e] border border-[#202634] rounded-lg p-5 flex flex-col justify-between">
              <div>
                <div className="flex items-center gap-2 pb-3.5 mb-4 border-b border-[#1c2230]">
                  <HardDrive className="w-5 h-5 text-sky-400" />
                  <h3 className="text-base font-semibold text-slate-100">Host Storage & Load</h3>
                </div>

                <div className="space-y-4 text-xs font-mono">
                  <div>
                    <div className="flex justify-between text-slate-300 mb-1">
                      <span>Disk Usage (/)</span>
                      <span className="font-semibold text-slate-100">{info.diskUsedPercent}%</span>
                    </div>
                    <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
                      <div
                        className={`h-full ${
                          info.diskUsedPercent > 85 ? "bg-rose-500" : "bg-sky-500"
                        }`}
                        style={{ width: `${Math.min(info.diskUsedPercent, 100)}%` }}
                      />
                    </div>
                    <div className="text-[11px] text-slate-500 mt-1">
                      {info.diskUsed} of {info.diskTotal} used
                    </div>
                  </div>

                  <div>
                    <div className="flex justify-between text-slate-300 mb-1">
                      <span>RAM Utilization</span>
                      <span className="font-semibold text-slate-100">{info.memUsedPercent}%</span>
                    </div>
                    <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
                      <div
                        className={`h-full ${
                          info.memUsedPercent > 85 ? "bg-rose-500" : "bg-[#ff5500]"
                        }`}
                        style={{ width: `${Math.min(info.memUsedPercent, 100)}%` }}
                      />
                    </div>
                    <div className="text-[11px] text-slate-500 mt-1">
                      {info.memFree} free / {info.memTotal} total
                    </div>
                  </div>
                </div>
              </div>

              <div className="pt-4 border-t border-[#1c2230] text-[11px] text-slate-400 font-mono">
                Load Averages: {info.loadAvg.join(", ")}
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
