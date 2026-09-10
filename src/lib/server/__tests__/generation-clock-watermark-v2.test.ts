/** Real local scheduling files only; no source, decoder, API or generation success is simulated. */
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import test, { type TestContext } from "node:test";
import { guardGenerationAttempt, retainGenerationClockObservation, startGuardedProposalDeadline } from "../generation-clock-watermark";
import { startProposalDeadline } from "../generation-deadline";
import { canonicalJson, canonicalJsonSha256 } from "../auto-edit-hash";
import { writeContentAddressedJsonSync } from "../content-addressed-json";
import { acquireProjectMutationLease } from "../project-mutation-lease";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";

const origin = { clockHash: "a".repeat(64), startedAt: "2026-09-08T00:00:00.000Z" };
const start = Date.parse(origin.startedAt), stamp = (offset: number) => new Date(start + offset).toISOString();

function fixture(t: TestContext) {
  const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sniper-clock-v2-unit-")));
  t.after(() => {
    assert.equal(fs.realpathSync(dir), dir); assert.equal(path.dirname(dir), fs.realpathSync(os.tmpdir()));
    fs.rmSync(dir, { recursive: true, force: true });
  });
  const executionId = randomUUID(), folder = path.join(dir, "generation-clock-observations", origin.clockHash);
  const value = (offset: number, id = executionId) => ({ dir, origin, executionId: id, observedAt: stamp(offset) });
  const save = (offset: number, id = executionId) => retainGenerationClockObservation(value(offset, id), () => undefined);
  return { dir, folder, executionId, value, save, file: path.join(folder, `${executionId}.json`) };
}
function legacy(f: ReturnType<typeof fixture>, offset: number) {
  fs.mkdirSync(f.folder, { recursive: true, mode: 0o700 });
  return writeContentAddressedJsonSync(f.folder, { schemaVersion: 1, kind: "generation-wall-clock-observation",
    clockHash: origin.clockHash, generationStartedAt: origin.startedAt, executionId: f.executionId, observedAt: stamp(offset) });
}

test("2415 increasing checks persist one latest execution watermark without capacity exhaustion", t => {
  const f = fixture(t), began = performance.now();
  for (let index = 0; index < 2415; index++) f.save(index);
  const elapsedMs = performance.now() - began, value = JSON.parse(fs.readFileSync(f.file, "utf8"));
  assert.deepEqual(fs.readdirSync(f.folder), [`${f.executionId}.json`]);
  assert.equal(value.schemaVersion, 2); assert.equal(value.observedAt, stamp(2414));
  const { watermarkHash, ...body } = value; assert.equal(watermarkHash, canonicalJsonSha256(body));
  assert.throws(() => f.save(2413, randomUUID()), /backwards across attempts/);
  f.save(2415, randomUUID()); assert.equal(fs.readdirSync(f.folder).length, 2);
  t.diagnostic(JSON.stringify({ scope: "TEST durable scheduling only; inert lease callback", checks: 2415, elapsedMs }));
});

test("legacy immutable bytes survive mixed-history writes and both formats contribute high-water", t => {
  const f = fixture(t), old = legacy(f, 100), bytes = fs.readFileSync(old.path), inode = fs.lstatSync(old.path).ino;
  assert.throws(() => f.save(99), /backwards across attempts/); f.save(101);
  assert.deepEqual(fs.readFileSync(old.path), bytes); assert.equal(fs.lstatSync(old.path).ino, inode);
  assert.throws(() => f.save(100, randomUUID()), /backwards across attempts/);
  assert.equal(fs.readdirSync(f.folder).length, 2);
});

test("same timestamp is a no-op only for its own execution after fresh validation", t => {
  const f = fixture(t); f.save(1); const before = fs.lstatSync(f.file); f.save(1);
  assert.equal(fs.lstatSync(f.file).ino, before.ino); f.save(1, randomUUID());
  assert.equal(fs.readdirSync(f.folder).length, 2);
  fs.writeFileSync(f.file, "{}"); assert.throws(() => f.save(1), /clock|field|missing|changed/i);
});

test("expired and failed-attempt observations still prevent a fresh caller recovering time", t => {
  const f = fixture(t); let wall = start, mono = 0;
  const first = startGuardedProposalDeadline({ dir: f.dir, origin, executionId: f.executionId, guard: () => undefined },
    { wall: () => wall, monotonic: () => mono });
  const admission = structuredClone(first.admission); first.remainingMs(); wall += 11 * 60_000; mono += 11 * 60_000;
  assert.throws(first.remainingMs, /deadline-exceeded/); assert.deepEqual(first.admission, admission);
  const retry = startGuardedProposalDeadline({ dir: f.dir, origin, executionId: randomUUID(), guard: () => undefined },
    { wall: () => start + 10 * 60_000, monotonic: () => 0 });
  assert.throws(retry.remainingMs, /backwards across attempts/);
  assert.equal(JSON.parse(fs.readFileSync(f.file, "utf8")).observedAt, stamp(11 * 60_000));
});

