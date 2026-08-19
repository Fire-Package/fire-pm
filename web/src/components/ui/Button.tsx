import React from "react";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "danger" | "ghost" | "outline";
  size?: "sm" | "md" | "lg";
  isLoading?: boolean;
}

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = "primary",
  size = "md",
  isLoading = false,
  className = "",
  disabled,
  ...props
}) => {
  const baseStyles =
    "inline-flex items-center justify-center font-semibold rounded-lg transition-all duration-150 focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed select-none cursor-pointer tactile-btn";

  const sizeStyles = {
    sm: "px-2.5 py-1 text-xs gap-1.5",
    md: "px-3.5 py-1.5 text-xs gap-2",
    lg: "px-4.5 py-2.5 text-sm gap-2.5",
  };

  const variantStyles = {
    primary:
      "bg-[#ff5500] hover:bg-[#ff681a] text-white shadow-sm shadow-[#ff5500]/25 focus:ring-1 focus:ring-[#ff5500] border border-transparent",
    secondary:
      "bg-[#0a0d14] hover:bg-[#121622] text-slate-200 border border-white/[0.08] hover:border-white/[0.15] shadow-sm",
    danger:
      "bg-rose-600/90 hover:bg-rose-600 text-white shadow-sm shadow-rose-600/25 border border-transparent",
    ghost:
      "bg-transparent hover:bg-white/[0.04] text-slate-400 hover:text-white",
    outline:
      "bg-transparent hover:bg-white/[0.04] text-slate-300 border border-white/[0.08] hover:border-white/[0.15]",
  };

  return (
    <button
      className={`${baseStyles} ${sizeStyles[size]} ${variantStyles[variant]} ${className}`}
      disabled={disabled || isLoading}
      {...props}
    >
      {isLoading && (
        <svg
          className="animate-spin -ml-1 mr-1.5 h-3.5 w-3.5 text-current"
          fill="none"
          viewBox="0 0 24 24"
        >
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
      )}
      {children}
    </button>
  );
};
