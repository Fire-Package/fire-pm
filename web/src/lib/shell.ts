import { execFile, spawn, ExecFileOptions } from "child_process";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

export interface SafeExecResult {
  stdout: string;
  stderr: string;
  code: number;
}

const ALLOWED_COMMANDS = new Set([
  "/usr/local/bin/fire",
  "fire",
  "/usr/bin/systemctl",
  "systemctl",
  "/usr/bin/journalctl",
  "journalctl",
  "/usr/bin/ps",
  "ps",
  "/usr/bin/ss",
  "ss",
  "/usr/bin/df",
  "df",
  "/usr/bin/free",
  "free",
  "/usr/bin/uname",
  "uname",
  "/usr/bin/hostname",
  "hostname",
]);

export async function safeExec(
  file: string,
  args: string[] = [],
  options: ExecFileOptions = {}
): Promise<SafeExecResult> {
  const binaryBase = file.split("/").pop() || file;
  if (!ALLOWED_COMMANDS.has(file) && !ALLOWED_COMMANDS.has(binaryBase)) {
    throw new Error(`Command execution forbidden: ${file}`);
  }

  try {
    const { stdout, stderr } = await execFileAsync(file, args, {
      timeout: 15000,
      maxBuffer: 10 * 1024 * 1024,
      ...options,
    });
    return {
      stdout: stdout ? stdout.toString() : "",
      stderr: stderr ? stderr.toString() : "",
      code: 0,
    };
  } catch (error: any) {
    return {
      stdout: error.stdout ? error.stdout.toString() : "",
      stderr: error.stderr ? error.stderr.toString() : error.message || "",
      code: typeof error.code === "number" ? error.code : 1,
    };
  }
}

export function safeSpawn(
  file: string,
  args: string[] = []
) {
  const binaryBase = file.split("/").pop() || file;
  if (!ALLOWED_COMMANDS.has(file) && !ALLOWED_COMMANDS.has(binaryBase)) {
    throw new Error(`Command spawn forbidden: ${file}`);
  }
  return spawn(file, args, {
    stdio: ["ignore", "pipe", "pipe"],
  });
}