test("a real acquired project lease is required to remain live during the write", t => {
  const f = fixture(t), acquired = acquireProjectMutationLease(f.dir, "TEST clock watermark");
  assert(acquired.lease); const lease = acquired.lease, guard = cutPreviewLeaseGuard(f.dir, lease);
  try {
    retainGenerationClockObservation(f.value(1), guard); const before = fs.readFileSync(f.file);
    lease.release(); assert.throws(() => retainGenerationClockObservation(f.value(2), guard), /ENOENT|lease|lock/);
    assert.deepEqual(fs.readFileSync(f.file), before);
  } finally { lease.release(); }
});

test("the original input cannot be rebaselined by the first caller guard", t => {
  const f = fixture(t), input = f.value(1);
  assert.throws(() => retainGenerationClockObservation(input, () => { input.observedAt = stamp(2); }), /original input changed/);
  assert(!fs.existsSync(f.folder));
});

test("a last-guard concurrent newer watermark is retained rather than overwritten by stale input", t => {
  const f = fixture(t); f.save(1); let calls = 0;
  assert.throws(() => retainGenerationClockObservation(f.value(2), () => {
    if (++calls === 2) {
      const body = { schemaVersion: 2, kind: "generation-wall-clock-watermark", clockHash: origin.clockHash,
        generationStartedAt: origin.startedAt, executionId: f.executionId, observedAt: stamp(3) };
      // Exact TEST-owned target; simulates another writer violating serialization, not a legitimate second lease.
      fs.writeFileSync(f.file, canonicalJson({ ...body, watermarkHash: canonicalJsonSha256(body) }));
    }
  }), /changed|identity|history/i);
  assert.equal(JSON.parse(fs.readFileSync(f.file, "utf8")).observedAt, stamp(3));
  assert.throws(() => f.save(2, randomUUID()), /backwards across attempts/);
});

test("same-byte inode replacement during the last guard cannot become the original history", t => {
  const f = fixture(t); f.save(1); let calls = 0;
  assert.throws(() => retainGenerationClockObservation(f.value(2), () => {
    if (++calls !== 2) return;
    const replacement = path.join(f.dir, "TEST-replacement.json");
    fs.writeFileSync(replacement, fs.readFileSync(f.file), { flag: "wx" }); fs.renameSync(replacement, f.file);
  }), /changed|identity|history/i);
  assert.equal(JSON.parse(fs.readFileSync(f.file, "utf8")).observedAt, stamp(1));
});

test("a saturated legacy folder remains fenced with every historical byte retained", t => {
  const f = fixture(t), records = Array.from({ length: 512 }, (_, index) => legacy(f, index));
  assert.throws(() => f.save(512), /capacity exhausted/); assert.equal(fs.readdirSync(f.folder).length, 512);
  records.forEach(row => assert.equal(canonicalJsonSha256(JSON.parse(fs.readFileSync(row.path, "utf8"))), row.hash));
});

test("links and unknown history entries fail even at an unchanged timestamp", t => {
  const f = fixture(t); f.save(1);
  const alias = path.join(f.folder, `${randomUUID()}.json`); fs.symlinkSync(path.join(f.dir, "TEST-absent"), alias);
  assert.throws(() => f.save(1), /regular|link|ENOENT|history|artifact/i);
  fs.unlinkSync(alias); fs.writeFileSync(path.join(f.folder, "TEST-unknown.txt"), "TEST unknown", { flag: "wx" });
  assert.throws(() => f.save(1), /unknown|history/i);
});

test("persistence time is charged before returning the original remaining allowance", t => {
  const f = fixture(t); let mono = 0;
  const guard = () => { mono += 3; };
  const budget = startGuardedProposalDeadline({ dir: f.dir, origin, executionId: f.executionId, guard },
    { wall: () => start + mono, monotonic: () => mono });
  const left = budget.remainingMs();
  assert.equal(left, 600_000 - mono); assert(mono >= 6);
});

test("expiry during a final persistence guard cannot return its stale positive remainder", t => {
  const f = fixture(t); let mono = 0, calls = 0;
  const budget = startGuardedProposalDeadline({ dir: f.dir, origin, executionId: f.executionId,
    guard: () => { if (++calls === 3) mono += 2; } },
  { wall: () => start + mono, monotonic: () => mono });
  mono = 599_999;
  assert.throws(budget.remainingMs, /deadline-exceeded/);
});

test("persistence callbacks cannot swap the original remaining-time function", t => {
  const f = fixture(t), clock = startProposalDeadline(origin, { wall: () => start, monotonic: () => 0 });
  const budget = guardGenerationAttempt({ dir: f.dir, origin, executionId: f.executionId,
    guard: () => { clock.remainingMs = () => 600_000; } }, clock);
  assert.throws(budget.remainingMs, /original clock callbacks changed/);
});
