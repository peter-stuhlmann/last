"use client";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main id="inhalt" className="mx-auto max-w-xl px-4 py-16 text-center">
      <h1 className="font-display text-[34px] font-bold tracking-[-0.02em]">Da ist etwas schiefgegangen.</h1>
      <p className="mt-3 text-white/75">Die Seite konnte nicht geladen werden. Ein laufender Test ist davon nicht betroffen.</p>
      <p className="mt-6">
        <button type="button" className="btn btn-primary" onClick={reset}>
          Noch einmal versuchen
        </button>
      </p>
    </main>
  );
}
