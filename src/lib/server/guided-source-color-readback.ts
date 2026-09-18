/** Explicit schema2 verification only. Public execution/selection/body activation remains separately fenced. */
import path from "node:path";
import { randomUUID } from "node:crypto";
import { lstatSync, realpathSync } from "node:fs";
import { isDeepStrictEqual } from "node:util";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { readCommittedOpeningCleanup, assertOpeningCleanupMetadata } from "./guided-opening-cleanup-store";
import { readGuidedProposalReadiness } from "./guided-proposal-review-store";
import { openingChildTools, invokeOpeningChild, assertToolsUnchanged } from "./guided-opening-process";
import { assertHeldSourceColorOpeningResultUnchanged, assertSourceColorOpeningReadbackIdentity,
  readHeldSourceColorOpeningResult } from "./guided-source-color-opening-result";
import { holdSourceColorReadInvocation, assertSourceColorReadInvocation, assertSourceColorReadTools } from "./guided-source-color-read-transport";
import { createOpeningRecord, assertOpeningRecord, assertOpeningFailureAbsent } from "./guided-opening-process-activation";
import { humanCutDirectory, observeHumanCutJob } from "./human-cut-acceptance-store";
import { recordOpeningReadbackFailure, type ReadbackInput } from "./guided-opening-readback";
import { withStageTimingContext } from "./stage-timing-context";
import { timedStage } from "./stage-timing";
import { capturePublication, assertPublication } from "./guided-source-color-cleanup-pending-commit";
import { freezeSourceColorValue, snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import { directoryIdentity } from "./guided-source-color-cleanup-attempt-hold";
import { selectedOpeningRow } from "./guided-opening-selection";
import { holdSelectionMedia } from "./guided-source-color-selection-read";

/** Only upstream readiness/tools and native invocation are TEST leaves; records and retained joins stay actual. */
export const sourceColorReadbackDependencies = { readiness: readGuidedProposalReadiness, tools: openingChildTools, invoke: invokeOpeningChild };
type Dependencies = typeof sourceColorReadbackDependencies;
const verifiedReads = new WeakMap<object, { check: () => void; owner: ReadbackInput }>();
type OriginalInput = ReadbackInput & { release: ReadbackInput["lease"]["release"] };

/** Installed executables need not be private metadata files; preserve their actual canonical regular-file identity. */
function toolIdentity(file: string): bigint[] {
  const row = lstatSync(file, { bigint: true });
  if (!row.isFile() || realpathSync(file) !== file) throw new Error("Source-color read tool is not its canonical regular file");
  return [row.dev, row.ino, row.mode, row.uid, row.nlink, row.size, row.mtimeNs, row.ctimeNs];
}

/** Capture four exact original tool roles once; late checks are stat/ancestry only, never repeated full-tool hashes. */
function holdReadTools(tools: ReturnType<typeof openingChildTools>): () => void {
  const files = [tools.script, tools.runnerScript, tools.pythonResolved, tools.venvConfig]
    .map(file => ({ file, identity: toolIdentity(file) }));
  const parents = new Map<string, bigint[]>();
  for (const { file } of files) {
    for (let directory = path.dirname(file); !parents.has(directory); directory = path.dirname(directory)) {
      parents.set(directory, directoryIdentity(directory));
    }
  }
  return () => {
    if (realpathSync(tools.python) !== tools.pythonResolved) throw new Error("Source-color read interpreter link changed");
    for (const [directory, state] of parents) {
      if (!isDeepStrictEqual(directoryIdentity(directory), state)) throw new Error("Source-color read tool ancestry changed");
    }
    for (const { file, identity } of files) {
      if (!isDeepStrictEqual(toolIdentity(file), identity)) throw new Error("Source-color read original tool identity changed");
    }
  };
}

/** Capture original callbacks/lease before the first caller callback; never borrow the expired cleanup-read clock. */
function originalOwner(input: ReadbackInput, observed: ReturnType<typeof readCommittedOpeningCleanup>, original: OriginalInput) {
  const lease = cutPreviewLeaseGuard(original.dir, original.lease);
  const metadata = () => {
    if (input.dir !== original.dir || input.lease !== original.lease || input.lease.release !== original.release
        || input.remainingMs !== original.remainingMs || input.expectedCleanupHash !== original.expectedCleanupHash) {
      throw new Error("Source-color readback original request owner changed");
    }
    assertOpeningCleanupMetadata(observed);
  };
  const remainingMs = () => {
    metadata(); lease(); const started = performance.now(), remaining = original.remainingMs(); metadata();
    if (!Number.isSafeInteger(remaining) || remaining <= 0 || remaining > 1_500_000) throw new Error("Source-color readback original remainder is invalid");
    if (observeHumanCutJob(original.dir).sha256 !== observed.sha256) throw new Error("Source-color readback original current journal changed");
    lease(); metadata(); const elapsed = performance.now() - started, bounded = Math.floor(remaining - elapsed);
    if (!Number.isFinite(elapsed) || elapsed < 0 || bounded <= 0) throw new Error("Source-color readback original metadata exhausted its remainder");
    return bounded;
  };
  return { original, metadata, remainingMs, guard: () => { remainingMs(); } };
}

/** Join actual final cleanup to actual stopped/result metadata before any private attempt is published. */
function readbackAttempt(input: ReadbackInput, controls: Dependencies, original: OriginalInput) {
  const observed = readCommittedOpeningCleanup(original.dir);
  assertOpeningCleanupMetadata(observed);
  if (!("pending" in observed) || observed.cleanupHash !== original.expectedCleanupHash
      || observed.job.guidedHandoffV2?.openingExecutionClaimHash) throw new Error("Source-color readback requires exact current final cleanup");
  const failureHeld = snapshotSourceColorMetadata(observed.held);
  const owner = originalOwner(input, observed, original); owner.guard(); controls.readiness(original.dir); owner.guard();
  const held = observed.held, selected = readHeldSourceColorOpeningResult({ held, guard: owner.guard });
  const mediaMetadata = holdSelectionMedia({ core: selectedOpeningRow(selected.record.value, "core", held.claim.outputRoot),
    review: selectedOpeningRow(selected.record.value, "review", held.claim.outputRoot) });
  const invocation = holdSourceColorReadInvocation({ cleanup: observed, selected });
  const tools = Object.freeze(structuredClone(controls.tools(held, "read")));
  assertSourceColorReadTools(invocation, held, tools);
  const toolMetadata = holdReadTools(tools); owner.guard(); toolMetadata();
  const binding = structuredClone({ sourceColor: selected.process.sourceColor, archive: observed.pending.fact.archive,
    sourceColorEvidence: selected.completion.sourceColorEvidence });
  const directory = humanCutDirectory(humanCutDirectory(path.dirname(held.claimPath), "readback-attempts"), randomUUID());
  const start = freezeSourceColorValue(createOpeningRecord(path.join(directory, "start.json"), { schemaVersion: 2, kind: "guided-opening-readback-start",
    beforeJournalHash: observed.sha256, cleanupHash: observed.cleanupHash, claimHash: held.claimHash,
    executionId: held.claim.executionId, receiptSha256: selected.completion.receiptSha256, tools, ...binding,
    clockHash: held.claim.clockHash, generationStartedAt: held.claim.generationStartedAt, startedAt: new Date().toISOString() }));
  const startPublication = capturePublication(start.path, start.sha256);
  return { observed, owner, selected, tools, toolMetadata, mediaMetadata, invocation, binding, directory, start, startPublication, failureHeld };
}
type Attempt = ReturnType<typeof readbackAttempt>;

/** Metadata follows every caller frontier; checking it cannot reset the owner's time or recontact Docker. */
function metadata(attempt: Attempt): void {
  attempt.owner.metadata(); assertSourceColorReadInvocation(attempt.invocation, attempt.observed.held);
  assertPublication(attempt.startPublication); assertOpeningFailureAbsent(path.join(attempt.directory, "failure.json"));
  attempt.owner.metadata(); attempt.toolMetadata(); attempt.mediaMetadata();
}

/** Charge the final callback-free proof tail to the owner's just-captured remaining allowance. */
function finalCheck(attempt: Attempt, check: () => void): void {
  const started = performance.now(), remaining = attempt.owner.remainingMs(); check();
  const elapsed = performance.now() - started;
  if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed >= remaining) throw new Error("Source-color readback final evidence exhausted its original remainder");
}

