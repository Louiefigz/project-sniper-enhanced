"use client";

import OpenPalmierButton from "./open-palmier-button";
import {
  candidateActionLabel,
  candidateActionTitle,
} from "@/lib/producer/candidate-qc-action";
import { useCandidateQc } from "./use-candidate-qc";

export default function CandidateQcControls({
  dir,
  disabled,
  mode,
  onChanged,
}: {
  dir: string;
  disabled: boolean;
  mode?: "short" | "longform";
  onChanged: () => void;
}) {
  const { state, working, message, act } = useCandidateQc(dir, onChanged);

  const candidate = state && state.state !== "none";
  const preserved = state?.state === "rejected" || state?.state === "quarantined";
  const openLabel = preserved ? "Open preserved parent"
    : state?.state === "stale" ? "Review stale candidate"
      : candidate ? "Review candidate" : "Open in Palmier";
  const durableActive = state?.run.active === true;
  const durableAction = durableActive ? state?.run.action ?? null : null;
  const activeAction = working ?? durableAction;
  const actionActive = working != null || durableActive;
  const busy = disabled || actionActive;
  return (
    <span className="flex items-center gap-1">
      <OpenPalmierButton
        dir={dir}
        disabled={busy}
        mode={mode}
        label={openLabel}
        onOpened={onChanged}
      />
      {actionActive && (
        <button type="button" disabled title={candidateActionTitle(activeAction)}
          className="rounded border border-amber-700 px-2 py-0.5 text-amber-300 opacity-70">
          {candidateActionLabel(activeAction)}
        </button>
      )}
      {!activeAction && state?.canRunQc && (
        <button type="button" disabled={busy} onClick={() => void act("run_qc")}
          title="Export the exact candidate, run deterministic Audit B, then independent composition and editorial reviews. This does not promote it."
          className="rounded border border-amber-700 px-2 py-0.5 text-amber-300 disabled:opacity-40">
          Run candidate QC
        </button>
      )}
      {!activeAction && state?.canPromote && (
        <button type="button" disabled={busy} onClick={() => void act("promote")}
          title="Freshly recheck the approved candidate and parent, then make it the Palmier working head."
          className="rounded border border-emerald-700 px-2 py-0.5 text-emerald-300 disabled:opacity-40">
          Use approved candidate
        </button>
      )}
      {!activeAction && state?.canDiscard && (
        <button type="button" disabled={busy} onClick={() => void act("discard")}
          title="Archive this candidate and its QC evidence, then restore and verify the exact parent. Nothing is promoted."
          className="rounded border border-neutral-700 px-2 py-0.5 text-neutral-300 disabled:opacity-40">
          Discard candidate & keep parent
        </button>
      )}
      {(message || state?.run.message || state?.state === "stale") && (
        <span className="max-w-96 truncate text-neutral-400"
          title={message || state?.run.message || state?.detail}>
          {message || state?.run.message || state?.detail}
        </span>
      )}
    </span>
  );
}
