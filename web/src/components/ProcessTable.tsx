"use client";

import React, { useState, useMemo } from "react";
import { 
  MagnifyingGlass, 
  CaretUpDown, 
  CaretUp, 
  CaretDown, 
  Stack, 
  CheckCircle, 
  XCircle 
} from "@phosphor-icons/react";
import { ProcessItem } from "@/lib/types";
import { ProcessRow } from "./ProcessRow";

export interface ProcessTableProps {
  processes: ProcessItem[];
  isLoading: boolean;
  onRefresh: () => void;
}

type SortKey = "name" | "status" | "port" | "mem" | "cpu" | "uptime" | "restarts";

export const ProcessTable: React.FC<ProcessTableProps> = ({
  processes,
  isLoading,
  onRefresh,
}) => {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "online" | "stopped">("all");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortAsc, setSortAsc] = useState(true);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(true);
    }
  };

  const filteredAndSorted = useMemo(() => {
    return processes
      .filter((p) => {
        // Status filter
        if (statusFilter === "online" && p.status !== "online" && p.status !== "active") {
          return false;
        }
        if (statusFilter === "stopped" && (p.status === "online" || p.status === "active")) {
          return false;
        }

        // Search query
        if (search.trim()) {
          const q = search.toLowerCase();
          return (
            p.name.toLowerCase().includes(q) ||
            p.port.includes(q) ||
            (p.pid && p.pid.toString().includes(q))
          );
        }
        return true;
      })
      .sort((a, b) => {
        let valA: any = a[sortKey];
        let valB: any = b[sortKey];

        if (sortKey === "restarts") {
          valA = Number(valA) || 0;
          valB = Number(valB) || 0;
        } else if (sortKey === "mem") {
          valA = parseFloat(a.mem.replace("MB", "")) || 0;
          valB = parseFloat(b.mem.replace("MB", "")) || 0;
        } else if (sortKey === "cpu") {
          valA = parseFloat(a.cpu.replace("%", "")) || 0;
          valB = parseFloat(b.cpu.replace("%", "")) || 0;
        } else {
          valA = String(valA).toLowerCase();
          valB = String(valB).toLowerCase();
        }

        if (valA < valB) return sortAsc ? -1 : 1;
        if (valA > valB) return sortAsc ? 1 : -1;
        return 0;
      });
  }, [processes, search, statusFilter, sortKey, sortAsc]);

  const renderSortIcon = (key: SortKey) => {
    if (sortKey !== key) {
      return <CaretUpDown className="w-3.5 h-3.5 opacity-30 group-hover:opacity-100 transition-opacity" />;
    }
    return sortAsc ? (
      <CaretUp weight="bold" className="w-3.5 h-3.5 text-[#ff5500]" />
    ) : (
      <CaretDown weight="bold" className="w-3.5 h-3.5 text-[#ff5500]" />
    );
  };

  const totalCount = processes.length;
  const onlineCount = processes.filter((p) => p.status === "online" || p.status === "active").length;
  const stoppedCount = totalCount - onlineCount;

  return (
    <div className="double-bezel">
      <div className="double-bezel-inner overflow-hidden flex flex-col">
        {/* Table Toolbar */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 p-3 bg-white/[0.015] border-b border-white/[0.05]">
          {/* Status filters */}
          <div className="flex items-center gap-1 bg-[#06070b] p-1 rounded-xl border border-white/[0.05]">
            <button
              onClick={() => setStatusFilter("all")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer haptic-btn ${
                statusFilter === "all"
                  ? "bg-[#ff5500] text-white shadow-sm shadow-[#ff5500]/30"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Stack weight="bold" className="w-3.5 h-3.5" />
              All ({totalCount})
            </button>
            <button
              onClick={() => setStatusFilter("online")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer haptic-btn ${
                statusFilter === "online"
                  ? "bg-emerald-600 text-white shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <CheckCircle weight="fill" className="w-3.5 h-3.5 text-emerald-200" />
              Online ({onlineCount})
            </button>
            <button
              onClick={() => setStatusFilter("stopped")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer haptic-btn ${
                statusFilter === "stopped"
                  ? "bg-slate-700 text-white shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <XCircle weight="fill" className="w-3.5 h-3.5 text-slate-400" />
              Stopped ({stoppedCount})
            </button>
          </div>

          {/* Search input */}
          <div className="relative max-w-xs w-full">
            <MagnifyingGlass weight="bold" className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search apps, ports, PID..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-[#06070b] border border-white/[0.06] rounded-xl text-xs pl-9 pr-3 py-1.5 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-[#ff5500]/70 transition-colors font-mono"
            />
          </div>
        </div>

        {/* Main Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-white/[0.04] bg-white/[0.01] text-[10px] font-mono font-bold uppercase tracking-[0.15em] text-slate-400 select-none">
                <th
                  onClick={() => handleSort("name")}
                  className="py-3 px-4 group cursor-pointer hover:text-slate-200 transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    Daemon App {renderSortIcon("name")}
                  </div>
                </th>
                <th
                  onClick={() => handleSort("status")}
                  className="py-3 px-4 group cursor-pointer hover:text-slate-200 transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    State {renderSortIcon("status")}
                  </div>
                </th>
                <th
                  onClick={() => handleSort("port")}
                  className="py-3 px-4 group cursor-pointer hover:text-slate-200 transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    Port {renderSortIcon("port")}
                  </div>
                </th>
                <th
                  onClick={() => handleSort("mem")}
                  className="py-3 px-4 group cursor-pointer hover:text-slate-200 transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    Memory {renderSortIcon("mem")}
                  </div>
                </th>
                <th
                  onClick={() => handleSort("cpu")}
                  className="py-3 px-4 group cursor-pointer hover:text-slate-200 transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    CPU {renderSortIcon("cpu")}
                  </div>
                </th>
                <th
                  onClick={() => handleSort("uptime")}
                  className="py-3 px-4 group cursor-pointer hover:text-slate-200 transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    Uptime {renderSortIcon("uptime")}
                  </div>
                </th>
                <th
                  onClick={() => handleSort("restarts")}
                  className="py-3 px-4 group cursor-pointer hover:text-slate-200 transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    Restarts {renderSortIcon("restarts")}
                  </div>
                </th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && processes.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-14 text-center text-slate-500 font-mono text-xs">
                    Introspecting systemd process tables...
                  </td>
                </tr>
              ) : filteredAndSorted.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-14 text-center text-slate-500 font-mono text-xs">
                    {search ? `No daemons match "${search}"` : "No active processes managed by Fire PM."}
                  </td>
                </tr>
              ) : (
                filteredAndSorted.map((proc) => (
                  <ProcessRow key={proc.name} process={proc} onRefresh={onRefresh} />
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
