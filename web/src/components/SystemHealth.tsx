"use client";

import React from "react";
import { CheckCircle, AlertTriangle, XCircle, Activity } from "lucide-react";
import { SystemHealthResponse } from "@/lib/types";

export const SystemHealth: React.FC<{
  health?: SystemHealthResponse;
  isLoading?: boolean;
}> = ({ health, isLoading }) => {
  if (isLoading || !health) {
    return (
      <div className="bg-[#12151e] border border-[#202634] rounded-lg p-5 animate-pulse">
        <div className="h-5 bg-slate-800 rounded w-1/3 mb-4" />
        <div className="space-y-2">
          <div className="h-4 bg-slate-800 rounded w-full" />
          <div className="h-4 bg-slate-800 rounded w-5/6" />
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
    <div className="bg-[#12151e] border border-[#202634] rounded-lg p-5">
      <div className="flex items-center justify-between pb-3.5 mb-4 border-b border-[#1c2230]">
        <div className="flex items-center gap-2">
          <Activity className="w-5 h-5 text-[#ff5500]" />
          <h3 className="text-base font-semibold text-slate-100">System Doctor</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">Health Score:</span>
          <span className={`text-lg font-bold font-mono ${scoreColor}`}>
            {health.score}%
          </span>
        </div>
      </div>

      <div className="space-y-2.5">
        {health.checks.map((check, idx) => (
          <div
            key={idx}
            className="flex items-start gap-2.5 text-xs p-2 rounded bg-[#0e1017] border border-[#1b202c]"
          >
            {check.passed ? (
              <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
            ) : (
              <XCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
            )}
            <div className="flex-1">
              <span className="font-semibold text-slate-200">{check.name}: </span>
              <span className={check.passed ? "text-slate-400" : "text-rose-300"}>
                {check.message}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
