export default function Loading() {
  return (
    <main className="flex min-h-[60vh] items-center justify-center bg-background px-6 text-foreground">
      <div role="status" aria-live="polite" className="text-center">
        <span className="mx-auto block size-5 animate-spin rounded-full border-2 border-border border-t-signal" />
        <p className="mt-3 text-sm text-muted-foreground">Loading your video workspace…</p>
      </div>
    </main>
  );
}
