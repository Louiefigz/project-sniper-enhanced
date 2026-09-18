/** Actual TEMP metadata/CAS/private capabilities. Native/readiness/admission remain explicit existing fixture TEST leaves. */
import assert from "node:assert/strict";
import test, { type TestContext } from "node:test";
import { readSelectedOpeningMedia, readHistoricalOpeningSelection } from "../guided-opening-selection";
import { readHeldSourceColorOpeningResult } from "../guided-source-color-opening-result";
import { holdBodySourceColorReplayReferences, assertBodySourceColorReplayMetadata } from "../guided-body-source-color-replay";
import { saveHumanCutJobSnapshot } from "../human-cut-acceptance-store";
import { parseBodySourceColorReplayReferences } from "@/lib/producer/contracts/guided-body-source-color-replay-v2";
import { sourceColorSelectionFixture, replaceSelectionFixtureFile } from "./_guided-source-color-selection-fixture";

/** Same existing allowance; metadata assertions below never call this guard again. */
async function fixture(t: TestContext) {
  const f = await sourceColorSelectionFixture(t); f.select(); const selected = readSelectedOpeningMedia(f.input.dir);
  const callbacks = { guard: () => {} }, calls = { guard: 0 };
  const guard = () => { calls.guard++; f.input.remainingMs(); callbacks.guard(); };
  const result = readHeldSourceColorOpeningResult({ held: selected.held, guard }); calls.guard = 0;
  return { f, selected, result, callbacks, calls, input: { selected, result, guard } };
}

test("body source replay joins actual current cleanup through its distinct actual held object", async t => {
  const f = await fixture(t); assert.notEqual(f.selected.held, f.selected.observed.held);
  const native = f.f.calls.native, held = holdBodySourceColorReplayReferences(f.input), refs = held.references;
  assertBodySourceColorReplayMetadata(held); assert.equal(f.f.calls.native, native);
  assert.deepEqual(refs.input, f.result.process.sourceColor!.input); assert.deepEqual(refs.reservationArchive, f.f.recorded.fact.archive);
  assert.equal(refs.opening.selectionHash, f.selected.selectionHash); assert.equal(refs.opening.mediaResultSha256, f.result.record.sha256);
  assert.equal(refs.opening.receiptHash, f.result.completion.receiptHash); assert.equal(refs.executable, false);
  assert.equal(refs.bodyApproved, false); assert.equal(refs.deliveryApproved, false);
});
test("body source replay supports genuine explicit historical selected cleanup without a current-journal clock", async t => {
  const f = await fixture(t); saveHumanCutJobSnapshot(f.f.input.dir, f.selected.observed);
  const selected = readHistoricalOpeningSelection(f.f.input.dir, f.selected.observed.sha256, f.input.guard);
  const result = readHeldSourceColorOpeningResult({ held: selected.held, guard: f.input.guard });
  const held = holdBodySourceColorReplayReferences({ selected, result, guard: f.input.guard }), count = f.calls.guard;
  f.callbacks.guard = () => { throw new Error("TEST original work guard must not be replayed"); };
  assertBodySourceColorReplayMetadata(held); assert.equal(f.calls.guard, count);
  assert.equal(held.references.opening.selectionHash, f.selected.selectionHash);
});
test("body source replay rejects copied or legacy parent handles before caller guard", async t => {
  const f = await fixture(t);
  for (const change of [{ selected: { ...f.selected } }, { result: { ...f.result } },
    { selected: { ...f.selected, fact: { ...f.selected.fact, schemaVersion: 1 } } }]) {
    assert.throws(() => holdBodySourceColorReplayReferences({ ...f.input, ...change }), /actual original/);
  }
  assert.equal(f.calls.guard, 0);
  const otherHeldResult = readHeldSourceColorOpeningResult({ held: f.selected.observed.held, guard: () => {} });
  assert.throws(() => holdBodySourceColorReplayReferences({ ...f.input, result: otherHeldResult }), /actual original/);
  assert.equal(f.calls.guard, 0);
});
test("body source replay refuses another genuine complete source2 execution before caller guard", async t => {
  const original = await fixture(t), other = await fixture(t);
  assert.throws(() => holdBodySourceColorReplayReferences({ ...original.input, result: other.result }), /actual original/);
  assert.equal(original.calls.guard, 0);
});
test("body source replay retains original selected result and guard identities across its first callback", async t => {
  const f = await fixture(t), original = { ...f.input };
  for (const change of [{ selected: { ...f.selected } }, { result: { ...f.result } }, { guard: () => original.guard() }]) {
    f.callbacks.guard = () => { Object.assign(f.input, change); };
    assert.throws(() => holdBodySourceColorReplayReferences(f.input), /original caller identity/); Object.assign(f.input, original);
  }
});
test("body source replay rejects exact original TEMP archive replacement at its first callback", async t => {
  const f = await fixture(t); f.callbacks.guard = () => { if (f.calls.guard === 1) replaceSelectionFixtureFile(f.f, "archive"); };
  assert.throws(() => holdBodySourceColorReplayReferences(f.input), /changed|identity/);
});
test("body source replay rejects final callback raw metadata drift and preserves immutable original source references", async t => {
  const f = await fixture(t), source = f.result.process.sourceColor!.input as unknown as { sha256: string }, original = source.sha256;
  f.callbacks.guard = () => { if (f.calls.guard === 2) f.result.record.bytes[0] ^= 1; };
  assert.throws(() => holdBodySourceColorReplayReferences(f.input), /changed/); f.result.record.bytes[0] ^= 1;
  assert.throws(() => { source.sha256 = "0".repeat(64); }, TypeError); assert.equal(source.sha256, original);
  f.callbacks.guard = () => {}; const held = holdBodySourceColorReplayReferences(f.input);
  f.result.record.bytes[0] ^= 1; assert.throws(() => assertBodySourceColorReplayMetadata(held), /changed/);
});
test("body source replay DTOs cannot reconstruct a capability or grant flags and retained files remain checked", async t => {
  const f = await fixture(t), held = holdBodySourceColorReplayReferences(f.input), count = f.calls.guard;
  assert.throws(() => assertBodySourceColorReplayMetadata({ ...held }), /actual original/);
  const data = parseBodySourceColorReplayReferences(held.references);
  assert.throws(() => assertBodySourceColorReplayMetadata({ ...held, references: data }), /actual original/);
  assert.throws(() => { held.references.input.sha256 = "b".repeat(64); }, TypeError);
  assert.throws(() => { held.references.bodyApproved = true as false; }, TypeError);
  f.callbacks.guard = () => { throw new Error("TEST no late caller clock"); };
  assertBodySourceColorReplayMetadata(held); assert.equal(f.calls.guard, count);
  replaceSelectionFixtureFile(f.f, "archive"); assert.throws(() => assertBodySourceColorReplayMetadata(held), /changed|identity/);
});
