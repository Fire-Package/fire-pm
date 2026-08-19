import { apiFetch } from "./client";
import { ProcessListResponse, ProcessDetail } from "../types";

export const ProcessApi = {
  list: () => apiFetch<ProcessListResponse>("/api/processes"),
  
  getDetail: (name: string) => apiFetch<ProcessDetail>(`/api/processes/${encodeURIComponent(name)}`),

  create: (data: {
    script: string;
    name?: string;
    interpreter?: string;
    env?: string[];
    watch?: boolean;
    reload?: boolean;
    mem?: string;
    cpu?: string;
  }) =>
    apiFetch<{ success: boolean; message: string }>("/api/processes", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  
  start: (name: string) =>
    apiFetch<{ success: boolean; message: string }>(`/api/processes/${encodeURIComponent(name)}/start`, {
      method: "POST",
    }),
    
  stop: (name: string) =>
    apiFetch<{ success: boolean; message: string }>(`/api/processes/${encodeURIComponent(name)}/stop`, {
      method: "POST",
    }),
    
  restart: (name: string) =>
    apiFetch<{ success: boolean; message: string }>(`/api/processes/${encodeURIComponent(name)}/restart`, {
      method: "POST",
    }),
    
  delete: (name: string) =>
    apiFetch<{ success: boolean; message: string }>(`/api/processes/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),
    
  setLimits: (name: string, memory?: string | null, cpu?: string | null) =>
    apiFetch<{ success: boolean }>(`/api/processes/${encodeURIComponent(name)}/limits`, {
      method: "PUT",
      body: JSON.stringify({ memory, cpu }),
    }),
    
  toggleWatch: (name: string) =>
    apiFetch<{ success: boolean; watch: string }>(`/api/processes/${encodeURIComponent(name)}/watch`, {
      method: "POST",
    }),
    
  toggleReload: (name: string) =>
    apiFetch<{ success: boolean; reload: string }>(`/api/processes/${encodeURIComponent(name)}/reload`, {
      method: "POST",
    }),
    
  getUnitContent: (name: string) =>
    apiFetch<{ content: string }>(`/api/processes/${encodeURIComponent(name)}/config`),
    
  updateUnitContent: (name: string, content: string) =>
    apiFetch<{ success: boolean }>(`/api/processes/${encodeURIComponent(name)}/config`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),
    
  getLogHistory: (name: string, lines: number = 100) =>
    apiFetch<{ lines: string[]; service: string }>(
      `/api/processes/${encodeURIComponent(name)}/logs/history?lines=${lines}`
    ),
};
