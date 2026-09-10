/** Persisted TEST assertions only; neither watching/listening nor native source/media qualification is claimed. */
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { readSourceColorOpeningApproval, assertSourceColorOpeningApprovalMetadata } from "../guided-source-color-approval-read";
import { readHistoricalOpeningSelection } from "../guided-opening-selection";
import { saveHumanCutJobSnapshot } from "../human-cut-acceptance-store";
import { autoEditJobPath } from "../auto-edit-job-persistence";
import { sourceColorApprovalReadFixture, replaceApprovalReadFixtureFile, rewriteApprovalReadFixtureFile } from "./_guided-source-color-approval-read-fixture";

test("actual persisted TEST human decision joins exact source2 selected result and approval job edge", async t => {
  const f = await sourceColorApprovalReadFixture(t), result = f.read();
  assert.equal(result.summary.approvalHash, f.approved.approvalHash); assert.equal(result.fact.schemaVersion, 2);
  assert.equal(result.fact.openingApproved, true); assert.equal(result.fact.bodyGenerated, false); assert.equal(result.fact.deliveryApproved, false);
  assert.equal(result.decision.attestation.listened, true); assert.match(result.observationScope, /not-current-source-body-or-delivery/);
  assert.doesNotThrow(() => assertSourceColorOpeningApprovalMetadata(result));
  assert.throws(() => assertSourceColorOpeningApprovalMetadata({ ...result }), /actual original/);
});

test("actual historical selected journal supports only its exact original approved edge without active-journal reads", async t => {
  const f = await sourceColorApprovalReadFixture(t); saveHumanCutJobSnapshot(f.input.dir, f.input.current);
  const selected = readHistoricalOpeningSelection(f.input.dir, f.input.current.sha256);
  const open = fs.openSync;
  t.mock.method(fs, "openSync", (...args: Parameters<typeof fs.openSync>) => {
    if (String(args[0]) === autoEditJobPath(f.input.dir)) throw new Error("TEST historical approval must not open the active journal");
    return open(...args);
  });
  const result = readSourceColorOpeningApproval({ ...f.input, selected }); assertSourceColorOpeningApprovalMetadata(result);
  assert.equal(result.summary.approvalHash, f.approved.approvalHash);
});

test("copied source selection and mismatched raw current observation refuse before original guard", async t => {
  const f = await sourceColorApprovalReadFixture(t);
  assert.throws(() => readSourceColorOpeningApproval({ ...f.input, selected: { ...f.input.selected } }), /actual original/);
  const current = { ...f.input.current, bytes: Buffer.from(f.input.current.bytes) }; current.bytes[0] ^= 1;
  assert.throws(() => readSourceColorOpeningApproval({ ...f.input, current }), /selected journal/); assert.equal(f.calls.guard, 0);
});

test("first original guard cannot substitute any captured approval child file with equal bytes", async t => {
  const f = await sourceColorApprovalReadFixture(t);
  for (const role of ["start", "output", "verified", "published", "fact", "before"] as const) {
    f.calls.guard = 0; f.callbacks.guard = () => { if (f.calls.guard === 1) replaceApprovalReadFixtureFile(f, role); };
    assert.throws(f.read, /file identity changed/);
  }
});

test("final original guard cannot replace original current Buffer, raw size or callback", async t => {
  const f = await sourceColorApprovalReadFixture(t); f.read(); const total = f.calls.guard, bytes = f.input.current.bytes, guard = f.input.guard;
  f.calls.guard = 0; f.callbacks.guard = () => { if (f.calls.guard === total) f.input.current.bytes = Buffer.from(bytes); };
  assert.throws(f.read, /caller identity/); f.input.current.bytes = bytes; f.calls.guard = 0;
  f.callbacks.guard = () => { if (f.calls.guard === total) f.input.guard = () => {}; };
  assert.throws(f.read, /caller identity/); f.input.guard = guard;
  f.calls.guard = 0; f.callbacks.guard = () => { if (f.calls.guard === total) f.input.current.sizeBytes++; };
  assert.throws(f.read, /current journal/);
});

test("later metadata rejects retained nested fact, decision, before and raw output mutations without old guard calls", async t => {
  const f = await sourceColorApprovalReadFixture(t), result = f.read(), calls = f.calls.guard;
  f.callbacks.guard = () => { throw new Error("TEST old proof callback must stay expired"); };
  t.mock.method(performance, "now", () => { throw new Error("TEST metadata may not start or sample a clock"); });
  assertSourceColorOpeningApprovalMetadata(result); assert.equal(f.calls.guard, calls);
  result.fact.schemaVersion = 1; assert.throws(() => assertSourceColorOpeningApprovalMetadata(result), /parsed or raw return/); result.fact.schemaVersion = 2;
  const attestation = result.decision.attestation as Record<string, boolean>; attestation.listened = false;
  assert.throws(() => assertSourceColorOpeningApprovalMetadata(result), /parsed or raw return/); attestation.listened = true;
  const message = result.before.value.message; result.before.value.message = "TEST different prior journal";
  assert.throws(() => assertSourceColorOpeningApprovalMetadata(result), /parsed or raw return/); result.before.value.message = message;
  result.files.output.bytes[0] ^= 1; assert.throws(() => assertSourceColorOpeningApprovalMetadata(result), /parsed or raw return/);
});

test("original approval fact raw bytes cannot be normalized silently to the same semantic hash", async t => {
  const f = await sourceColorApprovalReadFixture(t), value = JSON.parse(fs.readFileSync(f.files.fact, "utf8"));
  rewriteApprovalReadFixtureFile(f, "fact", JSON.stringify(value, null, 2));
  assert.throws(f.read, /fact raw SHA/); assert.equal(f.calls.guard, 0);
});

test("late cancellation and recursive caller entry never publish an approval metadata handle", async t => {
  const f = await sourceColorApprovalReadFixture(t); f.read(); const total = f.calls.guard; f.calls.guard = 0;
  f.callbacks.guard = () => { if (f.calls.guard === total) throw new Error("TEST original protected read expired"); };
  assert.throws(f.read, /protected read expired/);
  f.callbacks.guard = () => { f.read(); }; assert.throws(f.read, /reenter/);
});
