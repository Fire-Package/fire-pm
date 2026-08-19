import type { Metadata } from "next";
import "./globals.css";
import { ToastProvider } from "@/components/ui/Toast";

export const metadata: Metadata = {
  title: "Fire PM — Linux Process Supervisor",
  description: "Real-time Linux daemon orchestration, cgroup telemetry & reverse-proxy tunnels",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased bg-[#06080d] text-[#f1f5f9] min-h-screen">
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
