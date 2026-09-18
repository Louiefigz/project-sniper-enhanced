/** Actual first CAS and raw objects; inherited native/tool/claim admission remains explicitly TEST-stubbed. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { snapshotSourceColorMetadata } from "../guided-source-color-staging-hold";
import { retainGenerationClockObservation } from "../generation-clock-watermark";
import { buildSourceColorCleanupPendingJob } from "../guided-source-color-cleanup-pending-job";
import { commitPreparedSourceColorCleanup } from "../guided-source-color-cleanup-pending-commit";
import { cleanupPendingCommitFixture, cleanupCommitFiles, replaceCleanupCommitFile,
  assertCleanupCommitRetained } from "./_guided-source-color-cleanup-pending-commit-fixture";

test("actual first CAS retains claim/outcome and exact unrelated journal fields without retirement", async t => {
  const f = cleanupPendingCommitFixture(t), recorded = await f.write(), before = snapshotSourceColorMetadata(f.before);
  const expected = buildSourceColorCleanupPendingJob(f.input.held, recorded.fact), calls: number[] = [];
  const committed = commitPreparedSourceColorCleanup(recorded, { beforeCasGuard: invocation => { calls.push(invocation); } });
  const current = observeHumanCutJob(f.before.job.ctx.dir), files = cleanupCommitFiles(f, recorded);
  assert.deepEqual(calls, [1, 2]); assert.deepEqual(current.job, expected); assert.deepEqual(f.before, before);
  assert.equal(committed.pendingJournalHash, current.sha256); assert.equal(committed.preparedFactHash, recorded.factHash);
  assert.equal(committed.claimRetained, true); assert.equal(committed.retirementObserved, false);
  assert.equal(committed.mediaSelected, false); assert.equal(committed.openingApproved, false); assert.equal(committed.deliveryApproved, false);
  assert.equal(readCutPreviewObject(files.fact).sha256, recorded.factHash);
  assert.equal(readCutPreviewObject(files.result).sha256, recorded.fact.cleanupResultHash);
  const snapshot = readCutPreviewObject(files.snapshot); assert(Buffer.isBuffer(snapshot.bytes));
  assert.equal(snapshot.sha256, before.sha256); assert.equal(snapshot.sizeBytes, before.sizeBytes); assert.deepEqual(snapshot.bytes, before.bytes);
  assert.deepEqual(snapshot.value, before.job); assertCleanupCommitRetained(f, true); f.assertLeases();
  const clock = path.join(f.before.job.ctx.dir, "generation-clock-observations", f.input.held.claim.clockHash);
  assert.deepEqual(fs.readdirSync(clock), [`${f.input.held.claim.executionId}.json`]);
  const watermark = readCutPreviewObject(path.join(clock, fs.readdirSync(clock)[0])).value;
  assert.equal(watermark.kind, "generation-wall-clock-watermark"); assert.equal(watermark.executionId, f.input.held.claim.executionId);
});

test("pure builder changes only the explicit pending transition and retains raw original observation", async t => {
  const f = cleanupPendingCommitFixture(t), recorded = await f.write(), before = snapshotSourceColorMetadata(f.input.held);
  const pending = buildSourceColorCleanupPendingJob(f.input.held, recorded.fact), expected = snapshotSourceColorMetadata(before.job);
  expected.updatedAt = recorded.fact.createdAt; expected.message = pending.message;
  expected.guidedHandoffV2!.openingCleanupHash = recorded.factHash; expected.nextEventId++;
  expected.events = [...expected.events, { id: before.job.nextEventId, at: recorded.fact.createdAt, payload: {
    event: "opening_source_color_cleanup_prepared", executionId: before.claim.executionId, cleanupHash: recorded.factHash,
    claimRetained: true, clockHash: before.claim.clockHash, generationStartedAt: before.claim.generationStartedAt,
    mediaSelected: false, openingApproved: false, deliveryApproved: false } }].slice(-256);
  assert.deepEqual(pending, expected); assert.deepEqual(f.input.held, before); assert(Buffer.isBuffer(f.input.held.bytes));
  assertCleanupCommitRetained(f, false);
});

test("pure builder refuses selected, already-pending and mismatched original authority", async t => {
  const f = cleanupPendingCommitFixture(t), recorded = await f.write(), original = snapshotSourceColorMetadata(f.input.held);
  for (const key of ["openingCleanupHash", "openingMediaSelectionHash", "openingApprovalHash", "bodyExecutionClaimHash", "bodyCandidateHash"] as const) {
    const held = snapshotSourceColorMetadata(original); held.job.guidedHandoffV2![key] = "0".repeat(64);
    assert.throws(() => buildSourceColorCleanupPendingJob(held, recorded.fact), /original unselected stopped claim/);
  }
  for (const key of ["beforeJournalHash", "claimHash", "clockHash", "sourceColorHash"] as const) {
    assert.throws(() => buildSourceColorCleanupPendingJob(original, { ...recorded.fact, [key]: "0".repeat(64) }), /entire original claim and clock/);
  }
  assert.deepEqual(f.input.held, original); assertCleanupCommitRetained(f, false);
});

test("spread and JSON recordings are not live capabilities and produce no new publications", async t => {
  const f = cleanupPendingCommitFixture(t), recorded = await f.write(), files = cleanupCommitFiles(f, recorded);
  const objects = path.dirname(files.fact), names = fs.readdirSync(objects).sort();
  for (const value of [{ ...recorded }, JSON.parse(JSON.stringify(recorded))]) {
    assert.throws(() => commitPreparedSourceColorCleanup(value), /actual live recorded attempt/);
    assert.deepEqual(fs.readdirSync(objects).sort(), names); assert.deepEqual(fs.readFileSync(files.journal), f.before.bytes);
  }
  assertCleanupCommitRetained(f, false); f.assertLeases();
});

test("stale original journal refuses before preparation publication", async t => {
  const f = cleanupPendingCommitFixture(t), recorded = await f.write();
  const stale = snapshotSourceColorMetadata(f.before.job); stale.message = "TEST competing journal mutation";
  replaceCleanupCommitFile(f, { recorded, name: "journal", bytes: Buffer.from(JSON.stringify(stale)) });
  assert.throws(() => commitPreparedSourceColorCleanup(recorded), /publication original bytes or identity/);
  assert(!fs.existsSync(cleanupCommitFiles(f, recorded).fact)); assertCleanupCommitRetained(f, false); f.assertLeases();
});

test("both actual CAS guard invocations preserve journal on expiry or loss of either original lease", async t => {
  for (const invocation of [1, 2]) for (const kind of ["expiry", "project", "resource"] as const) await t.test(`${kind}-${invocation}`, async t => {
    const f = cleanupPendingCommitFixture(t), recorded = await f.write();
    assert.throws(() => commitPreparedSourceColorCleanup(recorded, { beforeCasGuard: call => {
      if (call !== invocation) return;
      if (kind === "expiry") f.timing.elapsed = 300_000;
      else if (kind === "project") f.projectLease.release();
      else f.staging.resource.lease.release();
    } }), error => kind === "expiry" ? error instanceof Error && /remainder/.test(error.message)
      : (error as NodeJS.ErrnoException).code === "ENOENT" && (error as NodeJS.ErrnoException).path === path.join(
        kind === "project" ? f.staging.root : f.staging.resource.resource, ".sniper-project-mutation.lock"));
    assert.deepEqual(fs.readFileSync(cleanupCommitFiles(f, recorded).journal), f.before.bytes);
    assertCleanupCommitRetained(f, false);
    if (kind === "resource") f.assertProject();
    else f.staging.resource.assertResource();
  });
});

test("both CAS guard invocations reject a future retained wall observation without resetting it", async t => {
  for (const invocation of [1, 2]) await t.test(`future-${invocation}`, async t => {
    const f = cleanupPendingCommitFixture(t), recorded = await f.write(), claim = f.input.held.claim;
    const future = new Date(Date.now() + 60_000).toISOString();
    assert.throws(() => commitPreparedSourceColorCleanup(recorded, { beforeCasGuard: call => {
      if (call === invocation) retainGenerationClockObservation({ dir: f.before.job.ctx.dir,
        origin: { clockHash: claim.clockHash, startedAt: claim.generationStartedAt }, executionId: claim.executionId,
        observedAt: future }, f.assertLeases);
    } }), /wall clock moved backwards/);
    const file = path.join(f.before.job.ctx.dir, "generation-clock-observations", claim.clockHash, `${claim.executionId}.json`);
    assert.equal(readCutPreviewObject(file).value.observedAt, future); assertCleanupCommitRetained(f, false); f.assertLeases();
  });
});

test("original journal inode substitution in either CAS guard is not adopted", async t => {
  for (const invocation of [1, 2]) await t.test(`journal-${invocation}`, async t => {
    const f = cleanupPendingCommitFixture(t), recorded = await f.write();
    assert.throws(() => commitPreparedSourceColorCleanup(recorded, { beforeCasGuard: call => {
      if (call === invocation) replaceCleanupCommitFile(f, { recorded, name: "journal" });
    } }), /publication original bytes or identity/);
    assertCleanupCommitRetained(f, false); f.assertLeases();
  });
});

test("published result, fact, snapshot and original output/media reject substitution before or after CAS", async t => {
  for (const name of ["result", "fact", "snapshot", "output", "media"] as const) await t.test(name, async t => {
    for (const after of [false, true]) await t.test(after ? "after CAS" : "before CAS", async t => {
      const f = cleanupPendingCommitFixture(t), recorded = await f.write();
      const mutate = () => replaceCleanupCommitFile(f, { recorded, name });
      assert.throws(() => commitPreparedSourceColorCleanup(recorded, after ? { afterCas: mutate }
        : { beforeCasGuard: invocation => { if (invocation === 2) mutate(); } }), /original|changed/);
      assertCleanupCommitRetained(f, after); f.assertLeases();
    });
  });
});

test("after-CAS exception retains actual pending journal and never rewrites the attempt as failed", async t => {
  const f = cleanupPendingCommitFixture(t), recorded = await f.write(), failure = new Error("TEST lost response after committed CAS");
  assert.throws(() => commitPreparedSourceColorCleanup(recorded, { afterCas: () => { throw failure; } }), error => error === failure);
  assert.equal(observeHumanCutJob(f.before.job.ctx.dir).job.guidedHandoffV2!.openingCleanupHash, recorded.factHash);
  assert.throws(() => commitPreparedSourceColorCleanup(recorded), /publication original bytes or identity/);
  assertCleanupCommitRetained(f, true); f.assertLeases();
});

test("successful or lost-response CAS cannot be blindly retried or repeat native cleanup", async t => {
  const f = cleanupPendingCommitFixture(t), recorded = await f.write();
  const committed = commitPreparedSourceColorCleanup(recorded), current = observeHumanCutJob(f.before.job.ctx.dir);
  assert.throws(() => commitPreparedSourceColorCleanup(recorded), /publication original bytes or identity/);
  assert.deepEqual(observeHumanCutJob(f.before.job.ctx.dir).bytes, current.bytes);
  assert.equal(canonicalJsonSha256(current.job), canonicalJsonSha256(buildSourceColorCleanupPendingJob(f.input.held, recorded.fact)));
  assert.equal(current.sha256, committed.pendingJournalHash); assertCleanupCommitRetained(f, true); f.assertLeases();
});
