/** Retained protocol tests only: no actual media, admission, controller or Docker execution. */
import assert from "node:assert/strict";
import { writeFileSync, readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { openingProcessFixture as fixture } from "./_guided-opening-process-fixture";
import { readStoppedOpeningProcess, ownershipUnresolved } from "../guided-opening-process";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { writeGuidedObject } from "../guided-cut-v2-store";

/** Rebuild TEST protocol hashes deliberately, to reach the semantic version/join checks. */
function reseal(f: ReturnType<typeof fixture>, patch: { intent?: Record<string, unknown>; outcome?: Record<string, unknown>; activation?: Record<string, unknown> }) {
  const intent = { ...f.intent, ...patch.intent }, outcome = { ...f.outcome, intentHash: canonicalJsonSha256(intent), ...patch.outcome };
  const activation = { ...f.activation, intentSha256: canonicalJsonSha256(intent), outcomeSha256: canonicalJsonSha256(outcome), ...patch.activation };
  f.write(intent, outcome); f.held.job.guidedHandoffV2!.openingProcessOutcomeHash = writeGuidedObject(f.held.job.ctx.dir, activation);
}

test("V3 actual retained-record parser carries all request refs without pretending to read nonexistent metadata", () => {
  const f = fixture({}, 3);
  try {
    f.write(); const result = readStoppedOpeningProcess(f.held);
    assert.deepEqual(result.sourceColor, f.colors.reference); assert(Object.isFrozen(result.sourceColor));
    assert.equal(result.nestedOwnership, "resolved-by-normal-return"); assert.equal(result.resourceAbsence, "not-observed");
    assert.equal(ownershipUnresolved(result), false);
  } finally { f.cleanup(); }
});

test("V3 intent/outcome require V2 activation; legacy records cannot borrow its semantics", async t => {
  for (const version of [1, 2, 3]) await t.test(`version ${version}`, () => {
    const f = fixture({}, version);
    try {
      reseal(f, { activation: { schemaVersion: version === 3 ? 1 : 2 } }); assert.throws(() => readStoppedOpeningProcess(f.held));
      for (const schemaVersion of [0, 4, "3", null]) {
        reseal(f, { intent: { schemaVersion }, outcome: { schemaVersion } }); assert.throws(() => readStoppedOpeningProcess(f.held));
      }
    } finally { f.cleanup(); }
  });
});

test("even mutually resealed V3 records cannot replace the actual retained source clauses or claim identity", () => {
  const f = fixture({}, 3);
  try {
    for (const sourceColor of [undefined, { ...f.colors.reference, sourceColorHash: "b".repeat(64) },
      { ...f.colors.reference, input: { ...f.colors.reference.input, path: path.join(f.root, "other.json") } },
      { ...f.colors.reference, reservation: { ...f.colors.reference.reservation, path: path.join(f.root, "other/active.json") } },
      { ...f.colors.reference, cleanupVerified: true }]) {
      reseal(f, { intent: { sourceColor } }); assert.throws(() => readStoppedOpeningProcess(f.held));
    }
    reseal(f, {});
    const submission = f.held.submission;
    for (const patch of [{ schemaVersion: 1 }, { idempotencyKey: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" }, { expectedJournalHash: "b".repeat(64) }]) {
      f.held.submission = { ...submission, ...patch } as typeof submission; assert.throws(() => readStoppedOpeningProcess(f.held));
    }
  } finally { f.cleanup(); }
});

test("legacy process cannot silently downgrade a retained V2 request or carry extra source clauses", () => {
  const f = fixture({}, 2);
  try {
    f.write(); f.held.submission = f.colors.submission as typeof f.held.submission;
    assert.throws(() => readStoppedOpeningProcess(f.held), /cannot drop/);
    reseal(f, { intent: { sourceColor: f.colors.reference } }); assert.throws(() => readStoppedOpeningProcess(f.held));
  } finally { f.cleanup(); }
});

test("V3 still requires exact original worker-ledger bytes and retains forced-stop ownership", () => {
  const f = fixture({}, 3), forced = fixture({ forcedStop: true, timedOut: true }, 3);
  try {
    f.write(); const ledger = path.join(f.root, "owned-process-ledger.media.jsonl"), bytes = readFileSync(ledger);
    writeFileSync(ledger, bytes.subarray(0, bytes.length - 1)); assert.throws(() => readStoppedOpeningProcess(f.held));
    forced.write(); assert.equal(ownershipUnresolved(readStoppedOpeningProcess(forced.held)), true);
    assert.deepEqual(readStoppedOpeningProcess(forced.held).sourceColor, forced.colors.reference);
  } finally { f.cleanup(); forced.cleanup(); }
});
