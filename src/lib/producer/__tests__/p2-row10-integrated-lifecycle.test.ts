import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import {
  parseCutRepairDirective,
  type CutRepairDirectiveV1,
} from "@/app/api/producer/ai-edit/cut-repair-route-policy";
import { runCutRepairMode } from
  "@/app/api/producer/ai-edit/cut-repair-route-dispatch";
import { loadCutRepairCandidateQc } from
  "@/app/api/producer/ai-edit/cut-repair-candidate-qc-runner";
import {
  pythonInterpreter,
  SCRIPTS_DIR,
} from "@/app/api/_lib/spawn-python";
import { fileSha256 } from "@/lib/server/auto-edit-hash";
import { loadCutRepairExecutionPackageSync } from
  "@/lib/server/cut-repair-execution-package-store";
import { observeCurrentRenderGraphAuthoritySync } from
  "@/lib/server/current-render-graph-authority";

interface Seed {
  root: string;
  producerDir: string;
  manifestPath: string;
  parentRevisionHash: string;
  parentMediaPath: string;
  whisperPath: string;
  whisperModelPath: string;
  contextEvidenceFiles: Record<string, { path: string; sha256: string }>;
  contextEvidenceScope: string;
  target: { phrase: string; occurrence: number };
}

type Row = Record<string, unknown>;

function row(value: unknown, label: string): Row {
  assert.ok(value && typeof value === "object" && !Array.isArray(value), label);
  return value as Row;
}

function parsed(value: unknown): CutRepairDirectiveV1 {
  const directive = parseCutRepairDirective(value);
  assert.ok(directive, "test directive must use the production parser");
  return directive;
}

function runPython(script: string, args: string[] = []): Row {
  const cwd = path.join(SCRIPTS_DIR, "producer");
  const result = spawnSync(pythonInterpreter(), [script, ...args], {
    cwd,
    encoding: "utf8",
    maxBuffer: 30 * 1024 * 1024,
    env: {
      ...process.env,
      PYTHONPATH: [".", "tests", process.env.PYTHONPATH ?? ""]
        .filter(Boolean).join(path.delimiter),
    },
  });
  assert.equal(
    result.status, 0,
    `fixture process failed:\n${result.stderr || result.stdout}`);
  const line = result.stdout.trim().split("\n").at(-1);
  return row(JSON.parse(line ?? "null"), "fixture JSON");
}

function seedFixture(): Seed {
  const script = path.join(
    SCRIPTS_DIR, "producer", "tests", "_p2_row10_lifecycle_fixture.py");
  const seed = runPython(script) as unknown as Seed;
  assert.equal(
    seed.contextEvidenceScope,
    "controlled-precondition-only-not-row10-qc-claim");
  assert.equal(Object.keys(seed.contextEvidenceFiles).length, 9);
  Object.values(seed.contextEvidenceFiles).forEach((item) => {
    assert.equal(fileSha256(item.path), item.sha256);
  });
  return seed;
}

function prepareDirective(seed: Seed): CutRepairDirectiveV1 {
  const alternateTake = {
    schemaVersion: 1,
    kind: "cut-repair-alternate-take-request",
    visualSpeechRegion: {
      xPpm: 0, yPpm: 0, widthPpm: 1_000_000, heightPpm: 1_000_000,
    },
  };
  assert.deepEqual(Object.keys(alternateTake).sort(), [
    "kind", "schemaVersion", "visualSpeechRegion",
  ]);
  return parsed({
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    mode: "prepare",
    idempotencyKey: "81000000-0000-4000-8000-000000000001",
    requestedAt: "2026-07-30T12:00:00.000Z",
    target: seed.target,
    alternateTake,
  });
}

async function prepare(seed: Seed): Promise<Row> {
  const result = await runCutRepairMode(
    seed.producerDir, seed.manifestPath, prepareDirective(seed));
  assert.equal(result.routeStatus, "rendered-plan-preparation-blocked");
  assert.equal(result.renderGraphCandidateStaged, true);
  assert.equal(result.authorityMutated, false);
  const selection = row(
    result.alternateTakeSelection, "alternate-take selection");
  assert.equal(selection.status, "selection-published");
  assert.match(String(selection.selectedCandidateId), /^take-[0-9a-f]{24}$/u);
  return result;
}

async function review(seed: Seed, preparation: Row) {
  const directive = parsed({
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    mode: "review",
    packageHash: preparation.preparationHash,
    target: seed.target,
  });
  const result = await runCutRepairMode(
    seed.producerDir, seed.manifestPath, directive);
  assert.equal(result.routeStatus, "cut-review-staged");
  const qc = await loadCutRepairCandidateQc(
    seed.producerDir, String(preparation.preparationHash));
  assertPositiveQc(qc, preparation);
  return { result, qc };
}

function assertPositiveQc(
  qc: Awaited<ReturnType<typeof loadCutRepairCandidateQc>>,
  preparation: Row,
): void {
  const seam = qc.seam.receipt;
  const visual = row(seam.visualOracleReceipt, "visual oracle receipt");
  assert.equal(seam.clickFree, true);
  assert.equal(seam.duplicateFree, true);
  assert.equal(seam.roomToneContinuous, true);
  assert.equal(seam.lipSyncDisposition, "passed");
  assert.equal(qc.vad.receipt.unintendedSpeechGapCount, 0);
  assert.deepEqual(visual.sourceFrameRange, {
    firstFrame: 60, endFrameExclusive: 78,
    fpsNumerator: 30, fpsDenominator: 1,
  });
  assert.deepEqual(visual.outputFrameRange, {
    firstFrame: 30, endFrameExclusive: 48,
    fpsNumerator: 30, fpsDenominator: 1,
  });
  const selection = row(preparation.alternateTakeSelection, "selection");
  assert.equal(
    seam.alternateTakeSelectionReceiptHash,
    selection.selectionReceiptHash);
  assert.equal(visual.visualMappingOffsetFrames, 0);
  assert.equal(visual.audioMappingOffsetFrames, 0);
}

