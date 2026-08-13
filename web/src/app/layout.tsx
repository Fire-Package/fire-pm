import type { Metadata } from "next";
import "./globals.css";
import { ToastProvider } from "@/components/ui/Toast";

export const metadata: Metadata = {
  title: "Fire PM — Process Manager",
  description: "Linux process and application management dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased bg-[#0a0c10] text-[#f0f3f8] min-h-screen">
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
