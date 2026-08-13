"use client";

import useSWR from "swr";
import { SystemApi } from "@/lib/api/system";
import { SystemInfoResponse, SystemHealthResponse } from "@/lib/types";

export function useSystemInfo(refreshInterval: number = 5000) {
  const { data: info, error: infoError, isLoading: isInfoLoading } = useSWR<SystemInfoResponse>(
    "/api/system/info",
    SystemApi.getInfo,
    { refreshInterval }
  );

  const { data: health, error: healthError, isLoading: isHealthLoading } = useSWR<SystemHealthResponse>(
    "/api/system/health",
    SystemApi.getHealth,
    { refreshInterval: 10000 }
  );

  return {
    info,
    health,
    isLoading: isInfoLoading || isHealthLoading,
    error: infoError || healthError,
  };
}
