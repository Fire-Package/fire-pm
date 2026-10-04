import fs from "fs";
import path from "path";
import { safeExec } from "../shell";
import { loadConfig, resolveCliBinary } from "../config";
import { validatePort } from "../validation";
import { SshSessionItem, SshSessionListResponse } from "../types";

export class SshService {
  private static getFireBinary(): string {
    const config = loadConfig();
    return resolveCliBinary(config.fire.cliBinary);
  }

  private static getStateDir(): string {
    const defaultDir = "/tmp/fire-ssh";
    if (fs.existsSync(defaultDir)) {
      return defaultDir;
    }
    const uid = typeof process.getuid === "function" ? process.getuid() : 0;
    const userDir = `/tmp/fire-ssh-${uid}`;
    if (fs.existsSync(userDir)) {
      return userDir;
    }
    return defaultDir;
  }

  static async list(): Promise<SshSessionListResponse> {
    const binary = this.getFireBinary();
    try {
      const result = await safeExec(binary, ["ssh", "list", "--json"]);
      if (result.code === 0 && result.stdout) {
        const data = JSON.parse(result.stdout.trim());
        if (data && Array.isArray(data.sessions)) {
          const sessions: SshSessionItem[] = data.sessions.map((s: any) => ({
            port: Number(s.port) || 0,
            pid: Number(s.pid) || 0,
            url: s.url || `http://localhost:${s.port}`,
            title: s.title || "",
            status: s.status || "ONLINE",
            age: s.age || "-",
            createdAt: Number(s.createdAt) || 0,
            localUrl: `http://127.0.0.1:${s.port}`,
          }));
          return {
            sessions,
            total: typeof data.total === "number" ? data.total : sessions.length,
            online: typeof data.online === "number" ? data.online : sessions.length,
          };
        }
      }
    } catch {
      // Fallback to reading state files directly
    }

    return this.listFromStateFiles();
  }

  private static listFromStateFiles(): SshSessionListResponse {
    const stateDir = this.getStateDir();
    if (!fs.existsSync(stateDir)) {
      return { sessions: [], total: 0, online: 0 };
    }

    const sessions: SshSessionItem[] = [];
    try {
      const files = fs.readdirSync(stateDir).filter((f) => f.endsWith(".json"));
      const now = Math.floor(Date.now() / 1000);

      for (const file of files) {
        const filePath = path.join(stateDir, file);
        try {
          const raw = fs.readFileSync(filePath, "utf-8");
          const data = JSON.parse(raw);
          const pid = Number(data.pid);

          let isAlive = false;
          if (pid > 0) {
            try {
              process.kill(pid, 0);
              isAlive = true;
            } catch {
              isAlive = false;
            }
          }

          if (isAlive) {
            const createdAt = Number(data.created_at || data.createdAt || 0);
            let age = "-";
            if (createdAt > 0 && now >= createdAt) {
              const diff = now - createdAt;
              if (diff < 60) age = `${diff}s`;
              else if (diff < 3600) age = `${Math.floor(diff / 60)}m`;
              else age = `${Math.floor(diff / 3600)}h`;
            }

            sessions.push({
              port: Number(data.port),
              pid,
              url: data.url || `http://localhost:${data.port}`,
              title: data.title || "",
              status: "ONLINE",
              age,
              createdAt,
              localUrl: `http://127.0.0.1:${data.port}`,
            });
          }
        } catch {
          // Ignore invalid files
        }
      }
    } catch {
      // Return whatever gathered
    }

    return {
      sessions,
      total: sessions.length,
      online: sessions.length,
    };
  }

  static async create(options: {
    port?: number;
    title?: string;
    password?: string;
    provider?: string;
    noTunnel?: boolean;
  } = {}): Promise<SshSessionItem> {
    if (options.port !== undefined && !validatePort(options.port)) {
      throw new Error(`Invalid port number: ${options.port}`);
    }

    const binary = this.getFireBinary();
    const args = ["ssh", "--daemon", "--json"];

    if (options.port) {
      args.push("--port", options.port.toString());
    }
    if (options.title && options.title.trim()) {
      args.push("--title", options.title.trim());
    }
    if (options.password) {
      args.push("--password", options.password);
    }
    if (options.provider) {
      args.push("--provider", options.provider);
    }
    if (options.noTunnel) {
      args.push("--no-tunnel");
    }

    const result = await safeExec(binary, args);

    if (result.code !== 0 && !result.stdout) {
      if (result.stderr && result.stderr.includes("ENOENT")) {
        throw new Error(
          `Fire PM CLI binary not found at "${binary}". Please ensure Fire PM is installed (sudo ./install.sh) or that app/fire is executable.`
        );
      }
      throw new Error(result.stderr || `Failed to create SSH session`);
    }

    try {
      const data = JSON.parse(result.stdout.trim());
      if (data && (data.success || data.port)) {
        return {
          port: Number(data.port),
          pid: Number(data.pid),
          url: data.url || `http://localhost:${data.port}`,
          title: data.title || options.title || "",
          status: "ONLINE",
          age: "0s",
          createdAt: Number(data.createdAt || Math.floor(Date.now() / 1000)),
          localUrl: `http://127.0.0.1:${data.port}`,
        };
      }
    } catch {
      // If output is not JSON, check state directory for newest file
    }

    // Refresh list to find newly created session
    const list = await this.list();
    if (options.port) {
      const found = list.sessions.find((s) => s.port === options.port);
      if (found) return found;
    }

    if (list.sessions.length > 0) {
      // Return newest session
      const sorted = [...list.sessions].sort((a, b) => b.createdAt - a.createdAt);
      return sorted[0];
    }

    throw new Error(result.stderr || result.stdout || "SSH session started but state could not be verified");
  }

  static async close(port: number | "all"): Promise<{ success: boolean }> {
    if (port !== "all" && !validatePort(port)) {
      throw new Error(`Invalid port number: ${port}`);
    }

    const binary = this.getFireBinary();
    const args = ["ssh", "close", port.toString(), "--json"];
    const result = await safeExec(binary, args);

    if (result.code !== 0 && result.stderr && !result.stderr.includes("Closed")) {
      throw new Error(result.stderr || `Failed to close SSH session on port ${port}`);
    }

    // Ensure state file is deleted
    if (port !== "all") {
      const stateDir = this.getStateDir();
      const stateFile = path.join(stateDir, `${port}.json`);
      if (fs.existsSync(stateFile)) {
        try {
          fs.unlinkSync(stateFile);
        } catch {}
      }
    }

    return { success: true };
  }

  static async setTitle(port: number, title: string): Promise<{ success: boolean; port: number; title: string }> {
    if (!validatePort(port)) {
      throw new Error(`Invalid port number: ${port}`);
    }

    const binary = this.getFireBinary();
    const result = await safeExec(binary, ["ssh", "title", port.toString(), title]);

    if (result.code !== 0) {
      throw new Error(result.stderr || `Failed to update title for SSH session on port ${port}`);
    }

    return { success: true, port, title };
  }
}
