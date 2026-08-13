"use client";

import React, { use } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Header } from "@/components/Header";
import { LogViewer } from "@/components/LogViewer";
import { useLogs } from "@/hooks/useLogs";

export default function FullscreenLogsPage(props: { params: Promise<{ name: string }> }) {
  const params = use(props.params);
  const { logs, isConnected, clearLogs } = useLogs(params.name);

  return (
    <div className="flex-1 flex flex-col min-w-0 h-screen overflow-hidden">
      <Header
        title={`Live Logs: ${params.name}`}
        subtitle="Real-time journalctl output stream"
      />

      <div className="p-4 flex flex-col flex-1 min-h-0">
        <div className="mb-3">
          <Link
            href={`/processes/${encodeURIComponent(params.name)}`}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-400 hover:text-slate-200 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" /> Back to Process Overview
          </Link>
        </div>

        <LogViewer
          logs={logs}
          isConnected={isConnected}
          serviceName={params.name}
          onClear={clearLogs}
          className="flex-1 min-h-[500px]"
        />
      </div>
    </div>
  );
}
