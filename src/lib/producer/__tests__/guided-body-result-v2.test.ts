/** Pure transport validation only; no process, source freshness or approval is inferred. */
import assert from "node:assert/strict";
import test from "node:test";
import { parseBodyMediaCompletion, parseBodyMediaReadback } from "../contracts/guided-body-result-v1";
import { parseSourceColorBodyCompletion as completion, parseSourceColorBodyReadback as readback,
  parseSourceColorBodyMediaResult as result, parseCurrentBodyMediaCompletion, parseCurrentBodyMediaReadback } from "../contracts/guided-body-result-v2";
import { bodyMediaOmissions } from "./_guided-body-media-v2-fixture";
import { bodySourceCompletion, bodySourceReadback, bodySourceRawResult, bodyLegacyCompletion } from "./_guided-body-result-v2-fixture";

test("body V2 completion/raw/readback require original replay and completed non-grading projection", () => {
  assert.deepEqual(completion(JSON.stringify(bodySourceCompletion())), bodySourceCompletion());
  assert.deepEqual(readback(JSON.stringify(bodySourceReadback())), bodySourceReadback());
  const original = bodySourceRawResult(), parsed = result(original); assert.deepEqual(parsed, original);
  parsed.sourceColorReplay.input.sha256 = "b".repeat(64); assert.deepEqual(original, bodySourceRawResult());
});
test("legacy completion/readback parsers stay closed and current dispatch preserves schema1", () => {
  const old = bodyLegacyCompletion(); assert.deepEqual(parseCurrentBodyMediaCompletion(JSON.stringify(old)), old);
  assert.deepEqual(parseBodyMediaCompletion(JSON.stringify(old)), old);
  assert.throws(() => parseBodyMediaCompletion(JSON.stringify(bodySourceCompletion())));
  assert.throws(() => parseBodyMediaReadback(JSON.stringify(bodySourceReadback())));
  assert.throws(() => completion(JSON.stringify(old)));
  assert.equal(parseCurrentBodyMediaReadback(JSON.stringify(bodySourceReadback())).schemaVersion, 2);
});
test("V2 source completion and raw result reject every missing or unknown top-level field", () => {
  for (const row of [...bodyMediaOmissions(bodySourceCompletion()), { ...bodySourceCompletion(), extra: false }]) {
    assert.throws(() => completion(JSON.stringify(row)));
  }
  for (const row of [...bodyMediaOmissions(bodySourceRawResult()), { ...bodySourceRawResult(), extra: false }]) assert.throws(() => result(row));
});
test("V2 readback rejects every missing or unknown top-level field", () => {
  for (const row of [...bodyMediaOmissions(bodySourceReadback()), { ...bodySourceReadback(), extra: false }]) {
    assert.throws(() => readback(JSON.stringify(row)));
  }
});
test("V2 replay proof is closed at each level with strict coverage and false qualification flags", () => {
  const original = bodySourceCompletion(), proof = original.sourceColorReadback;
  const changes = [...bodyMediaOmissions(proof), { ...proof, extra: false }, { ...proof, schemaVersion: true },
    { ...proof, sourceColorRecordsReplayed: false }, { ...proof, basePictureConsumptionVerified: false }];
  for (const key of ["gamutMeasured", "gradeApplied", "colorQualified", "bodyApproved", "deliveryApproved"]) changes.push({ ...proof, [key]: true });
  for (const sourceColorReadback of changes) assert.throws(() => completion(JSON.stringify({ ...original, sourceColorReadback })));
});
test("V2 original evidence has bounded exact raw/semantic hashes and the original opening role", () => {
  const original = bodySourceCompletion(), proof = original.sourceColorReadback, evidence = proof.sourceColorEvidence;
  for (const sourceColorEvidence of [...bodyMediaOmissions(evidence), { ...evidence, extra: false }, { ...evidence, sha256: true },
    { ...evidence, receiptHash: "bad" }, { ...evidence, sizeBytes: 0 }, { ...evidence, sizeBytes: 16 * 1024 * 1024 + 1 },
    { ...evidence, path: original.receiptPath }, { ...evidence, path: evidence.path.replace("/executions/", "/other/") }]) {
    assert.throws(() => completion(JSON.stringify({ ...original, sourceColorReadback: { ...proof, sourceColorEvidence } })));
  }
  for (const key of ["observationRecordHash", "consumptionRecordHash"]) {
    assert.throws(() => completion(JSON.stringify({ ...original, sourceColorReadback: { ...proof, [key]: "A".repeat(64) } })));
  }
});
test("V2 source readback rejects legacy-only, missing, duplicate, reordered and failed source stages", () => {
  const original = bodySourceReadback(), reordered = structuredClone(original.stages); [reordered[4], reordered[5]] = [reordered[5], reordered[4]];
  for (const stages of [original.stages.filter((_row, index) => index !== 4 && index !== 5), reordered,
    [...original.stages, original.stages[4]], original.stages.map((row, index) => index === 5 ? { ...row, status: "failed" } : row)]) {
    assert.throws(() => readback(JSON.stringify({ ...original, stages })));
  }
});
test("V2 readback stage totals cannot exceed actual elapsed except independent-rounding tolerance", () => {
  const original = bodySourceReadback();
  for (const elapsedMs of [true, -1, 3_300_001, "10"]) assert.throws(() => readback(JSON.stringify({ ...original, elapsedMs })));
  assert.throws(() => readback(JSON.stringify({ ...original, stages: original.stages.map(row => ({ ...row, elapsedMs: 10 })) })));
  assert.throws(() => readback(JSON.stringify({ ...original, stages: original.stages.map(row => ({ ...row, elapsedMs: 0.5 })) })));
});
test("V2 raw result cannot omit, duplicate, reverse or fail completed source work", () => {
  const original = bodySourceRawResult();
  for (const stages of [[], original.stages.slice(2), [...original.stages, original.stages[1]], [...original.stages].reverse(),
    original.stages.map((row, index) => index === 1 ? { ...row, status: "failed" } : row)]) assert.throws(() => result({ ...original, stages }));
});
test("V2 stdout rejects duplicate keys, trailing values, null bytes and oversized transports", () => {
  const text = JSON.stringify(bodySourceCompletion());
  for (const value of [text.replace('"schemaVersion":2', '"schemaVersion":2,"schemaVersion":2'), text + "{}", text + "\0", " ".repeat(128 * 1024) + text]) {
    assert.throws(() => completion(value));
  }
});
