/** New-only complete TEST protocol records. Candidate/AV/worker claims are inert fixture data, never native qualification. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { observeCutPreviewFile, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { bodySourceRawResult, bodySourceReadback } from "@/lib/producer/__tests__/_guided-body-result-v2-fixture";
import { createOpeningRecord } from "../guided-opening-process-activation";
import { observeOwnedWorkerLedger, ownedProcessLedgerPath, type OwnedLedgerKind } from "../guided-opening-process-ledger";
import { commitBodyPhase, readBodyPhase } from "../guided-body-phase";
import { readStoppedBodyProcess } from "../guided-body-process";
import { readHeldBodyCleanup, readHeldBodyResult } from "../guided-body-result";
import { canonicalJsonSha256 as hash } from "../auto-edit-hash";
import type { FreshBodyAdmission } from "../guided-body-claim";
import type { BodyActivation, bodyChildTools } from "../guided-body-process-tools";

export type TestBodyTools = Record<OwnedLedgerKind, ReturnType<typeof bodyChildTools>>;

/** Exact new path only; never replaces a previously held source, tool or protocol record. */
export function publishBodyTestFile(file: string, bytes: string): void {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  fs.writeFileSync(file, bytes, { mode: 0o600, flag: "wx" });
}

/** Real parser two-row lifecycle with no child rows, so no native/ps leaf is needed. */
export function publishBodyTestLedger(root: string, kind: OwnedLedgerKind, script: string): string {
  const rows = ["worker-started", "worker-finished"].map((event, index) =>
    JSON.stringify({ event, pid: process.pid, argv0: script, at: Date.now() / 1000 + index / 1000 }));
  publishBodyTestFile(ownedProcessLedgerPath(root, kind), rows.join("\n") + "\n");
  return observeOwnedWorkerLedger(root, kind, script);
}

/** Publish the entire inert candidate/result before ANY process result/phase hold exists. */
function candidateRecord(held: BodyActivation) {
  const a = held.activation, input = held.invocation.input;
  if (input.schemaVersion !== 2) throw new Error("TEST genuine source2 input required");
  const candidate = path.join(a.outputRoot, "body-candidate", "final.mp4");
  publishBodyTestFile(candidate, "TEST inert body candidate, never decoded or approved\n");
  const observed = observeCutPreviewFile(candidate, 1024), original = readCutPreviewObject(input.references.openingResult.path);
  const raw = { ...bodySourceRawResult(), profile: input.profile, executionId: a.executionId, inputPath: a.inputPath,
    inputSha256: a.inputSha256, executionActivationPath: held.activationPath, executionActivationSha256: held.activationSha256,
    references: input.references, sourceColorReplay: input.sourceColorReplay,
    media: { final: { path: candidate, sha256: observed.sha256, sizeBytes: observed.sizeBytes, videoDecodeSucceeded: true },
      audit: { finalSha256: observed.sha256, overall: "pass", exitCode: 0,
        scope: "actual-full-Audit-B-not-creative-or-subjective-listening-approval", TEST: "synthetic native/AV leaf only" } } };
  raw.sourceColorReadback.sourceColorEvidence = original.value.sourceColorEvidence as typeof raw.sourceColorReadback.sourceColorEvidence;
  const { receiptHash: _prior, ...body } = raw; void _prior;
  const record = createOpeningRecord(path.join(a.outputRoot, "body-result.json"), { ...body, receiptHash: hash(body) });
  const completion = { schemaVersion: 2, kind: "guided-body-media-completion", status: "complete", executionId: a.executionId,
    inputSha256: a.inputSha256, executionActivationSha256: held.activationSha256, receiptPath: record.path,
    receiptSha256: record.sha256, receiptHash: record.value.receiptHash, sourceColorReplay: input.sourceColorReplay,
    sourceColorReadback: raw.sourceColorReadback, bodyApproved: false, deliveryApproved: false };
  const old = bodySourceReadback();
  return { candidate, record, completion, readback: { ...old, ...completion, kind: "guided-body-media-readback", status: "verified",
    elapsedMs: 0, stages: old.stages.map(row => ({ ...row, elapsedMs: 0 })) } };
}

