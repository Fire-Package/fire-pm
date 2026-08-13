import React from "react";

export interface StatusBadgeProps {
  status: "online" | "stopped" | "errored" | "active" | string;
  size?: "sm" | "md";
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, size = "md" }) => {
  const normalized = status.toLowerCase();
  const isOnline = normalized === "online" || normalized === "active";
  const isErrored = normalized === "errored" || normalized === "failed";

  const sizeClasses = size === "sm" ? "text-xs py-0.5 px-2" : "text-xs py-1 px-2.5";
  const dotSize = size === "sm" ? "w-1.5 h-1.5" : "w-2 h-2";

  if (isOnline) {
    return (
      <span
        className={`inline-flex items-center gap-1.5 rounded-full font-medium bg-emerald-950/70 border border-emerald-800/60 text-emerald-400 ${sizeClasses}`}
      >
        <span className={`${dotSize} rounded-full bg-emerald-400 animate-pulse`} />
        online
      </span>
    );
  }

  if (isErrored) {
    return (
      <span
        className={`inline-flex items-center gap-1.5 rounded-full font-medium bg-rose-950/70 border border-rose-800/60 text-rose-400 ${sizeClasses}`}
      >
        <span className={`${dotSize} rounded-full bg-rose-500`} />
        errored
      </span>
    );
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-medium bg-slate-900 border border-slate-700 text-slate-400 ${sizeClasses}`}
    >
      <span className={`${dotSize} rounded-full bg-slate-500`} />
      {normalized}
    </span>
  );
};
