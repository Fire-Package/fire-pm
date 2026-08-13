import React from "react";

export const Card: React.FC<{
  children: React.ReactNode;
  className?: string;
  title?: string;
  subtitle?: string;
  action?: React.ReactNode;
}> = ({ children, className = "", title, subtitle, action }) => {
  return (
    <div className={`bg-[#12151e] border border-[#202634] rounded-lg p-5 shadow-sm ${className}`}>
      {(title || action) && (
        <div className="flex items-center justify-between pb-3.5 mb-4 border-b border-[#1c2230]">
          <div>
            {title && <h3 className="text-base font-semibold text-slate-100">{title}</h3>}
            {subtitle && <p className="text-xs text-slate-400 mt-0.5">{subtitle}</p>}
          </div>
          {action && <div>{action}</div>}
        </div>
      )}
      {children}
    </div>
  );
};
