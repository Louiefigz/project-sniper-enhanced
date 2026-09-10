/** Actual TEMP final CAS and history, never native media/daemon or source-admission qualification. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { commitRetiredSourceColorCleanup, sourceColorFinalCommitDependencies } from "../guided-source-color-cleanup-final-commit";
import { readRetainedSourceColorCleanupPending, readSourceColorCleanupPending } from "../guided-source-color-cleanup-pending-read";
import { assertSourceColorRetirementResourceOwnership } from "../guided-source-color-reservation-retirement";
import { buildSourceColorCleanupRetiredJob } from "../guided-source-color-cleanup-retired-job";
import { parseFinalSourceColorCleanupFact } from "../../producer/contracts/guided-source-color-cleanup-facts";
import { retainGenerationClockObservation } from "../generation-clock-watermark";
import { cleanupPendingReadLeaves } from "./_guided-source-color-cleanup-pending-read-fixture";
import { cleanupFinalCommitFixture, finalCommitFactFile, replaceFinalCommitFile,
  assertFinalCommitRetained } from "./_guided-source-color-cleanup-final-commit-fixture";

test("final commit defaults to actual retained pending history", () => {
  assert.equal(sourceColorFinalCommitDependencies.history, readRetainedSourceColorCleanupPending);
});

test("both CAS operations plus exact retirement clear only claim/outcome with retained raw history", async t => {
  const f = await cleanupFinalCommitFixture(t), invocations: number[] = [];
  const result = commitRetiredSourceColorCleanup(f.retired, f.finalControls, { beforeCasGuard: count => { invocations.push(count); } });
  const actual = observeHumanCutJob(f.before.job.ctx.dir), rawFact = readCutPreviewObject(finalCommitFactFile(f));
  const fact = parseFinalSourceColorCleanupFact(rawFact.value), snapshot = readCutPreviewObject(f.finalFiles.pendingSnapshot);
  assert.deepEqual(invocations, [1, 2]); assert.equal(result.cleanupHash, rawFact.sha256); assert.equal(result.journalHash, actual.sha256);
  assert.deepEqual(actual.job, buildSourceColorCleanupRetiredJob({ job: f.pendingBefore.job,
    pendingJournalHash: f.pendingBefore.sha256, prepared: f.recorded.fact }, fact));
  assert.deepEqual(snapshot.bytes, f.pendingBefore.bytes); assert.equal(snapshot.sha256, f.pendingBefore.sha256);
  assert(Buffer.isBuffer(snapshot.bytes)); assert.deepEqual(fact.retirementAck, f.retired.reference);
  assert.equal(readCutPreviewObject(f.files.ack).sha256, f.retired.reference.sha256);
  assert.equal(result.claimRetained, false); assert.equal(result.mediaSelected, false);
  assert.equal(result.openingApproved, false); assert.equal(result.deliveryApproved, false); assertFinalCommitRetained(f, true); f.assertLeases();
  assertSourceColorRetirementResourceOwnership(f.retired); assert.throws(f.pending.assertCurrent, /original|changed/);
  const historyInput = { dir: f.before.job.ctx.dir, guard: f.assertLeases, remainingMs: f.writerInput.clock.remainingMs };
  assert.throws(() => readSourceColorCleanupPending(historyInput, cleanupPendingReadLeaves(f)));
  const history = readRetainedSourceColorCleanupPending(historyInput, f.pendingBefore.sha256, cleanupPendingReadLeaves(f));
  assert.deepEqual(history.job, f.pendingBefore.job); assert.equal(history.pendingJournalHash, f.pendingBefore.sha256);
  assert.equal(history.retirementObserved, false); history.assertCurrent();
});

test("spread and JSON retirement records fail before final publications or journal writes", async t => {
  const f = await cleanupFinalCommitFixture(t);
  for (const value of [{ ...f.retired }, JSON.parse(JSON.stringify(f.retired))]) {
    assert.throws(() => commitRetiredSourceColorCleanup(value, f.finalControls), /actual original verified retirement/);
    assert.deepEqual(fs.readdirSync(f.objects).sort(), f.names); assert(!fs.existsSync(f.finalFiles.pendingSnapshot));
  }
  assertFinalCommitRetained(f, false); f.assertLeases();
});

test("history DTOs cannot replace the actual private reader capability", async t => {
  for (const json of [false, true]) await t.test(json ? "JSON" : "spread", async t => {
    const f = await cleanupFinalCommitFixture(t), original = f.finalControls.history;
    f.finalControls.history = (input, hash) => {
      const history = original(input, hash); return json ? JSON.parse(JSON.stringify(history)) : { ...history };
    };
    assert.throws(() => commitRetiredSourceColorCleanup(f.retired, f.finalControls), /actual original read evidence/);
    assert.deepEqual(fs.readdirSync(f.objects).sort(), f.names); assertFinalCommitRetained(f, false); f.assertLeases();
  });
});

test("each final CAS guard rejects original expiry and either actual lease loss", async t => {
  for (const invocation of [1, 2]) for (const kind of ["expiry", "project", "resource"] as const) await t.test(`${kind}-${invocation}`, async t => {
    const f = await cleanupFinalCommitFixture(t);
    assert.throws(() => commitRetiredSourceColorCleanup(f.retired, f.finalControls, { beforeCasGuard: call => {
      if (call !== invocation) return;
      if (kind === "expiry") f.timing.elapsed = 300_000;
      else if (kind === "project") f.projectLease.release();
      else f.staging.resource.lease.release();
    } }), error => kind === "expiry" ? error instanceof Error && /remainder|deadline/.test(error.message)
      : (error as NodeJS.ErrnoException).code === "ENOENT" && (error as NodeJS.ErrnoException).path === path.join(
        kind === "project" ? f.staging.root : f.staging.resource.resource, ".sniper-project-mutation.lock"));
    assertFinalCommitRetained(f, false);
    if (kind === "resource") f.assertProject();
    else f.staging.resource.assertResource();
  });
});

test("both final guards reject future retained wall observations without resetting history", async t => {
  for (const invocation of [1, 2]) await t.test(`future-${invocation}`, async t => {
    const f = await cleanupFinalCommitFixture(t), claim = f.input.held.claim, future = new Date(Date.now() + 60_000).toISOString();
    assert.throws(() => commitRetiredSourceColorCleanup(f.retired, f.finalControls, { beforeCasGuard: call => {
      if (call === invocation) retainGenerationClockObservation({ dir: f.before.job.ctx.dir,
        origin: { clockHash: claim.clockHash, startedAt: claim.generationStartedAt }, executionId: claim.executionId,
        observedAt: future }, f.assertLeases);
    } }), /wall clock moved backwards/);
    const file = path.join(f.before.job.ctx.dir, "generation-clock-observations", claim.clockHash, `${claim.executionId}.json`);
    assert.equal(readCutPreviewObject(file).value.observedAt, future); assertFinalCommitRetained(f, false); f.assertLeases();
  });
});

test("journal, media, ack and final fact cannot be substituted at either final CAS guard", async t => {
  for (const name of ["journal", "media", "ack", "fact"] as const) await t.test(name, async t => {
    for (const invocation of [1, 2]) await t.test(`guard-${invocation}`, async t => {
      const f = await cleanupFinalCommitFixture(t);
      assert.throws(() => commitRetiredSourceColorCleanup(f.retired, f.finalControls, { beforeCasGuard: call => {
        if (call === invocation) replaceFinalCommitFile(f, name);
      } }), /original|changed/);
      assertFinalCommitRetained(f, false); f.assertLeases();
    });
  });
});

test("post-CAS ack, media, pending snapshot and final fact substitutions retain the final journal", async t => {
  for (const name of ["ack", "media", "pendingSnapshot", "fact"] as const) await t.test(name, async t => {
    const f = await cleanupFinalCommitFixture(t);
    assert.throws(() => commitRetiredSourceColorCleanup(f.retired, f.finalControls, { afterCas: () => replaceFinalCommitFile(f, name) }), /original|changed/);
    assertFinalCommitRetained(f, true); f.assertLeases();
  });
});

test("post-CAS ownership tail detects loss of either actual lease without clearing final evidence", async t => {
  for (const project of [false, true]) await t.test(project ? "project" : "resource", async t => {
    const f = await cleanupFinalCommitFixture(t);
    assert.throws(() => commitRetiredSourceColorCleanup(f.retired, f.finalControls, { afterCas: () => {
      if (project) f.projectLease.release();
      else f.staging.resource.lease.release();
    } }), { code: "ENOENT" });
    assertFinalCommitRetained(f, true);
  });
});

test("after-CAS lost response retains final fact and refuses blind retry without new cleanup", async t => {
  const f = await cleanupFinalCommitFixture(t), failure = new Error("TEST final CAS response lost");
  assert.throws(() => commitRetiredSourceColorCleanup(f.retired, f.finalControls, { afterCas: () => { throw failure; } }), error => error === failure);
  const current = observeHumanCutJob(f.before.job.ctx.dir), fact = readCutPreviewObject(finalCommitFactFile(f));
  assert.equal(current.job.guidedHandoffV2!.openingCleanupHash, fact.sha256);
  assert.throws(() => commitRetiredSourceColorCleanup(f.retired, f.finalControls), /original|changed|pending/);
  assert.deepEqual(observeHumanCutJob(f.before.job.ctx.dir).bytes, current.bytes); assertFinalCommitRetained(f, true); f.assertLeases();
});

test("successful final CAS cannot replay or create another final fact", async t => {
  const f = await cleanupFinalCommitFixture(t), committed = commitRetiredSourceColorCleanup(f.retired, f.finalControls);
  const names = fs.readdirSync(f.objects).sort(), current = observeHumanCutJob(f.before.job.ctx.dir);
  assert.throws(() => commitRetiredSourceColorCleanup(f.retired, f.finalControls), /original|changed|pending/);
  assert.deepEqual(fs.readdirSync(f.objects).sort(), names); assert.equal(current.sha256, committed.journalHash);
  assert.equal(canonicalJsonSha256(readCutPreviewObject(finalCommitFactFile(f)).value), committed.cleanupHash);
  assertFinalCommitRetained(f, true); f.assertLeases();
});
