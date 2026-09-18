import assert from "node:assert/strict";
import path from "node:path";
import { atomicWriteJsonSync } from "../atomic-file";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { reconcileClaimedOpeningUnderLease, type OpeningCleanupTestFaults } from "../guided-opening-cleanup";
import { readGuidedOpeningExecutionClaim } from "../guided-opening-claim";
import { readStoppedOpeningProcess } from "../guided-opening-process";
import { createHumanCutIndex } from "../human-cut-acceptance-store";

type CleanupInput = Parameters<typeof reconcileClaimedOpeningUnderLease>[0];
type Records = Parameters<NonNullable<OpeningCleanupTestFaults["afterOwnedCleanup"]>>[0];
type Fault = "held-start-mutation" | "held-output-mutation" | "second-cas-clock-rollback";

function injectFault(fault: Fault, records: Records, createdAt: string) {
  if (fault === "second-cas-clock-rollback") return new Date(Date.parse(createdAt) - 1).toISOString();
  const held = fault === "held-start-mutation" ? records.start : records.output;
  const mutated = { ...held.value, TEST_ONLY_CORRUPTION: fault };
  createHumanCutIndex(path.join(records.directory, "TEST-before-mutation.json"), { path: held.path, sha256: held.sha256, value: held.value });
  atomicWriteJsonSync(held.path, mutated);
  createHumanCutIndex(path.join(records.directory, "TEST-retained-mutation.json"), { path: held.path, value: mutated });
}

async function failedCleanup(input: CleanupInput, fault: Fault, retryNo: number) {
  const before = readGuidedOpeningExecutionClaim(input.dir), stop = readStoppedOpeningProcess(before);
  const started = performance.now(); let records: Records | undefined, guards = 0;
  const expected = fault === "second-cas-clock-rollback" ? /wall clock moved backwards/ : /changed/;
  await assert.rejects(reconcileClaimedOpeningUnderLease(input, {
    afterOwnedCleanup: (value) => { records = value; },
    beforeFinalCas: ({ invocation, createdAt }) => {
      guards = invocation;
      if (invocation !== 2) return;
      assert.ok(records, "Fault is allowed only after actual owned cleanup returned");
      return injectFault(fault, records, createdAt);
    },
  }), expected);
  assert.ok(records); assert.equal(guards, 2, "Fail at final second CAS, not an earlier test-only guard");
  const after = readGuidedOpeningExecutionClaim(input.dir);
  assert.equal(after.sha256, before.sha256); assert.equal(after.claimHash, before.claimHash);
  assert.equal(readStoppedOpeningProcess(after).receiptSha256, stop.receiptSha256);
  const failurePath = path.join(records.directory, "failure.json"), failure = readCutPreviewObject(failurePath);
  assert.equal(failure.value.claimCleared, false); assert.equal(failure.value.cleanupAttemptId, records.attemptId);
  const result = { scope: "TEST-only-real-owned-cleanup-CAS-fault-not-media-or-approval", fault, cleanupRetryNo: retryNo,
    attemptId: records.attemptId, failurePath, failureSha256: failure.sha256, beforeJournalHash: before.sha256,
    afterJournalHash: after.sha256, stoppedOutcomeSha256: stop.receiptSha256,
    actualCleanupElapsedMs: records.output.value.elapsedMs, testWallElapsedMs: performance.now() - started,
    secondCasReached: true, claimRetained: true, openingApproved: false, deliveryApproved: false };
  createHumanCutIndex(path.join(records.directory, "TEST-FAULT-RETAINED.json"), result);
  return result;
}

/** Explicit TEST invocation: real stopped worker and four real cleanups; no media rerender, fake stop, or restored failed artifact. */
export async function runOpeningCleanupCasFaults(input: CleanupInput) {
  const held = readGuidedOpeningExecutionClaim(input.dir), results = [];
  const faults: Fault[] = ["held-start-mutation", "held-output-mutation", "second-cas-clock-rollback"];
  for (const [index, fault] of faults.entries()) results.push(await failedCleanup(input, fault, index + 1));
  const started = performance.now(), cleanup = await reconcileClaimedOpeningUnderLease(input);
  for (const row of results) assert.equal(readCutPreviewObject(row.failurePath).sha256, row.failureSha256);
  createHumanCutIndex(path.join(path.dirname(held.claimPath), "TEST-CLEANUP-FAULT-COHORT.json"), {
    scope: "TEST-only-actual-owned-cleanup-and-CAS-not-media-or-approval", executionId: held.claim.executionId,
    claimHash: held.claimHash, mediaRenders: 1, cleanupAttempts: 4, failures: results,
    finalCleanupHash: cleanup.cleanupHash, finalCleanupWallElapsedMs: performance.now() - started,
    priorFailuresRetained: true, openingApproved: false, deliveryApproved: false,
  });
  return cleanup;
}
