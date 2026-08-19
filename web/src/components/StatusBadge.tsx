import React from "react";

export interface StatusBadgeProps {
  status: "online" | "stopped" | "errored" | "active" | "reloading" | "failed" | string;
  size?: "sm" | "md";
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, size = "md" }) => {
  const normalized = (status || "unknown").toLowerCase();
  const isOnline = normalized === "online" || normalized === "active" || normalized === "running";
  const isErrored = normalized === "errored" || normalized === "failed" || normalized === "error";
  const isReloading = normalized === "reloading" || normalized === "activating" || normalized === "restarting";

  const sizeClasses = size === "sm" ? "text-[10px] py-0.5 px-2 font-mono" : "text-xs py-1 px-2.5 font-mono";
  const dotSize = size === "sm" ? "w-1.5 h-1.5" : "w-2 h-2";

  if (isOnline) {
    return (
      <span
        className={`inline-flex items-center gap-1.5 rounded-full font-semibold bg-emerald-950/50 border border-emerald-500/30 text-emerald-400 shadow-sm ${sizeClasses}`}
      >
        <span className="relative flex h-1.5 w-1.5">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
          <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-400"></span>
        </span>
        online
      </span>
    );
  }

  if (isReloading) {
    return (
      <span
        className={`inline-flex items-center gap-1.5 rounded-full font-semibold bg-amber-950/50 border border-amber-500/30 text-amber-400 shadow-sm ${sizeClasses}`}
      >
        <span className="relative flex h-1.5 w-1.5">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
          <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-amber-400"></span>
        </span>
        {normalized}
      </span>
    );
  }

  if (isErrored) {
    return (
      <span
        className={`inline-flex items-center gap-1.5 rounded-full font-semibold bg-rose-950/50 border border-rose-500/30 text-rose-400 shadow-sm ${sizeClasses}`}
      >
        <span className={`${dotSize} rounded-full bg-rose-500`} />
        errored
      </span>
    );
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-medium bg-[#0e121a] border border-white/[0.08] text-slate-400 ${sizeClasses}`}
    >
      <span className={`${dotSize} rounded-full bg-slate-500`} />
      {normalized}
    </span>
  );
};
