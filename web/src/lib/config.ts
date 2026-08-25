import fs from "fs";
import path from "path";
import crypto from "crypto";

export interface FireConfig {
  auth: {
    passwordHash: string;
    jwtSecret: string;
    apiTokens: { id: string; name: string; tokenHash: string; createdAt: string }[];
  };
  server: {
    port: number;
    host: string;
    basePath: string;
  };
  fire: {
    cliBinary: string;
    systemdDir: string;
    servicePrefix: string;
  };
  tunnel?: {
    provider?: "quick" | "custom" | string;
    domain?: string;
    hostSuffix?: string;
    sslCert?: string;
    sslKey?: string;
  };
}

const PRIMARY_CONFIG_PATH = "/etc/fire-pm/config.json";
const LOCAL_CONFIG_PATH = path.join(process.cwd(), "config.json");

function getConfigPath(): string {
  if (fs.existsSync(PRIMARY_CONFIG_PATH)) {
    return PRIMARY_CONFIG_PATH;
  }
  if (fs.existsSync(LOCAL_CONFIG_PATH)) {
    return LOCAL_CONFIG_PATH;
  }
  // If running as root, try to create /etc/fire-pm
  try {
    if (!fs.existsSync("/etc/fire-pm")) {
      fs.mkdirSync("/etc/fire-pm", { recursive: true });
    }
    return PRIMARY_CONFIG_PATH;
  } catch {
    return LOCAL_CONFIG_PATH;
  }
}

const DEFAULT_CONFIG: FireConfig = {
  auth: {
    passwordHash: "",
    jwtSecret: crypto.randomBytes(32).toString("hex"),
    apiTokens: [],
  },
  server: {
    port: 3000,
    host: "0.0.0.0",
    basePath: "/",
  },
  fire: {
    cliBinary: "/usr/local/bin/fire",
    systemdDir: "/etc/systemd/system",
    servicePrefix: "fire",
  },
  tunnel: {
    provider: "quick",
    domain: "",
    hostSuffix: "-tunnel",
    sslCert: "",
    sslKey: "",
  },
};

let cachedConfig: FireConfig | null = null;

export function loadConfig(): FireConfig {
  if (cachedConfig) {
    return cachedConfig;
  }

  const configPath = getConfigPath();
  if (fs.existsSync(configPath)) {
    try {
      const data = fs.readFileSync(configPath, "utf-8");
      const parsed = JSON.parse(data);
      cachedConfig = {
        ...DEFAULT_CONFIG,
        ...parsed,
        auth: { ...DEFAULT_CONFIG.auth, ...(parsed.auth || {}) },
        server: { ...DEFAULT_CONFIG.server, ...(parsed.server || {}) },
        fire: { ...DEFAULT_CONFIG.fire, ...(parsed.fire || {}) },
        tunnel: { ...DEFAULT_CONFIG.tunnel, ...(parsed.tunnel || {}) },
      };
      return cachedConfig!;
    } catch (e) {
      console.error(`Error reading config from ${configPath}:`, e);
    }
  }

  // Create initial config if not exists
  cachedConfig = { ...DEFAULT_CONFIG };
  saveConfig(cachedConfig);
  return cachedConfig;
}

export function saveConfig(config: FireConfig): void {
  cachedConfig = config;
  const configPath = getConfigPath();
  try {
    const dir = path.dirname(configPath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
    }
    fs.writeFileSync(configPath, JSON.stringify(config, null, 2), {
      encoding: "utf-8",
      mode: 0o600,
    });
  } catch (e) {
    console.error(`Error writing config to ${configPath}:`, e);
  }
}

export function isSetupComplete(): boolean {
  const config = loadConfig();
  return Boolean(config.auth.passwordHash && config.auth.passwordHash.length > 0);
}
