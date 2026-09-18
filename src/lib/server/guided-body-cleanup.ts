import path from "node:path";
import { randomUUID } from "node:crypto";
import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { parseBodyCleanupResult } from "@/lib/producer/contracts/guided-body-result-v1";
import { exactKeys, objectValue, sha256, stringValue } from "@/lib/producer/contracts/validation";
import { acquireGuidedMutation } from "./guided-cut-v2-store";
import { observeHumanCutJob, humanCutDirectory } from "./human-cut-acceptance-store";
import { readBodyPhase, commitBodyPhase } from "./guided-body-phase";
import { readBodyCleanupControl } from "./guided-body-cleanup-control";
import { readOwnedBodyProcess, bodyOwnershipGuard, bodyClockObservation } from "./guided-body-process";
import { bodyChildTools, assertBodyToolsUnchanged, invokeBodyChild } from "./guided-body-process-tools";
import { observeOwnedWorkerLedger, liveRecordedDescendants } from "./guided-opening-process-ledger";
import { createOpeningRecord, assertOpeningRecord, assertOpeningFailureAbsent } from "./guided-opening-process-activation";
import { canonicalJsonSha256 as hash } from "./auto-edit-hash";
import type { ProjectMutationLease } from "./project-mutation-lease";

/** Explicit recovery request only. It can never choose a resource name/path or launch media. */
export function parseBodyCleanupRequest(value: unknown) {
  const row = objectValue(value, "body cleanup request"), keys = ["schemaVersion", "operation", "expectedToken", "expectedJournalHash", "activationHash"];
  exactKeys(row, keys, keys, "body cleanup request");
  if (row.schemaVersion !== 1 || row.operation !== "reconcile-guided-body") throw new Error("Unsupported body recovery operation");
  return { schemaVersion: 1 as const, operation: "reconcile-guided-body" as const,
    expectedToken: stringValue(row.expectedToken, "expectedToken", 200), expectedJournalHash: sha256(row.expectedJournalHash, "expectedJournalHash"),
    activationHash: sha256(row.activationHash, "activationHash") };
}

function cleanupAttempt(dir: string, lease: ProjectMutationLease) {
  const began = performance.now(), phase = readBodyCleanupControl(dir), stopped = readOwnedBodyProcess(phase), { held } = stopped;
  const guard = bodyOwnershipGuard(held, lease, phase.current.sha256);
  const remainingMs = () => {
    const left = Math.floor(300_000 - (performance.now() - began));
    if (left < 1) throw new Error("Body protected cleanup budget exhausted; retain ownership");
    return left;
  };
  guard(); remainingMs();
  const directory = humanCutDirectory(humanCutDirectory(path.dirname(held.activationPath), "body-cleanup-attempts"), randomUUID());
  const tools = bodyChildTools(held, "cleanup"), start = createOpeningRecord(path.join(directory, "start.json"), {
    schemaVersion: 1, kind: "guided-body-cleanup-start", beforeJournalHash: phase.current.sha256, activationHash: held.activationHash,
    processFactHash: phase.factHash, processOutcomeSha256: stopped.output.sha256, tools,
    clockHash: held.activation.clockHash, generationStartedAt: held.activation.generationStartedAt,
    startedAt: new Date().toISOString(), budgetScope: "protected-cleanup-counted-in-original-request-no-render-credit" });
  return { began, phase, stopped, held, guard, remainingMs, directory, tools, start };
}

/** A forced but proved outer stop can reconcile named Docker resources; an unproved outer stop cannot. */
export async function invokeStoppedBodyCleanup<T>(stopped: { receipt: Record<string, unknown> }, invoke: () => Promise<T>): Promise<T> {
  if (stopped.receipt.groupStopped !== true) throw new Error("Body outer process stop is unproved; cleanup cannot begin");
  return invoke();
}

/** Docker absence never launders unknown local descendants into fully resolved ownership. */
export function bodyCleanupCanCommit(first: { ownershipUnresolved: boolean }, latest: { ownershipUnresolved: boolean }): boolean {
  return first.ownershipUnresolved === false && latest.ownershipUnresolved === false;
}

function fullCleanupAuthority(attempt: ReturnType<typeof cleanupAttempt>) {
  try {
    const phase = readBodyPhase(attempt.held.controlJob.ctx.dir, "process"), stopped = readOwnedBodyProcess(phase);
    if (phase.factHash !== attempt.phase.factHash || stopped.output.sha256 !== attempt.stopped.output.sha256
        || !bodyCleanupCanCommit(attempt.stopped, stopped)) throw new Error("Body local ownership remains unresolved");
    return { phase, error: null };
  } catch (error) { return { phase: null, error: String(error).slice(0, 2000) }; }
}

