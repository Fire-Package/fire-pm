import fs from "fs";
import path from "path";
import { safeExec } from "../shell";
import { loadConfig } from "../config";
import { validateServiceName, validateMemoryLimit, validateCpuLimit } from "../validation";
import { ProcessItem, ProcessListResponse, ProcessDetail } from "../types";

export class ProcessService {
  private static getServiceName(name: string): string {
    const config = loadConfig();
    const prefix = config.fire.servicePrefix || "fire";
    if (name.startsWith(`${prefix}-`)) {
      return name.endsWith(".service") ? name : `${name}.service`;
    }
    return `${prefix}-${name}.service`;
  }

  private static getCleanName(serviceName: string): string {
    const config = loadConfig();
    const prefix = config.fire.servicePrefix || "fire";
    let n = serviceName;
    if (n.startsWith(`${prefix}-`)) {
      n = n.substring(prefix.length + 1);
    }
    if (n.endsWith(".service")) {
      n = n.substring(0, n.length - 8);
    }
    return n;
  }

  static async list(): Promise<ProcessListResponse> {
    const config = loadConfig();
    const result = await safeExec(config.fire.cliBinary, ["list", "--json"]);
    
    if (result.code !== 0 || !result.stdout) {
      // Fallback empty list
      return {
        processes: [],
        total: 0,
        online: 0,
        stopped: 0,
      };
    }

    try {
      const data = JSON.parse(result.stdout);
      const rawProcesses = data.processes || [];
      const processes: ProcessItem[] = rawProcesses.map((p: any) => ({
        id: p.id ?? 0,
        name: p.name ?? "unknown",
        status: p.status ?? "stopped",
        uptime: p.uptime ?? "-",
        restarts: p.restarts ?? 0,
        mem: p.mem ?? "0.0MB",
        cpu: p.cpu ?? "0.0%",
        pid: p.pid && p.pid > 0 ? p.pid : null,
        port: p.port ?? "-",
        watch: p.watch ?? "no",
        reload: p.reload ?? "off",
        memLimit: p.mem_limit ?? "-",
        cpuLimit: p.cpu_limit ?? "-",
      }));

      const total = data.total_process ?? processes.length;
      const online = data.active_process ?? processes.filter((p) => p.status === "online").length;
      const stopped = data.inactive_process ?? (total - online);

      return {
        processes,
        total,
        online,
        stopped,
      };
    } catch (e) {
      console.error("Error parsing fire list --json:", e, result.stdout);
      return {
        processes: [],
        total: 0,
        online: 0,
        stopped: 0,
      };
    }
  }

  static async getDetail(name: string): Promise<ProcessDetail | null> {
    if (!validateServiceName(name)) {
      throw new Error(`Invalid process name: ${name}`);
    }

    const config = loadConfig();
    const result = await safeExec(config.fire.cliBinary, ["info", name, "--json"]);
    
    let infoData: any = null;
    if (result.code === 0 && result.stdout) {
      try {
        infoData = JSON.parse(result.stdout);
      } catch (e) {
        console.error("Error parsing fire info --json:", e);
      }
    }

    const svcName = this.getServiceName(name);
    const unitPath = path.join(config.fire.systemdDir, svcName);

    let unitContent = "";
    if (fs.existsSync(unitPath)) {
      try {
        unitContent = fs.readFileSync(unitPath, "utf-8");
      } catch (e) {
        console.error("Error reading unit file:", e);
      }
    }

    if (!infoData && !fs.existsSync(unitPath)) {
      return null;
    }

    const cleanName = this.getCleanName(name);

    return {
      name: infoData?.name || cleanName,
      service: svcName,
      status: infoData?.status || "stopped",
      pid: infoData?.pid || null,
      restarts: infoData?.restarts || 0,
      uptime: infoData?.uptime || "-",
      stoppedAt: infoData?.stopped_at || "-",
      mem: infoData?.mem || "0.0MB",
      cpu: infoData?.cpu || "0.0%",
      interpreter: infoData?.interpreter || "-",
      script: infoData?.script || "-",
      args: infoData?.args || "",
      workingDirectory: infoData?.working_directory || "-",
      user: infoData?.user || "root",
      logPath: infoData?.log_path || `journalctl -u ${svcName} -f`,
      unitContent,
    };
  }

  static async start(name: string): Promise<{ success: boolean; message: string }> {
    if (!validateServiceName(name)) throw new Error("Invalid service name");
    const svcName = this.getServiceName(name);
    const result = await safeExec("systemctl", ["start", svcName]);
    if (result.code !== 0) {
      throw new Error(result.stderr || `Failed to start ${name}`);
    }
    return { success: true, message: `Started ${name}` };
  }

  static async stop(name: string): Promise<{ success: boolean; message: string }> {
    if (!validateServiceName(name)) throw new Error("Invalid service name");
    const svcName = this.getServiceName(name);
    const result = await safeExec("systemctl", ["stop", svcName]);
    if (result.code !== 0) {
      throw new Error(result.stderr || `Failed to stop ${name}`);
    }
    return { success: true, message: `Stopped ${name}` };
  }

  static async restart(name: string): Promise<{ success: boolean; message: string }> {
    if (!validateServiceName(name)) throw new Error("Invalid service name");
    const svcName = this.getServiceName(name);
    const result = await safeExec("systemctl", ["restart", svcName]);
    if (result.code !== 0) {
      throw new Error(result.stderr || `Failed to restart ${name}`);
    }
    return { success: true, message: `Restarted ${name}` };
  }

