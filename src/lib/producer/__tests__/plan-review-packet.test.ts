import assert from "node:assert/strict";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  assertPlanReviewPacketDestination,
  bindPlanReviewPacket,
  buildPlanReviewPacket,
  validatePlanReviewPacketRef,
} from "../../../app/api/producer/auto-edit/plan-review-packet";
import type { GateBundleVerdict } from "../../../app/api/producer/auto-edit/planning-gates";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import type { AutoEditAuthoritySnapshot } from "../../server/auto-edit-authority-snapshot";
import { stableAuthorityHash } from "../../server/auto-edit-authority-snapshot";
import { fileSha256 } from "../../server/auto-edit-hash";
import { writeQualityJson } from "../../server/auto-edit-quality-artifacts";

const PASS_GATES: GateBundleVerdict = {
  ok: true, errors: [], warnings: [],
  gates: {
    operatorIntent: { gate: "operator_intent", ok: true, errors: [], warnings: [], exit: 0 },
    transcriptCut: { gate: "transcript_cut", ok: true, errors: [], warnings: [], exit: 0 },
    planLint: { gate: "plan_lint", ok: true, errors: [], warnings: [], exit: 0 },
    hookContract: { gate: "hook_contract", ok: true, errors: [], warnings: [], exit: 0 },
    templateUsage: { gate: "template_usage", ok: true, errors: [], warnings: [], exit: 0 },
    claimsContract: { gate: "claims_contract", ok: true, errors: [], warnings: [], exit: 0 },
    compSize: { gate: "comp_size", ok: true, errors: [], warnings: [], exit: 0 },
    geometryFeasibility: { gate: "geometry_feasibility", ok: true, errors: [], warnings: [], exit: 0 },
    referenceLint: null,
  },
};

interface Fixture {
  root: string;
  ctx: AutoEditCtx;
  plan: Record<string, unknown>;
  manifest: Record<string, unknown>;
}

function utterance(start: number, words: Array<[string, number, number]>, text: string) {
  return {
    start, end: words.at(-1)?.[2] ?? start, text,
    words: words.map(([word, wordStart, end]) => ({ word, start: wordStart, end })),
  };
}

function fixture(root: string): Fixture {
  const producer = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(producer, { recursive: true });
  mkdirSync(source, { recursive: true });
  const aRows = [
    utterance(0, [["zero", 0, 0.4], ["one", 1, 1.4]], "zero one"),
    utterance(2, [["two", 2, 2.6], ["three", 3.8, 4.2], ["four", 4.4, 4.8]], "two three four"),
    ...Array.from({ length: 80 }, (_, index) =>
      utterance(20 + index, [[`tail-${index}`, 20 + index, 20.2 + index]], `tail utterance ${index}`)),
  ];
  const bRows = [utterance(9, [
    ["pre", 9, 9.4], ["alpha", 10, 10.4], ["beta", 11, 11.4], ["out", 12, 12.4],
  ], "pre alpha beta out")];
  writeFileSync(path.join(source, "a.transcript.json"), JSON.stringify({ transcript: aRows }));
  writeFileSync(path.join(source, "b.transcript.json"), JSON.stringify({ transcript: bRows }));
  const plan = {
    planVersion: 7,
    cutTrack: [
      { sourceId: "b", start: 10, end: 12, speed: 2 },
      { sourceId: "a", start: 1, end: 4, speed: 1 },
    ],
    graphicsTrack: [{ outStart: 1, outEnd: 2, kind: "statement-card" }],
  };
  const manifest = {
    sources: [
      { id: "a", transcriptPath: "a.transcript.json", path: "/untrusted/a.mp4" },
      { id: "b", transcriptPath: "b.transcript.json", path: "/untrusted/b.mp4" },
    ],
  };
  const planPath = path.join(producer, "edit_plan.json");
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(planPath, JSON.stringify(plan));
  writeFileSync(manifestPath, JSON.stringify(manifest));
  return {
    root,
    plan,
    manifest,
    ctx: {
      dir: producer, scope: "produced", planPath, manifestPath, transcriptsDir: source,
      intent: { mode: "longform", brief: "Keep the argument tight." },
    },
  };
}

function authority(ctx: AutoEditCtx): AutoEditAuthoritySnapshot {
  const content = {
    schemaVersion: 1 as const, qualityPolicyVersion: 1 as const,
    planHash: fileSha256(ctx.planPath)!, planContentHash: "1".repeat(64),
    manifestHash: fileSha256(ctx.manifestPath)!,
    operatorIntentDigest: "2".repeat(64), transcriptDigest: "3".repeat(64),
    referenceDigest: "4".repeat(64), pipelineDigest: "5".repeat(64),
  };
  return { ...content, digest: stableAuthorityHash(content) };
}

function packetPath(ctx: AutoEditCtx): string {
  return path.join(
    ctx.dir, ".sniper-qc", "packet-test", "planning", "round-1",
    "critic-input-test", "plan-review-packet.json",
  );
}

