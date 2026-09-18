"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { cutAcceptanceSubmission } from "@/lib/producer/cut-acceptance-client";
import { fetchPendingCutDecision } from "@/lib/producer/cut-pending-decision-client";
import type { CutReviewDescription } from "@/lib/producer/cut-review-client";
import { useCutDecision } from "./use-cut-checkpoint";

const CONFIRMATIONS = [
  "I watched this entire cut and checked the hook and story order.",
  "I listened to this entire cut and checked the audio edits.",
  "I accept this exact cut, including its retained content and timing.",
  "I understand the grade, graphics, final mix and delivery still need review.",
] as const;

function VerificationRecovery({ dir, review, onStatusChanged, onSubmitted }: {
  dir: string; review: CutReviewDescription; onStatusChanged?: () => void; onSubmitted?: () => void;
}) {
  const decision = useCutDecision(dir, onStatusChanged, onSubmitted);
  const retry = () => void decision.run((signal) => fetchPendingCutDecision({ dir, review, signal }));
  return <div className="space-y-2 border-t border-neutral-800 pt-3">
    <p className="text-sm">Verification is unconfirmed. If it was interrupted or its response was lost, you can explicitly retry the same saved decision.</p>
    <p className="text-xs text-neutral-400">This cannot make a new choice or bypass a live verifier. Sniper rechecks the project lease, exact preview and source bytes.</p>
    <p className="text-xs text-neutral-400">The original decision is recovered from this project, so recovery also works from a different tab. No new approval is inferred.</p>
    <Button type="button" size="xs" disabled={decision.running || !!decision.result} onClick={retry}>
      {decision.running ? "Rechecking saved decision…" : "Retry saved cut decision"}
    </Button>
    {decision.error && <p role="alert" className="text-sm text-red-300">{decision.error}</p>}
    {decision.result && <p role="status" className="text-sm">Cut acceptance is saved. Recheck project status for its continuation; final approval is still required.</p>}
  </div>;
}

/** User attestation is explicit and initially empty; media load/progress never checks these boxes. */
export default function CutAcceptanceControls({ dir, review, playable, onStatusChanged, onSubmitted }: {
  dir: string; review: CutReviewDescription; playable: boolean; onStatusChanged?: () => void; onSubmitted?: () => void;
}) {
  const [confirmed, setConfirmed] = useState<boolean[]>([false, false, false, false]);
  const decision = useCutDecision(dir, onStatusChanged, onSubmitted);
  const busy = decision.running || review.acceptanceState === "verifying";
  const accepted = decision.result !== null;
  const permitted = playable && confirmed.every(Boolean) && !busy && !accepted;
  const accept = () => {
    if (!permitted) return;
    void decision.run(() => cutAcceptanceSubmission({ review, storage: window.sessionStorage,
      newKey: () => window.crypto.randomUUID() }));
  };
  if (review.acceptanceState === "verifying") return <VerificationRecovery dir={dir} review={review}
    onStatusChanged={onStatusChanged} onSubmitted={onSubmitted} />;
  return <div className="space-y-3 border-t border-neutral-800 pt-3">
    <fieldset disabled={busy || accepted} className="space-y-2">
      <legend className="mb-2 text-sm font-medium">Your cut decision</legend>
      {CONFIRMATIONS.map((label, index) => <label key={label} className="flex items-start gap-2 text-sm text-neutral-300">
        <input type="checkbox" className="mt-1" checked={confirmed[index]}
          onChange={(event) => setConfirmed((previous) => previous.map((value, at) => at === index ? event.target.checked : value))} />
        <span>{label}</span>
      </label>)}
    </fieldset>
    <p className="text-xs text-neutral-400">Acceptance continues the brief already saved for this run. It does not approve a finished video or change your treatment instructions.</p>
    <Button type="button" size="xs" disabled={!permitted} onClick={accept}>
      {busy ? "Verifying decision and sources…" : accepted ? "Cut acceptance saved" : "Accept cut & continue saved brief"}
    </Button>
    {!playable && <p className="text-xs text-amber-200">Playback must be verified before you can accept this cut.</p>}
    {decision.running && <p role="status" className="text-xs text-neutral-400">Source verification is system work. Closing this view does not cancel the server transaction.</p>}
    {decision.error && <p role="alert" className="text-sm text-red-300">{decision.error} Recheck project status before retrying.</p>}
    {decision.result && <p role="status" className="text-sm text-amber-200">{decision.result.state === "running"
      ? "Cut accepted. The continuation worker has started; final quality checks are still required."
      : "Cut accepted. Continuation is pending; check project status for Retry continuation."}</p>}
  </div>;
}
