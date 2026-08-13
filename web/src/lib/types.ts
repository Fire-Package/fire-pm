export interface ProcessItem {
  id: number;
  name: string;
  status: "online" | "stopped" | "errored" | string;
  uptime: string;
  restarts: number;
  mem: string;
  cpu: string;
  pid: number | null;
  port: string;
  watch: string;
  reload: string;
  memLimit: string;
  cpuLimit: string;
}

export interface ProcessListResponse {
  processes: ProcessItem[];
  total: number;
  online: number;
  stopped: number;
}

export interface ProcessDetail {
  name: string;
  service: string;
  status: string;
  pid: number | null;
  restarts: number;
  uptime: string;
  stoppedAt: string;
  mem: string;
  cpu: string;
  interpreter: string;
  script: string;
  args: string;
  workingDirectory: string;
  user: string;
  logPath: string;
  port?: string;
  watch?: string;
  reload?: string;
  memLimit?: string;
  cpuLimit?: string;
  environment?: string[];
  unitContent?: string;
}

export interface TunnelItem {
  port: number;
  pid: number;
  age: string;
  status: "ONLINE" | "PENDING" | string;
  hash: string;
  url: string;
  name: string;
}

export interface TunnelListResponse {
  tunnels: TunnelItem[];
  total: number;
  online: number;
  pending: number;
}

export interface HealthCheckItem {
  name: string;
  passed: boolean;
  message: string;
}

export interface SystemHealthResponse {
  score: number;
  checks: HealthCheckItem[];
  passed: number;
  total: number;
}

export interface SystemInfoResponse {
  hostname: string;
  platform: string;
  uptime: string;
  cpuCount: number;
  memTotal: string;
  memFree: string;
  memUsedPercent: number;
  diskTotal: string;
  diskUsed: string;
  diskUsedPercent: number;
  loadAvg: number[];
}

export interface ApiErrorResponse {
  error: {
    code: string;
    message: string;
  };
}
