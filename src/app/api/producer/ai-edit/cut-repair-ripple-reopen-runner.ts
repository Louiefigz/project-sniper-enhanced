import { parseProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import { parseCutRepairRippleAnalysisV1 } from
  "@/lib/producer/contracts/cut-repair-ripple-analysis";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import {
  loadCutRepairRippleReopenActionSync,
  recoverCutRepairRippleReopenSync,
  reopenCutRepairForRippleSync,
} from "@/lib/server/cut-repair-ripple-reopen-store";
import type { CutRepairTransitionOutcome } from
  "@/lib/server/cut-repair-transition-model";
import { assertCutRepairRippleRecoverySync } from
  "@/lib/server/cut-repair-transition-reconciliation";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
} from "@/lib/server/producer-authority-files";
import { resolveProducerAuthorityHeadSync } from
  "@/lib/server/producer-revision-head";
import { runCutRepairAnalysis } from "./cut-repair-route-runner";
import type { CutRepairDirectiveV1 } from "./cut-repair-route-policy";

function completedOutcome(
  outcome: CutRepairTransitionOutcome,
): asserts outcome is CutRepairTransitionOutcome & { receiptHash: string } {
  if (!["committed", "replayed"].includes(outcome.status)
      || !outcome.receiptHash) {
    throw new Error("ripple picture-lock reopen did not commit");
  }
}

function response(
  action: NonNullable<ReturnType<
    typeof loadCutRepairRippleReopenActionSync
  >>,
  outcome: CutRepairTransitionOutcome & { receiptHash: string },
): Record<string, unknown> {
  const impact = action.analysis.rippleImpact;
  return {
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    routeStatus: "picture-lock-reopened-for-ripple",
    parentRevisionHash: action.expectedParentRevisionHash,
    reopenedRevisionHash: outcome.childRevisionHash,
    reopenReceiptHash: outcome.receiptHash,
    analysisHash: action.analysisHash,
    impactHash: action.impactHash,
    rippleImpact: impact,
    affectedDependentIds: [
      ...impact.movedDependents.map((item) => item.stableId),
      ...impact.invalidatedDependents,
    ],
    unchangedOutputLockedIds: impact.unchangedOutputLockedIds,
    rippleEditApplied: false,
    nextWorkflowState: "CUT_DRAFT",
    replayed: outcome.status === "replayed",
  };
}

function proposedAction(
  producerDir: string,
  directive: CutRepairDirectiveV1,
  analysisValue: unknown,
): Record<string, unknown> {
  const analysis = parseCutRepairRippleAnalysisV1(analysisValue);
  const paths = producerAuthorityPaths(producerDir);
  const head = resolveProducerAuthorityHeadSync(producerDir);
  if (head !== analysis.parentRevisionHash) {
    throw new Error("ripple analysis no longer targets the selected revision");
  }
  const parent = parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions, head));
  if (parent.schemaVersion !== 2
      || parent.workflowState !== "PICTURE_LOCKED"
      || !parent.pictureLockHash) {
    throw new Error(
      "ripple reopen requires exact V2 PICTURE_LOCKED authority");
  }
  return {
    schemaVersion: 1,
    kind: "cut-repair-ripple-reopen-action",
    idempotencyKey: directive.idempotencyKey,
    expectedParentRevisionHash: head,
    parentPictureLockHash: parent.pictureLockHash,
    target: directive.target,
    targetHash: canonicalJsonSha256(directive.target),
    analysis,
    analysisHash: canonicalJsonSha256(analysis),
    impactHash: canonicalJsonSha256(analysis.rippleImpact),
    preservedPlanObjectHash: parent.planObjectHash,
    preservedPlanContentHash: parent.planContentHash,
    preservedTimelineMapHash: parent.timelineMapHash,
    preservedRenderGraphHash: parent.renderGraphHash,
    preservedProjectionReceiptHash: parent.projectionReceiptHash,
    requestedAt: directive.requestedAt,
  };
}

function recoverExisting(
  producerDir: string,
  directive: CutRepairDirectiveV1,
): Record<string, unknown> | null {
  const action = loadCutRepairRippleReopenActionSync(
    producerDir, directive.idempotencyKey!);
  if (!action) return null;
  const targetHash = canonicalJsonSha256(directive.target);
  const recovered = recoverCutRepairRippleReopenSync(
    producerDir, directive.idempotencyKey!, targetHash);
  completedOutcome(recovered);
  return response(action, recovered);
}

/**
 * Reopen exact picture-lock authority; this deliberately does not apply ripple.
 */
export async function runCutRepairRippleReopen(
  producerDir: string,
  manifestPath: string,
  directive: CutRepairDirectiveV1,
): Promise<Record<string, unknown>> {
  if (directive.mode !== "reopen"
      || !directive.idempotencyKey || !directive.requestedAt) {
    throw new Error("cut repair ripple reopen requires identity and requestedAt");
  }
  assertCutRepairRippleRecoverySync(
    producerDir, directive.idempotencyKey);
  const recovered = recoverExisting(producerDir, directive);
  if (recovered) return recovered;
  const analysis = await runCutRepairAnalysis(
    producerDir, manifestPath, directive);
  const action = proposedAction(producerDir, directive, analysis);
  const reopened = reopenCutRepairForRippleSync({ producerDir, action });
  completedOutcome(reopened);
  const stored = loadCutRepairRippleReopenActionSync(
    producerDir, directive.idempotencyKey);
  if (!stored) throw new Error("committed ripple reopen action is missing");
  return response(stored, reopened);
}
