import React from "react";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  helperText?: string;
}

export const Input: React.FC<InputProps> = ({
  label,
  error,
  helperText,
  className = "",
  id,
  ...props
}) => {
  const inputId = id || (label ? label.toLowerCase().replace(/\s+/g, "-") : undefined);

  return (
    <div className="flex flex-col gap-1.5 w-full">
      {label && (
        <label htmlFor={inputId} className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          {label}
        </label>
      )}
      <input
        id={inputId}
        className={`w-full bg-[#12151e] border ${
          error ? "border-rose-500/80 focus:border-rose-500" : "border-[#252c3d] focus:border-[#ff5500]"
        } rounded-md px-3.5 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-[#ff5500]/50 transition-colors ${className}`}
        {...props}
      />
      {error && <span className="text-xs text-rose-400 mt-0.5">{error}</span>}
      {helperText && !error && <span className="text-xs text-slate-500 mt-0.5">{helperText}</span>}
    </div>
  );
};
