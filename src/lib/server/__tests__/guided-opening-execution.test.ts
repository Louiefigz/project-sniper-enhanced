import assert from "node:assert/strict";
import { test } from "node:test";
import { executeGuidedOpeningUnderLease, openingExecutionDependencies, type OpeningExecutionInput } from "../guided-opening-execution";

/** TEST-ONLY protocol doubles: these never render media or mint real approval receipts. */
function fixture() {
  const calls: string[] = [], hash = "a".repeat(64);
  const input = { proposal: { job: { ctx: { dir: "/TEST/producer" } } }, lease: {},
    operation: { record: { submission: { schemaVersion: 1, operation: "prepare-guided-opening",
      idempotencyKey: "11111111-1111-4111-8111-111111111111", expectedToken: "TEST-only", expectedJournalHash: hash,
      proposalReadinessHash: hash, treatmentDraftRevisionHash: hash } } },
    remainingMs: () => { calls.push("budget"); return 20_000; } } as unknown as OpeningExecutionInput;
  const result = { held: { claimHash: hash }, process: { receipt: { groupStopped: true, status: "complete", error: "" } },
    cleanup: { cleanupHash: hash, claimRetained: false }, observed: { cleanupHash: hash, held: { claimHash: hash } },
    verified: {}, selection: { selectionHash: hash }, status: { state: "ready-for-review", selectionHash: hash, openingApproved: false } };
  const deps = {
    claim: () => { calls.push("claim"); return result.held; },
    run: async () => { calls.push("run"); return result.process; },
    cleanup: async () => { calls.push("cleanup"); return result.cleanup; },
    readCleanup: () => { calls.push("read-cleanup"); return result.observed; },
    verify: async () => { calls.push("verify"); return result.verified; },
    select: () => { calls.push("select"); return result.selection; },
    status: () => { calls.push("status"); return result.status; },
  } as unknown as typeof openingExecutionDependencies;
  return { input, calls, result, deps };
}

test("one production sequence claims, executes, cleans, verifies and selects without approving", async () => {
  const f = fixture(), result = await executeGuidedOpeningUnderLease(f.input, f.deps);
  assert.equal(result.status.openingApproved, false);
  assert.deepEqual(f.calls, ["budget", "claim", "run", "cleanup", "read-cleanup", "budget", "verify", "budget", "select", "status"]);
});

test("internal V2 metadata cannot silently execute the legacy path and drop requested source color", async () => {
  const f = fixture(), record = f.input.operation.record;
  record.submission = { ...record.submission as object, schemaVersion: 2, sourceColor: { schemaVersion: 1,
    declarations: { test: { profile: null, declaration: { schemaVersion: 1, sourceId: "test", sourceProfile: "bt709-sdr",
      cameraProfile: null, historyState: "known", transformHistory: [], lightingGroups: [{ id: "whole", startFrame: 0,
        endFrame: 24, intent: "neutral", description: "TEST explicit metadata only" }] } } } } };
  await assert.rejects(executeGuidedOpeningUnderLease(f.input, f.deps), /full-reservation cleanup are not connected/);
  assert.deepEqual(f.calls, []);
});

test("unproved stop never permits cleanup or media selection", async () => {
  const f = fixture(); f.result.process.receipt.groupStopped = false;
  await assert.rejects(executeGuidedOpeningUnderLease(f.input, f.deps), /stop is unproved/);
  assert.deepEqual(f.calls, ["budget", "claim", "run"]);
});

test("a stopped failed worker still receives protected cleanup but never a readback", async () => {
  const f = fixture(); f.result.process.receipt.status = "failed"; f.result.process.receipt.error = "TEST failure";
  await assert.rejects(executeGuidedOpeningUnderLease(f.input, f.deps), /Opening worker failed: TEST failure/);
  assert.deepEqual(f.calls, ["budget", "claim", "run", "cleanup", "read-cleanup"]);
});

test("retained ownership or mismatched cleanup prevents verification", async () => {
  for (const mode of ["retained", "mismatched"] as const) {
    const f = fixture();
    if (mode === "retained") f.result.cleanup.claimRetained = true;
    else f.result.observed.held.claimHash = "b".repeat(64);
    await assert.rejects(executeGuidedOpeningUnderLease(f.input, f.deps), /ownership remains unresolved|cleanup differs/);
    assert.equal(f.calls.includes("verify"), false);
  }
});

test("expired media budget cannot skip cleanup or purchase a fresh selection budget", async () => {
  const f = fixture(); let checks = 0;
  f.input.remainingMs = () => { if (++checks > 1) throw new Error("TEST original deadline exhausted"); return 1; };
  await assert.rejects(executeGuidedOpeningUnderLease(f.input, f.deps), /original deadline exhausted/);
  assert.deepEqual(f.calls, ["claim", "run", "cleanup", "read-cleanup"]);
});

test("failed readback and stale/approved selection are not reported as generation success", async () => {
  const failed = fixture();
  failed.deps.verify = async () => { throw new Error("TEST readback failed"); };
  await assert.rejects(executeGuidedOpeningUnderLease(failed.input, failed.deps), /readback failed/);
  assert.equal(failed.calls.includes("select"), false);
  for (const mode of ["hash", "approved"] as const) {
    const f = fixture();
    if (mode === "hash") f.result.status.selectionHash = "b".repeat(64);
    else f.result.status.openingApproved = true;
    await assert.rejects(executeGuidedOpeningUnderLease(f.input, f.deps), /exact unapproved reviewable media/);
  }
});
