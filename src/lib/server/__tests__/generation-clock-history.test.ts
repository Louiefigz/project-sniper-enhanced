/** TEST-only private history files; guards model the enclosing lease, not lock-free writer CAS. */
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import test, { type TestContext } from "node:test";
import { canonicalJson, canonicalJsonSha256 } from "../auto-edit-hash";
import { readGenerationClockHistory, publishGenerationClockWatermark } from "../generation-clock-history";

const origin = { clockHash: "a".repeat(64), startedAt: "2026-09-08T00:00:00.000Z" };
const execution = "f612f0c0-bd72-4adf-96b9-50fbb55ef777";
const at = (milliseconds: number) => new Date(Date.parse(origin.startedAt) + milliseconds).toISOString();
function value(milliseconds = 0, id = execution) {
  const body = { schemaVersion: 2, kind: "generation-wall-clock-watermark", clockHash: origin.clockHash,
    generationStartedAt: origin.startedAt, executionId: id, observedAt: at(milliseconds) };
  return { ...body, watermarkHash: canonicalJsonSha256(body) };
}
function fixture(t: TestContext) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "generation-history-unit-")));
  t.after(() => {
    assert.equal(fs.realpathSync(root), root); assert.equal(path.dirname(root), fs.realpathSync(os.tmpdir()));
    fs.rmSync(root, { recursive: true, force: true });
  });
  const directory = path.join(root, "history"); fs.mkdirSync(directory, { mode: 0o700 });
  return { root, directory, read: () => readGenerationClockHistory(directory, origin) };
}
function legacy(directory: string, milliseconds = 0) {
  const row = { schemaVersion: 1, kind: "generation-wall-clock-observation", clockHash: origin.clockHash,
    generationStartedAt: origin.startedAt, executionId: execution, observedAt: at(milliseconds) };
  const file = path.join(directory, `${canonicalJsonSha256(row)}.json`);
  fs.writeFileSync(file, canonicalJson(row), { flag: "wx", mode: 0o600 }); return file;
}
function publish(directory: string, milliseconds: number, id = execution) {
  publishGenerationClockWatermark(readGenerationClockHistory(directory, origin), value(milliseconds, id), () => undefined);
}

test("legacy observations remain byte-identical while one execution advances one fresh-read watermark", t => {
  const f = fixture(t), old = legacy(f.directory), original = fs.readFileSync(old), oldStat = fs.lstatSync(old, { bigint: true });
  for (let index = 1; index <= 12; index++) publish(f.directory, index);
  const held = f.read(); assert.equal(held.names.length, 2); assert.equal(held.highWater, at(12));
  assert.equal(held.observedAtForExecution(execution), at(12)); assert.equal(held.observedAtForExecution(randomUUID()), undefined);
  assert.deepEqual(fs.readFileSync(old), original); assert.deepEqual(fs.lstatSync(old, { bigint: true }), oldStat);
  assert.equal(fs.lstatSync(path.join(f.directory, `${execution}.json`)).mode & 0o777, 0o600);
  held.assertCurrent(); assert(Object.isFrozen(held.names)); assert(Object.isFrozen(held));
});

test("equal global time on a different execution retains its own record", t => {
  const f = fixture(t), other = randomUUID(); publish(f.directory, 1); publish(f.directory, 1, other);
  assert.equal(f.read().names.length, 2); assert.equal(f.read().observedAtForExecution(other), at(1));
});

test("every read detects changed bytes instead of borrowing a cached history", t => {
  const f = fixture(t); publish(f.directory, 1); const held = f.read();
  fs.writeFileSync(path.join(f.directory, `${execution}.json`), "{}");
  assert.throws(() => held.assertCurrent(), /file changed/); assert.throws(f.read, /missing|unknown/);
});

test("same-byte inode replacement is not adopted by the original held history", t => {
  const f = fixture(t); publish(f.directory, 1); const held = f.read(), target = path.join(f.directory, `${execution}.json`);
  const replacement = path.join(f.root, "TEST-replacement"); fs.writeFileSync(replacement, fs.readFileSync(target)); fs.renameSync(replacement, target);
  assert.throws(() => held.assertCurrent(), /file changed/);
});

