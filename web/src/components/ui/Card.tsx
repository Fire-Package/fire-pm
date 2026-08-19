import React from "react";

export const Card: React.FC<{
  children: React.ReactNode;
  className?: string;
  title?: string;
  subtitle?: string;
  action?: React.ReactNode;
}> = ({ children, className = "", title, subtitle, action }) => {
  return (
    <div className={`telemetry-panel p-5 ${className}`}>
      {(title || action) && (
        <div className="flex items-center justify-between pb-3.5 mb-4 border-b border-white/[0.05]">
          <div>
            {title && <h3 className="text-sm font-bold text-slate-100 tracking-tight font-sans">{title}</h3>}
            {subtitle && <p className="text-[10px] text-slate-400 font-mono mt-0.5">{subtitle}</p>}
          </div>
          {action && <div>{action}</div>}
        </div>
      )}
      {children}
    </div>
  );
};