async function actualRead(attempt: Attempt, controls: Dependencies) {
  const { observed, owner, selected, tools, invocation } = attempt, held = observed.held;
  owner.guard(); metadata(attempt); const began = performance.now();
  const value = await controls.invoke({ held, tools, kind: "read", remainingMs: owner.remainingMs, sourceColorRead: invocation,
    beforeSpawn: () => { owner.guard(); metadata(attempt); }, afterSettled: () => metadata(attempt) });
  const elapsedMs = performance.now() - began;
  const output = freezeSourceColorValue(createOpeningRecord(path.join(attempt.directory, "output.json"), { schemaVersion: 2,
    kind: "guided-opening-readback-owned-output", startSha256: attempt.start.sha256, ...value,
    processGroupStopped: true, observedAt: new Date().toISOString(), elapsedMs }));
  const outputPublication = capturePublication(output.path, output.sha256);
  const result = assertSourceColorOpeningReadbackIdentity(value.stdout, { held, selected });
  if (!Number.isFinite(elapsedMs) || elapsedMs < 0 || result.elapsedMs > elapsedMs + 1) throw new Error("Source-color child readback exceeds actual owned elapsed time");
  assertToolsUnchanged(tools); assertHeldSourceColorOpeningResultUnchanged(held, selected);
  assertOpeningRecord(output); owner.guard(); metadata(attempt);
  const receipt = freezeSourceColorValue(createOpeningRecord(path.join(attempt.directory, "verified.json"), { schemaVersion: 2, kind: "guided-opening-owned-readback",
    scope: "actual-current-readback-not-selected-or-approved", beforeJournalHash: observed.sha256, cleanupHash: observed.cleanupHash,
    claimHash: held.claimHash, startSha256: attempt.start.sha256, outputSha256: output.sha256, result, ...attempt.binding,
    clockHash: held.claim.clockHash, generationStartedAt: held.claim.generationStartedAt, createdAt: new Date().toISOString(),
    mediaSelected: false, openingApproved: false, deliveryApproved: false }));
  const receiptPublication = capturePublication(receipt.path, receipt.sha256);
  const check = () => { metadata(attempt); assertPublication(outputPublication); assertPublication(receiptPublication); metadata(attempt); };
  finalCheck(attempt, check);
  const verified = Object.freeze({ observed, selected, result, receipt, output,
    mediaSelected: false as const, openingApproved: false as const, deliveryApproved: false as const });
  verifiedReads.set(verified, { check, owner: owner.original }); return verified;
}

