import { apiFetch } from "./client";
import { TunnelListResponse } from "../types";

export const TunnelApi = {
  list: () => apiFetch<TunnelListResponse>("/api/tunnels"),
  
  open: (port: number, provider?: string) =>
    apiFetch<{ port: number; url: string; hash?: string; provider?: string }>("/api/tunnels", {
      method: "POST",
      body: JSON.stringify({ port, provider }),
    }),
    
  close: (port: number) =>
    apiFetch<{ success: boolean }>(`/api/tunnels/${port}`, {
      method: "DELETE",
    }),
};
