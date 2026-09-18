/** Private typed snapshots; real TEMP raw observations, no source/process/native admission. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import test from "node:test";
import { isDeepStrictEqual } from "node:util";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { snapshotSourceColorMetadata } from "../guided-source-color-staging-hold";
import { recoverSourceColorResource } from "../guided-source-color-resource-recovery";
import { sourceColorRecoveryFixture } from "./_guided-source-color-resource-recovery-fixture";
import { cleanupAttemptWriterFixture, assertWriterRetained } from "./_guided-source-color-cleanup-attempt-fixture";
import { sourceColorArchiveFixture } from "./_guided-source-color-reservation-archive-fixture";

test("actual raw object observation keeps Buffer type, exact bytes and repeated references", t => {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "TEST-color-snapshot-")));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const file = path.join(root, "journal.json");
  fs.writeFileSync(file, '{"brief":"雪 🛰️ hostile </script>","count":24}\n', { flag: "wx", mode: 0o600 });
  const observed = readCutPreviewObject(file), original = { observed, repeated: observed, bytes: observed.bytes };
  const copied = snapshotSourceColorMetadata(original);
  assert(!isDeepStrictEqual(original, structuredClone(original))); assert.deepEqual(copied, original);
  assert(Buffer.isBuffer(copied.observed.bytes)); assert.notEqual(copied.observed.bytes, observed.bytes);
  assert.equal(copied.observed, copied.repeated); assert.equal(copied.bytes, copied.observed.bytes);
  assert.equal(copied.observed.sizeBytes, copied.bytes.length); assert.deepEqual(copied.bytes, fs.readFileSync(file));
  assert(!Object.isFrozen(observed.bytes)); observed.bytes[0] ^= 1;
  assert(!isDeepStrictEqual(original, copied)); assert.deepEqual(copied.bytes, fs.readFileSync(file));
});

test("typed private data retains numeric distinctions, cycles and container identity", () => {
  const bytes = Buffer.from([0, 255]), shared = { bytes }, value = {
    bytes, uint8: new Uint8Array([0, 255]), shared, again: shared, missing: undefined,
    negativeZero: -0, invalid: NaN, huge: BigInt(12), set: new Set([1, 2]), map: new Map([["same", shared]]), self: null as unknown,
  };
  value.self = value; const copied = snapshotSourceColorMetadata(value);
  assert.deepEqual(copied, value); assert.equal(copied.self, copied); assert.equal(copied.map.get("same"), copied.shared);
  assert.equal(copied.shared, copied.again); assert.equal(copied.bytes, copied.shared.bytes);
  assert(Buffer.isBuffer(copied.bytes)); assert(!Buffer.isBuffer(copied.uint8)); assert(Object.is(copied.negativeZero, -0));
  assert(Object.hasOwn(copied, "missing")); assert.notEqual(copied.shared, shared);
});

test("unsupported functions and prototype conversion never silently become a metadata baseline", () => {
  assert.throws(() => snapshotSourceColorMetadata({ callback: () => {} }));
  const value = Object.assign(Object.create(null), { bytes: Buffer.from("TEST") });
  assert.throws(() => snapshotSourceColorMetadata(value), /snapshot changed its original types or values/);
  assert(Buffer.isBuffer(value.bytes)); assert.equal(Object.getPrototypeOf(value), null);
});

test("cold resource recovery accepts actual observed Buffer then rejects in-place raw mutation", t => {
  const f = sourceColorRecoveryFixture(t), original = Buffer.from(f.input.held.bytes);
  assert(Buffer.isBuffer(f.input.held.bytes)); assert.equal(f.input.held.sizeBytes, original.length);
  assert.deepEqual(f.input.held.value, f.input.held.job); f.releaseOriginal();
  const recovered = recoverSourceColorResource(f.input, f.dependencies); recovered.assertCurrent();
  assert(!Object.isFrozen(f.input.held.bytes)); f.input.held.bytes[0] ^= 1;
  assert.throws(recovered.assertCurrent, /original claim\/stopped metadata/); recovered.assertResource();
  assert.deepEqual(fs.readFileSync(path.join(f.staging.root, "TEST-initial-job.json")), original);
  recovered.lease.release();
});

test("first recovery callback cannot rebaseline observed raw Buffer before acquisition", t => {
  const f = sourceColorRecoveryFixture(t); f.releaseOriginal();
  f.callbacks.guard = () => { f.input.held.bytes[0] ^= 1; };
  assert.throws(() => recoverSourceColorResource(f.input, f.dependencies), /original claim\/stopped metadata/);
  assert.equal(f.events.acquires, 0); assert(fs.existsSync(f.staged.reservation.path));
});

test("same-byte Uint8Array cannot replace the original observed Buffer type", async t => {
  const f = cleanupAttemptWriterFixture(t), original = f.writerInput.held.bytes;
  f.clockCallbacks.remaining = () => { Object.assign(f.writerInput.held, { bytes: new Uint8Array(original) }); };
  await assert.rejects(f.write(), /original caller metadata changed/);
  assert.equal(f.counts.run, 0); assertWriterRetained(f);
});

test("writer first callback catches mutable raw Buffer bytes without freezing the caller", async t => {
  const f = cleanupAttemptWriterFixture(t), original = Buffer.from(f.writerInput.held.bytes);
  assert(Buffer.isBuffer(f.writerInput.held.bytes)); assert.deepEqual(f.writerInput.held.value, f.writerInput.held.job);
  f.clockCallbacks.remaining = () => { f.writerInput.held.bytes[0] ^= 1; };
  await assert.rejects(f.write(), /original caller metadata changed/); assert.equal(f.counts.run, 0);
  assert.deepEqual(fs.readFileSync(path.join(f.staging.root, "TEST-attempt-job.json")), original); assertWriterRetained(f);
});

test("actual writer and historical reader preserve raw evidence through the final callback", async t => {
  const f = cleanupAttemptWriterFixture(t); let reading = false;
  const read = f.writerDependencies.read;
  f.writerDependencies.read = input => { reading = true; return read(input); };
  f.clockCallbacks.guard = () => { if (reading) f.writerInput.held.bytes[0] ^= 1; };
  await assert.rejects(f.write(), /original caller metadata changed/);
  assert.equal(f.calls.length, 1); assert.equal(f.counts.read, 1); assertWriterRetained(f);
});

test("archive historical metadata retains its original observed bytes after successful read", t => {
  const f = sourceColorArchiveFixture(t), written = f.write(), read = f.read(written.archive);
  read.assertCurrent(); f.context.held.bytes[0] ^= 1;
  assert.throws(read.assertCurrent, /original claim\/reference metadata/);
  assert(fs.existsSync(f.staged.reservation.path));
});