/** Synthetic full owned outcome, then real process CAS and independent closed stopped reader. */
function processRecords(context: FreshBodyAdmission, held: BodyActivation, result: ReturnType<typeof candidateRecord>, tools: TestBodyTools) {
  const a = held.activation, root = path.dirname(held.activationPath), startedAt = new Date().toISOString();
  const intent = createOpeningRecord(path.join(root, "body-media-process-intent.json"), { schemaVersion: 1,
    kind: "guided-body-process-intent", activationHash: held.activationHash, inputSha256: a.inputSha256,
    executionId: a.executionId, journalHash: held.current.sha256, startedAt, tools: tools.media });
  const ledgerSha256 = publishBodyTestLedger(root, "media", tools.media.script);
  const output = createOpeningRecord(path.join(root, "body-media-process-result.json"), { schemaVersion: 1,
    kind: "guided-body-process-outcome", scope: "owned-process-stop-not-body-or-delivery-approval", activationHash: held.activationHash,
    inputSha256: a.inputSha256, executionId: a.executionId, intentSha256: intent.sha256, startedAt,
    finishedAt: startedAt, elapsedMs: 0, status: "complete", error: "", timedOut: false, groupStopped: true,
    forcedStop: false, stdout: JSON.stringify(result.completion), stderr: "TEST no native body execution", ledgerSha256 });
  commitBodyPhase({ held, current: held.current, phase: "process", guard: context.budget.remainingMs,
    references: { intent: { path: intent.path, sha256: intent.sha256 }, outcome: { path: output.path, sha256: output.sha256 } } });
  const phase = readBodyPhase(context.dir, "process");
  assert.equal(readStoppedBodyProcess(phase).ownershipUnresolved, false);
  assert.equal(readHeldBodyResult(phase).completion.schemaVersion, 2);
  return phase;
}

/** Exact all-row unarmed TEST cleanup data; no daemon absence is inferred or tested. */
function cleanupResult(held: BodyActivation) {
  const a = held.activation;
  const graphics = a.selectedGraphicOrders.map(order => ({ order, state: "not-initialized", containerNames: [], cleanupVerified: true }));
  return { schemaVersion: 1, kind: "guided-body-cleanup-result", activationPath: held.activationPath,
    activationSha256: held.activationSha256, inputSha256: a.inputSha256, outputRoot: a.outputRoot, executionId: a.executionId,
    cleanupVerified: true, graphics, elapsedMs: 0, stages: ["body-cleanup-control", ...graphics.map(row => `reconcile-graphic-${row.order}`),
      "body-cleanup-control-after"].map(stage => ({ stage, status: "complete", elapsedMs: 0 })),
    budgetScope: "separate-protected-cleanup-not-render-allowance", processGroupStopped: "requires-owned-controller-observation",
    bodyApproved: false, deliveryApproved: false };
}

/** Original complete cleanup parser and phase CAS stay real; no whole-reader stub supplies a proof. */
function cleanupRecords(context: FreshBodyAdmission, process: ReturnType<typeof readBodyPhase>, tools: TestBodyTools) {
  const { held } = process, a = held.activation, stopped = readStoppedBodyProcess(process);
  const directory = path.join(path.dirname(held.activationPath), "body-cleanup-attempts", randomUUID());
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  const start = createOpeningRecord(path.join(directory, "start.json"), { schemaVersion: 1, kind: "guided-body-cleanup-start",
    beforeJournalHash: process.current.sha256, activationHash: held.activationHash, processFactHash: process.factHash,
    processOutcomeSha256: stopped.output.sha256, tools: tools.cleanup, clockHash: a.clockHash,
    generationStartedAt: a.generationStartedAt, startedAt: new Date().toISOString(),
    budgetScope: "protected-cleanup-counted-in-original-request-no-render-credit" });
  const ledgerSha256 = publishBodyTestLedger(directory, "cleanup", tools.cleanup.script);
  const output = createOpeningRecord(path.join(directory, "output.json"), { schemaVersion: 1, kind: "guided-body-cleanup-owned-output",
    stdout: JSON.stringify(cleanupResult(held)), stderr: "TEST no native cleanup", groupStopped: true, forcedStop: false,
    ledgerSha256, observedAt: new Date().toISOString(), elapsedMs: 0 });
  commitBodyPhase({ held, current: process.current, phase: "cleanup", guard: context.budget.remainingMs,
    references: { start: { path: start.path, sha256: start.sha256 }, output: { path: output.path, sha256: output.sha256 } } });
  const phase = readBodyPhase(context.dir, "cleanup"), cleanup = readHeldBodyCleanup(phase);
  assert.equal(cleanup.result.cleanupVerified, true); return phase;
}

/** All initial immutable records are complete before their actual admission/phase readers capture them. */
export function bodyReadbackProtocol(context: FreshBodyAdmission, held: BodyActivation, tools: TestBodyTools) {
  const result = candidateRecord(held), process = processRecords(context, held, result, tools);
  const cleanup = cleanupRecords(context, process, tools); return { ...result, process, cleanup };
}
