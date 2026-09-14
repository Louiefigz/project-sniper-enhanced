"use client";

import { useState } from "react";
import { Loader2, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { isGuidedCheckpoint } from "@/lib/producer/guided-checkpoint-state";
import { ingestInto, type IngestedPayload } from "./stage-ingest";
import type { ProjectStatus } from "./use-project-status";

async function post(url: string, body: Record<string, unknown>) {
  const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.error === "string" ? result.error : "Could not add supporting media");
  return result;
}

/** Add before cut acceptance; rescan preserves speech and never invokes transcription. */
export function SupportingMediaControl({ status, onIngested }: {
  status: ProjectStatus; onIngested?: (payload: IngestedPayload) => void;
}) {
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(""), [error, setError] = useState("");
  const blocked = status.run?.status === "running" || isGuidedCheckpoint(status.run);
  const add = async () => {
    if (busy || blocked || !status.sourceDir || !status.projectRoot) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const picked = await post("/api/producer/pick-file", { kind: "file", purpose: "supporting", prompt: "Choose supporting image or video" });
      if (picked.canceled) return;
      const staged = await post("/api/producer/supporting-media", { dir: status.producerDir, inputPath: picked.path });
      setMessage("File added. Checking media and preserving the current transcript…");
      try {
        await ingestInto(staged.sourceDir, status.projectRoot, onIngested, { reuseTranscripts: true });
      } catch (reason) {
        setMessage("File remains in the source B-roll folder. Media preparation is incomplete."); throw reason;
      }
      setMessage("Supporting media prepared. Prepare a new Short brief to include it.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not add supporting media"); }
    finally { setBusy(false); }
  };
  if (!status.sourceDir || !status.projectRoot) return null;
  return <div className="mt-2 text-xs">
    <Button variant="outline" size="xs" disabled={blocked || busy} onClick={() => void add()}
      title={blocked ? "Add supporting media before accepting the guided cut, or use a new project" : "PNG, JPEG, WebP, MP4 or MOV; up to 1 GiB"}>
      {busy ? <Loader2 className="size-3 animate-spin" /> : <Plus className="size-3" />} Add supporting image or video
    </Button>
    {!blocked && <p className="mt-1 text-muted-foreground">
      PNG, JPEG or WebP images; MP4 or MOV video, up to 1 GiB. Add these before accepting the cut.
    </p>}
    {message && <p role="status" className="mt-1 text-muted-foreground">{message}</p>}
    {error && <p role="alert" className="mt-1 text-destructive">{error}</p>}
  </div>;
}
