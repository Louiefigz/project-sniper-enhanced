"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { cutWaitLabel, fetchCutReview, type CutReviewDescription } from "@/lib/producer/cut-review-client";
import CutAcceptanceControls from "./cut-acceptance-controls";
import CutAcceptedPanel from "./cut-accepted-panel";
import { useCutCheckpoint } from "./use-cut-checkpoint";

function WaitingClock({ startedAt, stoppedAt }: { startedAt: string; stoppedAt: string | null }) {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const at = stoppedAt ? Date.parse(stoppedAt) : now;
  return <p className="text-xs text-neutral-400">{at == null ? "Reading waiting clock…" : cutWaitLabel(startedAt, at)}
    {stoppedAt ? " (stopped at your submission). Verification is system work." : ". Current waiting interval; prior attempts remain in the job history."}</p>;
}

function CutPlayer({ review, onPlayable }: { review: CutReviewDescription; onPlayable: (value: boolean) => void }) {
  const failed = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  return <>
    <video className="max-h-[55vh] w-full rounded bg-black" controls playsInline preload="metadata"
      aria-label="Reviewed cut preview, not a finished video" src={review.mediaUrl}
      onError={() => { failed.current = true; setReady(false); onPlayable(false);
        setError("The verified preview could not play. Recheck the cut; do not treat this as approval."); }}
      onLoadedMetadata={(event) => {
        const video = event.currentTarget;
        const matches = !failed.current && Number.isFinite(video.duration) && Math.abs(video.duration - review.durationSeconds) <= 0.1
          && video.videoWidth === review.width && video.videoHeight === review.height;
        if (!matches) { failed.current = true; video.pause(); setError("Playback dimensions or duration differ from the reviewed preview, or playback already failed."); }
        setReady(matches); onPlayable(matches);
      }} />
    <p role={error ? "alert" : "status"} className={error ? "text-sm text-red-300" : "text-xs text-neutral-400"}>
      {error ?? (ready ? "Ready to play. Loading this video does not record that you watched or approved it." : "Verifying playback…")}
    </p>
  </>;
}

function CutReviewContent({ dir, review, onStatusChanged }: {
  dir: string; review: CutReviewDescription; onStatusChanged?: () => void;
}) {
  const [playable, setPlayable] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  return <>
    <CutPlayer review={review} onPlayable={setPlayable} />
    <p className="text-xs text-amber-200">{review.caveat}</p>
    {submitted ? <p className="text-xs text-neutral-400">Decision submitted. Recheck for the server’s waiting and verification timing; the previous waiting clock is no longer current.</p>
      : <WaitingClock startedAt={review.waitStartedAt} stoppedAt={review.waitStoppedAt} />}
    {review.acceptanceState === "verifying" && <p role="status" className="text-sm">Your decision was received. Sniper is verifying the exact sources before accepting it.</p>}
    {review.acceptanceError && <p role="alert" className="text-sm text-red-300">{review.acceptanceError}</p>}
    <CutAcceptanceControls dir={dir} review={review} playable={playable}
      onStatusChanged={onStatusChanged} onSubmitted={() => setSubmitted(true)} />
  </>;
}

/** Receipt-bound playback, followed only by an explicit versioned human decision. */
export default function CutReviewPanel({ dir, onStatusChanged }: { dir: string; onStatusChanged?: () => void }) {
  const state = useCutCheckpoint(dir, fetchCutReview);
  const refresh = () => { state.refresh(); onStatusChanged?.(); };
  return <section aria-label="Cut review" className="space-y-3 rounded border border-neutral-700 bg-neutral-950 p-4">
    <div className="flex items-center justify-between gap-4">
      <h2 className="text-base font-medium">Review the story cut</h2>
      <Button type="button" size="xs" variant="outline" onClick={refresh}>Recheck cut preview</Button>
    </div>
    <p className="text-sm text-neutral-300">Check the hook, retained story, cut rhythm and audio edits before visual treatment.</p>
    {state.error && <p role="alert" className="text-sm text-red-300">{state.error}</p>}
    {!state.error && !state.data && <p role="status" className="text-sm">Checking the saved cut and exact preview…</p>}
    {state.elapsedMs !== null && <p className="text-xs text-neutral-400">Last cut evidence check: {(state.elapsedMs / 1000).toFixed(1)}s
      {state.error ? " · failed" : " · verified"}. Player loading is separate.</p>}
    {state.data && <CutReviewContent key={`${dir}:${state.data.receiptHash}:${state.revision}`}
      dir={dir} review={state.data} onStatusChanged={onStatusChanged} />}
  </section>;
}

export function CutReviewControl({ dir, accepted = false, onStatusChanged }: {
  dir: string; accepted?: boolean; onStatusChanged?: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => { if (open) dialog.current?.showModal(); else dialog.current?.close(); }, [open]);
  return <>
    <Button type="button" size="xs" onClick={() => setOpen(true)}>{accepted ? "Continue accepted cut" : "Review cut"}</Button>
    <dialog ref={dialog} aria-label="Review cut checkpoint" onClose={() => setOpen(false)}
      className="m-auto max-h-[95vh] w-[min(64rem,95vw)] overflow-auto rounded border border-neutral-700 bg-neutral-950 p-4 text-neutral-100 backdrop:bg-black/70">
      <div className="mb-3 flex justify-end"><Button type="button" variant="outline" size="xs" onClick={() => setOpen(false)}>Close cut review</Button></div>
      {open && (accepted ? <CutAcceptedPanel dir={dir} onStatusChanged={onStatusChanged} />
        : <CutReviewPanel dir={dir} onStatusChanged={onStatusChanged} />)}
    </dialog>
  </>;
}
