"use client";

import { useEffect, useState, useRef } from "react";
import { ProcessApi } from "@/lib/api/processes";

export function useLogs(serviceName: string) {
  const [logs, setLogs] = useState<string[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!serviceName) return;

    // Load initial history
    ProcessApi.getLogHistory(serviceName, 100)
      .then((res) => {
        if (res.lines) setLogs(res.lines);
      })
      .catch((e) => console.error("Error loading log history:", e));

    // Connect SSE stream
    const url = `/api/processes/${encodeURIComponent(serviceName)}/logs`;
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onopen = () => {
      setIsConnected(true);
      setError(null);
    };

    es.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data);
        if (parsed.line) {
          setLogs((prev) => [...prev.slice(-1500), parsed.line]);
        }
        if (parsed.error) {
          setError(parsed.error);
        }
      } catch (e) {
        if (event.data) {
          setLogs((prev) => [...prev.slice(-1500), event.data]);
        }
      }
    };

    es.onerror = () => {
      setIsConnected(false);
    };

    return () => {
      es.close();
    };
  }, [serviceName]);

  const clearLogs = () => setLogs([]);

  return {
    logs,
    isConnected,
    error,
    clearLogs,
  };
}
