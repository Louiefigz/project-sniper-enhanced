import path from "node:path";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { exactKeys, objectValue, sha256 } from "@/lib/producer/contracts/validation";
import { bodyTimestamp } from "@/lib/producer/contracts/guided-body-activation-v1";
import { bodyChildTools, assertBodyToolsUnchanged, invokeBodyChild, type BodyActivation, type BodyExecutionControl } from "./guided-body-process-tools";
import { observeOwnedWorkerLedger, liveRecordedDescendants } from "./guided-opening-process-ledger";
import { createOpeningRecord, assertOpeningRecord } from "./guided-opening-process-activation";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import { commitBodyPhase, readBodyPhase } from "./guided-body-phase";
import { readBodyCleanupControl } from "./guided-body-cleanup-control";
import { readGuidedProposalReadiness } from "./guided-proposal-review-store";
import { canonicalJsonSha256 as hash } from "./auto-edit-hash";
import { retainGenerationClockObservation } from "./generation-clock-watermark";
import { withStageTimingContext } from "./stage-timing-context";
import { timedStage } from "./stage-timing";
import type { ProjectMutationLease } from "./project-mutation-lease";

interface BodyOutcome {
  status: "complete" | "failed"; error: string; timedOut: boolean; groupStopped: boolean; forcedStop: boolean;
  stdout: string; stderr: string; ledgerSha256: string | null;
}

/** This guard never admits a different checkpoint or reuses an expired lease. */
export function bodyOwnershipGuard(held: BodyExecutionControl, lease: ProjectMutationLease, journalHash: string) {
  const dir = held.controlJob.ctx.dir, guard = cutPreviewLeaseGuard(dir, lease);
  return () => {
    guard();
    if (observeHumanCutJob(dir).sha256 !== journalHash) throw new Error("Body exact owned journal changed");
  };
}

/** Scheduling observation only; used even for failed actual returns and protected cleanup. */
export function bodyClockObservation(held: BodyExecutionControl, guard: () => void) {
  retainGenerationClockObservation({ dir: held.controlJob.ctx.dir,
    origin: { clockHash: held.activation.clockHash, startedAt: held.activation.generationStartedAt },
    executionId: held.activation.executionId, observedAt: new Date().toISOString() }, guard);
}

async function outcome(input: { held: BodyActivation; tools: ReturnType<typeof bodyChildTools>; remainingMs: () => number; guard: () => void }): Promise<BodyOutcome> {
  let status: "complete" | "failed" = "failed", error = "", timedOut = false, groupStopped = false, forcedStop = false, stdout = "", stderr = "";
  try {
    const result = await invokeBodyChild({ ...input, purpose: "media" });
    groupStopped = true; stdout = result.stdout; stderr = result.stderr;
    assertBodyToolsUnchanged(input.tools); input.guard(); input.remainingMs(); status = "complete";
  } catch (failure) {
    error = String(failure).slice(0, 4000);
    if (failure instanceof CutPreviewProcessError) ({ timedOut, groupStopped, forcedStop, stdout, stderr } = failure.details);
  }
  let ledgerSha256: string | null = null;
  if (groupStopped && !forcedStop) {
    try { ledgerSha256 = observeOwnedWorkerLedger(path.dirname(input.held.activationPath), "media", input.tools.script); }
    catch (failure) { status = "failed"; error = `${error}\n${String(failure)}`.slice(0, 4000); }
  }
  return { status, error, timedOut, groupStopped, forcedStop, stdout, stderr, ledgerSha256 };
}

/** Actual foreground invocation only; raw self-sealed sidecars cannot mint this separate journal-held return. */
export async function runActivatedBodyMedia(input: { held: BodyActivation; lease: ProjectMutationLease; remainingMs: () => number }) {
  if (input.held.invocation.input.schemaVersion === 2) throw new Error("Source-color body controller/runtime and native qualification are unfinished; native body launch is refused");
  const { held, remainingMs } = input, dir = held.admission.before.job.ctx.dir, root = path.dirname(held.activationPath);
  const guard = bodyOwnershipGuard(held, input.lease, held.current.sha256), mono = performance.now(), startedAt = new Date().toISOString();
  guard(); remainingMs(); readGuidedProposalReadiness(dir); guard(); remainingMs();
  const tools = bodyChildTools(held, "media"), intent = createOpeningRecord(path.join(root, "body-media-process-intent.json"), {
    schemaVersion: 1, kind: "guided-body-process-intent", activationHash: held.activationHash, inputSha256: held.activation.inputSha256,
    executionId: held.activation.executionId, journalHash: held.current.sha256, startedAt, tools });
  guard(); remainingMs();
  const output = await withStageTimingContext({ runId: held.current.job.artifactToken ?? held.current.job.token,
    attemptId: `body:${held.activation.executionId}`, attemptNo: held.current.job.attempts }, () =>
    timedStage(dir, "guided_body_owned_media", () => outcome({ held, tools, guard, remainingMs })));
  const record = createOpeningRecord(path.join(root, "body-media-process-result.json"), { schemaVersion: 1, kind: "guided-body-process-outcome",
    scope: "owned-process-stop-not-body-or-delivery-approval", activationHash: held.activationHash, inputSha256: held.activation.inputSha256,
    executionId: held.activation.executionId, intentSha256: intent.sha256, startedAt, finishedAt: new Date().toISOString(),
    elapsedMs: performance.now() - mono, ...output });
  const commitGuard = () => {
    guard(); assertOpeningRecord(intent); assertOpeningRecord(record); bodyClockObservation(held, guard); guard();
  };
  commitBodyPhase({ held, current: held.current, phase: "process", references: {
    intent: { path: intent.path, sha256: intent.sha256 }, outcome: { path: record.path, sha256: record.sha256 } }, guard: commitGuard });
  return readBodyCleanupControl(dir);
}

