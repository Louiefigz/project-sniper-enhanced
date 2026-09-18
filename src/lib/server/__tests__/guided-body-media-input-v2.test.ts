/** Real TEMP raw reads, explicit native fence; no genuine body admission or native media work is claimed. */
import assert from "node:assert/strict";
import fs from "node:fs";
import childProcess from "node:child_process";
import test from "node:test";
import { observeGuidedBodyMediaInput, writeGuidedBodyMediaInput, assertBodyInputReferences, type BodyAdmission } from "../guided-body-input";
import { runActivatedBodyMedia } from "../guided-body-process";
import { parseCurrentBodyMediaInput } from "@/lib/producer/contracts/guided-body-media-v1";
import { bodyMediaInputV2Fixture, replaceBodyMediaInputV2File, publishBodyMediaInputV2Case } from "./_guided-body-media-input-v2-fixture";

test("body media V2 observes only exact seven references and bounded original replay raw bytes", t => {
  t.mock.method(childProcess, "spawn", () => { throw new Error("TEST no native child"); });
  const f = bodyMediaInputV2Fixture(t), result = observeGuidedBodyMediaInput(f.file, f.sha256);
  assert.deepEqual(result.input, f.value); assert.equal(result.sourceBytesObserved, false);
  assert.equal(result.currentJournalObserved, false); assert.equal(result.record.sha256, f.sha256);
  assert.equal(result.input.schemaVersion, 2);
});
test("body media V1 still observes its original files without reading any replay path", t => {
  const f = bodyMediaInputV2Fixture(t), { sourceColorReplay: _replay, ...common } = f.value; void _replay;
  const value = { ...common, schemaVersion: 1 }, sha = publishBodyMediaInputV2Case(f, value);
  const open = fs.openSync;
  t.mock.method(fs, "openSync", (...args: Parameters<typeof fs.openSync>) => {
    assert.notEqual(args[0], f.paths.input); assert.notEqual(args[0], f.paths.archive); return open(...args);
  });
  assert.deepEqual(observeGuidedBodyMediaInput(f.file, sha).input, value);
});
test("body media V2 rejects changed raw input or archive bytes", t => {
  for (const role of ["input", "archive"] as const) {
    const f = bodyMediaInputV2Fixture(t); replaceBodyMediaInputV2File(f, role, "TEST changed original bytes");
    assert.throws(() => observeGuidedBodyMediaInput(f.file, f.sha256), /raw metadata bytes or size/);
  }
});
test("body media V2 rejects exact raw SHA with changed declared size", t => {
  for (const role of ["input", "reservationArchive"] as const) {
    const f = bodyMediaInputV2Fixture(t), value = structuredClone(f.value); value.sourceColorReplay[role].sizeBytes++;
    const sha = publishBodyMediaInputV2Case(f, value);
    assert.throws(() => observeGuidedBodyMediaInput(f.file, sha), /raw metadata bytes or size/);
  }
});
test("body media V2 bounds each raw reference at 8 MiB before retaining its bytes", t => {
  const f = bodyMediaInputV2Fixture(t); replaceBodyMediaInputV2File(f, "archive", Buffer.alloc(8 * 1024 * 1024 + 1, 65));
  assert.throws(() => observeGuidedBodyMediaInput(f.file, f.sha256), /bounded regular/);
});
test("body media V2 refuses linked original replay metadata rather than following it", t => {
  const f = bodyMediaInputV2Fixture(t), file = f.paths.archive, info = fs.lstatSync(file);
  assert(info.isFile()); assert.equal(info.nlink, 1); assert.equal(fs.realpathSync(file), file);
  fs.unlinkSync(file); fs.symlinkSync(f.paths.input, file);
  assert.throws(() => observeGuidedBodyMediaInput(f.file, f.sha256), /single-link/);
});
test("body media V2 retains the first replay inode through the last raw metadata read", t => {
  const f = bodyMediaInputV2Fixture(t), open = fs.openSync; let armed = true;
  t.mock.method(fs, "openSync", (...args: Parameters<typeof fs.openSync>) => {
    if (armed && args[0] === f.paths.archive) { armed = false; replaceBodyMediaInputV2File(f, "input"); }
    return open(...args);
  });
  assert.throws(() => observeGuidedBodyMediaInput(f.file, f.sha256), /original publication changed/);
});
test("body media V2 refuses an authentic-looking DTO before original writer guard or publication", t => {
  const f = bodyMediaInputV2Fixture(t); let callbacks = 0;
  const held = { input: { row: { schemaVersion: 2 }, input: { schemaVersion: 2, sourceColorReplay: f.value.sourceColorReplay } } } as unknown as BodyAdmission;
  const before = fs.readFileSync(f.file);
  assert.throws(() => writeGuidedBodyMediaInput(held, () => { callbacks++; }), /actual original/);
  assert.throws(() => assertBodyInputReferences(held, parseCurrentBodyMediaInput(f.value)), /actual original/);
  assert.equal(callbacks, 0); assert.deepEqual(fs.readFileSync(f.file), before);
});
test("source2 body native fence runs before any callback, tools, directory or intent access", async t => {
  t.mock.method(childProcess, "spawn", () => { throw new Error("TEST native fence failed"); });
  let callbacks = 0;
  const held = { invocation: { input: { schemaVersion: 2 } }, get admission() { throw new Error("TEST touched admission after fence"); } };
  const input = { held, get lease() { throw new Error("TEST touched lease after fence"); }, remainingMs: () => { callbacks++; return 1; } };
  await assert.rejects(runActivatedBodyMedia(input as unknown as Parameters<typeof runActivatedBodyMedia>[0]), /controller\/runtime and native qualification are unfinished/);
  assert.equal(callbacks, 0);
});
