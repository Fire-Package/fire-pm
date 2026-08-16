"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { 
  Flame, 
  SquaresFour, 
  Stack, 
  Plugs, 
  Gear, 
  SignOut, 
  TerminalWindow, 
  Pulse,
  Cpu
} from "@phosphor-icons/react";
import { AuthApi } from "@/lib/api/auth";

export const Sidebar: React.FC = () => {
  const pathname = usePathname();

  const navItems = [
    { label: "Dashboard", href: "/dashboard", icon: SquaresFour },
    { label: "Processes", href: "/processes", icon: Stack },
    { label: "Tunnels", href: "/tunnels", icon: Plugs },
    { label: "Settings", href: "/settings", icon: Gear },
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
    <aside className="w-64 bg-[#06070b]/95 backdrop-blur-2xl border-r border-white/[0.06] flex flex-col h-screen shrink-0 select-none z-20">
      {/* Brand header */}
      <div className="h-18 flex items-center px-5 border-b border-white/[0.05] gap-3">
        {/* Double-bezel logo mark */}
        <div className="p-1 rounded-2xl bg-white/[0.04] border border-white/[0.08] shadow-inner">
          <div className="w-9 h-9 rounded-[calc(1rem-0.25rem)] bg-gradient-to-br from-[#ff5500] via-[#ff3b00] to-[#d62800] flex items-center justify-center text-white shadow-md shadow-[#ff5500]/30 ring-1 ring-white/20">
            <Flame weight="fill" className="w-5 h-5 drop-shadow-sm" />
          </div>
        </div>
        <div>
          <div className="font-bold text-sm tracking-tight text-white flex items-center gap-1.5 font-sans">
            Fire PM <span className="text-[9px] font-mono font-bold px-1.5 py-0.5 rounded-full bg-[#ff5500]/15 text-[#ff5500] border border-[#ff5500]/30">PRO</span>
          </div>
          <div className="text-[10px] text-slate-400 font-mono tracking-wider uppercase">Linux Telemetry</div>
        </div>
      </div>

      {/* Nav items */}
      <nav className="flex-1 px-3 py-5 space-y-1.5 overflow-y-auto">
        <div className="px-3 pb-2 text-[9px] font-mono font-bold uppercase tracking-[0.2em] text-slate-500 flex items-center justify-between">
          <span>Systems & Engine</span>
          <Cpu weight="light" className="w-3.5 h-3.5 text-slate-600" />
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
              className={`group flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold tracking-tight transition-all duration-200 haptic-btn ${
                isActive
                  ? "bg-gradient-to-r from-[#ff5500]/15 to-transparent text-white border border-[#ff5500]/30 shadow-sm shadow-[#ff5500]/10 font-bold"
                  : "text-slate-400 hover:text-slate-100 hover:bg-white/[0.03]"
              }`}
            >
              <Icon 
                weight={isActive ? "fill" : "regular"} 
                className={`w-4.5 h-4.5 transition-colors ${isActive ? "text-[#ff5500]" : "text-slate-400 group-hover:text-slate-200"}`} 
              />
              <span className="flex-1">{item.label}</span>
              {isActive && (
                <div className="w-1.5 h-1.5 rounded-full bg-[#ff5500] shadow-sm shadow-[#ff5500]" />
              )}
            </Link>
          );
        })}
      </nav>

      {/* System prompt / status bar */}
      <div className="p-3.5 border-t border-white/[0.05] space-y-2">
        <div className="double-bezel">
          <div className="double-bezel-inner p-2.5 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <TerminalWindow weight="light" className="w-4 h-4 text-slate-400" />
              <span className="text-[11px] font-mono text-slate-300">systemd</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
              </span>
              <span className="text-[10px] font-mono text-emerald-400 font-bold">READY</span>
            </div>
          </div>
        </div>

        <button
          onClick={handleLogout}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs font-semibold text-slate-400 hover:text-rose-400 hover:bg-rose-950/20 rounded-xl transition-colors cursor-pointer haptic-btn"
        >
          <SignOut weight="bold" className="w-3.5 h-3.5" />
          Disconnect
        </button>
      </div>
    </aside>
  );
};
