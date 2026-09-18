/** Full parsed TEST journal; these builders perform no writer, native invocation, CAS or retirement. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test, { type TestContext } from "node:test";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { buildSourceColorCleanupPendingJob } from "../guided-source-color-cleanup-pending-job";
import { buildSourceColorCleanupRetiredJob } from "../guided-source-color-cleanup-retired-job";
import { parseFinalSourceColorCleanupFact, parsePreparedSourceColorCleanupFact } from "../../producer/contracts/guided-source-color-cleanup-facts";
import { parseAutoEditJobRecord } from "../auto-edit-job-persistence";
import { cleanupPendingPreRecordFixture } from "./_guided-source-color-cleanup-pending-read-fixture";

/** Syntactic TEST facts only; no matching ack file or actual first/second CAS is fabricated. */
function fixture(t: TestContext) {
  const f = cleanupPendingPreRecordFixture(t), held = f.input.held, hash = "a".repeat(64), createdAt = new Date().toISOString();
  const prepared = parsePreparedSourceColorCleanupFact({ schemaVersion: 2, kind: "guided-opening-source-color-cleanup-prepared",
    scope: "exact-owned-resource-cleanup-awaiting-reservation-retirement-not-approval", phase: "awaiting-retirement", claimRetained: true,
    claimHash: held.claimHash, executionId: held.claim.executionId, cleanupAttemptId: f.input.attemptId,
    beforeJournalHash: held.sha256, processOutcomeSha256: f.actual.receiptSha256, cleanupStartSha256: hash,
    cleanupOutputSha256: hash, cleanupResultHash: hash, cleanupInvocationSha256: hash, reservation: f.staged.reservation,
    archive: { ...f.staged.reservation, path: path.join(f.directory, "reservation.json") }, sourceColorHash: f.actual.sourceColor.sourceColorHash,
    clockHash: held.claim.clockHash, generationStartedAt: held.claim.generationStartedAt, createdAt,
    mediaSelected: false, openingApproved: false, deliveryApproved: false });
  const job = buildSourceColorCleanupPendingJob(held, prepared), pendingJournalHash = "b".repeat(64);
  const fact = parseFinalSourceColorCleanupFact({ schemaVersion: 2, kind: "guided-opening-source-color-cleanup-commit",
    scope: "exact-owned-resource-cleanup-and-reservation-retirement-not-approval", phase: "retired", claimRetained: false,
    claimHash: prepared.claimHash, executionId: prepared.executionId, cleanupAttemptId: prepared.cleanupAttemptId,
    preparedFactHash: canonicalJsonSha256(prepared), pendingJournalHash,
    retirementAck: { path: path.join(f.directory, "retirement-ack.json"), sha256: hash, sizeBytes: 512 },
    clockHash: prepared.clockHash, generationStartedAt: prepared.generationStartedAt, createdAt,
    mediaSelected: false, openingApproved: false, deliveryApproved: false });
  return { ...f, input: { job, pendingJournalHash, prepared }, fact };
}

test("deterministic retired transition clears only claim/outcome and preserves every unrelated field", t => {
  const f = fixture(t), before = structuredClone(f.input), factBefore = structuredClone(f.fact);
  const actual = buildSourceColorCleanupRetiredJob(f.input, f.fact), expected = structuredClone(before.job);
  delete expected.guidedHandoffV2!.openingExecutionClaimHash; delete expected.guidedHandoffV2!.openingProcessOutcomeHash;
  expected.guidedHandoffV2!.openingCleanupHash = canonicalJsonSha256(f.fact);
  expected.updatedAt = f.fact.createdAt; expected.nextEventId++;
  expected.message = "Exact opening resources are clean and the source-color reservation is retired. No media is selected or approved.";
  expected.events = [...expected.events, { id: before.job.nextEventId, at: f.fact.createdAt, payload: {
    event: "opening_source_color_cleanup_retired", executionId: f.fact.executionId, cleanupHash: canonicalJsonSha256(f.fact),
    preparedFactHash: f.fact.preparedFactHash, pendingJournalHash: f.fact.pendingJournalHash,
    retirementAckSha256: f.fact.retirementAck.sha256, claimRetained: false, clockHash: f.fact.clockHash,
    generationStartedAt: f.fact.generationStartedAt, mediaSelected: false, openingApproved: false, deliveryApproved: false } }].slice(-256);
  assert.deepEqual(actual, expected); assert.deepEqual(f.input, before); assert.deepEqual(f.fact, factBefore);
  assert.notEqual(actual.ctx, f.input.job.ctx); assert.equal(parseAutoEditJobRecord(actual), actual);
  assert.equal(f.calls.length, 0); assert(!fs.existsSync(f.fact.retirementAck.path)); assert.deepEqual(fs.readdirSync(f.directory), []);
});

test("retirement preserves the exact trailing 256 event window and safely increments its original sequence", t => {
  const f = fixture(t), at = f.input.job.updatedAt;
  f.input.job.events = Array.from({ length: 256 }, (_, index) => ({ id: index + 1, at, payload: { event: "TEST retained history", index } }));
  f.input.job.nextEventId = 257; f.input.job.activeEventStartId = 1;
  const before = structuredClone(f.input.job.events), actual = buildSourceColorCleanupRetiredJob(f.input, f.fact);
  assert.equal(actual.nextEventId, 258); assert.equal(actual.events.length, 256);
  assert.deepEqual(actual.events.slice(0, -1), before.slice(1)); assert.equal(actual.events.at(-1)!.id, 257);
  assert.deepEqual(f.input.job.events, before);
});

