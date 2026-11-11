"use client";

import { useEffect, useState } from "react";

import { getHealth } from "@/lib/api";

export function HealthStatus() {
  const [status, setStatus] = useState("checking…");

  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then((health) => {
        if (!cancelled) setStatus(health.status);
      })
      .catch(() => {
        if (!cancelled) setStatus("unreachable");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <p role="status" className="font-mono text-sm text-zinc-500 dark:text-zinc-400">
      API: {status}
    </p>
  );
}
