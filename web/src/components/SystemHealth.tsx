"use client";

import React from "react";
import { 
  CheckCircle, 
  XCircle, 
  Pulse, 
  ShieldCheck 
} from "@phosphor-icons/react";
import { SystemHealthResponse } from "@/lib/types";

export const SystemHealth: React.FC<{
  health?: SystemHealthResponse;
  isLoading?: boolean;
}> = ({ health, isLoading }) => {
  if (isLoading || !health) {
    return (
      <div className="double-bezel animate-pulse">
        <div className="double-bezel-inner p-5 space-y-3">
          <div className="h-5 bg-white/[0.05] rounded-lg w-1/3 mb-4" />
          <div className="h-4 bg-white/[0.05] rounded-lg w-full" />
          <div className="h-4 bg-white/[0.05] rounded-lg w-5/6" />
        </div>
      </div>
    );
  }

  const scoreColor =
    health.score >= 80
      ? "text-emerald-400"
      : health.score >= 50
      ? "text-amber-400"
      : "text-rose-400";

  return (
    <div className="double-bezel">
      <div className="double-bezel-inner p-5">
        <div className="flex items-center justify-between pb-4 mb-4 border-b border-white/[0.05]">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-[#ff5500]/10 border border-[#ff5500]/25 text-[#ff5500]">
              <Pulse weight="bold" className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-100 font-sans tracking-tight">System Doctor Diagnostics</h3>
              <p className="text-[11px] text-slate-400 font-mono">Real-time health audits & daemon integrity</p>
            </div>
          </div>
          <div className="flex items-center gap-2 bg-[#06070b] px-3.5 py-1.5 rounded-xl border border-white/[0.06] shadow-inner">
            <span className="text-[10px] font-mono text-slate-400 uppercase tracking-wider">Score:</span>
            <span className={`text-base font-bold font-mono ${scoreColor}`}>
              {health.score}%
            </span>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
          {health.checks.map((check, idx) => (
            <div
              key={idx}
              className="flex items-start gap-2.5 text-xs p-3 rounded-xl bg-white/[0.02] border border-white/[0.04] hover:border-white/[0.08] transition-colors"
            >
              {check.passed ? (
                <CheckCircle weight="fill" className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
              ) : (
                <XCircle weight="fill" className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
              )}
              <div className="flex-1 min-w-0 font-mono">
                <div className="font-bold text-slate-200 truncate">{check.name}</div>
                <div className={`text-[10px] leading-relaxed mt-0.5 ${check.passed ? "text-slate-400" : "text-rose-300 font-semibold"}`}>
                  {check.message}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
