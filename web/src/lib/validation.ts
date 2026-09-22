export function validateServiceName(name: string): boolean {
  if (!name || typeof name !== "string") return false;
  // Allow lowercase alphanumeric, underscores, hyphens, and dots (e.g. fire-app, admin_botpy)
  return /^[a-zA-Z0-9_.-]{1,64}$/.test(name);
}

export function validatePort(port: number | string): boolean {
  const p = typeof port === "string" ? parseInt(port, 10) : port;
  return Number.isInteger(p) && p > 0 && p <= 65535;
}

export function validateMemoryLimit(mem: string | null | undefined): boolean {
  if (!mem || mem === "none" || mem === "") return true;
  return /^[0-9]+(K|M|G|T)$/i.test(mem);
}

export function validateCpuLimit(cpu: string | null | undefined): boolean {
  if (!cpu || cpu === "none" || cpu === "") return true;
  return /^[0-9]{1,3}%$/.test(cpu);
}

export function validateInterpreter(interpreter: string | null | undefined): boolean {
  if (!interpreter || typeof interpreter !== "string") return false;
  const trimmed = interpreter.trim();
  if (trimmed.length === 0 || trimmed.length > 256) return false;
  // Disallow any whitespace, control characters, or shell metacharacters
  if (/[\s\r\n;&|`$<>(){}[\]*?!^~]/.test(trimmed)) return false;
  // Must be either a single binary name or an absolute executable path
  return /^[a-zA-Z0-9_.-]{1,64}$|^(\/[a-zA-Z0-9_.-]+){1,32}$/.test(trimmed);
}

export function validateEnvVar(env: string): boolean {
  if (!env || typeof env !== "string") return false;
  if (/[\r\n\0]/.test(env)) return false;
  // Must be KEY=VALUE where KEY is a valid identifier
  return /^[a-zA-Z_][a-zA-Z0-9_]*=/.test(env);
}
