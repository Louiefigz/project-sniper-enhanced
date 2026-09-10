import path from "node:path";
import { randomUUID } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import { lstatSync, realpathSync } from "node:fs";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { observeCutPreviewFile, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { objectValue, sha256, exactKeys } from "@/lib/producer/contracts/validation";
import { readBodyPhase, readHistoricalBodyPhase, commitBodyPhase } from "./guided-body-phase";
import { readHeldBodyCleanup, readHeldBodyResult, assertBodyReadbackIdentity, assertBodyOwnedOutput, assertHeldBodyResultMetadata } from "./guided-body-result";
import { bodyOwnershipGuard, bodyClockObservation } from "./guided-body-process";
import { bodyChildTools, assertBodyToolsUnchanged, invokeBodyChild } from "./guided-body-process-tools";
import { createOpeningRecord, assertOpeningRecord, assertOpeningFailureAbsent } from "./guided-opening-process-activation";
import { observeOwnedWorkerLedger, liveRecordedDescendants, ownedProcessLedgerPath } from "./guided-opening-process-ledger";
import { humanCutDirectory, observeHumanCutJob } from "./human-cut-acceptance-store";
import { readGuidedProposalReadiness } from "./guided-proposal-review-store";
import { canonicalJsonSha256 as hash } from "./auto-edit-hash";
import type { ProjectMutationLease } from "./project-mutation-lease";
import { snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import { holdBodyControllerSources } from "./guided-body-controller-sources";
import { fileIdentity } from "./guided-source-color-cleanup-attempt-hold";

/** Code-only readiness TEST leaf. Actual invocation, phase, result and candidate CAS remain hardwired. */
export const bodyReadbackReads = { readiness: readGuidedProposalReadiness };
type ReadbackInput = { dir: string; lease: ProjectMutationLease; remainingMs: () => number };

/** Capture only this attempt's four original publications; never process settlement or a new allowance. */
class ReadbackPublications {
  readonly #directory: string;
  readonly #files = new Map<string, bigint[]>();
  readonly #parents = new Map<string, bigint[]>();
  readonly #records: Array<{ value: object; fixed: unknown }> = [];
  constructor(directory: string) {
    this.#directory = directory;
    for (let parent = directory;; parent = path.dirname(parent)) {
      this.#parents.set(parent, this.#directoryIdentity(parent));
      if (path.dirname(parent) === parent) break;
    }
    this.metadata();
  }
  #directoryIdentity(directory: string): bigint[] {
    if (realpathSync(directory) !== directory) throw new Error("Body readback publication parent is not canonical");
    const stat = lstatSync(directory, { bigint: true });
    if (!stat.isDirectory()) throw new Error("Body readback publication parent is not a directory");
    return [stat.dev, stat.ino, stat.mode, stat.uid];
  }
  #fileIdentity(file: string): bigint[] {
    if (realpathSync(file) !== file) throw new Error("Body readback publication file is not canonical");
    return fileIdentity(file);
  }
  #same(actual: unknown, expected: unknown): void {
    if (!isDeepStrictEqual(actual, expected)) throw new Error("Body readback original publication identity or record changed");
  }
  #capture(file: string): void {
    const names = ["start.json", "output.json", "verified.json", "owned-process-ledger.read.jsonl"];
    if (path.dirname(file) !== this.#directory || !names.includes(path.basename(file)) || this.#files.has(file)) {
      throw new Error("Body readback publication role is foreign or repeated");
    }
    this.#files.set(file, this.#fileIdentity(file)); this.metadata();
  }
  retain(record: ReturnType<typeof createOpeningRecord>): void {
    this.#records.push({ value: record, fixed: snapshotSourceColorMetadata(record) });
    this.#capture(record.path);
  }
  captureLedger(): void { this.#capture(ownedProcessLedgerPath(this.#directory, "read")); }
  #ancestry(): void {
    for (const [directory, identity] of this.#parents) this.#same(this.#directoryIdentity(directory), identity);
  }
  metadata(): void {
    this.#ancestry();
    for (const [file, identity] of this.#files) this.#same(this.#fileIdentity(file), identity);
    assertOpeningFailureAbsent(path.join(this.#directory, "failure.json")); this.#ancestry();
    for (const row of this.#records) this.#same(row.value, row.fixed);
  }
  complete(): void {
    if (this.#files.size !== 4) throw new Error("Body readback publication coverage is incomplete");
    this.metadata();
  }
}

/** Save original caller fields before the first journal/tool/clock callback. */
function readbackRequest(input: ReadbackInput) {
  const original = { ...input }, release = input.lease.release;
  const metadata = () => {
    if (input.dir !== original.dir || input.lease !== original.lease || input.remainingMs !== original.remainingMs
        || input.lease.release !== release) throw new Error("Body readback original caller identity changed");
  };
  return { input: original, metadata };
}

/** Original historical admission plus this already-spent body remainder; no new render allowance or approval. */
function readbackLifetime(request: ReturnType<typeof readbackRequest>, phase: ReturnType<typeof readBodyPhase>, selected: ReturnType<typeof readHeldBodyResult>) {
  const fixed = snapshotSourceColorMetadata({ phase, selected });
  const sources = selected.completion.schemaVersion === 2
    ? holdBodyControllerSources({ admission: phase.held.admission, remainingMs: request.input.remainingMs }) : undefined;
  const metadata = () => {
    request.metadata();
    if (!isDeepStrictEqual({ phase, selected }, fixed)) throw new Error("Body readback original phase or result changed");
    assertHeldBodyResultMetadata(selected); sources?.assertMetadata(); request.metadata();
  };
  metadata(); return { sources, metadata };
}

/** Bind the actual worker's fixed private final, not an arbitrary user path or independent master. */
export function bodyCandidateReference(selected: ReturnType<typeof readHeldBodyResult>) {
  assertHeldBodyResultMetadata(selected);
  const media = objectValue(selected.record.value.media, "body media"), final = objectValue(media.final, "body final"), audit = objectValue(media.audit, "body AuditB");
  const expected = path.join(selected.stopped.held.activation.outputRoot, "body-candidate", "final.mp4");
  if (final.path !== expected || final.videoDecodeSucceeded !== true || audit.finalSha256 !== final.sha256
      || !["pass", "warn"].includes(String(audit.overall)) || audit.exitCode !== 0
      || audit.scope !== "actual-full-Audit-B-not-creative-or-subjective-listening-approval") throw new Error("Body candidate lacks its actual full decode/AuditB binding");
  return { path: expected, sha256: sha256(final.sha256, "private candidate SHA") };
}

/** Bind current exact final bytes before the private pointer is published; paths/mtime are not authority. */
function assertCandidateBytes(selected: ReturnType<typeof readHeldBodyResult>): void {
  const candidate = bodyCandidateReference(selected), final = objectValue(objectValue(selected.record.value.media, "body media").final, "body final");
  const observed = observeCutPreviewFile(candidate.path, 32 * 1024 ** 3);
  if (observed.sha256 !== candidate.sha256 || observed.sizeBytes !== final.sizeBytes) throw new Error("Body actual candidate bytes changed after qualification");
  assertHeldBodyResultMetadata(selected);
}

/** A durable observation captures time BEFORE invoking its guard. Do not let that
 * guard advance the same high-water via remainingMs; enforce budget separately. */
export function bodyReadbackGuards(held: Parameters<typeof bodyClockObservation>[0], ownership: () => void, remainingMs: () => number) {
  const guard = () => { ownership(); remainingMs(); };
  return { guard, observeClock: () => bodyClockObservation(held, ownership) };
}

function prepareReadback(caller: ReadbackInput) {
  const request = readbackRequest(caller), input = request.input;
  const leaseGuard = cutPreviewLeaseGuard(input.dir, input.lease);
  const phase = readBodyPhase(input.dir, "cleanup"), cleanup = readHeldBodyCleanup(phase), selected = readHeldBodyResult(cleanup.process);
  request.metadata(); const lifetime = readbackLifetime(request, phase, selected);
  const held = phase.held, ownership = bodyOwnershipGuard(held, input.lease, phase.current.sha256);
  const guards = bodyReadbackGuards(held, ownership, input.remainingMs), observeClock = guards.observeClock;
  const guard = () => { lifetime.metadata(); guards.guard(); lifetime.sources?.check(); ownership(); leaseGuard(); lifetime.metadata(); };
  guard(); bodyReadbackReads.readiness(input.dir); guard();
  const tools = bodyChildTools(held, "read"), directory = humanCutDirectory(
    humanCutDirectory(path.dirname(held.activationPath), "body-readback-attempts"), randomUUID());
  const publications = new ReadbackPublications(directory);
  const start = createOpeningRecord(path.join(directory, "start.json"), { schemaVersion: 1, kind: "guided-body-readback-start",
    activationHash: held.activationHash, beforeJournalHash: phase.current.sha256, cleanupHash: phase.factHash,
    resultSha256: selected.record.sha256, tools, clockHash: held.activation.clockHash, generationStartedAt: held.activation.generationStartedAt,
    startedAt: new Date().toISOString() });
  publications.retain(start);
  const check = () => { publications.metadata(); guard(); publications.metadata(); lifetime.sources?.assertMetadata(); };
  return { input, phase, cleanup, selected, held, guard: check, observeClock, tools, directory, start, mono: performance.now(), lifetime, leaseGuard, publications };
}

/** A successful CAS stays recorded even if the final original deadline, lease or metadata check fails. */
function completedReadback(attempt: ReturnType<typeof prepareReadback>, value: ReturnType<typeof commitBodyPhase>) {
  const fixed = snapshotSourceColorMetadata(value), { input, lifetime } = attempt, journalHash = value.current.sha256;
  if (lifetime.sources) lifetime.sources.check();
  else input.remainingMs();
  attempt.leaseGuard();
  if (observeHumanCutJob(input.dir).sha256 !== journalHash) throw new Error("Body candidate journal changed after its actual CAS");
  attempt.publications.complete(); lifetime.metadata();
  if (!isDeepStrictEqual(value, fixed)) throw new Error("Body candidate original committed return changed");
  lifetime.sources?.assertMetadata(); return value;
}

async function executeReadback(attempt: ReturnType<typeof prepareReadback>) {
  const { input, phase, selected, held, guard, tools, directory } = attempt;
  guard();
  const value = await invokeBodyChild({ held, tools, purpose: "read", remainingMs: input.remainingMs, ledgerRoot: directory,
    extraArgs: ["--receipt-sha256", selected.completion.receiptSha256, "--receipt-hash", selected.completion.receiptHash] });
  attempt.publications.captureLedger();
  assertHeldBodyResultMetadata(selected);
  const ledgerSha256 = observeOwnedWorkerLedger(directory, "read", tools.script), nested = liveRecordedDescendants(directory, "read");
  if (nested.live.length || nested.unknown.length || nested.unrecordedSpawns.length) throw new Error("Body readback helper ownership is unresolved");
  const output = createOpeningRecord(path.join(directory, "output.json"), { schemaVersion: 1, kind: "guided-body-readback-owned-output",
    ...value, groupStopped: true, forcedStop: false, ledgerSha256, observedAt: new Date().toISOString(), elapsedMs: performance.now() - attempt.mono });
  attempt.publications.retain(output);
  const result = assertBodyReadbackIdentity(value.stdout, selected);
  if (result.schemaVersion === 2 && result.elapsedMs > Math.ceil(Number(output.value.elapsedMs))) throw new Error("Body source readback exceeds its actual owned elapsed work");
  assertBodyToolsUnchanged(tools); guard();
  const receipt = createOpeningRecord(path.join(directory, "verified.json"), { schemaVersion: 1, kind: "guided-body-owned-readback",
    scope: "current-private-candidate-not-creative-or-listening-approval", startSha256: attempt.start.sha256, outputSha256: output.sha256,
    resultSha256: selected.record.sha256, cleanupHash: phase.factHash, result, createdAt: new Date().toISOString(),
    clockHash: held.activation.clockHash, generationStartedAt: held.activation.generationStartedAt, bodyApproved: false, deliveryApproved: false });
  attempt.publications.retain(receipt); attempt.publications.complete();
  const commitGuard = () => {
    guard(); assertOpeningRecord(attempt.start); assertOpeningRecord(output); assertOpeningRecord(receipt);
    assertOpeningFailureAbsent(path.join(directory, "failure.json"));
    const next = readHeldBodyResult(readHeldBodyCleanup(readBodyPhase(input.dir, "cleanup")).process);
    if (next.record.sha256 !== selected.record.sha256) throw new Error("Body candidate changed before selection");
    assertCandidateBytes(next); attempt.observeClock(); guard(); assertHeldBodyResultMetadata(next);
  };
  const committed = commitBodyPhase({ held, current: phase.current, phase: "candidate", references: {
    start: { path: attempt.start.path, sha256: attempt.start.sha256 }, output: { path: output.path, sha256: output.sha256 },
    receipt: { path: receipt.path, sha256: receipt.sha256 }, result: { path: selected.completion.receiptPath, sha256: selected.record.sha256 } }, guard: commitGuard });
  return completedReadback(attempt, committed);
}

/** A real pinned read-only worker must qualify whole media and inputs while the SAME original body clock remains live. */
export async function qualifyGuidedBodyUnderLease(input: ReadbackInput) {
  const attempt = prepareReadback(input);
  try { return await executeReadback(attempt); }
  catch (error) {
    let clockError: string | null = null;
    try { bodyClockObservation(attempt.held, bodyOwnershipGuard(attempt.held, attempt.input.lease, attempt.phase.current.sha256)); }
    catch (failure) { clockError = String(failure).slice(0, 2000); }
    createOpeningRecord(path.join(attempt.directory, "failure.json"), { schemaVersion: 1, kind: "guided-body-readback-failure",
      observedAt: new Date().toISOString(), error: String(error).slice(0, 4000), clockError,
      ...(error instanceof CutPreviewProcessError ? error.details : {}), bodyApproved: false, deliveryApproved: false });
    throw error;
  }
}

/** Historical owned selection only; no source hashes or encoded-media decode are refreshed by status. */
export function readQualifiedBodyCandidate(dir: string) {
  const phase = readBodyPhase(dir, "candidate"), cleanupPhase = readHistoricalBodyPhase(dir, "cleanup", phase.fact.beforeJournalHash);
  assertOpeningFailureAbsent(path.join(path.dirname(phase.held.activationPath), "body-command-failed.json"));
  const cleanup = readHeldBodyCleanup(cleanupPhase), selected = readHeldBodyResult(cleanup.process), refs = phase.fact.references;
  const start = readCutPreviewObject(refs.start.path), output = readCutPreviewObject(refs.output.path), receipt = readCutPreviewObject(refs.receipt.path);
  const directory = path.dirname(refs.start.path), relative = path.relative(path.join(path.dirname(phase.held.activationPath), "body-readback-attempts"), directory);
  if (!/^[a-f0-9-]{36}$/u.test(relative) || refs.start.path !== path.join(directory, "start.json") || refs.output.path !== path.join(directory, "output.json")
      || refs.receipt.path !== path.join(directory, "verified.json") || refs.result.path !== selected.completion.receiptPath
      || refs.result.sha256 !== selected.record.sha256 || start.sha256 !== refs.start.sha256 || output.sha256 !== refs.output.sha256
      || receipt.sha256 !== refs.receipt.sha256) throw new Error("Body candidate readback roles changed");
  assertOpeningFailureAbsent(path.join(directory, "failure.json"));
  verifyCandidateRecords({ phase, cleanupPhase, selected, start, output, receipt });
  if (readBodyPhase(dir, "candidate").current.sha256 !== phase.current.sha256) throw new Error("Body candidate changed during status read");
  assertHeldBodyResultMetadata(selected);
  return { phase, candidate: bodyCandidateReference(selected), selected, cleanupHash: cleanupPhase.factHash };
}

function verifyCandidateRecords(input: { phase: ReturnType<typeof readBodyPhase>; cleanupPhase: ReturnType<typeof readBodyPhase>;
  selected: ReturnType<typeof readHeldBodyResult>; start: ReturnType<typeof readCutPreviewObject>;
  output: ReturnType<typeof readCutPreviewObject>; receipt: ReturnType<typeof readCutPreviewObject> }) {
  const { phase, cleanupPhase, selected, start, output, receipt } = input, held = phase.held;
  const keys = ["schemaVersion", "kind", "activationHash", "beforeJournalHash", "cleanupHash", "resultSha256", "tools", "clockHash", "generationStartedAt", "startedAt"];
  exactKeys(start.value, keys, keys, "body selected readback start");
  const receiptKeys = ["schemaVersion", "kind", "scope", "startSha256", "outputSha256", "resultSha256", "cleanupHash", "result", "createdAt",
    "clockHash", "generationStartedAt", "bodyApproved", "deliveryApproved"];
  exactKeys(receipt.value, receiptKeys, receiptKeys, "body selected readback receipt");
  const tools = bodyChildTools(held, "read"), result = assertBodyReadbackIdentity(String(output.value.stdout), selected);
  if (start.value.schemaVersion !== 1 || start.value.kind !== "guided-body-readback-start" || start.value.activationHash !== held.activationHash
      || start.value.beforeJournalHash !== cleanupPhase.current.sha256 || start.value.cleanupHash !== cleanupPhase.factHash
      || start.value.resultSha256 !== selected.record.sha256 || hash(start.value.tools) !== hash(tools)
      || start.value.clockHash !== held.activation.clockHash || start.value.generationStartedAt !== held.activation.generationStartedAt
      || receipt.value.schemaVersion !== 1 || receipt.value.kind !== "guided-body-owned-readback"
      || receipt.value.scope !== "current-private-candidate-not-creative-or-listening-approval"
      || receipt.value.startSha256 !== start.sha256 || receipt.value.outputSha256 !== output.sha256
      || receipt.value.resultSha256 !== selected.record.sha256 || receipt.value.cleanupHash !== cleanupPhase.factHash
      || receipt.value.bodyApproved !== false || receipt.value.deliveryApproved !== false || hash(receipt.value.result) !== hash(result)
      || receipt.value.clockHash !== held.activation.clockHash || receipt.value.generationStartedAt !== held.activation.generationStartedAt) {
    throw new Error("Body selected candidate is not bound to its actual owned readback");
  }
  assertBodyOwnedOutput(output.value, { kind: "guided-body-readback-owned-output", startedAt: String(start.value.startedAt), createdAt: String(receipt.value.createdAt), limit: 3_300_000 });
  if (result.schemaVersion === 2 && result.elapsedMs > Math.ceil(Number(output.value.elapsedMs))) throw new Error("Body source readback exceeds its actual owned elapsed work");
  if (String(receipt.value.createdAt) > phase.fact.createdAt) throw new Error("Body candidate predates its verifier receipt");
  const directory = path.dirname(phase.fact.references.start.path);
  observeOwnedWorkerLedger(directory, "read", tools.script, sha256(output.value.ledgerSha256, "body read ledger SHA"));
  const nested = liveRecordedDescendants(directory, "read");
  if (nested.live.length || nested.unknown.length || nested.unrecordedSpawns.length) throw new Error("Body readback nested ownership is unresolved");
  assertHeldBodyResultMetadata(selected);
}
