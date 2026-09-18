import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";

// Vendored OFL fonts (src/app/fonts/README.md): the build needs no network.
const display = localFont({
  variable: "--font-display",
  src: "./fonts/bricolage-grotesque-latin-wght-normal.woff2",
  weight: "200 800",
});

const sans = localFont({
  variable: "--font-sans",
  src: "./fonts/archivo-latin-wght-normal.woff2",
  weight: "100 900",
});

const mono = localFont({
  variable: "--font-mono",
  src: [
    { path: "./fonts/ibm-plex-mono-latin-400-normal.woff2", weight: "400" },
    { path: "./fonts/ibm-plex-mono-latin-500-normal.woff2", weight: "500" },
    { path: "./fonts/ibm-plex-mono-latin-600-normal.woff2", weight: "600" },
  ],
});

export const metadata: Metadata = {
  title: "PROJECT SNIPER — Create and Edit Videos",
  description:
    "Create finished videos from local footage, revise edits in plain language, send versions to Palmier, split recordings, and check on-screen text.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${display.variable} ${sans.variable} ${mono.variable} font-sans antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
