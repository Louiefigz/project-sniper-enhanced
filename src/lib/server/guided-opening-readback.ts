import path from "node:path";
import { randomUUID } from "node:crypto";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { readCommittedOpeningCleanup } from "./guided-opening-cleanup-store";
import { readGuidedProposalReadiness } from "./guided-proposal-review-store";
import { openingChildTools, invokeOpeningChild } from "./guided-opening-process";
import { assertHeldOpeningResultUnchanged, assertOpeningReadbackIdentity, assertSupportedOpeningMediaProcess,
  openingReadbackReceiptArguments, readHeldOpeningResult } from "./guided-opening-result";
import { createOpeningRecord, assertOpeningRecord } from "./guided-opening-process-activation";
import { createHumanCutIndex, humanCutDirectory, observeHumanCutJob } from "./human-cut-acceptance-store";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { retainGenerationClockObservation } from "./generation-clock-watermark";
import { withStageTimingContext } from "./stage-timing-context";
import { timedStage } from "./stage-timing";
import type { ProjectMutationLease } from "./project-mutation-lease";

export interface ReadbackInput { dir: string; lease: ProjectMutationLease; expectedCleanupHash: string; remainingMs: () => number }

function readbackAttempt(input: ReadbackInput) {
  const observed = readCommittedOpeningCleanup(input.dir);
  assertSupportedOpeningMediaProcess(observed.evidence.stop);
  const lease = cutPreviewLeaseGuard(input.dir, input.lease);
  if (observed.cleanupHash !== input.expectedCleanupHash || observed.job.guidedHandoffV2?.openingExecutionClaimHash) {
    throw new Error("Opening readback requires exact committed cleanup with no newer owned execution");
  }
  const guard = () => {
    lease(); input.remainingMs();
    if (observeHumanCutJob(input.dir).sha256 !== observed.sha256) throw new Error("Opening readback journal changed");
  };
  guard(); readGuidedProposalReadiness(input.dir); guard();
  const selected = readHeldOpeningResult(observed.held), tools = openingChildTools(observed.held, "read");
  const directory = humanCutDirectory(humanCutDirectory(path.dirname(observed.held.claimPath), "readback-attempts"), randomUUID());
  const start = createOpeningRecord(path.join(directory, "start.json"), { schemaVersion: 1, kind: "guided-opening-readback-start",
    beforeJournalHash: observed.sha256, cleanupHash: observed.cleanupHash, claimHash: observed.held.claimHash,
    executionId: observed.held.claim.executionId, receiptSha256: selected.completion.receiptSha256, tools,
    clockHash: observed.held.claim.clockHash, generationStartedAt: observed.held.claim.generationStartedAt, startedAt: new Date().toISOString() });
  return { observed, guard, selected, tools, directory, start };
}

async function actualRead(input: ReadbackInput, attempt: ReturnType<typeof readbackAttempt>) {
  const { observed, guard, selected, tools } = attempt, held = observed.held, mono = performance.now();
  guard();
  const value = await invokeOpeningChild({ held, tools, kind: "read", remainingMs: input.remainingMs,
    extraArgs: openingReadbackReceiptArguments(selected) });
  const output = createOpeningRecord(path.join(attempt.directory, "output.json"), { schemaVersion: 1, kind: "guided-opening-readback-owned-output",
    ...value, processGroupStopped: true, observedAt: new Date().toISOString(), elapsedMs: performance.now() - mono });
  const result = assertOpeningReadbackIdentity(value.stdout, { held, selected });
  if (canonicalJsonSha256(openingChildTools(held, "read")) !== canonicalJsonSha256(tools)) throw new Error("Opening readback executable closure changed");
  assertHeldOpeningResultUnchanged(held, selected); assertOpeningRecord(attempt.start); assertOpeningRecord(output); guard();
  const currentCleanup = readCommittedOpeningCleanup(input.dir);
  if (currentCleanup.sha256 !== observed.sha256 || currentCleanup.cleanupHash !== observed.cleanupHash) throw new Error("Opening cleanup changed during readback");
  guard();
  const receipt = createOpeningRecord(path.join(attempt.directory, "verified.json"), { schemaVersion: 1, kind: "guided-opening-owned-readback",
    scope: "actual-current-readback-not-selected-or-approved", beforeJournalHash: observed.sha256, cleanupHash: observed.cleanupHash,
    claimHash: held.claimHash, startSha256: attempt.start.sha256, outputSha256: output.sha256, result,
    clockHash: held.claim.clockHash, generationStartedAt: held.claim.generationStartedAt, createdAt: new Date().toISOString(),
    mediaSelected: false, openingApproved: false, deliveryApproved: false });
  assertOpeningRecord(receipt); assertOpeningRecord(output); assertHeldOpeningResultUnchanged(held, selected); guard();
  return { observed, selected, result, receipt, output, mediaSelected: false as const, openingApproved: false as const, deliveryApproved: false as const };
}

/** Actual current-media verification only, under the original request remainder. No public playback selection or approval. */
export async function verifyCleanedOpeningMediaUnderLease(input: ReadbackInput) {
  const attempt = readbackAttempt(input), held = attempt.observed.held;
  try {
    return await withStageTimingContext({ runId: held.job.artifactToken ?? held.job.token,
      attemptId: `opening-readback:${held.claim.executionId}:${path.basename(attempt.directory)}`, attemptNo: held.job.attempts }, () =>
      timedStage(input.dir, "guided_opening_current_media_readback", () => actualRead(input, attempt)));
  } catch (error) {
    recordOpeningReadbackFailure({ input, held, directory: attempt.directory, error, schemaVersion: 1 });
    throw error;
  }
}

/** Retain actual failure/settlement facts without renewing work or inferring media approval. */
export function recordOpeningReadbackFailure(context: { input: ReadbackInput; held: ReturnType<typeof readCommittedOpeningCleanup>["held"];
  directory: string; error: unknown; schemaVersion: 1 | 2 }): void {
  const { input, held, directory, error, schemaVersion } = context;
  let clockError: string | null = null;
  try { retainGenerationClockObservation({ dir: input.dir, origin: { clockHash: held.claim.clockHash, startedAt: held.claim.generationStartedAt },
    executionId: held.claim.executionId, observedAt: new Date().toISOString() }, cutPreviewLeaseGuard(input.dir, input.lease)); }
  catch (failure) { clockError = String(failure).slice(0, 2000); }
  createHumanCutIndex(path.join(directory, "failure.json"), { schemaVersion, kind: "guided-opening-readback-failure",
    observedAt: new Date().toISOString(), error: String(error).slice(0, 4000), clockError,
    ...(error instanceof CutPreviewProcessError ? error.details : {}), mediaSelected: false, openingApproved: false, deliveryApproved: false });
}
