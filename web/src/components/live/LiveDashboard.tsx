"use client";

import { useRunEvents } from "@/lib/useRunEvents";
import { LiveView } from "./LiveView";

async function stop() {
  await fetch("/api/stop", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" }).catch(() => {});
}

export function LiveDashboard() {
  return <LiveView live={useRunEvents()} onStop={stop} />;
}
