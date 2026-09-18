/** Actual TEMP metadata, staging, leases and journal CAS. Native/readiness/claim provenance is explicitly TEST-only. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { guidedFixture } from "@/lib/producer/__tests__/_guided-cut-fixture";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { autoEditRequestKey, canonicalJson, canonicalJsonSha256 } from "../auto-edit-hash";
import { autoEditJobPath, parseAutoEditJobRecord } from "../auto-edit-job-persistence";
import { atomicCreateFileSync } from "../atomic-file";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { acquireProjectMutationLease, type ProjectMutationLease } from "../project-mutation-lease";
import { assertToolsUnchanged, type HeldOpeningClaim } from "../guided-opening-process";
import { stageGuidedSourceColor } from "../guided-source-color-staging";
import { runSourceColorOpeningMedia, sourceColorMediaProcessDependencies } from "../guided-source-color-media-process";
import { snapshotSourceColorMetadata } from "../guided-source-color-staging-hold";
import { sourceColorStagingFixture } from "./_guided-source-color-staging-fixture";
import { testSha } from "./_guided-source-color-expectations-fixture";

/** New inert regular files only. Nothing in this fixture is invoked as an executable. */
function artifact(file: string, bytes: string): string {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  fs.writeFileSync(file, bytes, { flag: "wx", mode: 0o600 }); return testSha(bytes);
}
function toolsAt(root: string) {
  const script = path.join(root, "scripts/producer/guided_opening_media.py");
  const runnerScript = path.join(root, "scripts/producer/headless/process_runner.py"), venvRoot = path.join(root, "TEST-venv");
  const python = path.join(venvRoot, "bin/python"), venvConfig = path.join(venvRoot, "pyvenv.cfg");
  return { script, scriptHash: artifact(script, "# TEST media worker; NEVER executed\n"), runnerScript,
    runnerScriptHash: artifact(runnerScript, "# TEST owned wrapper; NEVER executed\n"), python, pythonResolved: python,
    pythonHash: artifact(python, "TEST inert interpreter; NEVER executed\n"), venvRoot, venvConfig,
    venvConfigHash: artifact(venvConfig, "TEST inert virtual environment metadata\n") };
}
function jobAt(staging: ReturnType<typeof sourceColorStagingFixture>, tools: ReturnType<typeof toolsAt>) {
  const hash = "a".repeat(64), at = staging.opening.claim.generationStartedAt;
  const { run: { job } } = guidedFixture(path.join(staging.root, "TEST-media-journal-seed"), {
    schemaVersion: 2, mode: "guided", afterCut: "treatment-then-intro", approvalPolicy: "explicit-human" });
  job.ctx.dir = staging.producerDir;
  job.ctx.pipeline = { schemaVersion: 1, runId: "TEST-media", digest: hash, snapshotRoot: staging.root,
    lockPath: path.join(staging.root, "TEST-original-pipeline-lock.json"), files: [
      { path: "scripts/producer/guided_opening_media.py", hash: tools.scriptHash },
      { path: "scripts/producer/headless/process_runner.py", hash: tools.runnerScriptHash }] };
  job.requestKey = autoEditRequestKey(job.ctx);
  const core = { schemaVersion: 1 as const, requestKey: job.requestKey, planHash: hash, authorityDigest: hash,
    cutAuthorityDigest: hash, cutApprovalReceiptHash: hash, cutReviewApprovalReceiptHash: hash,
    pictureLockHash: hash, timelineMapHash: hash, projectionReceiptHash: hash, createdAt: at };
  Object.assign(job, { status: "treatment_admitted", checkpoint: "cut_reviewed", requestedAt: at, updatedAt: at,
    cutApprovalWaitStartedAt: at, cutApprovalRequest: { ...core, requestHash: canonicalJsonSha256(core) },
    cutPreview: { executionKey: hash, receiptHash: hash }, guidedHandoffV2: { schemaVersion: 2, cutDecisionHash: hash,
      cutActivationHash: hash, pictureLockedRevisionHash: hash, treatmentAdmissionHash: hash, treatmentProposalHash: hash,
      proposalReadinessHash: hash, treatmentDraftRevisionHash: hash, openingExecutionClaimHash: staging.opening.claimSha256 } });
  job.events = job.events.map(event => ({ ...event, at })); return parseAutoEditJobRecord(job);
}

