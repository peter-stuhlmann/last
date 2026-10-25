import type { Metadata } from "next";
import Link from "next/link";
import { AppHeader } from "@/components/AppHeader";
import { RunsList } from "@/components/RunsList";
import { Trend } from "@/components/Trend";
import { getRuns } from "@/lib/backend";
import { isRunName } from "@/lib/security";

export const metadata: Metadata = { title: "Frühere Läufe" };
export const dynamic = "force-dynamic";

export default async function LaeufePage({ searchParams }: PageProps<"/laeufe">) {
  const [runs, params] = await Promise.all([getRuns(), searchParams]);
  const deleted = typeof params.geloescht === "string" && isRunName(params.geloescht) ? params.geloescht : null;
  return (
    <>
      <AppHeader
        crumbs={[{ label: "Frühere Läufe" }]}
        actions={
          <Link href="/?neu=1" className="btn btn-primary">
            <span aria-hidden="true">+</span> Neuer Test
          </Link>
        }
      />
      <main id="inhalt" className="mx-auto max-w-[1000px] px-4 py-10 sm:px-8">
        <h1 className="mb-6 font-display text-[34px] font-bold tracking-[-0.02em]">Frühere Läufe</h1>
        {runs ? (
          <>
            <RunsList runs={runs} deleted={deleted} />
            <Trend runs={runs} />
          </>
        ) : (
          <p role="alert" className="rounded-xl border border-amber/35 bg-amber/10 px-4 py-3 text-sm text-amber-soft">
            Das Test-Backend antwortet nicht. Läuft der Container „backend“?
          </p>
        )}
      </main>
    </>
  );
}