function testExactContentAndMapping(fix: Fixture): void {
  const packet = buildPlanReviewPacket(fix.ctx, 1, PASS_GATES, authority(fix.ctx));
  assert.deepEqual(packet.plan.content, fix.plan);
  assert.deepEqual(packet.manifest.content, fix.manifest);
  assert.equal(packet.plan.byteHash, fileSha256(fix.ctx.planPath));
  assert.equal(packet.manifest.byteHash, fileSha256(fix.ctx.manifestPath));
  assert.equal(packet.gateVerdict, PASS_GATES);
  assert.deepEqual(packet.timeline.segments.map((row) => [row.outputStart, row.outputEnd]), [
    [0, 1], [1, 4],
  ]);
  assert.deepEqual(packet.transcriptEvidence.keptWords.map((row) => [
    row.word, row.segmentIndex, row.outputStart, row.outputEnd,
  ]), [
    ["alpha", 0, 0, 0.2], ["beta", 0, 0.5, 0.7],
    ["one", 1, 1, 1.4], ["two", 1, 2, 2.6], ["three", 1, 3.8, 4],
  ]);
  assert.equal(packet.transcriptEvidence.keptWords.at(-1)?.sourceOriginalEnd, 4.2);
  assert.equal(packet.transcriptEvidence.transcripts[0].utteranceCount, 82);
  assert.equal(packet.transcriptEvidence.transcripts[0].utterances.at(-1)?.text, "tail utterance 79");
  const aIn = packet.transcriptEvidence.boundaryNeighbors.find((row) =>
    row.segmentIndex === 1 && row.edge === "in");
  assert.equal(aIn?.before?.word, "zero");
  assert.equal(aIn?.after?.word, "one");
  const aOut = packet.transcriptEvidence.boundaryNeighbors.find((row) =>
    row.segmentIndex === 1 && row.edge === "out");
  assert.equal(aOut?.before?.word, "three");
  assert.equal(aOut?.after?.word, "four");
}

function testHashAndPathBinding(fix: Fixture): void {
  const packet = buildPlanReviewPacket(fix.ctx, 1, PASS_GATES, authority(fix.ctx));
  const destination = packetPath(fix.ctx);
  assertPlanReviewPacketDestination(fix.ctx, destination, 1);
  const ref = bindPlanReviewPacket(writeQualityJson(destination, packet), packet);
  assert.equal(validatePlanReviewPacketRef(fix.ctx, 1, ref).contentDigest, packet.contentDigest);
  const stale = path.join(path.dirname(destination), "stale-qc.json");
  writeFileSync(stale, "{}");
  assert.throws(
    () => validatePlanReviewPacketRef(fix.ctx, 1, ref),
    /contains unapproved evidence/,
  );
  rmSync(stale);
  const original = readFileSync(destination, "utf8");
  writeFileSync(destination, `${readFileSync(destination, "utf8")} `);
  assert.throws(
    () => validatePlanReviewPacketRef(fix.ctx, 1, ref),
    /file hash changed before critic launch/,
  );
  const forgedContent = JSON.parse(original) as { plan: { content: Record<string, unknown> } };
  forgedContent.plan.content.planVersion = 999;
  writeQualityJson(destination, forgedContent);
  assert.throws(
    () => validatePlanReviewPacketRef(fix.ctx, 1, {
      ...ref, hash: fileSha256(destination)!,
    }),
    /content binding is invalid/,
  );
  assert.throws(
    () => assertPlanReviewPacketDestination(fix.ctx, path.join(fix.ctx.dir, "..", "escape.json"), 1),
    /must stay inside/,
  );
}

function testTranscriptContainment(root: string): void {
  const outside = path.join(root, "outside.json");
  writeFileSync(outside, JSON.stringify({ transcript: [] }));
  const traversal = fixture(path.join(root, "traversal"));
  writeFileSync(traversal.ctx.planPath, JSON.stringify({
    cutTrack: [{ sourceId: "a", start: 0, end: 1 }],
  }));
  writeFileSync(traversal.ctx.manifestPath, JSON.stringify({
    sources: [{ id: "a", transcriptPath: "../outside.json" }],
  }));
  assert.throws(
    () => buildPlanReviewPacket(traversal.ctx, 1, PASS_GATES, authority(traversal.ctx)),
    /path traversal is forbidden/,
  );
  const linked = fixture(path.join(root, "linked"));
  writeFileSync(linked.ctx.planPath, JSON.stringify({
    cutTrack: [{ sourceId: "a", start: 0, end: 1 }],
  }));
  const linkPath = path.join(linked.ctx.transcriptsDir, "linked.json");
  symlinkSync(path.join(linked.ctx.transcriptsDir, "a.transcript.json"), linkPath);
  writeFileSync(linked.ctx.manifestPath, JSON.stringify({
    sources: [{ id: "a", transcriptPath: "linked.json" }],
  }));
  assert.throws(
    () => buildPlanReviewPacket(linked.ctx, 1, PASS_GATES, authority(linked.ctx)),
    /symlink/,
  );
}

function testUnknownSourceFails(root: string): void {
  const fix = fixture(path.join(root, "unknown"));
  writeFileSync(fix.ctx.planPath, JSON.stringify({
    cutTrack: [{ sourceId: "missing", start: 0, end: 1 }],
  }));
  assert.throws(
    () => buildPlanReviewPacket(fix.ctx, 1, PASS_GATES, authority(fix.ctx)),
    /unknown source missing/,
  );
}

const root = mkdtempSync(path.join(os.tmpdir(), "sniper-plan-review-packet-"));
try {
  const fix = fixture(path.join(root, "main"));
  testExactContentAndMapping(fix);
  testHashAndPathBinding(fix);
  testTranscriptContainment(root);
  testUnknownSourceFails(root);
  console.log("plan-review-packet.test.ts: all assertions passed");
} finally {
  rmSync(root, { recursive: true, force: true });
}
