import { apiFetch } from "./client";
import { SshSessionItem, SshSessionListResponse } from "../types";

export interface CreateSshSessionParams {
  port?: number;
  title?: string;
  password?: string;
  provider?: string;
  noTunnel?: boolean;
}

export const SshApi = {
  list: () => apiFetch<SshSessionListResponse>("/api/ssh"),

  create: (params: CreateSshSessionParams = {}) =>
    apiFetch<SshSessionItem>("/api/ssh", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  close: (port: number | "all") =>
    apiFetch<{ success: boolean }>(`/api/ssh/${port}`, {
      method: "DELETE",
    }),

  renameTitle: (port: number, title: string) =>
    apiFetch<{ success: boolean; port: number; title: string }>(`/api/ssh/${port}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
};
