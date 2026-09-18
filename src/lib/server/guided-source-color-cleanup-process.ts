/** Actual owned source-color cleanup. No commit, reservation retirement or media selection. */
import fs from "node:fs";
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { uuid } from "@/lib/producer/contracts/validation";
import { parseCurrentOpeningCleanupStdout } from "@/lib/producer/contracts/guided-opening-cleanup-v2";
import { openingChildTools, invokeOpeningChild, assertToolsUnchanged, ownershipUnresolved,
  readStoppedOpeningProcess, type HeldOpeningClaim } from "./guided-opening-process";
import { assertSourceColorCleanupReservationMetadata, copySourceColorCleanupReservation,
  type HeldSourceColorCleanupReservation } from "./guided-source-color-cleanup-hold";
import { liveRecordedDescendants, observeOwnedWorkerLedger, ownedProcessLedgerPath } from "./guided-opening-process-ledger";
import { freezeSourceColorValue, snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import { createOpeningRecord, assertOpeningRecord, type HeldOpeningRecord } from "./guided-opening-process-activation";

export interface SourceColorCleanupProcessInput {
  held: HeldOpeningClaim;
  reservation: HeldSourceColorCleanupReservation;
  attemptId: string;
  /** Original project AND already-held resource lease guard; never reacquire here. */
  guard: () => void;
  /** The enclosing cleanup's same protected allowance, including this module's setup. */
  remainingMs: () => number;
}

/** Code-only test seams. Production always uses the actual pinned worker and stopped reader. */
export const sourceColorCleanupProcessDependencies = {
  tools: openingChildTools, invoke: invokeOpeningChild, stopped: readStoppedOpeningProcess,
  toolsUnchanged: assertToolsUnchanged, ledger: observeOwnedWorkerLedger, descendants: liveRecordedDescendants,
};
type Dependencies = typeof sourceColorCleanupProcessDependencies;

function same(actual: unknown, expected: unknown, label: string): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error(`Source color cleanup process original ${label} changed`);
}

function directoryIdentity(directory: string): bigint[] {
  const row = fs.lstatSync(directory, { bigint: true });
  if (!row.isDirectory() || fs.realpathSync(directory) !== directory || row.uid !== BigInt(process.getuid!())
      || (row.mode & BigInt(0o077)) !== BigInt(0)) throw new Error("Source color cleanup attempt is not private and canonical");
  return [row.dev, row.ino, row.mode, row.uid];
}

/** Until all-prior-attempt settlement is wired, another directory entry is unresolved, not a retry. */
function firstAttemptIdentity(directory: string): bigint[] {
  const parent = path.dirname(directory), identity = directoryIdentity(parent), entries = fs.opendirSync(parent);
  try {
    const first = entries.readSync(), second = entries.readSync();
    if (first?.name !== path.basename(directory) || second) {
      throw new Error("Source color cleanup prior or unknown attempts require separately proven settlement");
    }
  } finally { entries.closeSync(); }
  return identity;
}

