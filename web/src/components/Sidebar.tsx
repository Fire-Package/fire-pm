"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Flame, LayoutDashboard, Layers, Network, Settings, LogOut, Terminal } from "lucide-react";
import { AuthApi } from "@/lib/api/auth";

export const Sidebar: React.FC = () => {
  const pathname = usePathname();

  const navItems = [
    { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
    { label: "Processes", href: "/processes", icon: Layers },
    { label: "Tunnels", href: "/tunnels", icon: Network },
    { label: "Settings", href: "/settings", icon: Settings },
  ];

  const handleLogout = async () => {
    try {
      await AuthApi.logout();
      window.location.href = "/login";
    } catch {
      window.location.href = "/login";
    }
  };

  return (
    <aside className="w-64 bg-[#0d0f17] border-r border-[#1e2433] flex flex-col h-screen shrink-0 select-none">
      {/* Brand header */}
      <div className="h-16 flex items-center px-6 border-b border-[#1c2230] gap-3">
        <div className="p-2 rounded-lg bg-gradient-to-br from-[#ff5500] to-[#ff2200] text-white shadow-md shadow-[#ff5500]/30">
          <Flame className="w-5 h-5 fill-current" />
        </div>
        <div>
          <div className="font-bold text-base tracking-tight text-white flex items-center gap-1.5">
            Fire PM <span className="text-[10px] font-mono font-medium px-1.5 py-0.5 rounded bg-[#ff5500]/20 text-[#ff5500] border border-[#ff5500]/30">v1.0</span>
          </div>
          <div className="text-[11px] text-slate-400 font-mono tracking-wide">Linux Process Manager</div>
        </div>
      </div>

      {/* Nav items */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        <div className="px-3 pb-2 text-[10px] font-bold uppercase tracking-wider text-slate-500">
          Overview & Manage
        </div>
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive =
            item.href === "/dashboard"
              ? pathname === "/dashboard"
              : pathname.startsWith(item.href);

          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-3.5 py-2.5 rounded-md text-sm font-medium transition-all ${
                isActive
                  ? "bg-[#ff5500]/15 text-[#ff5500] font-semibold border border-[#ff5500]/30 shadow-sm shadow-[#ff5500]/10"
                  : "text-slate-300 hover:text-slate-100 hover:bg-[#141824]"
              }`}
            >
              <Icon className={`w-4 h-4 ${isActive ? "text-[#ff5500]" : "text-slate-400"}`} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* System prompt / status bar */}
      <div className="p-3 border-t border-[#1c2230] space-y-2">
        <div className="p-2.5 rounded-md bg-[#12151e] border border-[#1e2433] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Terminal className="w-3.5 h-3.5 text-slate-400" />
            <span className="text-xs font-mono text-slate-300">systemd bridge</span>
          </div>
          <span className="w-2 h-2 rounded-full bg-emerald-400" title="Connected" />
        </div>

        <button
          onClick={handleLogout}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs font-medium text-slate-400 hover:text-rose-400 hover:bg-rose-950/20 rounded-md transition-colors cursor-pointer"
        >
          <LogOut className="w-3.5 h-3.5" />
          Sign Out
        </button>
      </div>
    </aside>
  );
};
