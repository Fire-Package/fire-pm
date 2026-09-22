import fs from "fs";
import path from "path";
import { safeExec } from "../shell";
import { loadConfig } from "../config";
import { validateServiceName } from "../validation";

export class ConfigService {
  private static getUnitPath(name: string): string {
    const config = loadConfig();
    const prefix = config.fire.servicePrefix || "fire";
    const svcName = name.startsWith(`${prefix}-`)
      ? (name.endsWith(".service") ? name : `${name}.service`)
      : `${prefix}-${name}.service`;
    return path.join(config.fire.systemdDir, svcName);
  }

  static async getUnitContent(name: string): Promise<string> {
    if (!validateServiceName(name)) throw new Error("Invalid service name");
    const unitPath = this.getUnitPath(name);
    if (!fs.existsSync(unitPath)) {
      throw new Error(`Unit file not found: ${unitPath}`);
    }
    return fs.readFileSync(unitPath, "utf-8");
  }

  static async updateUnitContent(name: string, content: string): Promise<{ success: boolean }> {
    if (!validateServiceName(name)) throw new Error("Invalid service name");
    if (!content || typeof content !== "string") throw new Error("Invalid unit content");

    // Validate structure: must contain [Unit] and [Service]
    if (!content.includes("[Unit]") || !content.includes("[Service]")) {
      throw new Error("Invalid systemd unit: missing [Unit] or [Service] section");
    }

    // Prohibit forbidden directives that could allow arbitrary execution escapes
    const forbiddenDirectives = new Set([
      "execstartpre",
      "execstoppost",
      "execstartpost",
      "execreload",
      "execstop",
    ]);

    const lines = content.split(/\r?\n/);
    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line || line.startsWith("#") || line.startsWith(";")) continue;
      const key = line.split(/[=\s!:]/)[0].toLowerCase();
      if (forbiddenDirectives.has(key)) {
        throw new Error(`Directive '${key}' is not allowed for security reasons.`);
      }
    }

    const unitPath = this.getUnitPath(name);
    fs.writeFileSync(unitPath, content, { encoding: "utf-8", mode: 0o600 });
    try {
      fs.chmodSync(unitPath, 0o600);
    } catch {}
    await safeExec("systemctl", ["daemon-reload"]);
    return { success: true };
  }
}
