"use client";

import useSWR from "swr";
import { ProcessApi } from "@/lib/api/processes";
import { ProcessListResponse } from "@/lib/types";

export function useProcesses(refreshInterval: number = 3000) {
  const { data, error, isLoading, mutate } = useSWR<ProcessListResponse>(
    "/api/processes",
    ProcessApi.list,
    {
      refreshInterval,
      revalidateOnFocus: true,
      dedupingInterval: 1000,
    }
  );

  return {
    processes: data?.processes || [],
    total: data?.total || 0,
    online: data?.online || 0,
    stopped: data?.stopped || 0,
    isLoading,
    error,
    refresh: mutate,
  };
}
