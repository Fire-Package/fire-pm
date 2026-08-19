import React from "react";
import { Sidebar } from "@/components/Sidebar";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-screen overflow-hidden bg-[#06080d]">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0 overflow-y-auto">
        {children}
      </div>
    </div>
  );
}