test("required pending cleanup/claim/outcome pointers cannot be missing or changed", t => {
  const f = fixture(t), before = structuredClone(f.input);
  for (const key of ["openingCleanupHash", "openingExecutionClaimHash", "openingProcessOutcomeHash"] as const) {
    const input = structuredClone(before); delete input.job.guidedHandoffV2![key];
    assert.throws(() => buildSourceColorCleanupRetiredJob(input, f.fact));
  }
  for (const key of ["openingCleanupHash", "openingExecutionClaimHash"] as const) {
    const input = structuredClone(before); input.job.guidedHandoffV2![key] = "0".repeat(64);
    assert.throws(() => buildSourceColorCleanupRetiredJob(input, f.fact), /exact unselected pending claim/);
  }
  assert.deepEqual(f.input, before);
});

test("selection, approval, body authority and wrong status never become a retired job", t => {
  const f = fixture(t);
  for (const key of ["openingMediaSelectionHash", "openingApprovalHash", "bodyExecutionClaimHash", "bodyActivationHash",
    "bodyProcessOutcomeHash", "bodyCleanupHash", "bodyCandidateHash"] as const) {
    const input = structuredClone(f.input); input.job.guidedHandoffV2![key] = "0".repeat(64);
    assert.throws(() => buildSourceColorCleanupRetiredJob(input, f.fact));
  }
  const input = structuredClone(f.input); input.job.status = "failed";
  assert.throws(() => buildSourceColorCleanupRetiredJob(input, f.fact));
});

test("full final identity joins cannot substitute parent, prepared fact, claim, execution, attempt or original clock", t => {
  const f = fixture(t), original = structuredClone(f.fact);
  for (const key of ["pendingJournalHash", "preparedFactHash", "claimHash", "clockHash"] as const) {
    assert.throws(() => buildSourceColorCleanupRetiredJob(f.input, { ...original, [key]: "0".repeat(64) }), /exact pending parent/);
  }
  for (const key of ["executionId", "cleanupAttemptId"] as const) {
    const fact = { ...original, [key]: "00000000-0000-4000-8000-000000000031" };
    fact.retirementAck = { ...fact.retirementAck, path: fact.retirementAck.path.replace(original[key], fact[key]) };
    assert.throws(() => buildSourceColorCleanupRetiredJob(f.input, fact), /exact pending parent/);
  }
  const start = new Date(Date.parse(original.generationStartedAt) + 1).toISOString();
  assert.throws(() => buildSourceColorCleanupRetiredJob(f.input, { ...original, generationStartedAt: start }), /exact pending parent/);
});

test("both original timestamps fence backwards retirement but equal timestamps remain valid", t => {
  const f = fixture(t), earlier = new Date(Date.parse(f.fact.createdAt) - 1).toISOString();
  assert.throws(() => buildSourceColorCleanupRetiredJob(f.input, { ...f.fact, createdAt: earlier }), /original clock/);
  const input = structuredClone(f.input); input.job.updatedAt = new Date(Date.parse(f.fact.createdAt) + 1).toISOString();
  assert.throws(() => buildSourceColorCleanupRetiredJob(input, f.fact), /original clock/);
  assert.doesNotThrow(() => buildSourceColorCleanupRetiredJob(input, { ...f.fact, createdAt: input.job.updatedAt }));
});

test("strict closed fact contracts and pending raw hash are checked before transition", t => {
  const f = fixture(t);
  assert.throws(() => buildSourceColorCleanupRetiredJob(f.input, { ...f.fact, approval: true } as typeof f.fact));
  assert.throws(() => buildSourceColorCleanupRetiredJob({ ...f.input, prepared: { ...f.input.prepared, qcPassed: true } as typeof f.input.prepared }, f.fact));
  for (const pendingJournalHash of ["", "A".repeat(64), null, 0]) {
    assert.throws(() => buildSourceColorCleanupRetiredJob({ ...f.input, pendingJournalHash: pendingJournalHash as string }, f.fact));
  }
  assert.throws(() => buildSourceColorCleanupRetiredJob(f.input, { ...f.fact, openingApproved: true } as unknown as typeof f.fact));
  assert.throws(() => buildSourceColorCleanupRetiredJob(f.input, { ...f.fact, retirementAck: { ...f.fact.retirementAck, sizeBytes: 0 } }));
});

test("unsafe event counters and replayed retired jobs remain rejected", t => {
  const f = fixture(t);
  for (const nextEventId of [0, -1, 1.5, NaN, Infinity, Number.MAX_SAFE_INTEGER]) {
    const input = structuredClone(f.input); input.job.nextEventId = nextEventId;
    assert.throws(() => buildSourceColorCleanupRetiredJob(input, f.fact));
  }
  const retired = buildSourceColorCleanupRetiredJob(f.input, f.fact);
  assert.throws(() => buildSourceColorCleanupRetiredJob({ ...f.input, job: retired }, f.fact), /exact unselected pending claim/);
});