test("unknown files, links and oversized history bytes reject", t => {
  const f = fixture(t), unknown = path.join(f.directory, "TEST-unknown"); fs.writeFileSync(unknown, "TEST");
  assert.throws(f.read, /unknown file/); fs.unlinkSync(unknown);
  fs.symlinkSync(path.join(f.root, "TEST-absent"), path.join(f.directory, `${execution}.json`));
  assert.throws(f.read, /single-link/); fs.unlinkSync(path.join(f.directory, `${execution}.json`));
  fs.writeFileSync(path.join(f.directory, `${execution}.json`), Buffer.alloc(65537));
  assert.throws(f.read, /bounded regular/);
});

test("noncanonical raw JSON, bad watermark digest, mixed schema/name and foreign origin reject", t => {
  for (const kind of ["pretty", "hash", "name", "origin"]) {
    const f = fixture(t), row = value();
    if (kind === "hash") row.watermarkHash = "0".repeat(64);
    if (kind === "origin") row.clockHash = "0".repeat(64);
    const name = kind === "name" ? `${canonicalJsonSha256(row)}.json` : `${execution}.json`;
    fs.writeFileSync(path.join(f.directory, name), kind === "pretty" ? JSON.stringify(row, null, 2) : canonicalJson(row));
    assert.throws(f.read, /canonical|hash|changed|original request/);
  }
});

test("exactly512 legacy facts remain fenced rather than migrated, reset or deleted", t => {
  const f = fixture(t); for (let index = 0; index < 512; index++) legacy(f.directory, index);
  const held = f.read(), names = fs.readdirSync(f.directory).sort(); assert.equal(held.names.length, 512);
  assert.throws(() => publishGenerationClockWatermark(held, value(512), () => undefined), /capacity exhausted/);
  assert.deepEqual(fs.readdirSync(f.directory).sort(), names);
});

test("512 total entries permits only the already-present execution watermark to advance", t => {
  const f = fixture(t); for (let index = 0; index < 511; index++) legacy(f.directory, index);
  publish(f.directory, 511); publish(f.directory, 512);
  assert.equal(f.read().names.length, 512); assert.equal(f.read().highWater, at(512));
  assert.throws(() => publish(f.directory, 513, randomUUID()), /capacity exhausted/);
});

test("stale histories cannot publish over a newer observation or unseen execution", t => {
  const f = fixture(t), held = f.read(); publish(f.directory, 2);
  assert.throws(() => publishGenerationClockWatermark(held, value(3), () => undefined), /entry set/);
  assert.equal(f.read().highWater, at(2)); assert.throws(() => publish(f.directory, 1), /backwards/);
});

test("a lost prepublication lease removes only its own temp and preserves original records", t => {
  const f = fixture(t), old = legacy(f.directory), bytes = fs.readFileSync(old), failure = new Error("TEST lease lost");
  assert.throws(() => publishGenerationClockWatermark(f.read(), value(1), () => { throw failure; }), error => error === failure);
  assert.deepEqual(fs.readdirSync(f.directory), [path.basename(old)]); assert.deepEqual(fs.readFileSync(old), bytes);
});

test("postpublication guard failure retains advanced durable bytes and never restores older time", t => {
  const f = fixture(t); publish(f.directory, 1); let calls = 0; const failure = new Error("TEST lease lost after rename");
  assert.throws(() => publishGenerationClockWatermark(f.read(), value(2), () => { if (++calls === 2) throw failure; }), error => error === failure);
  assert.equal(f.read().highWater, at(2)); assert.equal(fs.readdirSync(f.directory).length, 1);
});

test("one file sync and one directory sync persist each successful publication", t => {
  const f = fixture(t), realSync = fs.fsyncSync, kinds: string[] = [];
  const sync = t.mock.method(fs, "fsyncSync", (fd: number) => {
    kinds.push(fs.fstatSync(fd).isDirectory() ? "directory" : "file"); realSync(fd);
  });
  const redundant = t.mock.method(fs, "fdatasyncSync", () => { throw new Error("TEST redundant flush"); });
  try { publish(f.directory, 1); publish(f.directory, 2); }
  finally { sync.mock.restore(); redundant.mock.restore(); }
  assert.deepEqual(kinds, ["file", "directory", "file", "directory"]); assert.equal(f.read().highWater, at(2));
});

