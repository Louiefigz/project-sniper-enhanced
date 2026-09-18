import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { compatibilityPlanHash } from
  "@/app/api/producer/auto-edit/compatibility-picture-identity";
import { planObjectContentHash } from "../auto-edit-authority";
import { canonicalJsonSha256, fileSha256 } from "../auto-edit-hash";
import { writeContentAddressedJsonSync } from "../content-addressed-json";
import type { AutoEditGenesisExpectation } from
  "../producer-auto-edit-genesis";
import { stageAutoEditGraphFixture } from
  "./_producer-auto-edit-render-graph-fixture";

export interface AutoEditGenesisFixture {
  root: string;
  producer: string;
  planPath: string;
  manifestPath: string;
  candidatePath: string;
  input: AutoEditGenesisExpectation;
  plan: Record<string, unknown>;
  graphHash: string;
  projectionHash: string;
  pictureLockHash: string;
  sourceSetHash: string;
  transcriptHash: string;
  timelineMapHash: string;
}
export interface AutoEditGenesisFixtureOptions {
  sourceSetHash?: string;
  toolchainHash?: string;
}
const hash = (value: string): string => createHash("sha256")
  .update(value).digest("hex");

function writeJson(filePath: string, value: unknown): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(value)}\n`);
}
function projection(
  producer: string,
  approvedCutPlanHash: string,
  cutTrackDigest: string,
  cutDecisionsDigest: string,
) {
  const timelineMap = {
    outputDuration: 1,
    segments: [{
      index: 0,
      source_id: "source-1",
      src_start: 0,
      src_end: 1,
      speed: 1,
      out_start: 0,
      out_end: 1,
      audio_lead_s: 0,
    }],
  };
  const timelineMapHash = canonicalJsonSha256({
    quantization: "millionths-half-up-v1",
    outputDuration: 1_000_000,
    segments: [{
      index: 0,
      source_id: "source-1",
      src_start: 0,
      src_end: 1_000_000,
      speed: 1_000_000,
      out_start: 0,
      out_end: 1_000_000,
      audio_lead_s: 0,
    }],
  });
  const value = {
    schemaVersion: 1,
    kind: "compatibility-timeline-projection",
    approvedCutPlanHash,
    cutTrackDigest,
    cutDecisionsDigest,
    compilerHash: hash("compiler"),
    timelineMap,
    timelineMapHash,
  };
  const stored = writeContentAddressedJsonSync(
    path.join(producer, "compatibility_projections"), value);
  return { value, hash: stored.hash, timelineMapHash };
}

function pictureLock(
  producer: string,
  plan: Record<string, unknown>,
  manifestHash: string,
  transcriptHash: string,
) {
  const cutTrackDigest = canonicalJsonSha256(plan.cutTrack);
  const cutDecisionsDigest = canonicalJsonSha256(plan.cutDecisions);
  const approvedCutPlanHash = hash("approved-cut-plan");
  const projected = projection(
    producer,
    approvedCutPlanHash,
    cutTrackDigest,
    cutDecisionsDigest,
  );
  const value = {
    schemaVersion: 1,
    kind: "compatibility-picture-lock",
    adapterVersion: 1,
    approvedCutPlanHash,
    planContentHash: compatibilityPlanHash(
      plan, cutTrackDigest, cutDecisionsDigest),
    manifestHash,
    transcriptDigest: transcriptHash,
    cutTrackDigest,
    cutDecisionsDigest,
    cutApprovalReceiptHash: hash("cut-approval"),
    cutReviewApprovalReceiptHash: hash("cut-review-approval"),
    cutReviewAuthorityDigest: hash("cut-review-authority"),
    cutAuthorityDigest: hash("cut-authority"),
    projectionReceiptHash: projected.hash,
    timelineMapHash: projected.timelineMapHash,
    qualityPolicyVersion: 1,
    requiredCleanReviews: 2,
  };
  const stored = writeContentAddressedJsonSync(
    path.join(producer, "picture_locks"), value);
  return {
    hash: stored.hash,
    projectionHash: projected.hash,
    timelineMapHash: projected.timelineMapHash,
  };
}

interface FixturePaths {
  root: string;
  producer: string;
  planPath: string;
  manifestPath: string;
  candidatePath: string;
}

function fixturePaths(name: string): FixturePaths {
  const root = fs.realpathSync(
    fs.mkdtempSync(path.join(os.tmpdir(), `sniper-genesis-${name}-`)));
  const producer = path.join(root, "producer");
  const candidatePath = path.join(
    producer, ".sniper-qc", name, "round-1", "final.mp4");
  fs.mkdirSync(path.dirname(candidatePath), { recursive: true });
  fs.writeFileSync(candidatePath, `candidate-${name}`);
  return {
    root,
    producer,
    candidatePath,
    planPath: path.join(producer, "edit_plan.json"),
    manifestPath: path.join(producer, "asset_manifest.json"),
  };
}

function initialPlan(): Record<string, unknown> {
  return {
    schemaVersion: 1,
    planVersion: "fixture",
    target: {
      mode: "short",
      aspect: "9:16",
      width: 1080,
      height: 1920,
      fps: 30,
    },
    cutTrack: [{
      sourceId: "source-1", start: 0, end: 1, speed: 1,
    }],
    cutDecisions: { schemaVersion: 1, removals: [] },
    graphicsTrack: [],
  };
}

function writeManifest(
  paths: FixturePaths,
  sourceSetHash: string,
  receiptHash: string,
): void {
  writeJson(paths.manifestPath, {
    generatedAt: "2026-07-29T12:00:00.000Z",
    input: paths.root,
    sources: [],
    broll: [],
    music: [],
    sourceSetAdmission: {
      schemaVersion: 1,
      receiptPath: `.sniper-source-sets/${receiptHash}.json`,
      receiptSha256: receiptHash,
      sourceSetDigest: sourceSetHash,
      entryCount: 0,
    },
  });
}

function expectation(paths: FixturePaths): AutoEditGenesisExpectation {
  return {
    producerDir: paths.producer,
    planPath: paths.planPath,
    manifestPath: paths.manifestPath,
    candidatePath: paths.candidatePath,
    expectedPlanHash: fileSha256(paths.planPath)!,
    expectedManifestHash: fileSha256(paths.manifestPath)!,
    expectedCandidateHash: fileSha256(paths.candidatePath)!,
  };
}

export function autoEditGenesisFixture(
  name: string,
  options: AutoEditGenesisFixtureOptions = {},
): AutoEditGenesisFixture {
  const paths = fixturePaths(name);
  const plan = initialPlan();
  writeJson(paths.planPath, plan);
  const sourceSetHash = options.sourceSetHash ?? hash(`${name}-source-set`);
  const sourceSetReceiptHash = hash(`${name}-source-receipt`);
  writeManifest(paths, sourceSetHash, sourceSetReceiptHash);
  const transcriptHash = hash(`${name}-transcript`);
  const locked = pictureLock(
    paths.producer, plan, fileSha256(paths.manifestPath)!, transcriptHash);
  const graphHash = stageAutoEditGraphFixture({
    producer: paths.producer,
    candidatePath: paths.candidatePath,
    planContentHash: planObjectContentHash(plan)!,
    manifestHash: fileSha256(paths.manifestPath)!,
    sourceSetHash,
    toolchainHash: options.toolchainHash,
  });
  return {
    ...paths,
    input: expectation(paths),
    plan,
    graphHash,
    projectionHash: locked.projectionHash,
    pictureLockHash: locked.hash,
    sourceSetHash,
    transcriptHash,
    timelineMapHash: locked.timelineMapHash,
  };
}

export function rerenderAutoEditGenesisFixture(
  item: AutoEditGenesisFixture,
  name: string,
): AutoEditGenesisFixture {
  const plan = {
    ...item.plan,
    planVersion: `fixture-${name}`,
    graphicsTrack: [{
      id: `graphic-${name}`,
      kind: "statement-card",
      outStart: 0,
      outEnd: 1,
      text: `revision ${name}`,
    }],
  };
  writeJson(item.planPath, plan);
  const candidatePath = path.join(
    item.producer, ".sniper-qc", name, "round-2", "final.mp4");
  fs.mkdirSync(path.dirname(candidatePath), { recursive: true });
  fs.writeFileSync(candidatePath, `candidate-${name}`);
  const graphHash = stageAutoEditGraphFixture({
    producer: item.producer,
    candidatePath,
    planContentHash: planObjectContentHash(plan)!,
    manifestHash: fileSha256(item.manifestPath)!,
    sourceSetHash: item.sourceSetHash,
  });
  return {
    ...item,
    candidatePath,
    plan,
    graphHash,
    input: {
      producerDir: item.producer,
      planPath: item.planPath,
      manifestPath: item.manifestPath,
      candidatePath,
      expectedPlanHash: fileSha256(item.planPath)!,
      expectedManifestHash: fileSha256(item.manifestPath)!,
      expectedCandidateHash: fileSha256(candidatePath)!,
    },
  };
}
