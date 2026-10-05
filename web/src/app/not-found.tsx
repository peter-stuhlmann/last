import Link from "next/link";
import { AppHeader } from "@/components/AppHeader";

export default function NotFound() {
  return (
    <>
      <AppHeader crumbs={[{ label: "Nicht gefunden" }]} />
      <main id="inhalt" className="mx-auto max-w-xl px-4 py-16 text-center">
        <h1 className="font-display text-[34px] font-bold tracking-[-0.02em]">Diese Seite gibt es nicht.</h1>
        <p className="mt-3 text-white/75">Vielleicht wurde der Lauf gelöscht oder die Adresse ist vertippt.</p>
        <p className="mt-6 flex justify-center gap-3">
          <Link href="/" className="btn btn-primary">
            Neuer Test
          </Link>
          <Link href="/laeufe" className="btn btn-ghost">
            Frühere Läufe
          </Link>
        </p>
      </main>
    </>
  );
}
