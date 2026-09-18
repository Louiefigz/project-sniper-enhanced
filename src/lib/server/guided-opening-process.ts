import path from "node:path";
import { lstatSync, realpathSync } from "node:fs";
import { CutPreviewProcessError, runCutPreviewProcess } from "@/app/api/producer/auto-edit/cut-preview-process";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { observeCutPreviewFile, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { pythonInterpreter } from "@/app/api/_lib/spawn-python";
import { exactKeys, objectValue, sha256, uuid } from "@/lib/producer/contracts/validation";
import { readGuidedOpeningExecutionClaim } from "./guided-opening-claim";
import { observeHistoricalProposalSnapshot } from "./guided-proposal-history-snapshot";
import { readGuidedProposalReadiness } from "./guided-proposal-review-store";
import { readGuidedObject, strictGuidedTimestamp } from "./guided-cut-v2-store";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { openingRuntimeEnvironment } from "./guided-opening-runtime-control";
import { stageTimingEnv, withStageTimingContext } from "./stage-timing-context";
import { timedStage } from "./stage-timing";
import type { ProjectMutationLease } from "./project-mutation-lease";
import { createOpeningRecord, assertOpeningRecord, readOpeningProcessActivation } from "./guided-opening-process-activation";
import { writeGuidedObject } from "./guided-cut-v2-store";
import { commitGuidedJob } from "./guided-cut-v2";
import { retainGenerationClockObservation } from "./generation-clock-watermark";
import { OWNED_PROCESS_LEDGER_ENV, liveRecordedDescendants, observeOwnedWorkerLedger, ownedProcessLedgerPath } from "./guided-opening-process-ledger";
import { sourceColorFromOpeningProcessIntent } from "./guided-source-color-process-binding";
import { assertSourceColorReadInvocation, assertSourceColorReadTools, type SourceColorReadInvocation } from "./guided-source-color-read-transport";

export type HeldOpeningClaim = ReturnType<typeof readGuidedOpeningExecutionClaim>;
const OUTPUT_LIMIT = 2 * 1024 * 1024;

/** Preserve venv invocation semantics while independently binding its resolved executable and configuration. */
export function openingPythonIdentity() {
  const python = pythonInterpreter();
  if (!path.isAbsolute(python)) throw new Error("Opening execution requires the actual project venv, not an ambient Python fallback");
  const venvRoot = realpathSync(path.dirname(path.dirname(python))), pythonResolved = realpathSync(python);
  if (venvRoot !== path.dirname(path.dirname(python))) throw new Error("Opening venv root is not canonical");
  const venvConfig = path.join(venvRoot, "pyvenv.cfg");
  return { python, pythonResolved, pythonHash: observeCutPreviewFile(pythonResolved, 256 * 1024 * 1024).sha256,
    venvRoot, venvConfig, venvConfigHash: observeCutPreviewFile(venvConfig, 64 * 1024).sha256 };
}

/** Pinned-byte observation is sufficient only for exact claimed recovery; media still requires current readiness. */
export function openingChildTools(held: HeldOpeningClaim, kind: "media" | "cleanup" | "read") {
  const pipeline = held.job.ctx.pipeline;
  if (!pipeline) throw new Error("Opening owned process has no pinned executable closure");
  const proposal = readGuidedObject(held.job.ctx.dir, held.job.guidedHandoffV2!.treatmentProposalHash!);
  const compiler = readGuidedObject(held.job.ctx.dir, sha256(proposal.compilerAuthorityHash, "compilerAuthorityHash"));
  observeHistoricalProposalSnapshot(pipeline, compiler);
  const script = path.join(pipeline.snapshotRoot, `scripts/producer/guided_opening_${kind}.py`);
  const scriptHash = observeCutPreviewFile(script, 1024 * 1024).sha256;
  const runnerScript = path.join(pipeline.snapshotRoot, "scripts/producer/headless/process_runner.py");
  const runnerScriptHash = observeCutPreviewFile(runnerScript, 1024 * 1024).sha256;
  if (!pipeline.files.some((row) => row.path === `scripts/producer/guided_opening_${kind}.py` && row.hash === scriptHash)
      || !pipeline.files.some((row) => row.path === "scripts/producer/headless/process_runner.py" && row.hash === runnerScriptHash)) {
    throw new Error("Opening exact worker is absent from the original pinned closure");
  }
  return { script, scriptHash, runnerScript, runnerScriptHash, ...openingPythonIdentity() };
}

/** Every asynchronous caller retains its original claimed journal and actual lease. */
export function openingOwnershipGuard(held: HeldOpeningClaim, lease: ProjectMutationLease): () => void {
  const guard = cutPreviewLeaseGuard(held.job.ctx.dir, lease);
  return () => {
    guard();
    if (observeHumanCutJob(held.job.ctx.dir).sha256 !== held.sha256) throw new Error("Opening exact owned journal changed");
  };
}

/** Run one actual pinned child; cleanup's caller separately supplies its protected remainder. */
export function invokeOpeningChild(input: { held: HeldOpeningClaim; tools: ReturnType<typeof openingChildTools>;
  kind: "media" | "cleanup" | "read"; remainingMs: () => number; extraArgs?: string[]; cleanupAttemptId?: string;
  sourceColorRead?: SourceColorReadInvocation;
  beforeSpawn?: () => void; afterSettled?: (details: Readonly<CutPreviewProcessError["details"]>) => void }) {
  const { held, sourceColorRead, kind, cleanupAttemptId, afterSettled, remainingMs, beforeSpawn } = input;
  const extraArgs = input.extraArgs === undefined ? undefined : Object.freeze([...input.extraArgs]);
  if (sourceColorRead !== undefined && (kind !== "read" || extraArgs !== undefined || cleanupAttemptId !== undefined)) {
    throw new Error("Final-bound source-color read cannot override its exact role or arguments");
  }
  if (kind === "read" && sourceColorRead === undefined && extraArgs?.some(arg => arg.startsWith("--source-color-"))) {
    throw new Error("Source-color read arguments require the actual final-bound invocation");
  }
  if (sourceColorRead !== undefined) assertSourceColorReadInvocation(sourceColorRead, held);
  const tools = sourceColorRead !== undefined ? Object.freeze(structuredClone(input.tools)) : input.tools;
  if (sourceColorRead !== undefined) assertSourceColorReadTools(sourceColorRead, held, tools);
  const runtime = sourceColorRead !== undefined ? sourceColorRead.environment : openingRuntimeEnvironment(held.claim.runtime);
  const ledgerRoot = cleanupAttemptId === undefined ? path.dirname(held.claimPath) : cleanupLedgerRoot(input);
  const remaining = remainingMs();
  if (sourceColorRead !== undefined) assertSourceColorReadInvocation(sourceColorRead, held);
  const before = sourceColorRead !== undefined ? () => {
    beforeSpawn?.(); assertToolsUnchanged(tools); assertSourceColorReadInvocation(sourceColorRead, held);
  } : beforeSpawn;
  const scriptArgs = kind === "media" || cleanupAttemptId !== undefined ? [tools.runnerScript, tools.script] : [tools.script];
  return runCutPreviewProcess({ command: tools.python, args: [...scriptArgs, held.claim.inputPath, held.claim.outputRoot,
    "--input-sha256", held.claim.inputSha256, "--execution-claim", held.claimPath, "--execution-claim-sha256", held.claimSha256,
    ...(sourceColorRead?.args ?? extraArgs ?? []), "--timeout-seconds", String(Math.max(1, remaining - 250) / 1000)], cwd: path.dirname(tools.script),
    env: { ...stageTimingEnv(), ...runtime, PYTHONPATH: path.dirname(tools.script), SNIPER_PIPELINE_ROOT: held.job.ctx.pipeline!.snapshotRoot,
      [OWNED_PROCESS_LEDGER_ENV]: ownedProcessLedgerPath(ledgerRoot, kind),
      PYTHONDONTWRITEBYTECODE: "1", PYTHONHOME: undefined, PYTHONNOUSERSITE: "1" }, purpose: kind === "cleanup" ? "cut-preview" : "guided-opening", timeoutMs: remainingMs(),
    ...(before ? { beforeSpawn: before } : {}), ...(afterSettled ? { afterSettled } : {}) });
}

/** Each additive cleanup invocation has one new-only wrapper ledger in its exact attempt. */
function cleanupLedgerRoot(input: { held: HeldOpeningClaim; kind: string; cleanupAttemptId?: string }): string {
  const id = uuid(input.cleanupAttemptId, "source color cleanup attempt");
  if (input.kind !== "cleanup" || id[14] !== "4") throw new Error("An attempt-scoped lifecycle belongs only to cleanup");
  const directory = path.join(path.dirname(input.held.claimPath), "cleanup-attempts", id), info = lstatSync(directory);
  if (!info.isDirectory() || realpathSync(directory) !== directory || info.uid !== process.getuid?.() || (info.mode & 0o077) !== 0) {
    throw new Error("Cleanup lifecycle requires its existing canonical private attempt directory");
  }
  return directory;
}

/** Read back the originally captured worker/interpreter closure, never choose replacement tools. */
export function assertToolsUnchanged(tools: ReturnType<typeof openingChildTools>): void {
  if (observeCutPreviewFile(tools.script, 1024 * 1024).sha256 !== tools.scriptHash
      || observeCutPreviewFile(tools.runnerScript, 1024 * 1024).sha256 !== tools.runnerScriptHash
      || realpathSync(tools.python) !== tools.pythonResolved
      || observeCutPreviewFile(tools.pythonResolved, 256 * 1024 * 1024).sha256 !== tools.pythonHash
      || observeCutPreviewFile(tools.venvConfig, 64 * 1024).sha256 !== tools.venvConfigHash) throw new Error("Opening actual interpreter or worker bytes changed");
}

interface OpeningMediaOutcome {
  status: "complete" | "failed"; error: string; timedOut: boolean; groupStopped: boolean;
  /** The runner force-stopped the OUTER group. Nested local probe sessions (headless/process_runner.py
   * start_new_session) were never observed, so ownership stays unresolved and the claim must be retained. */
  forcedStop: boolean; stdout: string; stderr: string; ledgerSha256: string | null;
}

async function mediaOutcome(input: { held: HeldOpeningClaim; tools: ReturnType<typeof openingChildTools>;
  remainingMs: () => number; guard: () => void }): Promise<OpeningMediaOutcome> {
  let groupStopped = false, status: "complete" | "failed" = "failed", error = "", timedOut = false, forcedStop = false, stdout = "", stderr = "";
  try {
    await timedStage(input.held.job.ctx.dir, "guided_opening_owned_media", async () => {
      const result = await invokeOpeningChild({ ...input, kind: "media" });
      groupStopped = true; stdout = result.stdout; stderr = result.stderr;
      assertToolsUnchanged(input.tools); input.guard(); input.remainingMs(); status = "complete";
    });
  } catch (failure) {
    error = String(failure).slice(0, 4000);
    if (failure instanceof CutPreviewProcessError) ({ groupStopped, timedOut, forcedStop, stdout, stderr } = failure.details);
  }
  let ledgerSha256: string | null = null;
  if (groupStopped && !forcedStop) {
    try { ledgerSha256 = observeOwnedWorkerLedger(path.dirname(input.held.claimPath), "media", input.tools.script); }
    catch (failure) { status = "failed"; error = `${error}\n${String(failure)}`.slice(0, 4000); }
  }
  return { status, error, timedOut, groupStopped, forcedStop, stdout, stderr, ledgerSha256 };
}

/** A caller cannot supply a stopped boolean. Only this real owned runner writes the durable stop outcome. */
export async function runClaimedOpeningMedia(input: { dir: string; lease: ProjectMutationLease; remainingMs: () => number }) {
  const startedAt = new Date().toISOString(), mono = performance.now(), held = readGuidedOpeningExecutionClaim(input.dir);
  if (held.submission.schemaVersion === 2) {
    throw new Error("Source-color process and full-reservation cleanup are not connected yet; retain claim without spawning");
  }
  const guard = openingOwnershipGuard(held, input.lease); guard(); input.remainingMs();
  readGuidedProposalReadiness(input.dir); // Strong current == pinned executor and accepted proposal, not historical recovery.
  const tools = openingChildTools(held, "media"), root = path.dirname(held.claimPath); guard(); input.remainingMs();
  const intent = { schemaVersion: 2, kind: "guided-opening-process-intent", claimHash: held.claimHash,
    inputSha256: held.claim.inputSha256, executionId: held.claim.executionId, journalHash: held.sha256,
    clockHash: held.claim.clockHash, generationStartedAt: held.claim.generationStartedAt, startedAt, tools };
  const intentRecord = createOpeningRecord(path.join(root, "media-process-intent.json"), intent); // New-only. Never replay a possible spawn.
  const output = await withStageTimingContext({ runId: held.job.artifactToken ?? held.job.token,
    attemptId: `opening:${held.claim.executionId}`, attemptNo: held.job.attempts }, () =>
    mediaOutcome({ held, tools, guard, remainingMs: input.remainingMs }));
  const receipt = { schemaVersion: 2, kind: "guided-opening-process-outcome", scope: "owned-process-stop-not-media-or-delivery-approval",
    intentHash: canonicalJsonSha256(intent), claimHash: held.claimHash, inputSha256: held.claim.inputSha256,
    executionId: held.claim.executionId, startedAt, finishedAt: new Date().toISOString(), elapsedMs: performance.now() - mono, ...output };
  const outcomeRecord = createOpeningRecord(path.join(root, "media-process-result.json"), receipt);
  guard(); assertOpeningRecord(intentRecord); assertOpeningRecord(outcomeRecord);
  const createdAt = new Date().toISOString(), activation = { schemaVersion: 1, kind: "guided-opening-process-activation",
    scope: "actual-owned-process-outcome-not-media-or-delivery-approval", claimHash: held.claimHash,
    beforeJournalHash: held.sha256, executionId: held.claim.executionId, inputSha256: held.claim.inputSha256,
    intentSha256: intentRecord.sha256, outcomeSha256: outcomeRecord.sha256, clockHash: held.claim.clockHash,
    generationStartedAt: held.claim.generationStartedAt, createdAt };
  const activationHash = writeGuidedObject(input.dir, activation); saveHumanCutJobSnapshot(input.dir, held);
  const commitGuard = () => {
    guard(); assertOpeningRecord(intentRecord); assertOpeningRecord(outcomeRecord);
    const observedAt = new Date().toISOString();
    if (observedAt < createdAt || createdAt < receipt.finishedAt) throw new Error("Opening owned outcome clock moved backwards; keep unresolved claim");
    retainGenerationClockObservation({ dir: input.dir, origin: { clockHash: held.claim.clockHash, startedAt: held.claim.generationStartedAt },
      executionId: held.claim.executionId, observedAt }, guard);
  };
  commitGuidedJob({ beforeHash: held.sha256, guard: commitGuard,
    job: { ...held.job, updatedAt: createdAt, guidedHandoffV2: { ...held.job.guidedHandoffV2!, openingProcessOutcomeHash: activationHash } } });
  return { held: readGuidedOpeningExecutionClaim(input.dir), receipt, receiptSha256: outcomeRecord.sha256 };
}

export interface StoppedOwnership { receipt: Record<string, unknown>; nestedOwnership?: string }

/** Ownership is unresolved after a forced OUTER stop, while a pid the worker itself recorded is still alive, or when
 * the worker recorded an intent to spawn but died before recording the pid (that child is unknown, not absent). */
export function ownershipUnresolved(stopped: StoppedOwnership): boolean {
  return stopped.receipt.forcedStop !== false || stopped.nestedOwnership !== "resolved-by-normal-return";
}

/** Strong retained provenance permits cleanup only. Missing/incomplete stop evidence never authorizes guessed PID recovery. */
export function readStoppedOpeningProcess(held: HeldOpeningClaim) {
  const activation = readOpeningProcessActivation(held.job.ctx.dir, held);
  const root = path.dirname(held.claimPath), intentFile = readCutPreviewObject(path.join(root, "media-process-intent.json"));
  const file = readCutPreviewObject(path.join(root, "media-process-result.json")), row = file.value, intent = intentFile.value;
  const keys = ["schemaVersion", "kind", "scope", "intentHash", "claimHash", "inputSha256", "executionId", "startedAt", "finishedAt",
    "elapsedMs", "status", "error", "timedOut", "groupStopped", "forcedStop", "stdout", "stderr"];
  if (row.schemaVersion === 2 || row.schemaVersion === 3) keys.push("ledgerSha256");
  exactKeys(row, keys, keys, "opening process outcome");
  const intentKeys = ["schemaVersion", "kind", "claimHash", "inputSha256", "executionId", "journalHash", "clockHash", "generationStartedAt", "startedAt", "tools"];
  if (intent.schemaVersion === 3) intentKeys.push("sourceColor");
  exactKeys(intent, intentKeys, intentKeys, "opening process intent");
  const tools = objectValue(intent.tools, "opening process tools"), toolKeys = ["script", "scriptHash", "python", "pythonResolved", "pythonHash", "venvRoot", "venvConfig", "venvConfigHash"];
  if (intent.schemaVersion === 2 || intent.schemaVersion === 3) toolKeys.push("runnerScript", "runnerScriptHash");
  exactKeys(tools, toolKeys, toolKeys, "opening process tools"); sha256(tools.scriptHash, "scriptHash"); sha256(tools.pythonHash, "pythonHash");
  sha256(tools.venvConfigHash, "venvConfigHash");
  const clocks = [held.claim.generationStartedAt, intent.startedAt, row.startedAt, row.finishedAt].map(strictGuidedTimestamp);
  if (![1, 2, 3].includes(Number(intent.schemaVersion)) || typeof intent.schemaVersion !== "number"
      || activation.fact.schemaVersion !== (intent.schemaVersion === 3 ? 2 : 1)
      || intent.schemaVersion !== row.schemaVersion || intent.kind !== "guided-opening-process-intent"
      || row.kind !== "guided-opening-process-outcome" || row.scope !== "owned-process-stop-not-media-or-delivery-approval"
      || row.intentHash !== canonicalJsonSha256(intent) || row.claimHash !== held.claimHash || intent.claimHash !== held.claimHash
      || row.inputSha256 !== held.claim.inputSha256 || intent.inputSha256 !== held.claim.inputSha256
      || row.executionId !== held.claim.executionId || intent.executionId !== held.claim.executionId || intent.journalHash !== activation.prior.sha256
      || intentFile.sha256 !== activation.fact.intentSha256 || file.sha256 !== activation.fact.outcomeSha256
      || intent.clockHash !== held.claim.clockHash || intent.generationStartedAt !== held.claim.generationStartedAt
      || clocks[1] !== clocks[2] || clocks[1] < activation.prior.job.updatedAt || clocks[3] > String(activation.fact.createdAt)
      || clocks.some((at, index) => index > 0 && at < clocks[index - 1])
      || typeof row.elapsedMs !== "number" || !Number.isFinite(row.elapsedMs) || row.elapsedMs < 0 || row.elapsedMs > 1_510_000
      || !["complete", "failed"].includes(String(row.status)) || typeof row.error !== "string" || row.error.length > 4000
      || typeof row.timedOut !== "boolean" || typeof row.forcedStop !== "boolean" || row.groupStopped !== true
      || (row.timedOut && !row.forcedStop && row.schemaVersion !== 3)
      || (row.status === "complete" && (row.error || row.timedOut || row.forcedStop))
      || [row.stdout, row.stderr].some((text) => typeof text !== "string" || Buffer.byteLength(text, "utf8") > OUTPUT_LIMIT)) {
    throw new Error("Opening durable stopped-process proof is absent, ambiguous or changed; no automatic recovery");
  }
  const expectedScript = path.join(held.job.ctx.pipeline!.snapshotRoot, "scripts/producer/guided_opening_media.py");
  if (tools.script !== expectedScript || !held.job.ctx.pipeline!.files.some((entry) => entry.path === "scripts/producer/guided_opening_media.py" && entry.hash === tools.scriptHash)
      || [tools.python, tools.pythonResolved, tools.venvRoot, tools.venvConfig].some((file) => typeof file !== "string" || !path.isAbsolute(file))) throw new Error("Opening stopped process was not the exact pinned worker");
  const sourceColor = sourceColorFromOpeningProcessIntent(intent, held); assertVersionedLedger(held, row, tools);
  // A normal return still leaves nested-session children unobserved by the group stop; the worker's own ledger of
  // exact pids (argv[0] + start time) is the only non-guessed evidence, and a live match keeps ownership unresolved.
  const observed = row.forcedStop ? { live: [], unknown: [], unrecordedSpawns: [] } : liveRecordedDescendants(root, "media");
  const nestedOwnership = row.forcedStop ? "unresolved-forced-outer-stop" as const
    : observed.live.length ? "unresolved-live-recorded-descendant" as const
    : observed.unknown.length ? "unresolved-unknown-descendant" as const
    : observed.unrecordedSpawns.length ? "unresolved-unrecorded-spawn" as const : "resolved-by-normal-return" as const;
  assertSettledV3Deadline(row, nestedOwnership);
  return { receipt: row, receiptSha256: file.sha256, intentHash: canonicalJsonSha256(intent), resourceAbsence: "not-observed" as const,
    sourceColor, nestedOwnership, liveDescendants: observed.live, unknownDescendants: observed.unknown, unrecordedSpawns: observed.unrecordedSpawns };
}

/** Only V3 can describe an unforced deadline failure after independently complete outer/nested settlement. */
function assertSettledV3Deadline(row: Record<string, unknown>, nestedOwnership: string): void {
  if (row.schemaVersion === 3 && row.timedOut && !row.forcedStop && nestedOwnership !== "resolved-by-normal-return") {
    throw new Error("V3 post-settlement deadline failure requires complete original nested settlement");
  }
}

function assertVersionedLedger(held: HeldOpeningClaim, row: Record<string, unknown>, tools: Record<string, unknown>): void {
  if (row.schemaVersion === 1) return; // Historical v1 still requires its original nonempty child ledger.
  const runner = "scripts/producer/headless/process_runner.py", pipeline = held.job.ctx.pipeline!;
  if (tools.runnerScript !== path.join(pipeline.snapshotRoot, runner)
      || !pipeline.files.some((file) => file.path === runner && file.hash === sha256(tools.runnerScriptHash, "runnerScriptHash"))) {
    throw new Error("Opening stopped process lost its exact pinned lifecycle wrapper");
  }
  if (row.ledgerSha256 !== null) sha256(row.ledgerSha256, "ledgerSha256");
  if (row.forcedStop) return; // Forced-stop ownership remains unresolved, never granted by a lifecycle row.
  observeOwnedWorkerLedger(path.dirname(held.claimPath), "media", String(tools.script), sha256(row.ledgerSha256, "ledgerSha256"));
}