  static async delete(name: string): Promise<{ success: boolean; message: string }> {
    if (!validateServiceName(name)) throw new Error("Invalid service name");
    const config = loadConfig();
    const result = await safeExec(config.fire.cliBinary, ["delete", name]);
    if (result.code !== 0) {
      throw new Error(result.stderr || `Failed to delete ${name}`);
    }
    return { success: true, message: `Deleted ${name}` };
  }

  static async setLimits(name: string, mem?: string | null, cpu?: string | null): Promise<{ success: boolean }> {
    if (!validateServiceName(name)) throw new Error("Invalid service name");
    if (mem && !validateMemoryLimit(mem)) throw new Error("Invalid memory limit format (e.g. 500M, 1G)");
    if (cpu && !validateCpuLimit(cpu)) throw new Error("Invalid CPU quota format (e.g. 50%, 100%)");

    const svcName = this.getServiceName(name);
    const args = ["set-property", svcName];

    if (mem && mem !== "none") {
      args.push(`MemoryMax=${mem}`, "MemorySwapMax=infinity");
    } else {
      args.push("MemoryMax=infinity", "MemorySwapMax=infinity");
    }

    if (cpu && cpu !== "none") {
      args.push(`CPUQuota=${cpu}`);
    } else {
      args.push("CPUQuota=");
    }

    const result = await safeExec("systemctl", args);
    if (result.code !== 0) {
      throw new Error(result.stderr || `Failed to set limits for ${name}`);
    }
    return { success: true };
  }

  static async toggleWatch(name: string): Promise<{ success: boolean; watch: string }> {
    if (!validateServiceName(name)) throw new Error("Invalid service name");
    const config = loadConfig();
    const svcName = this.getServiceName(name);
    const unitPath = path.join(config.fire.systemdDir, svcName);

    if (!fs.existsSync(unitPath)) {
      throw new Error(`Unit file not found: ${unitPath}`);
    }

    let content = fs.readFileSync(unitPath, "utf-8");
    let newWatch = "always";
    if (content.includes("Restart=always")) {
      content = content.replace("Restart=always", "Restart=no");
      newWatch = "no";
    } else if (content.includes("Restart=no")) {
      content = content.replace("Restart=no", "Restart=always");
      newWatch = "always";
    } else {
      // Add Restart=always under [Service]
      content = content.replace("[Service]", "[Service]\nRestart=always");
      newWatch = "always";
    }

    fs.writeFileSync(unitPath, content, "utf-8");
    await safeExec("systemctl", ["daemon-reload"]);
    return { success: true, watch: newWatch };
  }

  static async toggleReload(name: string): Promise<{ success: boolean; reload: string }> {
    if (!validateServiceName(name)) throw new Error("Invalid service name");
    const config = loadConfig();
    const svcName = this.getServiceName(name);
    const cleanName = this.getCleanName(name);
    const pathName = svcName.replace(".service", ".path");
    const pathFile = path.join(config.fire.systemdDir, pathName);

    if (fs.existsSync(pathFile)) {
      await safeExec("systemctl", ["stop", pathName]);
      await safeExec("systemctl", ["disable", pathName]);
      fs.unlinkSync(pathFile);
      await safeExec("systemctl", ["daemon-reload"]);
      return { success: true, reload: "off" };
    }

    // Find script path
    const detail = await this.getDetail(name);
    let scriptPath = detail?.script;
    if (!scriptPath || scriptPath === "-") {
      throw new Error("Could not detect script path for hot-reload");
    }

    if (!path.isAbsolute(scriptPath) && detail?.workingDirectory) {
      scriptPath = path.join(detail.workingDirectory, scriptPath);
    }

    const pathContent = `[Unit]\nDescription=Watch ${scriptPath} for ${cleanName}\n\n[Path]\nPathModified=${scriptPath}\nUnit=fire-reload@${svcName}\n\n[Install]\nWantedBy=multi-user.target\n`;
    fs.writeFileSync(pathFile, pathContent, "utf-8");
    await safeExec("systemctl", ["daemon-reload"]);
    await safeExec("systemctl", ["enable", "--now", pathName]);

    return { success: true, reload: "active" };
  }

  static async create(params: {
    script: string;
    name?: string;
    interpreter?: string;
    env?: string[];
    watch?: boolean;
    reload?: boolean;
    mem?: string;
    cpu?: string;
  }): Promise<{ success: boolean; message: string }> {
    const config = loadConfig();
    const args = ["start", params.script];

    if (params.name) {
      if (!validateServiceName(params.name)) throw new Error("Invalid service name");
      args.push("--name", params.name);
    }
    if (params.interpreter) {
      args.push("--interpreter", params.interpreter);
    }
    if (params.watch) {
      args.push("--watch");
    }
    if (params.reload) {
      args.push("--reload");
    }
    if (params.mem) {
      if (!validateMemoryLimit(params.mem)) throw new Error("Invalid memory limit format");
      args.push("--memory", params.mem);
    }
    if (params.cpu) {
      if (!validateCpuLimit(params.cpu)) throw new Error("Invalid CPU quota format");
      args.push("--cpu", params.cpu);
    }
    if (params.env && Array.isArray(params.env)) {
      for (const e of params.env) {
        if (typeof e === "string" && e.includes("=")) {
          args.push("--env", e);
        }
      }
    }

    const result = await safeExec(config.fire.cliBinary, args);
    if (result.code !== 0) {
      throw new Error(result.stderr || "Failed to start new process");
    }

    return { success: true, message: result.stdout || "Process started successfully" };
  }
}
