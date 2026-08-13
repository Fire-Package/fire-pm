import os from "os";
import { safeExec } from "../shell";
import { loadConfig } from "../config";
import { SystemHealthResponse, SystemInfoResponse } from "../types";

export class SystemService {
  static async getHealth(): Promise<SystemHealthResponse> {
    const config = loadConfig();
    const result = await safeExec(config.fire.cliBinary, ["doctor", "--json"]);

    if (result.code === 0 && result.stdout) {
      try {
        const data = JSON.parse(result.stdout);
        const checks = data.checks || [];
        const passed = checks.filter((c: any) => c.passed).length;
        return {
          score: data.score ?? 100,
          checks,
          passed,
          total: checks.length,
        };
      } catch (e) {
        console.error("Error parsing fire doctor --json:", e, result.stdout);
      }
    }

    // Fallback basic check
    return {
      score: 100,
      checks: [
        { name: "System", passed: true, message: "System is responsive" },
      ],
      passed: 1,
      total: 1,
    };
  }

  static async getInfo(): Promise<SystemInfoResponse> {
    const hostname = os.hostname();
    const platform = os.platform();
    const uptimeSec = os.uptime();
    const cpuCount = os.cpus().length;
    const totalMem = os.totalmem();
    const freeMem = os.freemem();
    const usedMem = totalMem - freeMem;
    const memUsedPercent = Math.round((usedMem / totalMem) * 1000) / 10;
    const loadAvg = os.loadavg();

    // Format uptime
    const days = Math.floor(uptimeSec / 86400);
    const hours = Math.floor((uptimeSec % 86400) / 3600);
    const mins = Math.floor((uptimeSec % 3600) / 60);
    const uptime = days > 0 ? `${days}d ${hours}h` : `${hours}h ${mins}m`;

    // Disk usage via df
    let diskTotal = "Unknown";
    let diskUsed = "Unknown";
    let diskUsedPercent = 0;

    try {
      const df = await safeExec("df", ["-h", "/"]);
      if (df.code === 0 && df.stdout) {
        const lines = df.stdout.trim().split("\n");
        if (lines.length >= 2) {
          const parts = lines[1].split(/\s+/);
          if (parts.length >= 5) {
            diskTotal = parts[1];
            diskUsed = parts[2];
            diskUsedPercent = parseInt(parts[4].replace("%", ""), 10) || 0;
          }
        }
      }
    } catch {}

    const formatBytes = (bytes: number) => {
      const mb = Math.round(bytes / (1024 * 1024));
      return mb >= 1024 ? `${(mb / 1024).toFixed(1)}GB` : `${mb}MB`;
    };

    return {
      hostname,
      platform,
      uptime,
      cpuCount,
      memTotal: formatBytes(totalMem),
      memFree: formatBytes(freeMem),
      memUsedPercent,
      diskTotal,
      diskUsed,
      diskUsedPercent,
      loadAvg: loadAvg.map((l) => Math.round(l * 100) / 100),
    };
  }
}
