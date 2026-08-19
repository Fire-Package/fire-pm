"use client";

import React, { useState, useMemo } from "react";
import { 
  MagnifyingGlass, 
  CaretUpDown, 
  CaretUp, 
  CaretDown, 
  Stack, 
  CheckCircle, 
  XCircle,
  Table,
  SquaresFour,
  Warning
} from "@phosphor-icons/react";
import { ProcessItem } from "@/lib/types";
import { ProcessRow } from "./ProcessRow";
import { ProcessCard } from "./ProcessCard";

export interface ProcessTableProps {
  processes: ProcessItem[];
  isLoading: boolean;
  onRefresh: () => void;
  onNewProcess?: () => void;
}

type SortKey = "name" | "status" | "port" | "mem" | "cpu" | "uptime" | "restarts";

export const ProcessTable: React.FC<ProcessTableProps> = ({
  processes,
  isLoading,
  onRefresh,
  onNewProcess,
}) => {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "online" | "stopped" | "errored">("all");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortAsc, setSortAsc] = useState(true);
  const [viewMode, setViewMode] = useState<"table" | "grid">("table");

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
        if (statusFilter === "stopped" && (p.status === "online" || p.status === "active" || p.status === "errored" || p.status === "failed")) {
          return false;
        }
        if (statusFilter === "errored" && p.status !== "errored" && p.status !== "failed") {
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
  const erroredCount = processes.filter((p) => p.status === "errored" || p.status === "failed").length;
  const stoppedCount = totalCount - onlineCount - erroredCount;

  return (
    <div className="telemetry-panel overflow-hidden flex flex-col">
      {/* Table Toolbar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 p-3 bg-white/[0.015] border-b border-white/[0.05]">
        {/* Status filters */}
        <div className="flex items-center gap-1 bg-[#06080d] p-1 rounded-lg border border-white/[0.06] overflow-x-auto">
          <button
            onClick={() => setStatusFilter("all")}
            className={`flex items-center gap-1.5 px-2.5 py-1.2 rounded-md text-xs font-semibold transition-all cursor-pointer tactile-btn whitespace-nowrap ${
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
            className={`flex items-center gap-1.5 px-2.5 py-1.2 rounded-md text-xs font-semibold transition-all cursor-pointer tactile-btn whitespace-nowrap ${
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
            className={`flex items-center gap-1.5 px-2.5 py-1.2 rounded-md text-xs font-semibold transition-all cursor-pointer tactile-btn whitespace-nowrap ${
              statusFilter === "stopped"
                ? "bg-slate-700 text-white shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <XCircle weight="fill" className="w-3.5 h-3.5 text-slate-400" />
            Stopped ({stoppedCount})
          </button>
          {erroredCount > 0 && (
            <button
              onClick={() => setStatusFilter("errored")}
              className={`flex items-center gap-1.5 px-2.5 py-1.2 rounded-md text-xs font-semibold transition-all cursor-pointer tactile-btn whitespace-nowrap ${
                statusFilter === "errored"
                  ? "bg-rose-600 text-white shadow-sm"
                  : "text-rose-400 hover:text-rose-300"
              }`}
            >
              <Warning weight="fill" className="w-3.5 h-3.5 text-rose-200" />
              Failed ({erroredCount})
            </button>
          )}
        </div>

        {/* Search & View Mode Switcher */}
        <div className="flex items-center gap-2">
          <div className="relative flex-1 sm:w-64">
            <MagnifyingGlass weight="bold" className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Filter processes, PID, port..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-[#06080d] border border-white/[0.06] rounded-lg text-xs pl-8 pr-3 py-1.5 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-[#ff5500]/70 transition-colors font-mono"
            />
          </div>

          <div className="flex items-center bg-[#06080d] p-0.5 rounded-lg border border-white/[0.06]">
            <button
              onClick={() => setViewMode("table")}
              className={`p-1.5 rounded-md transition-colors cursor-pointer ${
                viewMode === "table" ? "bg-white/[0.08] text-white" : "text-slate-500 hover:text-slate-300"
              }`}
              title="Table View"
            >
              <Table weight="bold" className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => setViewMode("grid")}
              className={`p-1.5 rounded-md transition-colors cursor-pointer ${
                viewMode === "grid" ? "bg-white/[0.08] text-white" : "text-slate-500 hover:text-slate-300"
              }`}
              title="Grid View"
            >
              <SquaresFour weight="bold" className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Main Content: Table or Grid */}
      {viewMode === "table" ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-white/[0.04] bg-white/[0.01] text-[10px] font-mono font-bold uppercase tracking-[0.15em] text-slate-400 select-none">
                <th
                  onClick={() => handleSort("name")}
                  className="py-2.5 px-3.5 group cursor-pointer hover:text-slate-200 transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    Process {renderSortIcon("name")}
                  </div>
                </th>
                <th
                  onClick={() => handleSort("status")}
                  className="py-2.5 px-3.5 group cursor-pointer hover:text-slate-200 transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    Status {renderSortIcon("status")}
                  </div>
                </th>
                <th
                  onClick={() => handleSort("port")}
                  className="py-2.5 px-3.5 group cursor-pointer hover:text-slate-200 transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    Port {renderSortIcon("port")}
                  </div>
                </th>
                <th
                  onClick={() => handleSort("mem")}
                  className="py-2.5 px-3.5 group cursor-pointer hover:text-slate-200 transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    Memory {renderSortIcon("mem")}
                  </div>
                </th>
                <th
                  onClick={() => handleSort("cpu")}
                  className="py-2.5 px-3.5 group cursor-pointer hover:text-slate-200 transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    CPU {renderSortIcon("cpu")}
                  </div>
                </th>
                <th
                  onClick={() => handleSort("uptime")}
                  className="py-2.5 px-3.5 group cursor-pointer hover:text-slate-200 transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    Uptime {renderSortIcon("uptime")}
                  </div>
                </th>
                <th
                  onClick={() => handleSort("restarts")}
                  className="py-2.5 px-3.5 group cursor-pointer hover:text-slate-200 transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    Restarts {renderSortIcon("restarts")}
                  </div>
                </th>
                <th className="py-2.5 px-3.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && processes.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-12 text-center text-slate-500 font-mono text-xs">
                    Querying systemd daemon tables...
                  </td>
                </tr>
              ) : filteredAndSorted.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-12 text-center text-slate-500 font-mono text-xs">
                    {search ? `No processes match "${search}"` : "No managed processes found."}
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
      ) : (
        <div className="p-4">
          {filteredAndSorted.length === 0 ? (
            <div className="py-12 text-center text-slate-500 font-mono text-xs">
              {search ? `No processes match "${search}"` : "No managed processes found."}
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
              {filteredAndSorted.map((proc) => (
                <ProcessCard key={proc.name} process={proc} onRefresh={onRefresh} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