function visualNegatives(seed: Seed, preparation: Row): Row {
  const script = path.join(
    SCRIPTS_DIR, "producer", "tests", "_p2_row10_visual_negatives.py");
  const toolManifest = path.join(
    seed.producerDir, ".sniper-authority-v1", "sagas",
    "cut-repair-automated-qc", "tool-manifest.json");
  const result = runPython(script, [
    seed.producerDir, String(preparation.preparationHash), toolManifest,
  ]);
  const selection = row(preparation.alternateTakeSelection, "selection");
  assert.equal(result.positiveCandidateSha256, preparation.candidateSha256);
  assert.equal(result.selectionReceiptHash, selection.selectionReceiptHash);
  assert.equal(row(result.delayed, "delayed").code, "VISIBLE_SPEECH_AV_OFFSET");
  assert.equal(
    row(result.occluded, "occluded").code,
    "VISUAL_SPEECH_OCCLUDED_OR_SUBSTITUTED");
  return result;
}

async function approve(seed: Seed, preparation: Row): Promise<Row> {
  const directive = parsed({
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    mode: "approve",
    packageHash: preparation.preparationHash,
    idempotencyKey: "82000000-0000-4000-8000-000000000001",
    requestedAt: "2026-07-30T12:02:00.000Z",
    target: seed.target,
    audition: {
      schemaVersion: 1,
      kind: "cut-repair-operator-audition-attestation",
      preparationHash: preparation.preparationHash,
      candidateDescriptorHash: preparation.candidateDescriptorHash,
      candidateSha256: preparation.candidateSha256,
      operatorReceiptId: "row10-controlled-operator-approval",
      reviewedAt: "2026-07-30T12:01:00.000Z",
      decision: "approved",
      reportedDamageResolved: true,
    },
  });
  const result = await runCutRepairMode(
    seed.producerDir, seed.manifestPath, directive);
  assert.equal(result.routeStatus, "promotion-package-sealed");
  assert.equal(result.executed, false);
  return result;
}

async function execute(seed: Seed, approval: Row): Promise<Row> {
  const directive = parsed({
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    mode: "execute",
    packageHash: approval.packageHash,
    target: seed.target,
  });
  const result = await runCutRepairMode(
    seed.producerDir, seed.manifestPath, directive);
  assert.equal(result.routeStatus, "two-step-promotion-committed");
  assert.equal(result.terminalAuthority, "rendered-plan-media-activated");
  assert.equal(result.finalMediaActivated, true);
  return result;
}

function assertActivated(seed: Seed, preparation: Row, approval: Row): void {
  const sealed = loadCutRepairExecutionPackageSync(
    seed.producerDir, String(approval.packageHash));
  const rendered = row(
    row(sealed.candidate, "candidate").renderedCandidate,
    "rendered candidate");
  assert.equal(rendered.candidateSha256, preparation.candidateSha256);
  assert.equal(
    fileSha256(path.join(seed.producerDir, "final.mp4")),
    preparation.candidateSha256);
  assert.equal(
    fileSha256(path.join(seed.producerDir, "edit_plan.json")),
    sealed.reviewAction.reviewPlanObjectHash);
  assert.doesNotThrow(() => observeCurrentRenderGraphAuthoritySync({
    producerDir: seed.producerDir,
    expectedGraphHash: sealed.reviewAction.reviewRenderGraphHash,
    expectedFinalHash: String(preparation.candidateSha256),
  }));
  const seam = row(sealed.promotionEvidence.seam, "sealed seam");
  const receipt = row(seam.receipt, "sealed seam receipt");
  const selection = row(preparation.alternateTakeSelection, "selection");
  assert.equal(
    receipt.alternateTakeSelectionReceiptHash,
    selection.selectionReceiptHash);
}

function clean(seed: Seed): void {
  const root = fs.realpathSync(seed.root);
  assert.equal(path.dirname(root), fs.realpathSync(os.tmpdir()));
  assert.match(path.basename(root), /^tmp/u);
  fs.rmSync(root, { recursive: true, force: true });
}

async function main(): Promise<void> {
  const seed = seedFixture();
  const previous = [
    process.env.WHISPER_CPP_BIN,
    process.env.WHISPER_CPP_MODEL,
  ];
  try {
    process.env.WHISPER_CPP_BIN = seed.whisperPath;
    process.env.WHISPER_CPP_MODEL = seed.whisperModelPath;
    const preparation = await prepare(seed);
    await review(seed, preparation);
    visualNegatives(seed, preparation);
    const approval = await approve(seed, preparation);
    await execute(seed, approval);
    assertActivated(seed, preparation, approval);
  } finally {
    [process.env.WHISPER_CPP_BIN, process.env.WHISPER_CPP_MODEL] = previous;
    clean(seed);
  }
}

main().then(() => {
  console.log("p2 row-10 integrated production lifecycle tests passed");
}).catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
