"use client";

import useSWR from "swr";
import { TunnelApi } from "@/lib/api/tunnels";
import { TunnelListResponse } from "@/lib/types";

export function useTunnels(refreshInterval: number = 3000) {
  const { data, error, isLoading, mutate } = useSWR<TunnelListResponse>(
    "/api/tunnels",
    TunnelApi.list,
    {
      refreshInterval,
      revalidateOnFocus: true,
    }
  );

  return {
    tunnels: data?.tunnels || [],
    total: data?.total || 0,
    online: data?.online || 0,
    pending: data?.pending || 0,
    isLoading,
    error,
    refresh: mutate,
  };
}
