/** Actual TEMP unlink/ack and CAS/readback. Native/source/claim admission remains explicitly TEST-stubbed. */
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { assertSourceColorReservationRetired, pendingSourceColorRetirement, remainingSourceColorRetirement,
  assertSourceColorRetirementResourceOwnership } from "../guided-source-color-reservation-retirement";
import { assertSourceColorCleanupPendingMetadata, readRetainedSourceColorCleanupPending } from "../guided-source-color-cleanup-pending-read";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "../human-cut-acceptance-store";
import { cleanupPendingReadLeaves } from "./_guided-source-color-cleanup-pending-read-fixture";
import { sourceColorRetirementFixture, replaceRetirementFile, removeRetirementMarker, insertRetirementMarker,
  assertRetirementPending } from "./_guided-source-color-reservation-retirement-fixture";

test("actual pending cleanup retires only its original marker and publishes an exact new acknowledgement", async t => {
  const f = await sourceColorRetirementFixture(t), archive = fs.readFileSync(f.files.archive), start = performance.now();
  const retired = f.retire();
  t.diagnostic(`actual TEMP retirement wall=${(performance.now() - start).toFixed(3)}ms; native and enclosing elapsed are TEST leaves`);
  assert.equal(retired.ack.disposition, "unlinked-original"); assert(!fs.existsSync(f.files.active));
  assert.deepEqual(fs.readFileSync(f.files.archive), archive); assert.deepEqual(retired.ack.reservation, f.recorded.fact.reservation);
  assert.equal(retired.ack.pendingJournalHash, f.committed.pendingJournalHash); assert.equal(retired.preparedFactHash, f.recorded.factHash);
  assert.equal(retired.claimRetained, true); assert.equal(retired.mediaSelected, false);
  assert.equal(retired.openingApproved, false); assert.equal(retired.deliveryApproved, false);
  assertSourceColorReservationRetired(retired); assertRetirementPending(f); f.assertLeases();
});

test("real committed-intent absence is honest and never claims an observed earlier unlink", async t => {
  const f = await sourceColorRetirementFixture(t); removeRetirementMarker(f);
  const retired = f.retire();
  assert.equal(retired.ack.disposition, "already-absent-after-committed-intent"); assertRetirementPending(f); f.assertLeases();
});

test("existing acknowledgement recovery preserves its exact bytes and inode without replaying cleanup", async t => {
  const f = await sourceColorRetirementFixture(t), first = f.retire(), bytes = fs.readFileSync(f.files.ack), stat = fs.lstatSync(f.files.ack);
  const second = f.retire();
  assert.deepEqual(second.reference, first.reference); assert.deepEqual(fs.readFileSync(f.files.ack), bytes);
  assert.equal(fs.lstatSync(f.files.ack).ino, stat.ino); assertRetirementPending(f);
});

test("an existing acknowledgement larger than the final-fact bound is refused", async t => {
  const f = await sourceColorRetirementFixture(t); f.retire();
  const bytes = fs.readFileSync(f.files.ack), oversized = Buffer.concat([bytes, Buffer.alloc(128 * 1024 + 1 - bytes.length, 32)]);
  replaceRetirementFile(f, "ack", oversized);
  assert.throws(() => f.retire(), /bounded|size|acknowledgement/);
  assert.deepEqual(fs.readFileSync(f.files.ack), oversized); assertRetirementPending(f);
});

test("only an actual pending read and actual retirement can cross their live boundaries", async t => {
  const f = await sourceColorRetirementFixture(t), actual = f.retirementInput.pending;
  f.retirementInput.pending = { ...actual };
  assert.throws(() => f.retire(), /actual original read evidence/);
  f.retirementInput.pending = actual; const retired = f.retire();
  assert.throws(() => assertSourceColorReservationRetired({ ...retired }), /actual original verified retirement/);
  assert.throws(() => assertSourceColorReservationRetired(JSON.parse(JSON.stringify(retired))), /actual original verified retirement/);
});

test("foreign active bytes are retained instead of being removed", async t => {
  const f = await sourceColorRetirementFixture(t), foreign = Buffer.from('{"TEST":"foreign reservation"}');
  replaceRetirementFile(f, "active", foreign);
  assert.throws(() => f.retire(), /active bytes differ/); assert.deepEqual(fs.readFileSync(f.files.active), foreign);
  assert(!fs.existsSync(f.files.ack)); assertRetirementPending(f);
});

test("same-byte active substitution by the last owner callback is refused before unlink", async t => {
  const f = await sourceColorRetirementFixture(t); let changed = false;
  f.callbacks.remaining = () => { if (!changed) { changed = true; replaceRetirementFile(f, "active"); } };
  assert.throws(() => f.retire(), /active reservation identity changed/);
  assert(fs.existsSync(f.files.active)); assert(!fs.existsSync(f.files.ack)); assertRetirementPending(f);
});

for (const lease of ["project", "resource"] as const) test(`lost actual ${lease} lease refuses before unlink`, async t => {
  const f = await sourceColorRetirementFixture(t);
  if (lease === "project") f.projectLease.release(); else f.staging.resource.lease.release();
  assert.throws(() => f.retire(), /ENOENT|lease/); assert(fs.existsSync(f.files.active)); assert(!fs.existsSync(f.files.ack));
  assertRetirementPending(f);
});

test("the original expired allowance refuses before unlink without renewing time", async t => {
  const f = await sourceColorRetirementFixture(t); f.timing.elapsed = 300_000;
  assert.throws(() => f.retire(), /remainder|deadline/); assert(fs.existsSync(f.files.active)); assert(!fs.existsSync(f.files.ack));
});

