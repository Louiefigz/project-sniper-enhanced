import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, linkSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { createOpeningMediaFixture } from "./_guided-opening-media-fixture";
import { observeGuidedOpeningMediaInput } from "../guided-opening-media-input";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { SCREENED_CAPTION_PROFILE } from "@/lib/producer/contracts/guided-caption-profile";

/** Real stored synthetic cut/candidate/readiness; no fake worker or playable media result. */
test("actual own-screen input closes exact14 documents under a lease without rendering or promoting", async () => {
  const built = await createOpeningMediaFixture(), { fixture, invocation } = built;
  try {
    const observed = observeGuidedOpeningMediaInput(invocation.inputPath, invocation.inputSha256);
    assert.equal(Object.keys(observed.documents).length, 14);
    assert.equal(observed.authority.frameRate, "30000/1001");
    assert.equal(observed.authority.profile, "unity-source-float-own-screen-v1");
    const source = (observed.documents.manifest.value.sources as Array<{ path: string }>)[0].path;
    const probe = JSON.parse(execFileSync("ffprobe", ["-v", "error", "-select_streams", "v:0", "-show_entries",
      "stream=width,height,r_frame_rate", "-of", "json", source], { timeout: 10_000, encoding: "utf8" }));
    assert.deepEqual(probe.streams.map((row: unknown) => row), [{ width: 1920, height: 1080, r_frame_rate: "30000/1001" }]);
    assert.equal(observed.documents.frameBindings.value.graphics instanceof Array, true);
    const graphic = (observed.documents.frameBindings.value.graphics as Record<string, unknown>[])[0];
    assert.ok(Number(graphic.startFrame) > 0); assert.ok(Number(graphic.endFrameExclusive) < observed.authority.totalFrames);
    assert.deepEqual((graphic.presentation as Record<string, unknown>).anchor, "own-screen");
    assert.equal(observed.authority.occurrenceEvidenceHash, observed.documents.occurrences.sha256);
    assert.equal(observed.sourceBytesObserved, false); assert.equal(observed.currentJournalObserved, false);
    assert.equal(observed.pipelineFilesObserved, false);
    // Semantic timeline/request seals are not mislabeled whole-document byte hashes.
    assert.notEqual(observed.documents.timelineMap.sha256, observed.authority.timelineMapHash);
    assert.notEqual(observed.documents.cutRequest.sha256, observed.authority.requestHash);
    const before = observeHumanCutJob(fixture.ctx.dir), active = readFileSync(path.join(fixture.ctx.dir, ".sniper-authority-v1/ACTIVE_HEAD"));
    assert.equal(before.job.status, "treatment_admitted"); assert.equal(before.job.workerPid, undefined);
    assert.equal(before.job.guidedHandoffV2?.openingPreparationHash, undefined);
    assert.equal(existsSync(built.descriptor.outputDirectory), false);
    corruptDocument(built); rejectResealedCutMetadata(built); rejectLinkedDocument(built);
    assert.equal(observeHumanCutJob(fixture.ctx.dir).sha256, before.sha256);
    assert.deepEqual(readFileSync(path.join(fixture.ctx.dir, ".sniper-authority-v1/ACTIVE_HEAD")), active);
    for (const name of ["final.mp4", "base.mp4", "program_audio.v2.json", ".sniper-qc-approved.json", ".sniper-template-usage-approved.json"]) {
      assert.equal(existsSync(path.join(fixture.ctx.dir, name)), false, name);
    }
  } finally { fixture.cleanup(); }
});

