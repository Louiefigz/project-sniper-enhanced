import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-6 text-foreground">
      <div className="max-w-lg text-center">
        <p className="label text-signal">PAGE NOT FOUND</p>
        <h1 className="mt-3 font-display text-3xl font-bold">This video tool does not exist.</h1>
        <p className="mt-3 text-sm text-muted-foreground">Return home to choose a workflow, or open Producer to create and revise a finished video.</p>
        <div className="mt-6 flex justify-center gap-3">
          <Link href="/" className="rounded-md border border-border px-4 py-2 text-sm hover:bg-card">Go home</Link>
          <Link href="/producer" className="rounded-md bg-signal px-4 py-2 text-sm font-semibold text-background">Open Producer</Link>
        </div>
      </div>
    </main>
  );
}
