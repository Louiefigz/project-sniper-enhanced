"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { fetchGuidedOpeningStatus, submitGuidedOpeningApproval } from "@/lib/producer/guided-opening-client";
import { GUIDED_OPENING_APPROVAL_ATTESTATIONS } from "@/lib/producer/contracts/guided-opening-approval-v1";
import type { GuidedOpeningStatusV1 } from "@/lib/producer/contracts/guided-opening-status-v1";
import { timingDuration } from "@/lib/producer/run-timing";
import { useCutCheckpoint } from "./use-cut-checkpoint";
import GuidedOpeningPlayer from "./guided-opening-player";
import type { OpeningLaunchStatus } from "@/lib/producer/guided-opening-launch-client";
import { useGuidedOpeningLaunch } from "./use-guided-opening-launch";

const LABELS: Record<GuidedOpeningStatusV1["state"], string> = {
  "unavailable": "No verified opening available",
  "pending-owned-execution": "Opening execution outcome is not yet verified",
  "pending-cleanup": "Opening stopped · resource cleanup pending",
  "failed": "Opening attempt failed · no selectable preview",
  "ready-for-review": "Opening available for review · not approved",
};

function OpeningTiming({ timing }: { timing: GuidedOpeningStatusV1["timing"] }) {
  return <div className="space-y-1 rounded border border-neutral-800 p-2 text-xs text-neutral-400">
    <p className="font-medium text-neutral-200">Recorded opening timing</p>
    {timing.elapsedStatus === "completed" ? <>
      <p>Owned attempt to verified stop: {timingDuration(timing.engineElapsedMs)}.</p>
      <p>Separate resource cleanup: {timingDuration(timing.cleanupElapsedMs)}.</p>
      <p>These measurements cover this attempt only. Earlier cut, proposal and review work are not included.</p>
    </> : <p>No verified stopped-attempt duration. Unknown time is not zero, and this status does not prove a worker is running.</p>}
    {timing.generationStartedAt && <p>Original generation request: <time dateTime={timing.generationStartedAt}>{timing.generationStartedAt}</time>.
      {" "}Rechecking does not restart that clock.</p>}
    <p>The two-hour full-video target is not a completion estimate or a quality approval.</p>
  </div>;
}

const ATTESTATION_LABELS: Record<typeof GUIDED_OPENING_APPROVAL_ATTESTATIONS[number], string> = {
  watchedOpening: "I watched the complete opening at full size.",
  watchedBodyTransition: "I watched the transition into the body context.",
  listened: "I listened to the audio with sound on.",
  approvesOpening: "I approve exactly this opening.",
  understandsBodyPending: "I understand the full body, whole-program review and delivery are not yet generated.",
};

type ReadyOpening = Extract<GuidedOpeningStatusV1, { state: "ready-for-review" }>;

/** Explicit human approval of THIS exact selection. It never launches body generation or delivery. */
export function GuidedOpeningApproval({ dir, opening, onApproved }: { dir: string; opening: ReadyOpening; onApproved: () => void }) {
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (opening.approval) return <p className="text-xs text-emerald-200">
    Operator approved this exact opening at <time dateTime={opening.approval.approvedAt}>{opening.approval.approvedAt}</time>.
    {" "}Body generation and delivery are separate, unstarted steps.</p>;
  const complete = GUIDED_OPENING_APPROVAL_ATTESTATIONS.every((key) => checked[key]);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await submitGuidedOpeningApproval(dir, { schemaVersion: 1, operation: "approve-guided-opening", idempotencyKey: crypto.randomUUID(),
        expectedToken: opening.journal.token, expectedJournalHash: opening.journal.sha256, selectionHash: opening.selectionHash,
        coreMediaSha256: opening.media.core.mediaSha256, reviewMediaSha256: opening.media.review.mediaSha256,
        attestation: Object.fromEntries(GUIDED_OPENING_APPROVAL_ATTESTATIONS.map((key) => [key, true])) }, new AbortController().signal);
      onApproved();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Opening approval was not confirmed"); }
    finally { setBusy(false); }
  };
  return <fieldset className="space-y-2 rounded border border-neutral-800 p-3" aria-label="Approve this exact opening">
    <legend className="px-1 text-xs font-medium text-neutral-200">Approve this exact opening</legend>
    {GUIDED_OPENING_APPROVAL_ATTESTATIONS.map((key) => <label key={key} className="flex items-start gap-2 text-xs text-neutral-300">
      <input type="checkbox" checked={Boolean(checked[key])} disabled={busy} onChange={(event) => setChecked({ ...checked, [key]: event.target.checked })} />
      <span>{ATTESTATION_LABELS[key]}</span>
    </label>)}
    <Button type="button" size="xs" disabled={!complete || busy} onClick={() => void submit()}>{busy ? "Verifying and recording approval…" : "Approve opening"}</Button>
    {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
    <p className="text-xs text-neutral-400">Approval re-verifies the exact sources, code and media before it is recorded. It does not start the full-body render.</p>
  </fieldset>;
}

