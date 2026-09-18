"use client";

import Link from "next/link";

export default function GlobalError({ reset }: { reset: () => void }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-6 text-foreground">
      <div className="max-w-lg text-center">
        <p className="label text-destructive">SOMETHING WENT WRONG</p>
        <h1 className="mt-3 font-display text-3xl font-bold">This screen could not finish loading.</h1>
        <p className="mt-3 text-sm text-muted-foreground">Your local media was not deleted. Try the screen again; if it still fails, return home and reopen the project.</p>
        <div className="mt-6 flex justify-center gap-3">
          <button type="button" onClick={reset} className="rounded-md bg-signal px-4 py-2 text-sm font-semibold text-background">Try again</button>
          <Link href="/" className="rounded-md border border-border px-4 py-2 text-sm hover:bg-card">Go home</Link>
        </div>
      </div>
    </main>
  );
}