/** Exact durable process-return provenance. Missing/forced/ambiguous nested ownership remains unresolved. */
export function readOwnedBodyProcess<T extends Omit<ReturnType<typeof readBodyPhase>, "held"> & { held: BodyExecutionControl }>(phase: T) {
  if (phase.fact.phase !== "process") throw new Error("Body stop proof requires its actual process phase");
  const { held, fact } = phase, root = path.dirname(held.activationPath), a = held.activation;
  if (fact.references.intent.path !== path.join(root, "body-media-process-intent.json")
      || fact.references.outcome.path !== path.join(root, "body-media-process-result.json")) throw new Error("Body process references changed roles");
  const intent = readCutPreviewObject(fact.references.intent.path), output = readCutPreviewObject(fact.references.outcome.path), row = output.value;
  const intentKeys = ["schemaVersion", "kind", "activationHash", "inputSha256", "executionId", "journalHash", "startedAt", "tools"];
  exactKeys(intent.value, intentKeys, intentKeys, "body intent");
  const keys = ["schemaVersion", "kind", "scope", "activationHash", "inputSha256", "executionId", "intentSha256", "startedAt", "finishedAt",
    "elapsedMs", "status", "error", "timedOut", "groupStopped", "forcedStop", "stdout", "stderr", "ledgerSha256"];
  exactKeys(row, keys, keys, "body actual outcome");
  if (intent.sha256 !== fact.references.intent.sha256 || output.sha256 !== fact.references.outcome.sha256
      || row.schemaVersion !== 1 || row.kind !== "guided-body-process-outcome" || row.scope !== "owned-process-stop-not-body-or-delivery-approval"
      || intent.value.schemaVersion !== 1 || intent.value.kind !== "guided-body-process-intent" || intent.value.journalHash !== fact.beforeJournalHash
      || row.intentSha256 !== intent.sha256 || row.activationHash !== held.activationHash || intent.value.activationHash !== held.activationHash
      || row.inputSha256 !== a.inputSha256 || intent.value.inputSha256 !== a.inputSha256 || row.executionId !== a.executionId
      || intent.value.executionId !== a.executionId || row.startedAt !== intent.value.startedAt) throw new Error("Body actual process authority changed");
  assertBodyOwnedOutcome(row, fact.createdAt, a.createdAt);
  const tools = objectValue(intent.value.tools, "body actual process tools"), currentTools = bodyChildTools(held, "media");
  if (hash(tools) !== hash(currentTools)) throw new Error("Body process worker/interpreter closure changed");
  const nestedOwnership = bodyNestedOwnership({ root, row, script: currentTools.script });
  return { held, intent, output, receipt: row, current: phase.current, nestedOwnership,
    ownershipUnresolved: nestedOwnership !== "resolved-by-normal-return" };
}

/** A proven stopped outer group permits only exact Docker reconciliation when local descendants remain unknown. */
export function bodyNestedOwnership(input: { root: string; row: Record<string, unknown>; script: string }): string {
  if (input.row.forcedStop === true) return "unresolved-forced-outer-stop";
  try {
    observeOwnedWorkerLedger(input.root, "media", input.script, sha256(input.row.ledgerSha256, "body ledger SHA"));
    const nested = liveRecordedDescendants(input.root, "media");
    return nested.live.length || nested.unknown.length || nested.unrecordedSpawns.length
      ? "unresolved-nested-ownership" : "resolved-by-normal-return";
  } catch (error) { return `unresolved-ledger: ${String(error).slice(0, 2000)}`; }
}

/** Selection/readback requires full normal-return ownership, not merely a stopped outer group. */
export function readStoppedBodyProcess(phase: ReturnType<typeof readBodyPhase>) {
  const stopped = readOwnedBodyProcess(phase);
  if (stopped.ownershipUnresolved) throw new Error(`Body nested ownership remains unresolved: ${stopped.nestedOwnership}`);
  return stopped;
}

export function assertBodyOwnedOutcome(row: Record<string, unknown>, committedAt: string, activatedAt: string): void {
  const start = bodyTimestamp(row.startedAt), finish = bodyTimestamp(row.finishedAt);
  if (start < activatedAt || finish < start || finish > committedAt || typeof row.elapsedMs !== "number"
      || !Number.isFinite(row.elapsedMs) || row.elapsedMs < 0 || row.elapsedMs > 3_310_000
      || !["complete", "failed"].includes(String(row.status)) || row.groupStopped !== true || typeof row.forcedStop !== "boolean"
      || typeof row.timedOut !== "boolean" || (row.timedOut && !row.forcedStop) || typeof row.error !== "string" || row.error.length > 4000
      || (row.status === "complete" && (row.error !== "" || row.forcedStop || row.timedOut))
      || [row.stdout, row.stderr].some((value) => typeof value !== "string" || Buffer.byteLength(value, "utf8") > 2 * 1024 * 1024)) {
    throw new Error("Body stopped ownership is missing, forced, ambiguous or outside its bounded invocation");
  }
}
