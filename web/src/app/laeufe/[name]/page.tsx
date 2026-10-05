import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { AppHeader, StatusPill, TargetChip } from "@/components/AppHeader";
import { ResultView } from "@/components/result/ResultView";
import { getRuns, getSummary } from "@/lib/backend";
import { clock, hostLabel, runLabel } from "@/lib/format";
import { isRunName } from "@/lib/security";

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: PageProps<"/laeufe/[name]">): Promise<Metadata> {
  const { name } = await params;
  return { title: isRunName(name) ? `Ergebnis ${runLabel(name)}` : "Ergebnis" };
}

export default async function ErgebnisPage({ params }: PageProps<"/laeufe/[name]">) {
  const { name } = await params;
  if (!isRunName(name)) notFound();
  const [summary, runs] = await Promise.all([getSummary(name), getRuns()]);
  if (!summary) notFound();

  const info = runs?.find((r) => r.name === name);
  const { started, finished } = summary.meta;
  const duration = started && finished ? (Date.parse(finished) - Date.parse(started)) / 1000 : null;
  const host = hostLabel(summary.config.base_url);

  return (
    <>
      <AppHeader
        crumbs={[
          { label: "Läufe", href: "/laeufe" },
          { label: `${host}${summary.config.model ? ` · ${summary.config.model}` : ""}` },
          { label: `Lauf ${runLabel(name)}` },
        ]}
        status={
          finished ? (
            <StatusPill tone="done" tag="Fertig" text={duration != null ? `Abgeschlossen in ${clock(duration)} min` : "Abgeschlossen"} />
          ) : (
            <StatusPill tone="warn" tag="Unvollständig" text="Lauf wurde nicht beendet" />
          )
        }
        actions={
          <>
            <TargetChip host={host} model={summary.config.model} />
            <Link href="/" className="btn btn-primary">
              <span aria-hidden="true">+</span> Neuer Test
            </Link>
          </>
        }
      />
      <main id="inhalt" className="mx-auto max-w-[1440px] px-4 py-8 sm:px-8">
        <ResultView name={name} summary={summary} report={info?.report ?? false} pdf={info?.pdf ?? false} />
      </main>
    </>
  );
}