test("file sync failure preserves old bytes and cleans only the unpublished owned temp", t => {
  const f = fixture(t), old = legacy(f.directory), bytes = fs.readFileSync(old), failure = new Error("TEST file sync failed");
  const mock = t.mock.method(fs, "fsyncSync", () => { throw failure; });
  try { assert.throws(() => publish(f.directory, 1), error => error === failure); }
  finally { mock.mock.restore(); }
  assert.deepEqual(fs.readdirSync(f.directory), [path.basename(old)]); assert.deepEqual(fs.readFileSync(old), bytes);
});

test("directory sync failure retains the advanced target without claiming successful persistence", t => {
  const f = fixture(t); publish(f.directory, 1); const realSync = fs.fsyncSync, failure = new Error("TEST directory sync failed");
  const mock = t.mock.method(fs, "fsyncSync", (fd: number) => {
    if (fs.fstatSync(fd).isDirectory()) throw failure;
    realSync(fd);
  });
  try { assert.throws(() => publish(f.directory, 2), error => error === failure); }
  finally { mock.mock.restore(); }
  assert.deepEqual(fs.readdirSync(f.directory), [`${execution}.json`]); assert.equal(f.read().highWater, at(2));
});

test("the prepublication callback cannot mutate original records or caller value unnoticed", t => {
  const f = fixture(t), old = legacy(f.directory), row = value(1);
  assert.throws(() => publishGenerationClockWatermark(f.read(), row, () => { fs.writeFileSync(old, "{}"); }), /history file changed/);
  assert.equal(fs.existsSync(path.join(f.directory, `${execution}.json`)), false);
  const other = fixture(t), changed = value(1);
  assert.throws(() => publishGenerationClockWatermark(other.read(), changed, () => { changed.observedAt = at(2); }), /original value changed/);
  assert.deepEqual(fs.readdirSync(other.directory), []);
});

test("postpublication callback substitution is detected without deleting the changed target", t => {
  const f = fixture(t); let calls = 0;
  assert.throws(() => publishGenerationClockWatermark(f.read(), value(1), () => {
    if (++calls === 2) fs.writeFileSync(path.join(f.directory, `${execution}.json`), "{\"TEST\":\"changed\"}");
  }), /history file changed/);
  assert.equal(fs.readFileSync(path.join(f.directory, `${execution}.json`), "utf8"), "{\"TEST\":\"changed\"}");
});

test("temporary path substitution never authorizes deleting a different inode", t => {
  const f = fixture(t), realWrite = fs.writeSync; let replaced = false, target = "";
  const mock = t.mock.method(fs, "writeSync", (...args: Parameters<typeof fs.writeSync>) => {
    if (!replaced) {
      replaced = true; target = path.join(f.directory, fs.readdirSync(f.directory).find(name => name.endsWith(".tmp"))!);
      fs.renameSync(target, path.join(f.root, "TEST-held-temp")); fs.writeFileSync(target, "TEST foreign inode");
    }
    return Reflect.apply(realWrite, fs, args) as number;
  });
  try { assert.throws(() => publish(f.directory, 1), /temporary cleanup uncertain|ownership changed/); }
  finally { mock.mock.restore(); }
  assert.equal(fs.readFileSync(target, "utf8"), "TEST foreign inode"); assert.equal(fs.existsSync(path.join(f.directory, `${execution}.json`)), false);
});

test("callers cannot ignore arbitrary history entries or reconstruct live read authority", t => {
  const f = fixture(t), held = f.read();
  assert.throws(() => held.assertCurrent("TEST-unowned.tmp"), /unowned temporary/);
  assert.throws(() => publishGenerationClockWatermark({ ...held }, value(), () => undefined), /original live read/);
});

test("uncertain temporary cleanup retains even a falsy original callback failure", t => {
  const f = fixture(t); let foreign = "";
  assert.throws(() => publishGenerationClockWatermark(f.read(), value(1), () => {
    foreign = path.join(f.directory, fs.readdirSync(f.directory).find(name => name.endsWith(".tmp"))!);
    fs.renameSync(foreign, path.join(f.root, "TEST-held-temp")); fs.writeFileSync(foreign, "TEST foreign inode");
    throw 0;
  }), error => error instanceof AggregateError && error.errors[0] === 0 && error.errors[1] instanceof Error);
  assert.equal(fs.readFileSync(foreign, "utf8"), "TEST foreign inode");
});
