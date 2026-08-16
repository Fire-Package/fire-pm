import React from "react";

export interface StatusBadgeProps {
  status: "online" | "stopped" | "errored" | "active" | string;
  size?: "sm" | "md";
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, size = "md" }) => {
  const normalized = status.toLowerCase();
  const isOnline = normalized === "online" || normalized === "active";
  const isErrored = normalized === "errored" || normalized === "failed";

  const sizeClasses = size === "sm" ? "text-[10px] py-0.5 px-2" : "text-xs py-1 px-2.5";
  const dotSize = size === "sm" ? "w-1.5 h-1.5" : "w-2 h-2";

  if (isOnline) {
    return (
      <span
        className={`inline-flex items-center gap-1.5 rounded-full font-semibold font-mono bg-emerald-950/60 border border-emerald-500/30 text-emerald-400 shadow-sm shadow-emerald-950/40 ${sizeClasses}`}
      >
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
          <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
        </span>
        online
      </span>
    );
  }

  if (isErrored) {
    return (
      <span
        className={`inline-flex items-center gap-1.5 rounded-full font-semibold font-mono bg-rose-950/60 border border-rose-500/30 text-rose-400 shadow-sm shadow-rose-950/40 ${sizeClasses}`}
      >
        <span className={`${dotSize} rounded-full bg-rose-500`} />
        errored
      </span>
    );
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-medium font-mono bg-[#141824] border border-[#262f44] text-slate-400 ${sizeClasses}`}
    >
      <span className={`${dotSize} rounded-full bg-slate-500`} />
      {normalized}
    </span>
  );
};
