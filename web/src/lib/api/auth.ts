import { apiFetch } from "./client";

export const AuthApi = {
  getMe: () => apiFetch<{ authenticated: boolean; isConfigured: boolean; user?: any }>("/api/auth/me"),
  
  setup: (password: string) =>
    apiFetch<{ ok: boolean }>("/api/auth/setup", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
    
  login: (password: string) =>
    apiFetch<{ ok: boolean }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
    
  logout: () =>
    apiFetch<{ ok: boolean }>("/api/auth/logout", {
      method: "POST",
    }),
    
  changePassword: (currentPassword: string, newPassword: string) =>
    apiFetch<{ ok: boolean; message: string }>("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ currentPassword, newPassword }),
    }),
};
