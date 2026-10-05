import type { Metadata } from "next";
import { LiveDashboard } from "@/components/live/LiveDashboard";

export const metadata: Metadata = { title: "Test läuft" };
export const dynamic = "force-dynamic";

export default function LaufPage() {
  return <LiveDashboard />;
}
