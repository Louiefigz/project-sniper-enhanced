/** Actual historical metadata proof only; native source/media replay and initial claim admission are TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { assertSourceColorReadbackHistoryMetadata, readSourceColorReadbackHistory } from "../guided-source-color-readback-history";
import { readHeldSourceColorOpeningResult } from "../guided-source-color-opening-result";
import { historyFixtureFile, replaceHistoryFile, rewriteHistoryRecord, sourceColorReadbackHistoryFixture } from "./_guided-source-color-readback-history-fixture";

test("actual service records join genuine historical cleanup and same-held result without granting selection", async t => {
  const f = await sourceColorReadbackHistoryFixture(t), held = f.read();
  assert(Object.isFrozen(held)); assert.equal(held.mediaSelected, false); assert.equal(held.openingApproved, false);
  assert.equal(held.deliveryApproved, false); assert.equal(f.counts.native, 1);
  assert.doesNotThrow(() => assertSourceColorReadbackHistoryMetadata(held));
  assert.throws(() => assertSourceColorReadbackHistoryMetadata({ ...held }), /actual original metadata handle/);
  assert.throws(() => assertSourceColorReadbackHistoryMetadata(JSON.parse(JSON.stringify(held))), /actual original metadata handle/);
});

test("actual current pre-selection cleanup is also accepted only with its own actual same-held result", async t => {
  const f = await sourceColorReadbackHistoryFixture(t), cleanup = f.verified.observed;
  const selected = readHeldSourceColorOpeningResult({ held: cleanup.held, guard: () => {} });
  const held = readSourceColorReadbackHistory({ ...f.input, cleanup, selected });
  assert.doesNotThrow(() => assertSourceColorReadbackHistoryMetadata(held));
});

test("copied cleanup/result and independently genuine wrong-held result refuse before the caller guard", async t => {
  const f = await sourceColorReadbackHistoryFixture(t);
  const variants = [{ cleanup: { ...f.input.cleanup } }, { selected: { ...f.input.selected } }, { selected: f.verified.selected }];
  for (const change of variants) {
    assert.throws(() => readSourceColorReadbackHistory({ ...f.input, ...change }), /actual|original|metadata/);
  }
  assert.equal(f.calls.guard, 0);
});

test("schema1, malformed role and changed exact references refuse before guard", async t => {
  const f = await sourceColorReadbackHistoryFixture(t);
  const variants = [{ schemaVersion: 1 }, { readbackDirectory: "../other" }, { beforeJournalHash: "f".repeat(64) },
    { claimHash: "f".repeat(64) }, { mediaResultSha256: "f".repeat(64) }, { outputRoot: "/TEST/not-original" }, { extra: true }];
  for (const change of variants) {
    const input = { ...f.input, reference: { ...f.input.reference, ...change } };
    assert.throws(() => readSourceColorReadbackHistory(input as typeof f.input));
  }
  assert.equal(f.calls.guard, 0);
});

for (const role of ["start", "output", "verified"] as const) {
  test(`first original guard cannot replace later ${role} bytes with an equal-byte inode`, async t => {
    const f = await sourceColorReadbackHistoryFixture(t), bytes = fs.readFileSync(f.files[role]);
    f.callbacks.guard = () => { if (f.calls.guard === 1) replaceHistoryFile(f, role); };
    assert.throws(f.read, /identity/); assert.deepEqual(fs.readFileSync(f.files[role]), bytes);
  });
}

test("final original guard cannot mutate reference fields after all record reads", async t => {
  const f = await sourceColorReadbackHistoryFixture(t); f.read(); const total = f.calls.guard; f.calls.guard = 0;
  f.callbacks.guard = () => { if (f.calls.guard === total) f.input.reference.receiptHash = "f".repeat(64); };
  assert.throws(f.read, /reference metadata/);
});

test("late cancellation and recursive reads cannot publish a metadata handle", async t => {
  const f = await sourceColorReadbackHistoryFixture(t); f.read(); const total = f.calls.guard; f.calls.guard = 0;
  f.callbacks.guard = () => { if (f.calls.guard === total) throw new Error("TEST original read allowance expired"); };
  assert.throws(f.read, /original read allowance expired/);
  f.callbacks.guard = () => { f.read(); }; assert.throws(f.read, /reenter/);
});

test("later checks keep original file and input identities without calling old guards or sampling a clock", async t => {
  const f = await sourceColorReadbackHistoryFixture(t), held = f.read(), count = f.calls.guard;
  f.callbacks.guard = () => { throw new Error("TEST expired old callback must not run"); };
  t.mock.method(performance, "now", () => { throw new Error("TEST no new clock"); });
  assert.doesNotThrow(() => assertSourceColorReadbackHistoryMetadata(held)); assert.equal(f.calls.guard, count);
  replaceHistoryFile(f, "verified"); assert.throws(() => assertSourceColorReadbackHistoryMetadata(held), /identity/);
});

test("later input reference and callback replacements do not rebaseline a held proof", async t => {
  const f = await sourceColorReadbackHistoryFixture(t), held = f.read(), reference = f.input.reference, guard = f.input.guard;
  f.input.reference = { ...reference }; assert.throws(() => assertSourceColorReadbackHistoryMetadata(held), /caller identity/);
  f.input.reference = reference; f.input.guard = () => {}; assert.throws(() => assertSourceColorReadbackHistoryMetadata(held), /caller identity/);
  f.input.guard = guard; f.input.selected.record.bytes[0] ^= 1;
  assert.throws(() => assertSourceColorReadbackHistoryMetadata(held), /metadata|bytes/);
});

test("mixed record versions and raw hash substitutions never inherit schema2 proof", async t => {
  const f = await sourceColorReadbackHistoryFixture(t), file = historyFixtureFile(f, "start"), bytes = fs.readFileSync(file);
  fs.writeFileSync(file, Buffer.concat([bytes, Buffer.from("\n")])); assert.throws(f.read, /raw record/);
  rewriteHistoryRecord(f, "start", row => { row.schemaVersion = 1; }); assert.throws(f.read, /start record/);
});

test("actual raw reference cannot hide altered source, archive, tools or false flags", async t => {
  const f = await sourceColorReadbackHistoryFixture(t), file = historyFixtureFile(f, "start"), original = JSON.parse(fs.readFileSync(file, "utf8"));
  const changes = [(row: Record<string, unknown>) => { (row.archive as Record<string, unknown>).sha256 = "f".repeat(64); },
    (row: Record<string, unknown>) => { (row.sourceColor as Record<string, unknown>).sourceColorHash = "f".repeat(64); },
    (row: Record<string, unknown>) => { (row.tools as Record<string, unknown>).python = "/TEST/other-python"; }];
  for (const change of changes) {
    rewriteHistoryRecord(f, "start", row => { Object.assign(row, structuredClone(original)); change(row); });
    assert.throws(f.read, /start record/);
  }
});

test("closed verified record rejects changed approval flags with its forged matching raw hash", async t => {
  const f = await sourceColorReadbackHistoryFixture(t);
  rewriteHistoryRecord(f, "verified", row => { row.openingApproved = true; }); assert.throws(f.read, /verified record/);
});

test("selection timestamp cannot predate verified record and output cannot upgrade the child result", async t => {
  const f = await sourceColorReadbackHistoryFixture(t), original = f.input.reference.selectionQualifiedAt;
  f.input.reference.selectionQualifiedAt = f.input.reference.generationStartedAt;
  assert.throws(f.read, /timestamps/); f.input.reference.selectionQualifiedAt = original;
  rewriteHistoryRecord(f, "output", row => { const result = JSON.parse(String(row.stdout)); result.colorQualified = true; row.stdout = JSON.stringify(result); });
  assert.throws(f.read, /unapproved|coverage|scope/);
});
