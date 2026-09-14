"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { ProjectIntent } from "@/lib/producer/intent-presets";

/** The optional app hands the same local packet to the conversational Producer. */
export function NativeShortLaunch({ dir, intent }: { dir: string; intent: ProjectIntent }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [packet, setPacket] = useState<{ handoff: string; directory: string } | null>(null);
  async function prepare() {
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/producer/native-short", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ dir }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Could not prepare the Short brief");
      setPacket(result);
    } catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  return <div className="space-y-3 rounded-lg border border-signal/25 bg-signal/5 p-4">
    <div className="flex items-start justify-between gap-4">
      <div><p className="text-sm font-medium">Create a Short with your edit assistant</p>
        <p className="mt-1 text-xs text-muted-foreground">{intent.shortDirection?.selection === "requested"
          ? intent.shortDirection.request : "Choose the treatment from my footage and the reference library."}</p>
        <p className="mt-1 text-xs text-muted-foreground">Prepare the footage and style request locally, then continue in your Codex task.</p></div>
      <Button disabled={busy} onClick={prepare}>{busy ? "Preparing…" : "Prepare Short brief"}</Button>
    </div>
    {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
    {packet && <div className="space-y-2">
      <p className="text-sm">The brief is ready. Paste it into your editing task to start the strategy and build.</p>
      <textarea aria-label="Short editing brief" readOnly rows={5} value={packet.handoff}
        className="w-full rounded border border-border bg-background p-2 text-xs" />
      <Button variant="outline" onClick={async () => {
        try { await navigator.clipboard.writeText(packet.handoff); }
        catch { setError("Select and copy the brief above; clipboard access was unavailable."); }
      }}>Copy editing brief</Button>
    </div>}
  </div>;
}
