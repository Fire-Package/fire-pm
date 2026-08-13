"use client";

import React, { useState, useMemo } from "react";
import { Search, ArrowUpDown, ArrowUp, ArrowDown, Layers, CheckCircle2, XCircle } from "lucide-react";
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
      return <ArrowUpDown className="w-3.5 h-3.5 opacity-40 group-hover:opacity-100" />;
    }
    return sortAsc ? (
      <ArrowUp className="w-3.5 h-3.5 text-[#ff5500]" />
    ) : (
      <ArrowDown className="w-3.5 h-3.5 text-[#ff5500]" />
    );
  };

  const totalCount = processes.length;
  const onlineCount = processes.filter((p) => p.status === "online" || p.status === "active").length;
  const stoppedCount = totalCount - onlineCount;

  return (
    <div className="bg-[#12151e] border border-[#202634] rounded-lg overflow-hidden flex flex-col shadow-sm">
      {/* Table Toolbar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4 p-4 bg-[#141824] border-b border-[#1c2230]">
        {/* Status filters */}
        <div className="flex items-center gap-1 bg-[#0c0e15] p-1 rounded-lg border border-[#232a3d]">
          <button
            onClick={() => setStatusFilter("all")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-all cursor-pointer ${
              statusFilter === "all"
                ? "bg-[#ff5500] text-white shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            All ({totalCount})
          </button>
          <button
            onClick={() => setStatusFilter("online")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-all cursor-pointer ${
              statusFilter === "online"
                ? "bg-emerald-600 text-white shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-300" />
            Online ({onlineCount})
          </button>
          <button
            onClick={() => setStatusFilter("stopped")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-all cursor-pointer ${
              statusFilter === "stopped"
                ? "bg-slate-700 text-white shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <XCircle className="w-3.5 h-3.5 text-slate-400" />
            Stopped ({stoppedCount})
          </button>
        </div>

        {/* Search input */}
        <div className="relative max-w-xs w-full">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search processes..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-[#0c0e15] border border-[#232a3d] rounded-lg text-xs pl-9 pr-3 py-2 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-[#ff5500] transition-colors"
          />
        </div>
      </div>

      {/* Main Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-[#1c2230] bg-[#0f121a] text-xs font-semibold uppercase tracking-wider text-slate-400 select-none">
              <th
                onClick={() => handleSort("name")}
                className="py-3 px-4 group cursor-pointer hover:text-slate-200 transition-colors"
              >
                <div className="flex items-center gap-1.5">
                  App Name {renderSortIcon("name")}
                </div>
              </th>
              <th
                onClick={() => handleSort("status")}
                className="py-3 px-4 group cursor-pointer hover:text-slate-200 transition-colors"
              >
                <div className="flex items-center gap-1.5">
                  Status {renderSortIcon("status")}
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
                <td colSpan={8} className="py-12 text-center text-slate-500 font-mono text-xs">
                  Loading process data from systemd...
                </td>
              </tr>
            ) : filteredAndSorted.length === 0 ? (
              <tr>
                <td colSpan={8} className="py-12 text-center text-slate-500 font-mono text-xs">
                  {search ? `No processes match "${search}"` : "No processes managed by Fire PM."}
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
  );
};
