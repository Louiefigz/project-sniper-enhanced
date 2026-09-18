"use client";

import { useState } from "react";
import { readEventStream, summarizeEvent } from "@/lib/producer/sse";
import type { CutSegment } from "@/lib/producer/edit-plan";
import type { StreamEvent } from "@/lib/producer/types";

interface Proposal {
  cutTrack: CutSegment[];
  segments: number;
  removedS: number;
}

interface Props {
  dir: string;
  onApply: (cutTrack: CutSegment[]) => void;
  onWarning?: (ev: StreamEvent) => void; // warning-class statuses → the editor's persistent strip
  locked?: boolean;
}

async function streamProposal(
  dir: string,
  onMsg: (m: string) => void,
  onWarning?: (ev: StreamEvent) => void,
): Promise<Proposal> {
  const res = await fetch("/api/producer/speech-cleanup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dir }),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.error || `speech-cleanup ${res.status}`);
  }
  let done: Proposal | null = null;
  let pyError: string | null = null; // python's own {"error": ...} line — the real cause
  await readEventStream(res, (ev) => {
    onWarning?.(ev); // the collector ignores non-warning statuses
    if (typeof ev.error === "string") pyError = ev.error;
    // The route's synthetic exit frame arrives AFTER python's {"error":...}
    // line — surface the python message (the real cause) when we have it.
    if (ev.event === "error") throw new Error(pyError ?? String(ev.message));
    if (ev.status === "done" && Array.isArray(ev.cutTrack)) {
      done = {
        cutTrack: ev.cutTrack as CutSegment[],
        segments: Number(ev.segments ?? (ev.cutTrack as CutSegment[]).length),
        removedS: Number(ev.removedS ?? 0),
      };
      return;
    }
    onMsg(summarizeEvent(ev));
  });
  // Prefer the python failure message over the generic no-proposal line so
  // the FINAL displayed msg says what actually broke.
  if (!done) throw new Error(pyError ?? "cleanup ended without a done proposal");
  return done;
}

// One-click pause/retake cleanup: runs edit/speech_cleanup.py (via the route),
// shows its proposed cutTrack as an explicit Apply/Dismiss decision — nothing
// touches the plan until the operator applies (and Apply is undo-able).
export default function SpeechCleanup({ dir, onApply, onWarning, locked }: Props) {
  const [state, setState] = useState<"idle" | "running" | "proposal" | "error">("idle");
  const [msg, setMsg] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null);

  const run = async () => {
    setState("running");
    setMsg("scanning…");
    try {
      const done = await streamProposal(dir, setMsg, onWarning);
      setProposal(done);
      setState("proposal");
    } catch (e) {
      setState("error");
      setMsg(e instanceof Error ? e.message : "speech cleanup failed");
    }
  };

  const apply = () => {
    if (proposal) onApply(proposal.cutTrack);
    setProposal(null);
    setState("idle");
    setMsg("Applied to the timeline · choose Render updated video to hear it");
  };

  if (state === "proposal" && proposal) {
    return (
      <span className="flex items-center gap-1.5 text-[11px] text-neutral-300">
        <span>
          proposal: {proposal.segments} segments, removes {proposal.removedS.toFixed(1)}s of
          pauses/retakes —
        </span>
        <button
          onClick={apply}
          className="rounded border border-emerald-500/50 px-1.5 py-px text-emerald-300 hover:bg-emerald-500/10"
        >
          Apply
        </button>
        <button
          onClick={() => {
            setProposal(null);
            setState("idle");
            setMsg("");
          }}
          className="text-neutral-500 hover:text-neutral-300"
        >
          Dismiss
        </button>
      </span>
    );
  }

  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <button
        onClick={run}
        disabled={locked || state === "running"}
        title="Scan the raw take for pauses + retakes and propose a tighter cutTrack"
        className="shrink-0 rounded border border-emerald-500/40 px-1.5 py-px text-[10px] text-emerald-300 enabled:hover:bg-emerald-500/10 disabled:opacity-50"
      >
        {state === "running" ? "Scanning…" : "Speech cleanup"}
      </button>
      {msg && (
        <span
          className={`truncate text-[10px] ${state === "error" ? "text-rose-400" : "text-neutral-500"}`}
          title={msg}
        >
          {msg}
        </span>
      )}
    </span>
  );
}
