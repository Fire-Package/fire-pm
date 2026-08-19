import React from "react";
import { Button } from "./ui/Button";
import { Warning, X } from "@phosphor-icons/react";

export interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: "danger" | "primary";
  isLoading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  isOpen,
  title,
  message,
  confirmText = "Confirm",
  cancelText = "Cancel",
  variant = "danger",
  isLoading = false,
  onConfirm,
  onCancel,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md animate-in fade-in select-none">
      <div className="telemetry-panel max-w-md w-full p-6 shadow-2xl animate-in zoom-in-95 border-white/[0.1]">
        <div className="flex items-start justify-between mb-4 pb-3 border-b border-white/[0.05]">
          <div className="flex items-center gap-2.5">
            <div
              className={`p-2 rounded-lg ${
                variant === "danger"
                  ? "bg-rose-950/80 text-rose-400 border border-rose-800/60"
                  : "bg-amber-950/80 text-amber-400 border border-amber-800/60"
              }`}
            >
              <Warning weight="bold" className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-bold text-slate-100 font-sans tracking-tight">{title}</h3>
          </div>
          <button
            onClick={onCancel}
            className="text-slate-400 hover:text-slate-200 transition-colors p-1 cursor-pointer tactile-btn"
          >
            <X weight="bold" className="w-4 h-4" />
          </button>
        </div>

        <p className="text-xs text-slate-300 mb-5 leading-relaxed font-mono">{message}</p>

        <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-white/[0.05]">
          <Button variant="secondary" onClick={onCancel} disabled={isLoading}>
            {cancelText}
          </Button>
          <Button
            variant={variant === "danger" ? "danger" : "primary"}
            onClick={onConfirm}
            isLoading={isLoading}
          >
            {confirmText}
          </Button>
        </div>
      </div>
    </div>
  );
};
