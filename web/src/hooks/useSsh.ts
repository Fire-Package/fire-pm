"use client";

import useSWR from "swr";
import { SshApi } from "@/lib/api/ssh";
import { SshSessionListResponse } from "@/lib/types";

export function useSsh(refreshInterval: number = 3000) {
  const { data, error, isLoading, mutate } = useSWR<SshSessionListResponse>(
    "/api/ssh",
    SshApi.list,
    {
      refreshInterval,
      revalidateOnFocus: true,
    }
  );

  return {
    sessions: data?.sessions || [],
    total: data?.total || 0,
    online: data?.online || 0,
    isLoading,
    error,
    refresh: mutate,
  };
}