/** One actual owned read under the caller's original remaining allowance, without release, retry, selection or approval. */
export async function verifyCleanedSourceColorOpeningMediaUnderLease(input: ReadbackInput,
  dependencies: Dependencies = sourceColorReadbackDependencies) {
  const original = { ...input, release: input.lease.release };
  const controls = { ...dependencies }, attempt = readbackAttempt(input, controls, original), held = attempt.observed.held;
  try {
    const result = await withStageTimingContext({ runId: held.job.artifactToken ?? held.job.token,
      attemptId: `opening-readback:${held.claim.executionId}:${path.basename(attempt.directory)}`, attemptNo: held.job.attempts }, () =>
      timedStage(input.dir, "guided_opening_source_color_current_media_readback", () => actualRead(attempt, controls)));
    finalCheck(attempt, () => assertSourceColorOpeningReadbackMetadata(result)); return result;
  } catch (error) {
    recordOpeningReadbackFailure({ input: attempt.owner.original, held: attempt.failureHeld, directory: attempt.directory, error, schemaVersion: 2 });
    throw error;
  }
}

/** A later consumer retains the genuine original proof, without replaying expired read callbacks or minting a clock. */
export function assertSourceColorOpeningReadbackMetadata(value: Awaited<ReturnType<typeof verifyCleanedSourceColorOpeningMediaUnderLease>>): void {
  const original = verifiedReads.get(value);
  if (!original) throw new Error("Source-color readback requires its actual original verification result");
  original.check();
}

/** A later live selector must keep the same request/lease/remainder, not merely an equal receipt or new allowance. */
export function assertSourceColorOpeningReadbackOwner(value: Awaited<ReturnType<typeof verifyCleanedSourceColorOpeningMediaUnderLease>>,
  input: ReadbackInput): void {
  assertSourceColorOpeningReadbackMetadata(value);
  const original = verifiedReads.get(value)!.owner;
  if (input.dir !== original.dir || input.lease !== original.lease || input.remainingMs !== original.remainingMs
      || input.expectedCleanupHash !== original.expectedCleanupHash) throw new Error("Source-color readback cannot transfer to a different live request owner");
  assertSourceColorOpeningReadbackMetadata(value);
}
