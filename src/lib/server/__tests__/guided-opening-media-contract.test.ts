import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { test } from "node:test";
import { OPENING_DOCUMENT_NAMES, OPENING_MEDIA_PROFILE, OPENING_MEDIA_SCOPE, openingAbsolutePath,
  parseGuidedOpeningMediaInput, parseGuidedOpeningMediaAuthority } from "@/lib/producer/contracts/guided-opening-media-v1";
import { parseCurrentOpeningMediaInput, parseCurrentOpeningMediaAuthority } from "@/lib/producer/contracts/guided-opening-media-v1";
import { CAPTION_PROFILE, CAPTION_SHORT_PROFILE, SCREENED_CAPTION_PROFILE, SCREENED_CAPTION_SHORT_PROFILE } from "@/lib/producer/contracts/guided-caption-profile";
import { canonicalJsonSha256 } from "../auto-edit-hash";

const hash = "a".repeat(64);
function invocation() {
  const core = { schemaVersion: 1, kind: "guided-opening-media-input", executionId: randomUUID(), profile: OPENING_MEDIA_PROFILE,
    documents: Object.fromEntries(OPENING_DOCUMENT_NAMES.map((name) => [name, { path: `/private/tmp/TEST-ONLY/${name}.json`, sha256: hash }])),
    pipeline: { snapshotRoot: "/private/tmp/TEST-ONLY/pipeline/files", lockPath: "/private/tmp/TEST-ONLY/pipeline/pipeline-lock.json", lockSha256: hash, digest: hash } };
  return { ...core, executionInputHash: canonicalJsonSha256(core) };
}
function authority() {
  return { schemaVersion: 2, kind: "guided-opening-media-authority", scope: OPENING_MEDIA_SCOPE, profile: OPENING_MEDIA_PROFILE,
    runId: "TEST-ONLY", previewAttempt: 1, contextHash: hash, cutDecisionHash: hash, acceptedRevisionHash: hash,
    requestHash: hash, pictureLockHash: hash, projectionHash: hash, sourceSetDigest: hash, manifestHash: hash, timelineMapHash: hash,
    rawAdmissionHash: hash, proposalHash: hash, readinessHash: hash, draftRevisionHash: hash, candidatePlanHash: hash,
    frameBindingsHash: hash, occurrenceEvidenceHash: hash, clockHash: hash, generationStartedAt: "2026-09-06T00:00:00.000Z",
    frameRate: "30000/1001", totalFrames: 3000, target: { mode: "longform", width: 1920, height: 1080 },
    core: { startFrame: 0, endFrameExclusive: 1800 }, review: { startFrame: 0, endFrameExclusive: 2100 } };
}

test("worker invocation has closed server-derived references and no free output, approval or source selection", () => {
  const input = invocation(); assert.deepEqual(parseGuidedOpeningMediaInput(input), input);
  for (const patch of [{ outputPath: "/tmp/final.mp4" }, { sourceSelection: {} }, { approved: true }, { deadline: 7200 },
    { profile: "automatic" }, { executionId: "../execution" }, { pipeline: { ...input.pipeline, currentRootFallback: "/tmp" } }]) {
    assert.throws(() => parseGuidedOpeningMediaInput({ ...input, ...patch }));
  }
  const { authority: _omitted, ...missing } = input.documents; void _omitted;
  assert.throws(() => parseGuidedOpeningMediaInput({ ...input, documents: missing }), /missing/);
  assert.throws(() => parseGuidedOpeningMediaInput({ ...input, documents: { ...input.documents, extra: input.documents.authority } }), /unsupported/);
  assert.throws(() => parseGuidedOpeningMediaInput({ ...input, documents: { ...input.documents, authority: { ...input.documents.authority, symlinkAllowed: true } } }), /unsupported/);
});

test("worker paths are lexically canonical without claiming file or inode observation", () => {
  assert.equal(openingAbsolutePath("/private/tmp/TEST ONLY/authority.json"), "/private/tmp/TEST ONLY/authority.json");
  for (const value of ["relative.json", "/", "//private/tmp/file", "/private/../tmp/file", "/private/./tmp/file", "/tmp/file/", "/tmp/a\\b", "/tmp/a\u0000b", "/tmp/a\nb"]) {
    assert.throws(() => openingAbsolutePath(value));
  }
});

test("separate media authority preserves exact fractional frame core and original clock with no approval shape", () => {
  const value = authority(); assert.deepEqual(parseGuidedOpeningMediaAuthority(value), value);
  for (const patch of [{ schemaVersion: 1 }, { adapter: { state: "unavailable" } }, { media: {} }, { approved: true },
    { frameBindingsHash: null }, { frameRate: "60000/2002" }, { frameRate: "61/1" }, { frameRate: "30" },
    { totalFrames: 72001 }, { previewAttempt: true }, { generationStartedAt: "September 6, 2026" },
    { target: { mode: "longform" } }, { core: { startFrame: 1, endFrameExclusive: 1800 } },
    { review: { startFrame: 0, endFrameExclusive: 1799 } }]) {
    assert.throws(() => parseGuidedOpeningMediaAuthority({ ...value, ...patch }));
  }
});

test("current dispatch admits explicit screened tokens but historical parser never upgrades", () => {
  for (const profile of [CAPTION_PROFILE, CAPTION_SHORT_PROFILE, SCREENED_CAPTION_PROFILE, SCREENED_CAPTION_SHORT_PROFILE]) {
    const input = { ...invocation(), profile }, held = { ...authority(), profile };
    assert.deepEqual(parseCurrentOpeningMediaInput(input), input);
    assert.deepEqual(parseCurrentOpeningMediaAuthority(held), held);
    assert.throws(() => parseGuidedOpeningMediaInput(input), /Unsupported/);
    assert.throws(() => parseGuidedOpeningMediaAuthority(held), /malformed/);
  }
});
