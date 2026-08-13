import { safeExec, safeSpawn } from "../shell";
import { loadConfig } from "../config";
import { validateServiceName } from "../validation";

export class LogService {
  private static getServiceName(name: string): string {
    const config = loadConfig();
    const prefix = config.fire.servicePrefix || "fire";
    if (name.startsWith(`${prefix}-`)) {
      return name.endsWith(".service") ? name : `${name}.service`;
    }
    return `${prefix}-${name}.service`;
  }

  static async getHistory(name: string, lines: number = 100): Promise<string[]> {
    if (!validateServiceName(name)) throw new Error("Invalid service name");
    const svcName = this.getServiceName(name);
    const lineCount = Math.min(Math.max(lines, 1), 2000);

    const result = await safeExec("journalctl", [
      "-u",
      svcName,
      "-n",
      lineCount.toString(),
      "--no-pager",
    ]);

    if (result.code !== 0 && !result.stdout) {
      return [];
    }

    return result.stdout
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => {
        // Strip hostname/syslog prefix if standard syslog line
        const colonIdx = l.indexOf(": ");
        return colonIdx !== -1 ? l.substring(colonIdx + 2) : l;
      });
  }

  static streamLogs(
    name: string,
    onLine: (line: string) => void,
    onError?: (err: any) => void
  ): () => void {
    if (!validateServiceName(name)) throw new Error("Invalid service name");
    const svcName = this.getServiceName(name);

    const proc = safeSpawn("journalctl", [
      "-u",
      svcName,
      "-f",
      "-n",
      "50",
      "--no-pager",
    ]);

    let buffer = "";

    proc.stdout.on("data", (chunk: Buffer) => {
      buffer += chunk.toString("utf-8");
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (line.trim()) {
          const colonIdx = line.indexOf(": ");
          const cleanLine = colonIdx !== -1 ? line.substring(colonIdx + 2) : line;
          onLine(cleanLine);
        }
      }
    });

    proc.stderr.on("data", (chunk: Buffer) => {
      const err = chunk.toString("utf-8");
      if (onError) onError(err);
    });

    proc.on("error", (err) => {
      if (onError) onError(err);
    });

    return () => {
      try {
        proc.kill("SIGTERM");
      } catch {}
    };
  }
}
