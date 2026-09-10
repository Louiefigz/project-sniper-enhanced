/** Completion recovery is actual metadata/CAS only. These are not native or audiovisual qualification. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import test from "node:test";
import { assertAdoptedSourceColorCleanupMetadata, heldAdoptedSourceColorCleanup,
  remainingAdoptedSourceColorCleanup } from "../guided-source-color-cleanup-adoption";
import { heldRecordedSourceColorCleanupAttempt, type RecordedSourceColorCleanupAttempt } from "../guided-source-color-cleanup-attempt";
import { commitPreparedSourceColorCleanup } from "../guided-source-color-cleanup-pending-commit";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { cleanupAdoptionFixture, replaceAdoptionFile, addPartialAdoptionSibling } from "./_guided-source-color-cleanup-adoption-fixture";
import { assertCleanupCommitRetained } from "./_guided-source-color-cleanup-pending-commit-fixture";
import { replaceAttemptMediaFile } from "./_guided-source-color-cleanup-attempt-media-fixture";

test("actual completed history enters first CAS without rerunning the expired original native attempt", async t => {
  const f = await cleanupAdoptionFixture(t); f.timing.elapsed = 300_000;
  const value = f.adopt(), before = { ...f.adoptionCounts };
  assert.equal(value.scope, "completed-history-adoption-not-native-replay-retirement-or-approval");
  assert.equal(value.factHash, f.recorded.factHash); assert.deepEqual(value.preparedRef, f.recorded.preparedRef);
  assertAdoptedSourceColorCleanupMetadata(value); assert.deepEqual(f.adoptionCounts, before);
  assert.equal(heldAdoptedSourceColorCleanup(value), f.input.held);
  const result = commitPreparedSourceColorCleanup(value);
  assert.equal(result.pendingJournalHash, observeHumanCutJob(f.before.job.ctx.dir).sha256);
  assertCleanupCommitRetained(f, true); f.assertLeases();
  assertAdoptedSourceColorCleanupMetadata(value);
  assert.throws(() => commitPreparedSourceColorCleanup(value), /journal/);
});

test("DTOs and cross-scope casts cannot manufacture either private completion capability", async t => {
  const f = await cleanupAdoptionFixture(t), value = f.adopt();
  assert.throws(() => commitPreparedSourceColorCleanup({ ...value }), /actual authenticated historical completion/);
  assert.throws(() => assertAdoptedSourceColorCleanupMetadata(JSON.parse(JSON.stringify(value))), /actual authenticated/);
  assert.throws(() => heldRecordedSourceColorCleanupAttempt(value as unknown as RecordedSourceColorCleanupAttempt), /actual live/);
  assert.throws(() => heldAdoptedSourceColorCleanup({ ...value, fact: f.recorded.fact }), /actual authenticated/);
  assertCleanupCommitRetained(f, false);
});

for (const name of ["journal", "active", "claim", "input", "prepared", "output"] as const) {
  test(`first remaining callback cannot rebaseline original ${name}`, async t => {
    const f = await cleanupAdoptionFixture(t); let once = true;
    f.adoptionCallbacks.remaining = () => { if (once) { once = false; replaceAdoptionFile(f, name); } };
    assert.throws(f.adopt, /identity/); assertCleanupCommitRetained(f, false); f.assertLeases();
  });
}
for (const role of ["activation", "priorJournal", "intent", "outcome", "ledger"] as const) {
  test(`first remaining callback cannot replace original media ${role}`, async t => {
    const f = await cleanupAdoptionFixture(t); let once = true;
    f.adoptionCallbacks.remaining = () => { if (once) { once = false; replaceAttemptMediaFile(f.media, role); } };
    assert.throws(f.adopt, /identity/); assertCleanupCommitRetained(f, false);
  });
}

test("unresolved sibling and missing selected attempt refuse without new native work", async t => {
  const f = await cleanupAdoptionFixture(t); f.adoptionInput.attemptId = randomUUID();
  assert.throws(f.adopt, /selected attempt/); addPartialAdoptionSibling(f);
  assert.throws(f.adopt, /file set/); assertCleanupCommitRetained(f, false);
});

for (const callback of ["workspace", "claim"] as const) {
  test(`${callback} callback cannot replace the originally held active reservation`, async t => {
    const f = await cleanupAdoptionFixture(t);
    f.adoptionCallbacks[callback] = () => replaceAdoptionFile(f, "active");
    assert.throws(f.adopt, /identity/); assertCleanupCommitRetained(f, false);
  });
}

test("configured foreign workspace and forged current claim refuse", async t => {
  const f = await cleanupAdoptionFixture(t), original = f.adoptionDependencies.workspace;
  f.adoptionDependencies.workspace = () => f.staging.producerDir;
  assert.throws(f.adopt, /resource namespace/); f.adoptionDependencies.workspace = original;
  f.adoptionDependencies.claim = () => ({ ...f.input.held, claimHash: "0".repeat(64) });
  assert.throws(f.adopt, /actual current claim/); assertCleanupCommitRetained(f, false);
});

test("private adoption denies subsequent clock replacement and recursive completion reentry", async t => {
  const f = await cleanupAdoptionFixture(t), value = f.adopt();
  f.adoptionCallbacks.remaining = () => { remainingAdoptedSourceColorCleanup(value); };
  assert.throws(() => remainingAdoptedSourceColorCleanup(value), /reenter/);
  f.adoptionInput.clock.remainingMs = () => 300_000;
  assert.throws(() => commitPreparedSourceColorCleanup(value), /identity/); assertCleanupCommitRetained(f, false);
});

for (const invocation of [1, 2]) {
  test(`actual adopted CAS guard ${invocation} rejects expiry and retains original journal`, async t => {
    const f = await cleanupAdoptionFixture(t), value = f.adopt();
    assert.throws(() => commitPreparedSourceColorCleanup(value, { beforeCasGuard: call => {
      if (call === invocation) f.allowance.ms = 0;
    } }), /remainder/); assertCleanupCommitRetained(f, false); f.assertLeases();
  });
}

for (const kind of ["project", "resource"] as const) {
  test(`missing actual ${kind} lease refuses historical adoption`, async t => {
    const f = await cleanupAdoptionFixture(t);
    (kind === "project" ? f.projectLease : f.staging.resource.lease).release();
    assert.throws(f.adopt, /ENOENT|lease/); assertCleanupCommitRetained(f, false);
  });
  for (const invocation of [1, 2]) test(`adopted CAS ${invocation} rejects lost actual ${kind} lease`, async t => {
    const f = await cleanupAdoptionFixture(t), value = f.adopt();
    assert.throws(() => commitPreparedSourceColorCleanup(value, { beforeCasGuard: call => {
      if (call === invocation) (kind === "project" ? f.projectLease : f.staging.resource.lease).release();
    } }), /ENOENT|lease/); assertCleanupCommitRetained(f, false);
  });
}

test("an after-CAS failure retains actual pending proof without native replay or failed-attempt rewrite", async t => {
  const f = await cleanupAdoptionFixture(t), value = f.adopt(), failure = new Error("TEST interrupted response");
  assert.throws(() => commitPreparedSourceColorCleanup(value, { afterCas: () => { throw failure; } }), error => error === failure);
  assertCleanupCommitRetained(f, true); assert.throws(f.adopt, /journal|pending/);
});

test("post-CAS metadata still rejects original completion file replacement", async t => {
  const f = await cleanupAdoptionFixture(t), value = f.adopt();
  assert.throws(() => commitPreparedSourceColorCleanup(value, { afterCas: () => replaceAdoptionFile(f, "prepared") }), /identity/);
  assertCleanupCommitRetained(f, true); assert(!fs.existsSync(path.join(f.directory, "failure.json")));
});
