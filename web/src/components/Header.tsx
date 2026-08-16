"use client";

import React from "react";
import { 
  Cpu, 
  HardDrives, 
  Clock, 
  Broadcast, 
  ArrowsClockwise 
} from "@phosphor-icons/react";
import { useSystemInfo } from "@/hooks/useSystemInfo";

export const Header: React.FC<{
  title: string;
  subtitle?: string;
  onRefresh?: () => void;
  isRefreshing?: boolean;
}> = ({ title, subtitle, onRefresh, isRefreshing }) => {
  const { info } = useSystemInfo();

  return (
    <header className="h-18 px-6 lg:px-8 bg-[#040507]/80 backdrop-blur-2xl border-b border-white/[0.05] flex items-center justify-between sticky top-0 z-30 select-none">
      <div>
        <h1 className="text-base font-bold text-slate-100 tracking-tight flex items-center gap-2 font-sans">
          {title}
        </h1>
        {subtitle && <p className="text-[11px] text-slate-400 font-mono tracking-tight">{subtitle}</p>}
      </div>

      <div className="flex items-center gap-3">
        {info && (
          <div className="hidden lg:flex items-center gap-3 text-xs font-mono text-slate-400 bg-white/[0.02] border border-white/[0.06] px-4 py-2 rounded-2xl shadow-inner">
            <div className="flex items-center gap-2" title="Host Server">
              <Broadcast weight="fill" className="w-3.5 h-3.5 text-[#ff5500]" />
              <span className="text-slate-200 font-semibold">{info.hostname}</span>
            </div>

            <div className="w-px h-3.5 bg-white/10" />

            <div className="flex items-center gap-2" title="RAM Capacity">
              <HardDrives weight="regular" className="w-3.5 h-3.5 text-sky-400" />
              <span>
                RAM <span className="text-slate-100 font-bold">{info.memFree}</span> free
              </span>
            </div>

            <div className="w-px h-3.5 bg-white/10" />

            <div className="flex items-center gap-2" title="CPU Cores & Load">
              <Cpu weight="regular" className="w-3.5 h-3.5 text-amber-400" />
              <span>
                CPU <span className="text-slate-100 font-bold">{info.cpuCount}c</span> ({info.loadAvg[0]})
              </span>
            </div>

            <div className="w-px h-3.5 bg-white/10" />

            <div className="flex items-center gap-2" title="Host Uptime">
              <Clock weight="regular" className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-slate-100 font-bold">{info.uptime}</span>
            </div>
          </div>
        )}

        {onRefresh && (
          <button
            onClick={onRefresh}
            disabled={isRefreshing}
            className="p-2.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] text-slate-300 hover:text-white border border-white/[0.08] transition-all cursor-pointer disabled:opacity-50 haptic-btn shadow-sm"
            title="Poll Telemetry"
          >
            <ArrowsClockwise weight="bold" className={`w-4 h-4 ${isRefreshing ? "animate-spin text-[#ff5500]" : ""}`} />
          </button>
        )}
      </div>
    </header>
  );
};
