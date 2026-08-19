"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Flame, ShieldWarning, ArrowRight, ShieldCheck } from "@phosphor-icons/react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { AuthApi } from "@/lib/api/auth";

export default function SetupPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirmPass, setConfirmPass] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isChecking, setIsChecking] = useState(true);

  useEffect(() => {
    AuthApi.getMe()
      .then((res) => {
        if (res.isConfigured) {
          router.replace("/login");
        }
      })
      .catch(() => {})
      .finally(() => setIsChecking(false));
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password || password.length < 6) {
      setError("Password must be at least 6 characters long.");
      return;
    }
    if (password !== confirmPass) {
      setError("Passwords do not match.");
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      await AuthApi.setup(password);
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message || "Failed to complete setup");
    } finally {
      setIsLoading(false);
    }
  };

  if (isChecking) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#06080d]">
        <div className="w-8 h-8 rounded-full border-2 border-[#ff5500] border-t-transparent animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 bg-[#06080d] select-none">
      <div className="w-full max-w-md p-7 bg-[#0a0d14]/90 border border-white/[0.08] rounded-2xl shadow-2xl backdrop-blur-xl">
        <div className="flex flex-col items-center text-center mb-6">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-[#ff5500] via-[#ff3b00] to-[#d62800] text-white shadow-lg shadow-[#ff5500]/30 ring-1 ring-white/20 flex items-center justify-center mb-3.5">
            <Flame weight="fill" className="w-6 h-6 drop-shadow-sm" />
          </div>
          <h1 className="text-xl font-bold text-slate-100 tracking-tight font-sans">Initial Security Setup</h1>
          <p className="text-[11px] text-slate-400 mt-1 font-mono">
            Create a master password for Fire PM Web Dashboard
          </p>
        </div>

        <div className="mb-5 p-3 rounded-lg bg-amber-950/30 border border-amber-800/40 text-amber-300 text-xs flex items-start gap-2.5 font-mono">
          <ShieldWarning weight="bold" className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <span>
            This master password encrypts your session and authorizes system process operations.
          </span>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <Input
            label="Master Password"
            type="password"
            placeholder="At least 6 characters"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
          />

          <Input
            label="Confirm Password"
            type="password"
            placeholder="Repeat master password"
            value={confirmPass}
            onChange={(e) => setConfirmPass(e.target.value)}
          />

          {error && (
            <div className="text-xs text-rose-400 bg-rose-950/40 p-3 rounded-lg border border-rose-900/60 font-mono">
              {error}
            </div>
          )}

          <Button type="submit" variant="primary" className="w-full mt-2" isLoading={isLoading}>
            Set Password & Access Dashboard <ArrowRight weight="bold" className="w-4 h-4 ml-1" />
          </Button>
        </form>

        <div className="mt-7 pt-4 border-t border-white/[0.05] text-center flex items-center justify-center gap-1.5 text-[11px] text-slate-500 font-mono">
          <ShieldCheck weight="fill" className="w-4 h-4 text-emerald-500" />
          Encrypted with bcrypt (cost factor 12)
        </div>
      </div>
    </div>
  );
}
