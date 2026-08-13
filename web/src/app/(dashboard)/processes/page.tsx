"use client";

import React from "react";
import { Header } from "@/components/Header";
import { ProcessTable } from "@/components/ProcessTable";
import { useProcesses } from "@/hooks/useProcesses";

export default function ProcessesPage() {
  const { processes, isLoading, refresh } = useProcesses();

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <Header
        title="Processes"
        subtitle="Manage and configure all system processes"
        onRefresh={refresh}
        isRefreshing={isLoading}
      />

      <main className="p-6 md:p-8 max-w-7xl w-full mx-auto">
        <ProcessTable
          processes={processes}
          isLoading={isLoading}
          onRefresh={refresh}
        />
      </main>
    </div>
  );
}