/** Retain actual metadata/callbacks/attempt inode before any external owner callback. */
class CleanupProcessLifetime {
  readonly directory;
  readonly original;
  private readonly fixed;
  private readonly identity;
  private readonly parentIdentity;
  private stopped: ReturnType<typeof readStoppedOpeningProcess> | undefined;
  private tools: ReturnType<typeof openingChildTools> | undefined;
  private invocation: { record: HeldOpeningRecord; identity: bigint[] } | undefined;
  constructor(readonly input: SourceColorCleanupProcessInput, readonly controls: Dependencies) {
    this.original = { ...input };
    this.fixed = snapshotSourceColorMetadata({ held: input.held, reference: input.reservation.reference, attemptId: input.attemptId });
    const id = uuid(input.attemptId, "cleanup attempt");
    if (id[14] !== "4") throw new Error("Source color cleanup needs a UUIDv4 attempt");
    this.directory = path.join(path.dirname(input.held.claimPath), "cleanup-attempts", id);
    this.identity = directoryIdentity(this.directory);
    this.parentIdentity = firstAttemptIdentity(this.directory);
  }
  unchanged = (): void => {
    const i = this.input, o = this.original;
    if (i.held !== o.held || i.reservation !== o.reservation || i.guard !== o.guard || i.remainingMs !== o.remainingMs) {
      throw new Error("Source color cleanup process original caller identity changed");
    }
    same({ held: i.held, reference: i.reservation.reference, attemptId: i.attemptId }, this.fixed, "claim/reference/attempt");
    same(directoryIdentity(this.directory), this.identity, "attempt directory");
    same(firstAttemptIdentity(this.directory), this.parentIdentity, "attempt ancestry/set");
  };
  check = (): void => {
    this.unchanged(); this.original.reservation.assertCurrent(); this.unchanged();
    this.original.guard(); this.unchanged(); this.readStopped();
    if (this.tools) this.controls.toolsUnchanged(this.tools);
    this.assertInvocation();
    assertSourceColorCleanupReservationMetadata(this.original.reservation); this.unchanged();
  };
  bindTools(tools: ReturnType<typeof openingChildTools>): ReturnType<typeof openingChildTools> {
    this.unchanged();
    if (this.tools) throw new Error("Source color cleanup cannot replace captured invocation tools");
    this.tools = freezeSourceColorValue(structuredClone(tools)); return this.tools;
  }
  publishInvocation(): HeldOpeningRecord {
    this.remaining();
    if (!this.tools || this.invocation) throw new Error("Source color cleanup invocation needs original tools and is new-only");
    const record = createOpeningRecord(path.join(this.directory, "invocation.json"), {
      schemaVersion: 1, kind: "guided-source-color-cleanup-invocation", scope: "pinned-cleanup-invocation-not-completion-or-retirement",
      attemptId: this.original.attemptId, claimHash: this.original.held.claimHash, processOutcomeSha256: this.outcomeSha256(),
      sourceColor: this.original.reservation.reference, tools: this.tools, observedAt: new Date().toISOString(),
    });
    this.invocation = { record: freezeSourceColorValue(record), identity: ledgerIdentity(record.path) };
    this.assertInvocation(); this.unchanged(); return this.invocation.record;
  }
  assertInvocation(): void {
    if (!this.invocation) return;
    const { record, identity } = this.invocation;
    same(ledgerIdentity(record.path), identity, "invocation file identity"); assertOpeningRecord(record);
    same(ledgerIdentity(record.path), identity, "invocation file identity");
  }
  readStopped(): void {
    const current = this.controls.stopped(this.original.held); this.unchanged();
    if (current.receipt.schemaVersion !== 3 || current.receipt.groupStopped !== true || !current.sourceColor
        || ownershipUnresolved(current) || current.liveDescendants.length || current.unknownDescendants.length
        || current.unrecordedSpawns.length) throw new Error("Source color cleanup requires resolved original V3 process ownership");
    same(current.sourceColor, this.fixed.reference, "stopped source color");
    if (this.stopped) same(current, this.stopped, "stopped evidence");
    else this.stopped = structuredClone(current);
  }
  /** Subtract guard/read cost from the original remainder; no fresh allowance or callback after final guard. */
  remaining = (): number => {
    this.unchanged(); const started = performance.now(), remaining = this.original.remainingMs();
    this.check();
    const elapsed = performance.now() - started, bounded = Math.floor(remaining - elapsed);
    if (!Number.isFinite(remaining) || remaining > 300_000 || !Number.isFinite(elapsed) || elapsed < 0 || bounded <= 250) {
      throw new Error("Source color cleanup original protected remainder is insufficient");
    }
    return bounded;
  };
  outcomeSha256(): string {
    if (!this.stopped) throw new Error("Source color cleanup has no original stopped observation");
    return this.stopped.receiptSha256;
  }
}

function assertUnusedLedger(lifetime: CleanupProcessLifetime): void {
  const file = ownedProcessLedgerPath(lifetime.directory, "cleanup");
  try { fs.lstatSync(file); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return; throw error; }
  throw new Error("Source color cleanup attempt may already have started; never replay its lifecycle");
}

