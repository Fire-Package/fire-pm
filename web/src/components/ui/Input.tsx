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
    <div className="flex flex-col gap-1.5 w-full font-mono text-xs">
      {label && (
        <label htmlFor={inputId} className="text-[10px] font-bold uppercase tracking-wider text-slate-300">
          {label}
        </label>
      )}
      <input
        id={inputId}
        className={`w-full bg-[#06080d] border ${
          error ? "border-rose-500/80 focus:border-rose-500" : "border-white/[0.08] focus:border-[#ff5500]"
        } rounded-lg px-3 py-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none transition-colors ${className}`}
        {...props}
      />
      {error && <span className="text-[11px] text-rose-400 mt-0.5">{error}</span>}
      {helperText && !error && <span className="text-[10px] text-slate-500 mt-0.5">{helperText}</span>}
    </div>
  );
};
