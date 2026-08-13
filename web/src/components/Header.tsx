"use client";

import React from "react";
import { Cpu, HardDrive, Clock, Server, RotateCw } from "lucide-react";
import { useSystemInfo } from "@/hooks/useSystemInfo";

export const Header: React.FC<{
  title: string;
  subtitle?: string;
  onRefresh?: () => void;
  isRefreshing?: boolean;
}> = ({ title, subtitle, onRefresh, isRefreshing }) => {
  const { info } = useSystemInfo();

  return (
    <header className="h-16 px-8 bg-[#0d0f17]/80 backdrop-blur-md border-b border-[#1c2230] flex items-center justify-between sticky top-0 z-30">
      <div>
        <h1 className="text-lg font-bold text-slate-100 tracking-tight flex items-center gap-2">
          {title}
        </h1>
        {subtitle && <p className="text-xs text-slate-400 font-medium">{subtitle}</p>}
      </div>

      <div className="flex items-center gap-4">
        {info && (
          <div className="hidden lg:flex items-center gap-4 text-xs font-mono text-slate-400 bg-[#12151e] border border-[#202634] px-3 py-1.5 rounded-lg">
            <div className="flex items-center gap-1.5" title="Hostname">
              <Server className="w-3.5 h-3.5 text-[#ff5500]" />
              <span className="text-slate-200 font-semibold">{info.hostname}</span>
            </div>

            <div className="w-px h-3.5 bg-slate-700" />

            <div className="flex items-center gap-1.5" title="Memory usage">
              <HardDrive className="w-3.5 h-3.5 text-sky-400" />
              <span>
                RAM <span className="text-slate-200 font-semibold">{info.memFree}</span> free
              </span>
            </div>

            <div className="w-px h-3.5 bg-slate-700" />

            <div className="flex items-center gap-1.5" title="CPU count and Load">
              <Cpu className="w-3.5 h-3.5 text-amber-400" />
              <span>
                CPU <span className="text-slate-200 font-semibold">{info.cpuCount}x</span> ({info.loadAvg[0]})
              </span>
            </div>

            <div className="w-px h-3.5 bg-slate-700" />

            <div className="flex items-center gap-1.5" title="System uptime">
              <Clock className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-slate-200 font-semibold">{info.uptime}</span>
            </div>
          </div>
        )}

        {onRefresh && (
          <button
            onClick={onRefresh}
            disabled={isRefreshing}
            className="p-2 rounded-md bg-[#161a26] hover:bg-[#202638] text-slate-300 hover:text-white border border-[#283145] transition-colors cursor-pointer disabled:opacity-50"
            title="Refresh data"
          >
            <RotateCw className={`w-4 h-4 ${isRefreshing ? "animate-spin text-[#ff5500]" : ""}`} />
          </button>
        )}
      </div>
    </header>
  );
};