function settledCleanup(lifetime: CleanupProcessLifetime, tools: ReturnType<typeof openingChildTools>) {
  const { controls, directory } = lifetime;
  const file = ownedProcessLedgerPath(directory, "cleanup"), identity = ledgerIdentity(file);
  const sha256 = controls.ledger(directory, "cleanup", tools.script);
  const descendants = controls.descendants(directory, "cleanup");
  if (descendants.live.length || descendants.unknown.length || descendants.unrecordedSpawns.length) {
    throw new Error("Source color cleanup child left unresolved nested ownership");
  }
  controls.ledger(directory, "cleanup", tools.script, sha256);
  same(ledgerIdentity(file), identity, "cleanup ledger identity");
  return { reference: { path: file, sha256 }, identity };
}

function ledgerIdentity(file: string): bigint[] {
  const row = fs.lstatSync(file, { bigint: true });
  if (!row.isFile() || row.nlink !== BigInt(1) || row.uid !== BigInt(process.getuid!())) throw new Error("Cleanup ledger is not an owned single-link file");
  return [row.dev, row.ino, row.mode, row.uid, row.nlink, row.size, row.mtimeNs, row.ctimeNs];
}

/** No arbitrary owner/clock callback after this final original-file/byte sweep. */
function finalEvidence(lifetime: CleanupProcessLifetime, tools: ReturnType<typeof openingChildTools>, ledger: ReturnType<typeof settledCleanup>): void {
  const remaining = lifetime.remaining(), started = performance.now();
  lifetime.controls.toolsUnchanged(tools);
  same(ledgerIdentity(ledger.reference.path), ledger.identity, "cleanup ledger identity");
  lifetime.controls.ledger(lifetime.directory, "cleanup", tools.script, ledger.reference.sha256);
  same(ledgerIdentity(ledger.reference.path), ledger.identity, "cleanup ledger identity");
  lifetime.assertInvocation();
  assertSourceColorCleanupReservationMetadata(lifetime.original.reservation); lifetime.unchanged();
  const elapsed = performance.now() - started;
  if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed >= remaining) throw new Error("Source color cleanup final evidence exhausted original remainder");
}

/** Normal actual outer return plus its complete original nested ledger is required even for cleanup.
 * This initial consumer supports only the first attempt: unknown prior cleanup workers
 * remain fenced until an actual journal-bound all-attempt settlement reader is connected.
 */
export async function runSourceColorCleanupProcess(input: SourceColorCleanupProcessInput,
  dependencies: Dependencies = sourceColorCleanupProcessDependencies) {
  const controls = { ...dependencies }, lifetime = new CleanupProcessLifetime(input, controls);
  copySourceColorCleanupReservation(lifetime.original.reservation); lifetime.remaining(); assertUnusedLedger(lifetime);
  const tools = lifetime.bindTools(controls.tools(lifetime.original.held, "cleanup")), fixedTools = structuredClone(tools);
  const invocation = lifetime.publishInvocation();
  const reference = lifetime.original.reservation.reference;
  const output = await controls.invoke({ held: lifetime.original.held, tools, kind: "cleanup", remainingMs: lifetime.remaining,
    cleanupAttemptId: lifetime.original.attemptId, extraArgs: ["--source-color-reservation", reference.reservation.path,
      "--source-color-reservation-sha256", reference.reservation.sha256, "--source-color-request-sha256", reference.sourceColorHash] });
  const fixedOutput = structuredClone(output); same(tools, fixedTools, "tool metadata");
  lifetime.remaining(); const ledger = settledCleanup(lifetime, tools);
  const result = parseCurrentOpeningCleanupStdout(output.stdout);
  if (result.schemaVersion !== 2) throw new Error("Source color cleanup returned only legacy graphics cleanup");
  lifetime.original.reservation.assertResult(result); finalEvidence(lifetime, tools, ledger);
  same(output, fixedOutput, "owned output"); same(tools, fixedTools, "tool metadata");
  return freezeSourceColorValue({ ...fixedOutput, result, invocation, tools, ledger: ledger.reference, processOutcomeSha256: lifetime.outcomeSha256(),
    mediaSelected: false as const, openingApproved: false as const, deliveryApproved: false as const });
}
