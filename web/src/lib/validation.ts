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