test("current V5 caption request survives actual durable proposal/readiness into exact original opening documents", async () => {
  const built = await createOpeningMediaFixture({ captionPreset: "producer-config-line-v1" }), { fixture, invocation } = built;
  try {
    const before = readFileSync(fixture.ctx.planPath);
    const observed = observeGuidedOpeningMediaInput(invocation.inputPath, invocation.inputSha256);
    assert.equal(Object.keys(observed.documents).length, 14);
    assert.equal(observed.authority.profile, SCREENED_CAPTION_PROFILE);
    const packet = observed.documents.readinessPacket.value;
    const proposal = packet.proposal as { schemaVersion: number; operations: Array<{ type: string; clauseIndex: number }> };
    assert.equal(proposal.schemaVersion, 5);
    assert.deepEqual(proposal.operations.map((row) => row.type), ["catalog-graphic", "captions-full-program"]);
    assert.equal(proposal.operations[1].clauseIndex, 1);
    assert.equal(Object.hasOwn(observed.documents.acceptedPlan.value, "captions"), false);
    assert.deepEqual(observed.documents.candidatePlan.value.captions, { burn: true });
    assert.deepEqual(observed.documents.candidatePlan.value.captionsTrack,
      { schemaVersion: 1, source: "kept-transcript", defaultPolicy: "line", groups: [] });
    const graphic = (observed.documents.frameBindings.value.graphics as Array<{ operationIndex: number }>)[0];
    assert.equal(graphic.operationIndex, 0);
    assert.equal(existsSync(built.descriptor.outputDirectory), false);
    assert.deepEqual(readFileSync(fixture.ctx.planPath), before);
    assert.equal(built.descriptor.genuineHumanAcceptance, false);
    assert.equal(built.descriptor.openingApproved, false);
  } finally { fixture.cleanup(); }
});

function corruptDocument(built: Awaited<ReturnType<typeof createOpeningMediaFixture>>) {
  const input = built.invocation, file = input.input.documents.frameBindings.path, original = readFileSync(file);
  try {
    const value = JSON.parse(original.toString()); value.graphics[0].startFrame += 1;
    writeFileSync(file, JSON.stringify(value));
    assert.throws(() => observeGuidedOpeningMediaInput(input.inputPath, input.inputSha256), /document changed/);
  } finally { writeFileSync(file, original); }
  const inputBytes = readFileSync(input.inputPath);
  try {
    const value = JSON.parse(inputBytes.toString()); value.executionId = "../../outside";
    const { executionInputHash: _old, ...core } = value; void _old;
    value.executionInputHash = canonicalJsonSha256(core); writeFileSync(input.inputPath, JSON.stringify(value));
    assert.throws(() => observeGuidedOpeningMediaInput(input.inputPath, input.inputSha256), /UUID/);
  } finally { writeFileSync(input.inputPath, inputBytes); }
  try {
    writeFileSync(input.inputPath, Buffer.alloc(128 * 1024 + 1, " "));
    assert.throws(() => observeGuidedOpeningMediaInput(input.inputPath, input.inputSha256), /bounded regular/);
  } finally { writeFileSync(input.inputPath, inputBytes); }
}

function rejectLinkedDocument(built: Awaited<ReturnType<typeof createOpeningMediaFixture>>) {
  const input = built.invocation, file = input.input.documents.occurrences.path;
  const duplicate = path.join(input.documentsRoot, "TEST-hardlink.json");
  linkSync(file, duplicate);
  try { assert.throws(() => observeGuidedOpeningMediaInput(input.inputPath, input.inputSha256), /bounded regular/); }
  finally { unlinkSync(duplicate); }
}

function rejectResealedCutMetadata(built: Awaited<ReturnType<typeof createOpeningMediaFixture>>) {
  const invocation = built.invocation, requestPath = invocation.input.documents.cutRequest.path;
  const original = readFileSync(requestPath), inputBytes = readFileSync(invocation.inputPath);
  const hashBytes = (bytes: Buffer) => createHash("sha256").update(bytes).digest("hex");
  try {
    const request = JSON.parse(original.toString()); request.cutAuthorityDigest = "f".repeat(64);
    const { requestHash: _requestHash, ...requestCore } = request; void _requestHash;
    request.requestHash = canonicalJsonSha256(requestCore); writeFileSync(requestPath, JSON.stringify(request));
    const input = JSON.parse(inputBytes.toString()); input.documents.cutRequest.sha256 = hashBytes(readFileSync(requestPath));
    const { executionInputHash: _inputHash, ...inputCore } = input; void _inputHash;
    input.executionInputHash = canonicalJsonSha256(inputCore); writeFileSync(invocation.inputPath, JSON.stringify(input));
    assert.throws(() => observeGuidedOpeningMediaInput(invocation.inputPath, hashBytes(readFileSync(invocation.inputPath))), /request\/lock\/manifest/);
  } finally { writeFileSync(requestPath, original); writeFileSync(invocation.inputPath, inputBytes); }
}
