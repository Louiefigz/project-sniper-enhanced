"use client";

import { Button } from "@/components/ui/button";
import { fetchAcceptedCutStatus, type AcceptedCutStatus } from "@/lib/producer/cut-accepted-status-client";
import { useCutCheckpoint, useCutDecision } from "./use-cut-checkpoint";

function AcceptedContinuation({ dir, status, onStatusChanged }: {
  dir: string; status: AcceptedCutStatus; onStatusChanged?: () => void;
}) {
  const decision = useCutDecision(dir, onStatusChanged);
  const retry = () => {
    if (!status.canRetryContinuation || decision.running || decision.result) return;
    void decision.run(() => ({ schemaVersion: 1, operation: "retry-continuation",
      acceptanceHash: status.acceptanceHash, requestHash: status.requestHash }));
  };
  return <div className="space-y-2">
    <p className="text-sm">{status.state === "cut_accepted" ? "Your cut decision is saved, but a production worker has not been confirmed."
      : `Your cut decision is saved. Current worker state: ${status.state}.`}</p>
    <p className="text-xs text-amber-200">{status.caveat}</p>
    {status.canRetryContinuation && <Button type="button" size="xs" onClick={retry} disabled={decision.running || !!decision.result}>
      {decision.running ? "Verifying sources and retrying…" : "Retry continuation"}
    </Button>}
    {decision.error && <p role="alert" className="text-sm text-red-300">{decision.error}</p>}
    {decision.result && <p role="status" className="text-sm">{decision.result.state === "running"
      ? "Continuation worker confirmed. This is not final approval." : "Continuation remains pending. Recheck its status."}</p>}
    <p className="text-xs text-neutral-400">{status.timingState === "verified-activation"
      ? `The last human waiting interval stopped at ${status.waitStoppedAt}. Verification and worker launch are system work.`
      : "The last waiting interval is unverified for this older acceptance; it is not counted as zero."}</p>
    <p className="text-xs text-neutral-400">Original decision submitted at {status.decisionSubmittedAt}. Retry activation does not rewrite that decision.</p>
  </div>;
}

export default function CutAcceptedPanel({ dir, onStatusChanged }: { dir: string; onStatusChanged?: () => void }) {
  const state = useCutCheckpoint(dir, fetchAcceptedCutStatus);
  const refresh = () => { state.refresh(); onStatusChanged?.(); };
  return <section aria-label="Accepted cut continuation" className="space-y-3 rounded border border-neutral-700 bg-neutral-950 p-4">
    <div className="flex items-center justify-between gap-4">
      <h2 className="text-base font-medium">Continue the accepted cut</h2>
      <Button type="button" size="xs" variant="outline" onClick={refresh}>Recheck accepted cut</Button>
    </div>
    {state.error && <p role="alert" className="text-sm text-red-300">{state.error}</p>}
    {!state.data && !state.error && <p role="status" className="text-sm">Verifying the saved human decision and current worker state…</p>}
    {state.elapsedMs !== null && <p className="text-xs text-neutral-400">Last accepted-cut check: {(state.elapsedMs / 1000).toFixed(1)}s
      {state.error ? " · failed" : " · verified"}. This is not a generation or delivery time.</p>}
    {state.data && <AcceptedContinuation key={`${dir}:${state.revision}:${state.data.continuationAttempt}`}
      dir={dir} status={state.data} onStatusChanged={onStatusChanged} />}
  </section>;
}
