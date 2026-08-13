"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Flame, Lock, ArrowRight, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { AuthApi } from "@/lib/api/auth";

export default function LoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isChecking, setIsChecking] = useState(true);

  useEffect(() => {
    AuthApi.getMe()
      .then((res) => {
        if (!res.isConfigured) {
          router.replace("/setup");
        } else if (res.authenticated) {
          router.replace("/dashboard");
        }
      })
      .catch(() => {})
      .finally(() => setIsChecking(false));
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password) {
      setError("Please enter your password");
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      await AuthApi.login(password);
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message || "Invalid password");
    } finally {
      setIsLoading(false);
    }
  };

  if (isChecking) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#090b10]">
        <div className="w-8 h-8 rounded-full border-2 border-[#ff5500] border-t-transparent animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 bg-[#090b10] bg-[radial-gradient(ellipse_80%_80%_at_50%_-20%,rgba(255,85,0,0.15),rgba(255,255,255,0))]">
      <div className="w-full max-w-md p-8 bg-[#12151e]/90 border border-[#232a3b] rounded-2xl shadow-2xl backdrop-blur-xl">
        {/* Brand */}
        <div className="flex flex-col items-center text-center mb-8">
          <div className="p-3 rounded-xl bg-gradient-to-br from-[#ff5500] to-[#ff2200] text-white shadow-lg shadow-[#ff5500]/30 mb-3">
            <Flame className="w-8 h-8 fill-current" />
          </div>
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight">Fire PM</h1>
          <p className="text-xs text-slate-400 mt-1">Authenticate to access system processes</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <Input
            label="Master Password"
            type="password"
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
          />

          {error && (
            <div className="text-xs text-rose-400 bg-rose-950/40 p-3 rounded-lg border border-rose-900/60 flex items-center gap-2">
              <Lock className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <Button type="submit" variant="primary" className="w-full mt-2" isLoading={isLoading}>
            Sign In to Dashboard <ArrowRight className="w-4 h-4 ml-1" />
          </Button>
        </form>

        <div className="mt-8 pt-4 border-t border-[#1c2230] text-center flex items-center justify-center gap-1.5 text-xs text-slate-500 font-mono">
          <ShieldCheck className="w-4 h-4 text-emerald-500" />
          Local Linux root session protected
        </div>
      </div>
    </div>
  );
}