async function executeCleanup(attempt: ReturnType<typeof cleanupAttempt>) {
  const { held, tools, guard, remainingMs, directory, phase } = attempt;
  guard(); remainingMs();
  const result = await invokeStoppedBodyCleanup(attempt.stopped,
    () => invokeBodyChild({ held, tools, purpose: "cleanup", remainingMs, ledgerRoot: directory }));
  const ledgerSha256 = observeOwnedWorkerLedger(directory, "cleanup", tools.script), nested = liveRecordedDescendants(directory, "cleanup");
  if (nested.live.length || nested.unknown.length || nested.unrecordedSpawns.length) throw new Error("Body cleanup helper ownership is unresolved");
  const output = createOpeningRecord(path.join(directory, "output.json"), { schemaVersion: 1, kind: "guided-body-cleanup-owned-output",
    ...result, groupStopped: true, forcedStop: false, ledgerSha256, observedAt: new Date().toISOString(), elapsedMs: performance.now() - attempt.began });
  const value = parseBodyCleanupResult(result.stdout), activation = held.activation;
  if (value.activationPath !== held.activationPath || value.activationSha256 !== held.activationSha256 || value.inputSha256 !== activation.inputSha256
      || value.outputRoot !== activation.outputRoot || value.executionId !== activation.executionId
      || hash(value.graphics.map((row) => row.order)) !== hash(activation.selectedGraphicOrders)) throw new Error("Body cleanup returned different exact ownership");
  assertBodyToolsUnchanged(tools); guard(); remainingMs();
  const commitGuard = () => {
    guard(); assertOpeningRecord(attempt.start); assertOpeningRecord(output); assertOpeningFailureAbsent(path.join(directory, "failure.json"));
    if (readOwnedBodyProcess(readBodyCleanupControl(held.controlJob.ctx.dir)).output.sha256 !== attempt.stopped.output.sha256) {
      throw new Error("Body stopped process changed before cleanup commit");
    }
    bodyClockObservation(held, guard); guard(); remainingMs();
  };
  commitGuard();
  const complete = fullCleanupAuthority(attempt);
  if (!complete.phase) {
    createOpeningRecord(path.join(directory, "unresolved.json"), { schemaVersion: 1, kind: "guided-body-cleanup-unresolved",
      startSha256: attempt.start.sha256, outputSha256: output.sha256, dockerCleanupVerified: true, unresolvedAuthority: complete.error,
      claimRetained: true, bodyApproved: false, deliveryApproved: false, observedAt: new Date().toISOString() });
    return { state: "resources-reconciled-ownership-unresolved" as const, dockerCleanupVerified: true as const, claimRetained: true as const };
  }
  const finalGuard = () => {
    commitGuard();
    if (!fullCleanupAuthority(attempt).phase) throw new Error("Body complete cleanup authority changed before CAS");
    commitGuard();
  };
  const committed = commitBodyPhase({ held: complete.phase.held, current: phase.current, phase: "cleanup", references: {
    start: { path: attempt.start.path, sha256: attempt.start.sha256 }, output: { path: output.path, sha256: output.sha256 } }, guard: finalGuard });
  return { ...committed, state: "cleanup-verified" as const };
}

/** Mandatory safety cleanup may outlive render admission, but never grants generation credit or candidate approval. */
export async function reconcileGuidedBodyUnderLease(dir: string, lease: ProjectMutationLease) {
  const attempt = cleanupAttempt(dir, lease);
  try { return await executeCleanup(attempt); }
  catch (error) {
    let clockError: string | null = null;
    try { bodyClockObservation(attempt.held, attempt.guard); } catch (failure) { clockError = String(failure).slice(0, 2000); }
    createOpeningRecord(path.join(attempt.directory, "failure.json"), { schemaVersion: 1, kind: "guided-body-cleanup-failure",
      error: String(error).slice(0, 4000), clockError, elapsedMs: performance.now() - attempt.began, observedAt: new Date().toISOString(),
      ...(error instanceof CutPreviewProcessError ? error.details : {}), cleanupQualified: false, bodyApproved: false, deliveryApproved: false });
    throw error;
  }
}

/** Explicit CLI recovery only: exact token/journal/activation, real guarded lease, no fresh body attempt. */
export async function cleanupGuidedBody(input: { dir: unknown; submission: unknown }) {
  const request = parseBodyCleanupRequest(input.submission), dir = canonicalProducerDir(input.dir), before = observeHumanCutJob(dir);
  if (before.sha256 !== request.expectedJournalHash || before.job.token !== request.expectedToken
      || before.job.guidedHandoffV2?.bodyActivationHash !== request.activationHash) throw new Error("Body cleanup request is stale");
  const lease = await acquireGuidedMutation(dir, { workflowVersion: 2, action: "reconcile-guided-body", expectedStatus: "treatment_admitted",
    expectedToken: request.expectedToken, expectedJournalHash: request.expectedJournalHash });
  try {
    const result = await reconcileGuidedBodyUnderLease(dir, lease);
    if (result.state === "resources-reconciled-ownership-unresolved") return { ok: true as const, ...result,
      bodyApproved: false as const, deliveryApproved: false as const, generationCreditMs: 0 };
    return { ok: true as const, state: "cleanup-verified" as const, cleanupHash: result.factHash, journalHash: result.current.sha256,
      bodyApproved: false as const, deliveryApproved: false as const, generationCreditMs: 0 };
  } finally { lease.release(); }
}
