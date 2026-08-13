"use client";

import React, { useState } from "react";
import { Header } from "@/components/Header";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { SystemHealth } from "@/components/SystemHealth";
import { useToast } from "@/components/ui/Toast";
import { useSystemInfo } from "@/hooks/useSystemInfo";
import { AuthApi } from "@/lib/api/auth";
import { KeyRound, Shield, Server, FileText } from "lucide-react";

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
        subtitle="Manage authentication security and view system configuration"
      />

      <main className="p-6 md:p-8 space-y-6 max-w-5xl w-full mx-auto">
        {/* Security / Password Card */}
        <Card
          title="Security & Password"
          subtitle="Update the master dashboard authentication password."
        >
          <form onSubmit={handleChangePassword} className="space-y-4 max-w-lg">
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
                <KeyRound className="w-4 h-4" /> Update Password
              </Button>
            </div>
          </form>
        </Card>

        {/* System Diagnostics */}
        <SystemHealth health={health} isLoading={isLoading} />

        {/* Server & Environment Paths */}
        {info && (
          <Card title="System Environment">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs font-mono">
              <div className="p-3 bg-[#0d0f16] border border-[#1e2330] rounded-lg">
                <span className="text-slate-400 block text-[11px] uppercase tracking-wider mb-1">Hostname</span>
                <span className="text-slate-200 font-semibold">{info.hostname}</span>
              </div>

              <div className="p-3 bg-[#0d0f16] border border-[#1e2330] rounded-lg">
                <span className="text-slate-400 block text-[11px] uppercase tracking-wider mb-1">Platform</span>
                <span className="text-slate-200 font-semibold">{info.platform}</span>
              </div>

              <div className="p-3 bg-[#0d0f16] border border-[#1e2330] rounded-lg">
                <span className="text-slate-400 block text-[11px] uppercase tracking-wider mb-1">CLI Path</span>
                <span className="text-slate-200 font-semibold">/usr/local/bin/fire</span>
              </div>

              <div className="p-3 bg-[#0d0f16] border border-[#1e2330] rounded-lg">
                <span className="text-slate-400 block text-[11px] uppercase tracking-wider mb-1">Systemd Directory</span>
                <span className="text-slate-200 font-semibold">/etc/systemd/system</span>
              </div>
            </div>
          </Card>
        )}
      </main>
    </div>
  );
}
