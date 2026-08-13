import { apiFetch } from "./client";
import { SystemHealthResponse, SystemInfoResponse } from "../types";

export const SystemApi = {
  getHealth: () => apiFetch<SystemHealthResponse>("/api/system/health"),
  getInfo: () => apiFetch<SystemInfoResponse>("/api/system/info"),
};
