/** Actual TEMP archive/raw-file tests; process admission and historical authority are TEST-only stubs. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { readSourceColorReservationArchive, writeSourceColorReservationArchive } from "../guided-source-color-reservation-archive";
import { sourceColorArchiveFixture, replaceArchiveFixtureFile, removeArchiveFixtureActive } from "./_guided-source-color-reservation-archive-fixture";

test("writer copies exact original literal bytes into only its existing private attempt", t => {
  const f = sourceColorArchiveFixture(t), active = fs.lstatSync(f.staged.reservation.path, { bigint: true });
  const saved = f.write(); saved.assertCurrent();
  assert.deepEqual(saved.archive, { path: f.archivePath, sha256: f.staged.reservation.sha256, sizeBytes: f.staged.reservation.sizeBytes });
  assert.deepEqual(fs.readFileSync(f.archivePath), f.bytes); assert.deepEqual(fs.readFileSync(f.staged.reservation.path), f.bytes);
  assert.deepEqual(fs.lstatSync(f.staged.reservation.path, { bigint: true }), active);
  assert.deepEqual(saved.reference, f.context.reservation.reference);
  assert.deepEqual(saved.containerNames, f.staged.jobs.map(job => job.containerName));
  assert.deepEqual(fs.readdirSync(f.attempt), ["reservation.json"]);
  assert(Object.isFrozen(saved.archive)); assert(Object.isFrozen(saved.reference)); assert(Object.isFrozen(saved.containerNames));
  assert(!Object.isFrozen(f.context.held));
});

test("historical read never opens or stats current active.json, sidecar, jobs, claim or input", t => {
  const f = sourceColorArchiveFixture(t), saved = f.write(); removeArchiveFixtureActive(f); f.releaseOriginal();
  fs.writeFileSync(f.staged.reservation.path, "TEST later unrelated reservation, not JSON", { flag: "wx", mode: 0o600 });
  const forbidden = new Set([f.staged.reservation.path, f.staged.input.path, f.input.held.claimPath, f.input.held.claim.inputPath,
    ...f.staged.jobs.flatMap(job => [job.input.path, job.implementation.path, job.launchClaim.path])]);
  const realStat = fs.lstatSync, realOpen = fs.openSync, opened: unknown[] = [];
  const statMock = t.mock.method(fs, "lstatSync", (...args: Parameters<typeof fs.lstatSync>) => {
    assert(!forbidden.has(String(args[0]))); return Reflect.apply(realStat, fs, args);
  });
  const openMock = t.mock.method(fs, "openSync", (...args: Parameters<typeof fs.openSync>) => {
    opened.push(args[0]); assert.equal(args[0], f.archivePath); return Reflect.apply(realOpen, fs, args);
  });
  try {
    const history = f.read(saved.archive); history.assertCurrent(); assert.deepEqual(history.reference, saved.reference);
    assert.deepEqual(history.containerNames, saved.containerNames); assert.deepEqual(opened, [f.archivePath]);
  } finally { statMock.mock.restore(); openMock.mock.restore(); }
  assert.throws(saved.assertCurrent); assert.equal(fs.existsSync(f.lock), false);
});

test("reader also succeeds when the active reservation is absent", t => {
  const f = sourceColorArchiveFixture(t), saved = f.write(); removeArchiveFixtureActive(f); f.releaseOriginal();
  f.read(saved.archive).assertCurrent(); assert.equal(fs.existsSync(f.staged.reservation.path), false);
});

test("writer cannot execute a forged JSON or duck-typed hold callback", t => {
  const f = sourceColorArchiveFixture(t); let calls = 0;
  const reservation = { ...f.context.reservation, assertCurrent: () => { calls++; } };
  assert.throws(() => writeSourceColorReservationArchive({ ...f.context, reservation }), /actual original metadata hold/);
  assert.equal(calls, 0); assert.equal(fs.existsSync(f.archivePath), false);
});

test("same attempt replay and any preexisting entry remain new-only fences", async t => {
  for (const kind of ["same-bytes", "different-bytes", "dangling-link", "directory"] as const) await t.test(kind, t => {
    const f = sourceColorArchiveFixture(t), missing = path.join(f.staging.root, "TEST-absent-archive-target");
    if (kind === "same-bytes") f.write();
    if (kind === "different-bytes") fs.writeFileSync(f.archivePath, "TEST prior failure", { flag: "wx", mode: 0o600 });
    if (kind === "dangling-link") fs.symlinkSync(missing, f.archivePath);
    if (kind === "directory") fs.mkdirSync(f.archivePath, { mode: 0o700 });
    const before = fs.lstatSync(f.archivePath, { bigint: true });
    assert.throws(f.write, /new-only/); assert.deepEqual(fs.lstatSync(f.archivePath, { bigint: true }), before);
    assert.deepEqual(fs.readFileSync(f.staged.reservation.path), f.bytes); assert.equal(fs.existsSync(missing), false);
  });
});

test("no missing attempt directory is created and aliased attempt paths reject", t => {
  const f = sourceColorArchiveFixture(t), attemptId = "00000000-0000-4000-8000-000000000032";
  const missing = path.join(path.dirname(f.attempt), attemptId);
  assert.throws(() => writeSourceColorReservationArchive({ ...f.context, attemptId }), /ENOENT/);
  assert.equal(fs.existsSync(missing), false); fs.symlinkSync(f.attempt, missing);
  assert.throws(() => writeSourceColorReservationArchive({ ...f.context, attemptId }), /Unsafe private/);
  assert(fs.lstatSync(missing).isSymbolicLink()); assert.equal(fs.existsSync(f.archivePath), false);
});

test("explicit archive path, raw hash, raw size, attempt and closed ref cannot be substituted", t => {
  const f = sourceColorArchiveFixture(t), saved = f.write(), original = f.readerContext(saved.archive);
  for (const patch of [{ path: path.join(f.staging.root, "TEST-other.json") }, { sha256: "0".repeat(64) },
    { sizeBytes: saved.archive.sizeBytes + 1 }, { extra: false }]) {
    assert.throws(() => readSourceColorReservationArchive({ ...original, archive: { ...original.archive, ...patch } }));
  }
  for (const attemptId of ["../escape", "00000000-0000-1000-8000-000000000031", "00000000-0000-4000-8000-000000000032"]) {
    assert.throws(() => readSourceColorReservationArchive({ ...original, attemptId }));
  }
});

test("historical process reference closes original namespace before opening archive bytes", t => {
  const f = sourceColorArchiveFixture(t), saved = f.write(), original = f.readerContext(saved.archive);
  let reads = 0;
  const mock = t.mock.method(fs, "openSync", () => { reads++; throw new Error("TEST archive should not be opened"); });
  try {
    for (const reference of [
      { ...original.reference, input: { ...original.reference.input, path: path.join(f.staging.root, "TEST-other-sidecar.json") } },
      { ...original.reference, reservation: { ...original.reference.reservation, path: path.join(f.staging.root, "active.json") } },
      { ...original.reference, extra: false },
    ]) assert.throws(() => readSourceColorReservationArchive({ ...original, reference }), error => {
      assert(error instanceof Error); assert.notEqual(error.message, "TEST archive should not be opened"); return true;
    });
    assert.equal(reads, 0);
  } finally { mock.mock.restore(); }
});

test("first writer callback cannot rebaseline original metadata or actual archive parent", async t => {
  for (const kind of ["claim", "callback", "parent"] as const) await t.test(kind, t => {
    const f = sourceColorArchiveFixture(t); let changed = false;
    f.callbacks.remaining = () => {
      if (changed) return 300_000; changed = true;
      if (kind === "claim") f.context.held.claimSha256 = "0".repeat(64);
      if (kind === "callback") f.context.guard = () => {};
      if (kind === "parent") fs.chmodSync(f.attempt, 0o500);
      return 300_000;
    };
    assert.throws(f.write, /original/); assert.equal(fs.existsSync(f.archivePath), false);
    if (kind === "parent") fs.chmodSync(f.attempt, 0o700);
  });
});

test("post-publication failure retains exact archive and original active record without selecting success", t => {
  const f = sourceColorArchiveFixture(t), failure = new Error("TEST postwrite guard refused");
  f.callbacks.guard = () => { if (fs.existsSync(f.archivePath)) throw failure; };
  assert.throws(f.write, error => error === failure);
  assert.deepEqual(fs.readFileSync(f.archivePath), f.bytes); assert.deepEqual(fs.readFileSync(f.staged.reservation.path), f.bytes);
  assert.deepEqual(fs.readdirSync(f.attempt), ["reservation.json"]);
});

test("original budget expiry after publication retains failure and all raw evidence", t => {
  const f = sourceColorArchiveFixture(t);
  f.callbacks.remaining = () => fs.existsSync(f.archivePath) ? 0 : 300_000;
  assert.throws(f.write, /deadline/); assert.deepEqual(fs.readFileSync(f.archivePath), f.bytes);
  assert.deepEqual(fs.readFileSync(f.staged.reservation.path), f.bytes);
});

test("historical first callback cannot adopt replacement file or original claim/ref objects", async t => {
  for (const kind of ["file", "claim", "reference", "callback"] as const) await t.test(kind, t => {
    const f = sourceColorArchiveFixture(t), saved = f.write(), context = f.readerContext(saved.archive);
    f.callbacks.guard = () => {
      if (kind === "file") replaceArchiveFixtureFile(f, f.archivePath);
      if (kind === "claim") context.held.claimSha256 = "0".repeat(64);
      if (kind === "reference") context.reference = structuredClone(context.reference);
      if (kind === "callback") context.remainingMs = () => 300_000;
    };
    assert.throws(() => readSourceColorReservationArchive(context), /original/);
  });
});

test("last historical observation callback mutation cannot escape as a valid report", t => {
  const f = sourceColorArchiveFixture(t), saved = f.write(); f.events.guards = 0;
  f.read(saved.archive); const last = f.events.guards; assert(last > 1); f.events.guards = 0;
  f.callbacks.guard = () => { if (f.events.guards === last) replaceArchiveFixtureFile(f, f.archivePath); };
  assert.throws(() => f.read(saved.archive), /original file/); assert.equal(f.events.guards, last);
});

test("raw byte corruption, hard links and late file mutation reject", async t => {
  for (const kind of ["bytes", "hardlink", "late"] as const) await t.test(kind, t => {
    const f = sourceColorArchiveFixture(t), saved = f.write();
    if (kind === "bytes") replaceArchiveFixtureFile(f, f.archivePath, Buffer.from("{\"TEST\":\"changed\"}"));
    if (kind === "hardlink") fs.linkSync(f.archivePath, path.join(f.attempt, "TEST-extra-link.json"));
    if (kind !== "late") { assert.throws(() => f.read(saved.archive)); return; }
    const history = f.read(saved.archive); replaceArchiveFixtureFile(f, f.archivePath); assert.throws(history.assertCurrent, /original file/);
  });
});

test("all invalid remaining values refuse historical read without renewing a clock", t => {
  const f = sourceColorArchiveFixture(t), saved = f.write();
  for (const remaining of [0, -1, NaN, Infinity, 300_001]) {
    f.callbacks.remaining = () => remaining; assert.throws(() => f.read(saved.archive), /deadline/);
  }
  assert.deepEqual(fs.readFileSync(f.archivePath), f.bytes);
});

test("invalid original allowance refuses publication before any archive is written", t => {
  const f = sourceColorArchiveFixture(t);
  for (const remaining of [0, -1, NaN, Infinity, 300_001]) {
    f.callbacks.remaining = () => remaining; assert.throws(f.write, /deadline/);
    assert.equal(fs.existsSync(f.archivePath), false);
  }
  assert.deepEqual(fs.readFileSync(f.staged.reservation.path), f.bytes);
});
