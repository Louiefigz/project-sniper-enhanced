import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { canonicalJsonSha256 as hash } from "../auto-edit-hash";
import { projectBodyProgramReferences, parseBodyFileReference } from "@/lib/producer/contracts/guided-body-media-v1";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";

const H = "a".repeat(64), ROOT = "/private/tmp/TEST-body-reference-projection";
function opening() {
  // Exact probe keys/class observed in failed DY4yOw; these constants are TEST shape evidence, not generated media.
  const base = { codec: "h264", frameRate: "30000/1001", frames: 9346, height: 1080, width: 1920,
    packetTimelineSha256: "7a454d3214ce0f84309b5343250c6d4ecaa5c17a0035743caa3765166f230efe",
    path: `${ROOT}/full-program-base/final.mp4`, sha256: "a1cfadb22748b32f530d1490c76668bae18be5324f7b6ef763d5f6bf3092f194",
    sizeBytes: 476126901, startPts: 0, timeBase: "1/30000", videoDecodeSucceeded: true };
  return { fullProgram: { base, fullMasterSelectionEventPath: `${ROOT}/selection-event.json`, fullMasterSelectionEventSha256: H },
    documents: { candidatePlan: { path: `${ROOT}/plan.json`, sha256: H }, manifest: { path: `${ROOT}/manifest.json`, sha256: H } } };
}

test("observed full base probe facts project to the exact same closed held reference, not a different DTO", () => {
  const result = opening(), references = projectBodyProgramReferences(result);
  assert.deepEqual(references.base, { path: result.fullProgram.base.path, sha256: result.fullProgram.base.sha256 });
  assert.notEqual(hash(references.base), hash(result.fullProgram.base)); // Prior lineage comparison necessarily failed.
  assert.throws(() => parseBodyFileReference(result.fullProgram.base), /unsupported fields/i);
  for (const name of ["base", "masterSelection", "candidatePlan", "manifest"] as const) {
    assert.deepEqual(Object.keys(references[name]).sort(), ["path", "sha256"]);
    for (const patch of [{ path: `${ROOT}/other.json` }, { sha256: "b".repeat(64) }, { unheld: true }]) {
      assert.notEqual(hash({ ...references, [name]: { ...references[name], ...patch } }), hash(references));
    }
  }
  for (const patch of [{ path: "relative.mp4" }, { sha256: "bad" }, { path: null }, { sha256: undefined }]) {
    assert.throws(() => projectBodyProgramReferences({ ...result, fullProgram: { ...result.fullProgram, base: { ...result.fullProgram.base, ...patch } } }));
  }
});

test("reference projection does not turn changed full receipt bytes into the same original receipt identity", () => {
  const result = opening(), changed = structuredClone(result); changed.fullProgram.base.frames += 1;
  assert.deepEqual(projectBodyProgramReferences(changed), projectBodyProgramReferences(result));
  assert.notEqual(hash(changed), hash(result)); // Existing whole-result SHA/approval checks still bind all probe facts.
});

test("opt-in retained failed run reference regression reads exact existing bytes and writes nothing", { skip: !process.env.SNIPER_TEST_BODY_REFERENCE_HELD }, () => {
  const file = process.env.SNIPER_TEST_BODY_REFERENCE_HELD!, before = readFileSync(file), held = readCutPreviewObject(file);
  const input = held.value.input as Record<string, unknown>, original = held.value.opening as Record<string, unknown>;
  const result = readCutPreviewObject(String(original.resultPath)), beforeResult = result.bytes;
  assert.equal(result.sha256, original.resultSha256);
  assert.deepEqual(projectBodyProgramReferences(result.value), input.references);
  assert.deepEqual(readFileSync(file), before); assert.deepEqual(readFileSync(String(original.resultPath)), beforeResult);
});
