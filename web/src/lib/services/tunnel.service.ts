import { safeExec } from "../shell";
import { loadConfig } from "../config";
import { validatePort } from "../validation";
import { TunnelItem, TunnelListResponse } from "../types";

export class TunnelService {
  static async list(): Promise<TunnelListResponse> {
    const config = loadConfig();
    const result = await safeExec(config.fire.cliBinary, ["tunnel", "list", "--json"]);

    if (result.code !== 0 || !result.stdout) {
      return {
        tunnels: [],
        total: 0,
        online: 0,
        pending: 0,
      };
    }

    try {
      const data = JSON.parse(result.stdout);
      const rawTunnels = data.tunnels || [];
      const tunnels: TunnelItem[] = rawTunnels.map((t: any) => ({
        port: t.port ?? 0,
        pid: t.pid ?? 0,
        age: t.age ?? "-",
        status: t.status ?? "PENDING",
        hash: t.hash ?? "",
        url: t.url ?? "",
        name: t.name ?? "-",
      }));

      return {
        tunnels,
        total: data.total ?? tunnels.length,
        online: data.online ?? tunnels.filter((t) => t.status === "ONLINE").length,
        pending: data.pending ?? tunnels.filter((t) => t.status !== "ONLINE").length,
      };
    } catch (e) {
      console.error("Error parsing fire tunnel list --json:", e, result.stdout);
      return {
        tunnels: [],
        total: 0,
        online: 0,
        pending: 0,
      };
    }
  }

  static async open(port: number): Promise<{ port: number; url: string; hash?: string }> {
    if (!validatePort(port)) {
      throw new Error(`Invalid port number: ${port}`);
    }

    const config = loadConfig();
    const result = await safeExec(config.fire.cliBinary, ["tunnel", "open", port.toString()]);

    if (result.code !== 0) {
      throw new Error(result.stderr || result.stdout || `Failed to open tunnel on port ${port}`);
    }

    // Parse URL from stdout (last non-empty line or https:// line)
    const lines = result.stdout.split("\n").map((l) => l.trim()).filter(Boolean);
    const urlLine = lines.find((l) => l.startsWith("https://")) || lines[lines.length - 1] || "";

    return {
      port,
      url: urlLine,
    };
  }

  static async close(port: number): Promise<{ success: boolean }> {
    if (!validatePort(port)) {
      throw new Error(`Invalid port number: ${port}`);
    }

    const config = loadConfig();
    const result = await safeExec(config.fire.cliBinary, ["tunnel", "close", port.toString()]);

    if (result.code !== 0) {
      throw new Error(result.stderr || result.stdout || `Failed to close tunnel on port ${port}`);
    }

    return { success: true };
  }
}