/** One TEST native leaf emits only known local JSONL bytes, not evidence of a real spawned worker. */
function nativeLeaf(root: string, callbacks: { invoke: () => void; settled: () => void; error?: CutPreviewProcessError;
  ledger: "complete" | "missing" | "unfinished" }, calls: { invoke: number }) {
  return async (request: Parameters<typeof sourceColorMediaProcessDependencies.invoke>[0]) => {
    request.remainingMs(); callbacks.invoke(); request.beforeSpawn?.(); calls.invoke++;
    if (callbacks.ledger !== "missing") {
      const events = callbacks.ledger === "complete" ? ["worker-started", "worker-finished"] : ["worker-started"];
      artifact(path.join(root, "owned-process-ledger.media.jsonl"), events.map((event, i) =>
        JSON.stringify({ event, pid: 123456, argv0: request.tools.script, at: 100 + i })).join("\n") + "\n");
    }
    callbacks.settled();
    const output = { stdout: "TEST normal owned leaf return; no media generated", stderr: "" };
    const details = callbacks.error?.details ?? { ...output, groupStopped: true, forcedStop: false, timedOut: false };
    try { request.afterSettled?.(details); }
    catch (error) { throw new CutPreviewProcessError(`TEST actual settled hook failed: ${String(error)}`, details); }
    if (callbacks.error) throw callbacks.error; return output;
  };
}

/** Actual lock identities and every writer/reader/CAS; only explicitly named leaves stand in for absent native qualification. */
export function sourceColorMediaFixture(t: TestContext) {
  const owned: { lease?: ProjectMutationLease } = {}; t.after(() => owned.lease?.release());
  const staging = sourceColorStagingFixture(t), tools = toolsAt(staging.root), job = jobAt(staging, tools);
  atomicCreateFileSync(autoEditJobPath(staging.producerDir), canonicalJson(job));
  const acquired = acquireProjectMutationLease(staging.root, "TEST internal V3 metadata writer");
  assert(acquired.lease); const lease = acquired.lease; owned.lease = lease;
  const projectGuard = cutPreviewLeaseGuard(staging.producerDir, lease), originalResource = staging.resource.assertResource;
  const callbacks = { work: () => {}, resource: () => {}, invoke: () => {}, settled: () => {}, claim: () => {},
    error: undefined as CutPreviewProcessError | undefined, ledger: "complete" as "complete" | "missing" | "unfinished" };
  const calls = { work: 0, resource: 0, invoke: 0 }, clock = { expired: false }, deadline = performance.now() + 1_500_000;
  const remainingMs = () => { calls.work++; callbacks.work(); if (clock.expired) throw new Error("TEST original work expired"); return deadline - performance.now(); };
  staging.guard = () => { remainingMs(); projectGuard(); };
  staging.resource.assertResource = () => { calls.resource++; originalResource(); callbacks.resource(); };
  const staged = stageGuidedSourceColor(staging), submission = { schemaVersion: 2 as const, operation: "prepare-guided-opening" as const,
    idempotencyKey: staging.opening.claim.requestId, expectedJournalHash: staging.opening.claim.beforeJournalHash,
    expectedToken: job.token, proposalReadinessHash: "a".repeat(64), treatmentDraftRevisionHash: "a".repeat(64),
    sourceColor: staging.sourceColor };
  const held = { ...observeHumanCutJob(staging.producerDir), ...staging.opening, submission,
    claimHash: staging.opening.claimSha256, resourceAbsence: "not-observed", selectable: false } as HeldOpeningClaim;
  const input = { held, lease, sourceColor: { staging, staged, submission }, remainingMs };
  const root = path.dirname(held.claimPath), requests: Parameters<typeof sourceColorMediaProcessDependencies.invoke>[0][] = [];
  const invoke = nativeLeaf(root, callbacks, calls), dependencies = { ...sourceColorMediaProcessDependencies,
    readiness: (() => ({})) as unknown as typeof sourceColorMediaProcessDependencies.readiness,
    tools: () => tools, toolsUnchanged: assertToolsUnchanged,
    invoke: (request: Parameters<typeof invoke>[0]) => { requests.push(request); return invoke(request); },
    claim: () => { const value = { ...snapshotSourceColorMetadata(held), ...observeHumanCutJob(staging.producerDir) };
      callbacks.claim(); return value; } };
  return { staging, staged, input, tools, root, callbacks, calls, clock, requests, dependencies,
    run: () => runSourceColorOpeningMedia(input, dependencies) };
}

/** Same-byte or changed-byte replacement is limited to named canonical private fixture records/inert tools. */
export function replaceMediaFixtureFile(f: ReturnType<typeof sourceColorMediaFixture>, name: "claim" | "input" | "sidecar" | "reservation" | "script" | "journal" | "intent" | "outcome" | "ledger", bytes?: string): void {
  const files = { claim: f.input.held.claimPath, input: f.input.held.claim.inputPath, sidecar: f.staged.input.path,
    reservation: f.staged.reservation.path, script: f.tools.script, journal: autoEditJobPath(f.staging.producerDir),
    intent: path.join(f.root, "media-process-intent.json"), outcome: path.join(f.root, "media-process-result.json"),
    ledger: path.join(f.root, "owned-process-ledger.media.jsonl") };
  const file = files[name]; assert(file.startsWith(f.staging.root + path.sep)); assert.equal(fs.realpathSync(file), file);
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const temporary = path.join(path.dirname(file), `TEST-media-replacement-${randomUUID()}`);
  fs.writeFileSync(temporary, bytes ?? fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}
