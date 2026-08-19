"use client";

import React, { useState } from "react";
import { Header } from "@/components/Header";
import { ProcessTable } from "@/components/ProcessTable";
import { StartProcessModal } from "@/components/StartProcessModal";
import { useProcesses } from "@/hooks/useProcesses";

export default function ProcessesPage() {
  const { processes, isLoading, refresh } = useProcesses();
  const [isLaunchModalOpen, setIsLaunchModalOpen] = useState(false);

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <Header
        title="Managed Processes & Daemons"
        subtitle="Full-spectrum Linux process supervision and cgroup resource configuration"
        onRefresh={refresh}
        isRefreshing={isLoading}
        onNewProcess={() => setIsLaunchModalOpen(true)}
      />

      <main className="p-4 sm:p-6 md:p-8 max-w-7xl w-full mx-auto">
        <ProcessTable
          processes={processes}
          isLoading={isLoading}
          onRefresh={refresh}
          onNewProcess={() => setIsLaunchModalOpen(true)}
        />
      </main>

      {/* Start Process Modal */}
      <StartProcessModal
        isOpen={isLaunchModalOpen}
        onClose={() => setIsLaunchModalOpen(false)}
        onSuccess={refresh}
      />
    </div>
  );
}
