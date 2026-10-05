import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

// Schriften liegen im Projekt – beim Laden der Seite geht keine Anfrage an fremde Server.
const inter = localFont({
  src: "../fonts/inter-latin-wght-normal.woff2",
  variable: "--font-inter",
  weight: "100 900",
  display: "swap",
});
const grotesk = localFont({
  src: "../fonts/space-grotesk-latin-wght-normal.woff2",
  variable: "--font-grotesk",
  weight: "300 700",
  display: "swap",
});
const jetbrains = localFont({
  src: "../fonts/jetbrains-mono-latin-wght-normal.woff2",
  variable: "--font-jetbrains",
  weight: "100 800",
  display: "swap",
  preload: false,
});

export const metadata: Metadata = {
  title: { default: "LAST – Lasttest für KI-Server und Websites", template: "%s · LAST" },
  description: "Wie viele Personen halten euer KI-Server oder eure Website gleichzeitig aus? LAST misst es und erklärt das Ergebnis in einfachen Worten.",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

// Jede Seite bekommt eine eigene CSP-Nonce (src/proxy.ts) – deshalb nie statisch vorrendern.
export const dynamic = "force-dynamic";

export const viewport: Viewport = {
  themeColor: "#05060a",
  colorScheme: "dark",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="de" className={`${inter.variable} ${grotesk.variable} ${jetbrains.variable} antialiased`}>
      <body className="min-h-dvh">
        <a
          href="#inhalt"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:text-ink"
        >
          Zum Inhalt springen
        </a>
        <div className="aurora" aria-hidden="true" />
        {children}
      </body>
    </html>
  );
}
