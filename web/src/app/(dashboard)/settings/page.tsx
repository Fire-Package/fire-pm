"use client";

import React, { useState } from "react";
import { Header } from "@/components/Header";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { SystemHealth } from "@/components/SystemHealth";
import { useToast } from "@/components/ui/Toast";
import { useSystemInfo } from "@/hooks/useSystemInfo";
import { AuthApi } from "@/lib/api/auth";
import { Key, ShieldCheck, HardDrives, TerminalWindow } from "@phosphor-icons/react";

export default function SettingsPage() {
  const { info, health, isLoading } = useSystemInfo();
  const { showToast } = useToast();

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isChangingPass, setIsChangingPass] = useState(false);

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentPassword || !newPassword) {
      showToast("All password fields are required", "error");
      return;
    }
    if (newPassword.length < 6) {
      showToast("New password must be at least 6 characters", "error");
      return;
    }
    if (newPassword !== confirmPassword) {
      showToast("New passwords do not match", "error");
      return;
    }

    setIsChangingPass(true);
    try {
      await AuthApi.changePassword(currentPassword, newPassword);
      showToast("Password updated successfully", "success");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err: any) {
      showToast(err.message || "Failed to change password", "error");
    } finally {
      setIsChangingPass(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <Header
        title="Settings & System Diagnostics"
        subtitle="Manage master authentication security and inspect runtime environment"
      />

      <main className="p-4 sm:p-6 md:p-8 space-y-5 max-w-5xl w-full mx-auto">
        {/* Security / Password Card */}
        <div className="telemetry-panel p-5 space-y-4">
          <div className="flex items-center gap-2.5 pb-3.5 border-b border-white/[0.05]">
            <div className="p-2 rounded-lg bg-[#ff5500]/10 border border-[#ff5500]/25 text-[#ff5500]">
              <Key weight="bold" className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-100 font-sans tracking-tight">Security & Master Password</h3>
              <p className="text-[10px] text-slate-400 font-mono">Update the root authentication credentials for web console access</p>
            </div>
          </div>

          <form onSubmit={handleChangePassword} className="space-y-3.5 max-w-lg">
            <Input
              label="Current Password"
              type="password"
              placeholder="••••••••"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
            />

            <Input
              label="New Master Password"
              type="password"
              placeholder="At least 6 characters"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />

            <Input
              label="Confirm New Password"
              type="password"
              placeholder="Repeat new master password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />

            <div className="pt-2">
              <Button type="submit" variant="primary" isLoading={isChangingPass}>
                <Key weight="bold" className="w-3.5 h-3.5" /> Update Password
              </Button>
            </div>
          </form>
        </div>

        {/* System Diagnostics */}
        <SystemHealth health={health} isLoading={isLoading} />

        {/* Server & Environment Paths */}
        {info && (
          <div className="telemetry-panel p-5">
            <div className="flex items-center gap-2.5 pb-3.5 mb-3.5 border-b border-white/[0.05]">
              <div className="p-2 rounded-lg bg-sky-500/10 border border-sky-500/20 text-sky-400">
                <TerminalWindow weight="bold" className="w-4 h-4" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-slate-100 font-sans tracking-tight">System Environment Paths</h3>
                <p className="text-[10px] text-slate-400 font-mono">Kernel host parameters & systemd directory bindings</p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs font-mono">
              <div className="p-3 bg-[#06080d] border border-white/[0.05] rounded-lg">
                <span className="text-slate-400 block text-[9px] uppercase tracking-wider mb-1 font-bold">Hostname</span>
                <span className="text-slate-200 font-semibold">{info.hostname}</span>
              </div>

              <div className="p-3 bg-[#06080d] border border-white/[0.05] rounded-lg">
                <span className="text-slate-400 block text-[9px] uppercase tracking-wider mb-1 font-bold">Platform / Architecture</span>
                <span className="text-slate-200 font-semibold">{info.platform}</span>
              </div>

              <div className="p-3 bg-[#06080d] border border-white/[0.05] rounded-lg">
                <span className="text-slate-400 block text-[9px] uppercase tracking-wider mb-1 font-bold">CLI Binary Path</span>
                <span className="text-slate-200 font-semibold">/usr/local/bin/fire</span>
              </div>

              <div className="p-3 bg-[#06080d] border border-white/[0.05] rounded-lg">
                <span className="text-slate-400 block text-[9px] uppercase tracking-wider mb-1 font-bold">Systemd Unit Directory</span>
                <span className="text-slate-200 font-semibold">/etc/systemd/system</span>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
