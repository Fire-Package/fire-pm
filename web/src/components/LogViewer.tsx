"use client";

import React, { useState, useEffect, useRef } from "react";
import { 
  Play, 
  Pause, 
  Trash, 
  Copy, 
  DownloadSimple, 
  MagnifyingGlass, 
  Check, 
  TerminalWindow 
} from "@phosphor-icons/react";
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
    <div className={`double-bezel ${className}`}>
      <div className="double-bezel-inner overflow-hidden flex flex-col">
        {/* Top Toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 bg-white/[0.015] border-b border-white/[0.05]">
          <div className="flex items-center gap-2.5">
            <div className="p-1 rounded-lg bg-white/[0.04] text-slate-400">
              <TerminalWindow weight="bold" className="w-3.5 h-3.5 text-[#ff5500]" />
            </div>
            <div className="flex items-center gap-2 text-xs font-mono">
              <span className="relative flex h-2 w-2">
                <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${isConnected ? "bg-emerald-400" : "bg-amber-400"} opacity-75`}></span>
                <span className={`relative inline-flex rounded-full h-2 w-2 ${isConnected ? "bg-emerald-500" : "bg-amber-500"}`}></span>
              </span>
              <span className="text-slate-100 font-bold">{serviceName}</span>
              <span className="text-[10px] text-slate-500 font-medium px-1.5 py-0.5 rounded bg-white/[0.03] border border-white/[0.05]">
                {logs.length} lines
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Search filter */}
            <div className="relative">
              <MagnifyingGlass weight="bold" className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                placeholder="Filter output..."
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="bg-[#06070b] border border-white/[0.06] rounded-lg text-xs px-2.5 pl-8 py-1 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-[#ff5500]/70 transition-colors font-mono"
              />
            </div>

            <Button
              size="sm"
              variant={autoScroll ? "primary" : "secondary"}
              onClick={() => setAutoScroll(!autoScroll)}
              title={autoScroll ? "Pause autoscroll" : "Resume autoscroll"}
            >
              {autoScroll ? <Pause weight="bold" className="w-3 h-3" /> : <Play weight="fill" className="w-3 h-3" />}
              {autoScroll ? "Streaming" : "Paused"}
            </Button>

            <Button size="sm" variant="secondary" onClick={handleCopy} title="Copy all logs">
              {copied ? <Check weight="bold" className="w-3 h-3 text-emerald-400" /> : <Copy weight="bold" className="w-3 h-3" />}
              {copied ? "Copied" : "Copy"}
            </Button>

            <Button size="sm" variant="secondary" onClick={handleDownload} title="Download logs">
              <DownloadSimple weight="bold" className="w-3 h-3" />
            </Button>

            {onClear && (
              <Button size="sm" variant="ghost" onClick={onClear} title="Clear log window">
                <Trash weight="bold" className="w-3 h-3 text-slate-400 hover:text-rose-400" />
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
          className="flex-1 p-4 font-mono text-xs text-slate-200 overflow-y-auto overflow-x-auto min-h-[320px] max-h-[620px] leading-relaxed space-y-0.5 selection:bg-[#ff5500]/30 select-text"
        >
          {filteredLogs.length === 0 ? (
            <div className="text-slate-500 italic py-10 text-center font-mono text-xs">
              {filter ? `No log entries matching "${filter}"` : "Waiting for log stream..."}
            </div>
          ) : (
            filteredLogs.map((line, idx) => (
              <div key={idx} className="hover:bg-white/[0.03] px-1.5 py-0.5 rounded transition-colors whitespace-pre-wrap break-all flex items-start gap-2">
                <span className="text-slate-600 select-none text-[9px] w-7 shrink-0 text-right font-mono">
                  {idx + 1}
                </span>
                <span className={
                  line.toLowerCase().includes("error") || line.toLowerCase().includes("exception") || line.toLowerCase().includes("fatal")
                    ? "text-rose-400 font-semibold"
                    : line.toLowerCase().includes("warn")
                    ? "text-amber-300"
                    : line.toLowerCase().includes("info")
                    ? "text-sky-300"
                    : line.toLowerCase().includes("success") || line.toLowerCase().includes("started")
                    ? "text-emerald-300"
                    : "text-slate-300"
                }>
                  {line}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