/** Pure presentation is separately testable; it does not create approval, retry or launch authority. */
export function GuidedOpeningContent({ opening, dir, onApproved }: { opening: GuidedOpeningStatusV1; dir?: string; onApproved?: () => void }) {
  return <div className="space-y-3">
    <h3 className="text-sm font-medium">{opening.openingApproved ? "Opening approved by operator · body pending" : LABELS[opening.state]}</h3>
    <p className="text-sm text-neutral-300">{opening.detail}</p>
    {opening.state === "pending-owned-execution" && <p className="text-xs text-amber-200">
      Do not start a duplicate render. Recheck for an owned completion; a lost connection is not a stopped worker.
    </p>}
    {opening.state === "pending-cleanup" && <p className="text-xs text-amber-200">
      The process stopped, but its resources are not yet verified released. No preview can be selected.
    </p>}
    {opening.state === "ready-for-review" && <GuidedOpeningPlayer opening={opening} />}
    {opening.state === "ready-for-review" && dir && onApproved && <GuidedOpeningApproval dir={dir} opening={opening} onApproved={onApproved} />}
    <OpeningTiming timing={opening.timing} />
    <p className="text-xs text-amber-200">{opening.openingApproved
      ? "Opening approved by the operator. No body or delivery approval. Subjective listening has not been performed by the system."
      : "No opening or delivery approval. Subjective listening has not been performed by the system."}</p>
  </div>;
}

/** On-demand journal/receipt readback, never full-source polling or an automatic render retry. */
export default function GuidedOpeningPanel({ dir }: { dir: string }) {
  const checkpoint = useCutCheckpoint(dir, fetchGuidedOpeningStatus);
  return <section aria-label="HyperFrames opening review" className="mt-4 space-y-3 rounded border border-neutral-700 bg-neutral-950 p-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-base font-medium">HyperFrames opening review</h2>
      <Button type="button" size="xs" variant="outline" onClick={checkpoint.refresh}
        disabled={!checkpoint.error && !checkpoint.data}>Recheck opening evidence</Button>
    </div>
    <p className="text-sm text-neutral-300">Generate the supported opening, then inspect it before explicitly approving that opening. Full-video continuation is a separate step.</p>
    <p className="text-xs text-neutral-400">This is the last checked evidence, not continuous monitoring. Recheck if the project or sources change.</p>
    <GuidedOpeningLaunch key={dir} dir={dir} onEvidenceRefresh={checkpoint.refresh} />
    {checkpoint.error && <p role="alert" className="text-sm text-red-300">{checkpoint.error}</p>}
    {!checkpoint.error && !checkpoint.data && <p role="status" className="text-sm text-neutral-400">Checking opening state and current evidence…</p>}
    {checkpoint.elapsedMs !== null && <p className="text-xs text-neutral-400">
      Last status request: {(checkpoint.elapsedMs / 1000).toFixed(1)}s · {checkpoint.error ? "failed" : "completed"}.
      {" "}This is readback time, not generation time or approval.
    </p>}
    {checkpoint.data && <GuidedOpeningContent key={`${dir}:${checkpoint.revision}:${checkpoint.data.executionId ?? "none"}`}
      opening={checkpoint.data} dir={dir} onApproved={checkpoint.refresh} />}
  </section>;
}

interface LaunchView {
  status: OpeningLaunchStatus | null; busy: boolean; retry: boolean; recorded: boolean; paused: boolean;
  error: string | null; onGenerate: () => void; onRecheck: () => void;
}

/** Display only: eligibility enables one explicit action, not approval, liveness, or body generation. */
export function GuidedOpeningLaunchControls(props: LaunchView) {
  const { status, busy, retry, recorded, paused, error, onGenerate, onRecheck } = props;
  return <div aria-label="Generate private opening" className="space-y-2 rounded border border-neutral-800 p-3">
    <p className="text-sm font-medium">Generate and review the opening</p>
    <p className="text-xs text-neutral-400">Only the currently supported opening treatment can run. Captions, sound treatment and other requested features may still block generation.
      {" "}The full body, whole-program review and delivery remain separate, unfinished stages.</p>
    {status && <p className="text-sm text-neutral-300">{status.detail}</p>}
    {!status && !error && <p role="status" className="text-xs text-neutral-400">Checking opening launch eligibility…</p>}
    {(status?.state === "launch-recorded" || (recorded && !status)) && <p role="status" className="text-xs text-amber-200">
      Opening launch recorded. This does not prove that a worker is running, that media is ready, or that the opening is approved.
      {" "}Do not start a duplicate render.</p>}
    {status?.receivedAt && <p className="text-xs text-neutral-400">Request recorded: <time dateTime={status.receivedAt}>{status.receivedAt}</time>.</p>}
    <div className="flex flex-wrap gap-2">
      {status?.state === "eligible" && !recorded && <Button type="button" size="xs" disabled={busy} onClick={onGenerate}>
        {busy ? "Recording opening request…" : retry ? "Retry saved opening request" : "Generate opening"}
      </Button>}
      <Button type="button" variant="outline" size="xs" disabled={busy} onClick={onRecheck}>Recheck launch status</Button>
    </div>
    {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
    {paused && <p className="text-xs text-amber-200">Automatic metadata checks paused after their bounded window. Recheck manually; no duplicate request was submitted.</p>}
    <p className="text-xs text-neutral-400">Recorded launches get metadata-only checks every five seconds, for up to 25 minutes. Rechecking never restarts the server’s original deadline.</p>
  </div>;
}

export function GuidedOpeningLaunch({ dir, onEvidenceRefresh }: { dir: string; onEvidenceRefresh: () => void }) {
  const state = useGuidedOpeningLaunch(dir, onEvidenceRefresh);
  return <GuidedOpeningLaunchControls status={state.status} busy={state.busy} retry={Boolean(state.pending)} recorded={state.recorded}
    paused={state.paused} error={state.error ?? state.readError} onGenerate={() => void state.submit()}
    onRecheck={() => { state.refresh(); onEvidenceRefresh(); }} />;
}
