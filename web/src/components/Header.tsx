"use client";

import React from "react";
import { 
  Cpu, 
  HardDrives, 
  Clock, 
  Broadcast, 
  ArrowsClockwise,
  Plus
} from "@phosphor-icons/react";
import { useSystemInfo } from "@/hooks/useSystemInfo";

export const Header: React.FC<{
  title: string;
  subtitle?: string;
  onRefresh?: () => void;
  isRefreshing?: boolean;
  onNewProcess?: () => void;
}> = ({ title, subtitle, onRefresh, isRefreshing, onNewProcess }) => {
  const { info } = useSystemInfo();

  return (
    <header className="h-16 px-5 lg:px-7 bg-[#06080d]/80 backdrop-blur-2xl border-b border-white/[0.05] flex items-center justify-between sticky top-0 z-30 select-none">
      <div>
        <h1 className="text-sm font-bold text-slate-100 tracking-tight flex items-center gap-2 font-sans">
          {title}
        </h1>
        {subtitle && <p className="text-[10px] text-slate-400 font-mono tracking-tight">{subtitle}</p>}
      </div>

      <div className="flex items-center gap-2.5">
        {info && (
          <div className="hidden lg:flex items-center gap-3 text-xs font-mono text-slate-400 bg-white/[0.02] border border-white/[0.06] px-3.5 py-1.5 rounded-lg">
            <div className="flex items-center gap-1.5" title="Host Server">
              <Broadcast weight="fill" className="w-3.5 h-3.5 text-[#ff5500]" />
              <span className="text-slate-200 font-semibold">{info.hostname}</span>
            </div>

            <div className="w-px h-3 bg-white/10" />

            <div className="flex items-center gap-1.5" title="Memory Free / Total">
              <HardDrives weight="regular" className="w-3.5 h-3.5 text-sky-400" />
              <span>
                <span className="text-slate-200 font-medium">{info.memFree}</span> free
              </span>
            </div>

            <div className="w-px h-3 bg-white/10" />

            <div className="flex items-center gap-1.5" title="CPU Cores & Load Average">
              <Cpu weight="regular" className="w-3.5 h-3.5 text-amber-400" />
              <span>
                <span className="text-slate-200 font-medium">{info.cpuCount}c</span> ({info.loadAvg[0]})
              </span>
            </div>

            <div className="w-px h-3 bg-white/10" />

            <div className="flex items-center gap-1.5" title="Host Uptime">
              <Clock weight="regular" className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-slate-200 font-medium">{info.uptime}</span>
            </div>
          </div>
        )}

        {onNewProcess && (
          <button
            onClick={onNewProcess}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#ff5500] hover:bg-[#ff681a] text-white text-xs font-semibold shadow-sm shadow-[#ff5500]/25 transition-all cursor-pointer tactile-btn"
          >
            <Plus weight="bold" className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Launch App</span>
          </button>
        )}

        {onRefresh && (
          <button
            onClick={onRefresh}
            disabled={isRefreshing}
            className="p-2 rounded-lg bg-white/[0.03] hover:bg-white/[0.07] text-slate-300 hover:text-white border border-white/[0.07] transition-all cursor-pointer disabled:opacity-50 tactile-btn"
            title="Poll Telemetry"
          >
            <ArrowsClockwise weight="bold" className={`w-3.5 h-3.5 ${isRefreshing ? "animate-spin text-[#ff5500]" : ""}`} />
          </button>
        )}
      </div>
    </header>
  );
};