test("a fault after unlink preserves pending evidence and recovery reports already absent", async t => {
  const f = await sourceColorRetirementFixture(t);
  assert.throws(() => f.retire({ afterUnlink: () => { throw new Error("TEST crash after original unlink"); } }), /TEST crash/);
  assert(!fs.existsSync(f.files.active)); assert(!fs.existsSync(f.files.ack)); assertRetirementPending(f);
  const recovered = f.retire(); assert.equal(recovered.ack.disposition, "already-absent-after-committed-intent"); assertRetirementPending(f);
});

test("a fault after acknowledgement preserves it for exact recovery", async t => {
  const f = await sourceColorRetirementFixture(t);
  assert.throws(() => f.retire({ afterAck: () => { throw new Error("TEST crash after acknowledgement"); } }), /TEST crash/);
  const original = fs.readFileSync(f.files.ack); assertRetirementPending(f);
  f.retire(); assert.deepEqual(fs.readFileSync(f.files.ack), original); assertRetirementPending(f);
});

for (const file of ["ack", "archive", "media"] as const) test(`post-ack ${file} substitution cannot become success`, async t => {
  const f = await sourceColorRetirementFixture(t);
  assert.throws(() => f.retire({ afterAck: () => replaceRetirementFile(f, file) }), /identity changed|file changed/);
  assert(!fs.existsSync(f.files.active)); assert(fs.existsSync(f.files.ack)); assertRetirementPending(f);
});

test("the original deadline still applies after the irreversible unlink", async t => {
  const f = await sourceColorRetirementFixture(t);
  assert.throws(() => f.retire({ afterUnlink: () => { f.timing.elapsed = 300_000; } }), /remainder|deadline/);
  assert(!fs.existsSync(f.files.active)); assert(!fs.existsSync(f.files.ack)); assertRetirementPending(f);
});

test("pending metadata remains valid after intentional marker retirement, without old active guards", async t => {
  const f = await sourceColorRetirementFixture(t); f.retire();
  assertSourceColorCleanupPendingMetadata(f.pending); f.pending.assertCurrent(); assertRetirementPending(f);
});

test("retirement commit helpers retain the actual parent, allowance and live resource owner", async t => {
  const f = await sourceColorRetirementFixture(t), retired = f.retire();
  assert.equal(pendingSourceColorRetirement(retired), f.pending);
  const remaining = remainingSourceColorRetirement(retired); assert(remaining > 0 && remaining < 295_900);
  assertSourceColorRetirementResourceOwnership(retired);
  for (const read of [pendingSourceColorRetirement, remainingSourceColorRetirement, assertSourceColorRetirementResourceOwnership]) {
    assert.throws(() => read({ ...retired }), /actual original verified retirement/);
  }
  f.staging.resource.lease.release(); assert.throws(() => assertSourceColorRetirementResourceOwnership(retired), /ENOENT|lease/);
});

test("authenticated retained history cannot authorize a present marker unlink", async t => {
  const f = await sourceColorRetirementFixture(t), current = observeHumanCutJob(f.before.job.ctx.dir);
  saveHumanCutJobSnapshot(f.before.job.ctx.dir, current);
  const historical = readRetainedSourceColorCleanupPending(f.pendingInput, current.sha256, cleanupPendingReadLeaves(f));
  f.retirementInput.pending = historical as unknown as typeof f.pending;
  assert.throws(() => f.retire(), /exact current pending journal/);
  assert(fs.existsSync(f.files.active)); assert(!fs.existsSync(f.files.ack));
});

for (const dangling of [false, true]) test(`entry absence does not admit a later ${dangling ? "dangling" : "regular"} marker`, async t => {
  const f = await sourceColorRetirementFixture(t); removeRetirementMarker(f); let inserted = false;
  f.callbacks.remaining = () => { if (!inserted) { inserted = true; insertRetirementMarker(f, dangling); } };
  assert.throws(() => f.retire(), /existing entry is retained/); assert(fs.lstatSync(f.files.active));
  assert(!fs.existsSync(f.files.ack)); assertRetirementPending(f);
});

test("acknowledgement replay never removes a reappearing active entry", async t => {
  const f = await sourceColorRetirementFixture(t); f.retire(); const ack = fs.readFileSync(f.files.ack);
  insertRetirementMarker(f);
  assert.throws(() => f.retire(), /existing entry is retained/);
  assert.deepEqual(fs.readFileSync(f.files.active), f.activeBytes); assert.deepEqual(fs.readFileSync(f.files.ack), ack);
});

test("a marker reappearing after unlink is retained without an acknowledgement", async t => {
  const f = await sourceColorRetirementFixture(t);
  assert.throws(() => f.retire({ afterUnlink: () => insertRetirementMarker(f) }), /existing entry is retained/);
  assert.deepEqual(fs.readFileSync(f.files.active), f.activeBytes); assert(!fs.existsSync(f.files.ack)); assertRetirementPending(f);
});

for (const lease of ["project", "resource"] as const) test(`lost ${lease} lease after unlink cannot publish an acknowledgement`, async t => {
  const f = await sourceColorRetirementFixture(t);
  assert.throws(() => f.retire({ afterUnlink: () => {
    if (lease === "project") f.projectLease.release(); else f.staging.resource.lease.release();
  } }), /ENOENT|lease/);
  assert(!fs.existsSync(f.files.active)); assert(!fs.existsSync(f.files.ack)); assertRetirementPending(f);
});
