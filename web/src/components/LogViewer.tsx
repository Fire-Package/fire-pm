"use client";

import React, { useState, useEffect, useRef } from "react";
import { Play, Pause, Trash2, Copy, Download, Search, Check } from "lucide-react";
import { Button } from "./ui/Button";

export interface LogViewerProps {
  logs: string[];
  isConnected: boolean;
  serviceName: string;
  onClear?: () => void;
  className?: string;
}

export const LogViewer: React.FC<LogViewerProps> = ({
  logs,
  isConnected,
  serviceName,
  onClear,
  className = "",
}) => {
  const [autoScroll, setAutoScroll] = useState(true);
  const [filter, setFilter] = useState("");
  const [copied, setCopied] = useState(false);
  const logContainerRef = useRef<HTMLDivElement>(null);

  const filteredLogs = filter
    ? logs.filter((line) => line.toLowerCase().includes(filter.toLowerCase()))
    : logs;

  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [filteredLogs, autoScroll]);

  const handleCopy = () => {
    navigator.clipboard.writeText(logs.join("\n"));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const blob = new Blob([logs.join("\n")], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${serviceName}-logs.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className={`flex flex-col bg-[#0b0d13] border border-[#1e2433] rounded-lg overflow-hidden ${className}`}>
      {/* Top Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 bg-[#121622] border-b border-[#1c2230]">
        <div className="flex items-center gap-2.5">
          <div className="flex items-center gap-1.5 text-xs font-mono">
            <span
              className={`w-2 h-2 rounded-full ${
                isConnected ? "bg-emerald-400 animate-pulse" : "bg-amber-500"
              }`}
            />
            <span className="text-slate-300 font-semibold">{serviceName}</span>
            <span className="text-slate-500">
              ({logs.length} lines)
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Search filter */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Filter logs..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="bg-[#0b0d13] border border-[#232a3b] rounded text-xs px-2.5 pl-8 py-1 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-[#ff5500]"
            />
          </div>

          <Button
            size="sm"
            variant={autoScroll ? "primary" : "secondary"}
            onClick={() => setAutoScroll(!autoScroll)}
            title={autoScroll ? "Pause autoscroll" : "Resume autoscroll"}
          >
            {autoScroll ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
            {autoScroll ? "Auto-scroll" : "Paused"}
          </Button>

          <Button size="sm" variant="secondary" onClick={handleCopy} title="Copy all logs">
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            {copied ? "Copied" : "Copy"}
          </Button>

          <Button size="sm" variant="secondary" onClick={handleDownload} title="Download logs">
            <Download className="w-3.5 h-3.5" />
          </Button>

          {onClear && (
            <Button size="sm" variant="ghost" onClick={onClear} title="Clear log window">
              <Trash2 className="w-3.5 h-3.5 text-slate-400 hover:text-rose-400" />
            </Button>
          )}
        </div>
      </div>

      {/* Terminal log output */}
      <div
        ref={logContainerRef}
        onScroll={(e) => {
          const target = e.currentTarget;
          const isAtBottom = target.scrollHeight - target.scrollTop - target.clientHeight < 30;
          if (!isAtBottom && autoScroll) {
            setAutoScroll(false);
          }
        }}
        className="flex-1 p-4 font-mono text-xs text-slate-200 overflow-y-auto overflow-x-auto min-h-[300px] max-h-[600px] leading-relaxed space-y-0.5 selection:bg-[#ff5500]/30 select-text"
      >
        {filteredLogs.length === 0 ? (
          <div className="text-slate-500 italic py-8 text-center">
            {filter ? `No log entries matching "${filter}"` : "Waiting for log output..."}
          </div>
        ) : (
          filteredLogs.map((line, idx) => (
            <div key={idx} className="hover:bg-slate-900/60 px-1.5 py-0.5 rounded whitespace-pre-wrap break-all">
              <span className="text-slate-600 select-none mr-3 text-[10px] w-6 inline-block text-right">
                {idx + 1}
              </span>
              <span className={
                line.toLowerCase().includes("error") || line.toLowerCase().includes("exception") || line.toLowerCase().includes("fatal")
                  ? "text-rose-400 font-medium"
                  : line.toLowerCase().includes("warn")
                  ? "text-amber-300"
                  : line.toLowerCase().includes("info")
                  ? "text-sky-300"
                  : "text-slate-300"
              }>
                {line}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
