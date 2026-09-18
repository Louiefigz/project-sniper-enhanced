/** Original historical metadata lifetime only; no active reservation, source or tool is opened. */
import fs from "node:fs";
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { parsePreparedSourceColorCleanupFact, type PreparedSourceColorCleanupFact } from "@/lib/producer/contracts/guided-source-color-cleanup-facts";
import { openingAbsolutePath } from "@/lib/producer/contracts/guided-opening-media-v1";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import type { HeldOpeningClaim } from "./guided-opening-process";
import { freezeSourceColorValue, snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import { ownedProcessLedgerPath } from "./guided-opening-process-ledger";
import { CLEANUP_MEDIA_ROLES, cleanupMediaReference, type CleanupMediaReference, type CleanupMediaRole,
  type captureSourceColorCleanupMedia } from "./guided-source-color-cleanup-attempt-media";

export interface SourceColorCleanupAttemptReadInput {
  held: HeldOpeningClaim; fact: PreparedSourceColorCleanupFact; guard: () => void; remainingMs: () => number;
}
const BOUNDS = { start: 128 * 1024, invocation: 128 * 1024, output: 4 * 1024 * 1024 };
type RecordKind = keyof typeof BOUNDS;

function same(actual: unknown, expected: unknown, label: string): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error(`Cleanup attempt original ${label} changed`);
}
export function directoryIdentity(directory: string): bigint[] {
  const row = fs.lstatSync(directory, { bigint: true });
  if (!row.isDirectory() || fs.realpathSync(directory) !== directory) throw new Error("Cleanup attempt parent is not canonical");
  return [row.dev, row.ino, row.mode, row.uid];
}
export function fileIdentity(file: string): bigint[] {
  const row = fs.lstatSync(file, { bigint: true });
  if (!row.isFile() || row.nlink !== BigInt(1) || row.uid !== BigInt(process.getuid!()) || (row.mode & BigInt(0o077)) !== BigInt(0)) {
    throw new Error("Cleanup attempt metadata must be private owned single-link files");
  }
  return [row.dev, row.ino, row.mode, row.uid, row.nlink, row.size, row.mtimeNs, row.ctimeNs];
}
function noFailure(directory: string): void {
  try { fs.lstatSync(path.join(directory, "failure.json")); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return; throw error; }
  throw new Error("Cleanup attempt has retained failure evidence");
}

/** One finite read/check operation charges all work to the original callback's remainder. */
export class CleanupAttemptReadHold {
  readonly directory;
  readonly fact;
  readonly ledger;
  readonly media = new Map<CleanupMediaRole, CleanupMediaReference>();
  private readonly original;
  private readonly fixed;
  private readonly parents = new Map<string, bigint[]>();
  private readonly files = new Map<string, bigint[]>();
  private budget: { started: number; remaining: number } | undefined;
  constructor(readonly input: SourceColorCleanupAttemptReadInput, media: typeof captureSourceColorCleanupMedia) {
    this.original = { ...input }; this.fixed = snapshotSourceColorMetadata({ held: input.held, fact: input.fact });
    this.fact = freezeSourceColorValue(parsePreparedSourceColorCleanupFact(input.fact));
    this.directory = path.join(path.dirname(openingAbsolutePath(input.held.claimPath)), "cleanup-attempts", this.fact.cleanupAttemptId);
    if (this.fact.archive.path !== path.join(this.directory, "reservation.json")) throw new Error("Cleanup attempt archive namespace differs");
    this.ledger = ownedProcessLedgerPath(this.directory, "cleanup");
    for (const file of ["start.json", "invocation.json", "output.json", "reservation.json"]) this.capture(path.join(this.directory, file));
    this.capture(this.ledger); this.assertMetadata(); media(input.held, this.captureMedia);
    if (this.media.size !== CLEANUP_MEDIA_ROLES.length) throw new Error("Cleanup original media file coverage is incomplete");
    this.assertMetadata();
  }
  private captureMedia = (reference: CleanupMediaReference): Buffer => {
    const fixed = freezeSourceColorValue(structuredClone(reference)), maximum = cleanupMediaReference(fixed, this.original.held);
    if (this.media.has(fixed.role)) throw new Error("Cleanup historical media role repeats");
    this.capture(fixed.path); this.assertMetadata();
    const observed = observeCutPreviewFile(fixed.path, maximum, true, this.assertMetadata);
    if (observed.sha256 !== fixed.sha256) throw new Error("Cleanup historical media original raw SHA differs");
    this.media.set(fixed.role, fixed); this.assertMetadata(); return observed.bytes;
  };
  private capture(file: string): void {
    this.files.set(file, fileIdentity(file));
    for (let directory = path.dirname(file);;) {
      const identity = directoryIdentity(directory), previous = this.parents.get(directory);
      if (previous) same(identity, previous, "parent during capture");
      this.parents.set(directory, identity);
      const parent = path.dirname(directory); if (parent === directory) break;
      directory = parent;
    }
  }
  /** Callback-free original identity sweep; never substitutes for the owner's clock/lease. */
  assertMetadata = (): void => {
    const i = this.input, o = this.original;
    if (i.held !== o.held || i.fact !== o.fact || i.guard !== o.guard || i.remainingMs !== o.remainingMs) {
      throw new Error("Cleanup attempt original caller identity changed");
    }
    same({ held: i.held, fact: i.fact }, this.fixed, "context metadata");
    for (const [directory, identity] of this.parents) same(directoryIdentity(directory), identity, "parent identity");
    for (const [file, identity] of this.files) same(fileIdentity(file), identity, "file identity");
    noFailure(this.directory); same({ held: i.held, fact: i.fact }, this.fixed, "final context metadata");
  };
  /** No caller callback here: nested raw/ledger/archive checks spend the same captured remainder. */
  remaining = (): number => {
    if (!this.budget) throw new Error("Cleanup attempt read has no original active remainder");
    const elapsed = performance.now() - this.budget.started, remaining = this.budget.remaining - elapsed;
    if (!Number.isFinite(elapsed) || elapsed < 0 || remaining <= 0) throw new Error("Cleanup attempt original protected deadline expired");
    return remaining;
  };
  check = (): void => { this.assertMetadata(); this.remaining(); };
  /** The original clock is sampled, not renewed; recursive owner re-entry is refused. */
  run<T>(operation: () => T): T {
    if (this.budget) throw new Error("Cleanup attempt cannot reenter its original read lifetime");
    this.assertMetadata(); this.budget = { started: performance.now(), remaining: 0 };
    try {
      this.original.guard(); const remaining = this.original.remainingMs();
      if (!Number.isFinite(remaining) || remaining <= 0 || remaining > 300_000) throw new Error("Cleanup attempt original protected remainder is invalid");
      this.budget.remaining = remaining; this.check();
      const result = operation(); this.check(); return result;
    } finally { this.budget = undefined; }
  }
  read(kind: RecordKind): Record<string, unknown> {
    const hashes = { start: this.fact.cleanupStartSha256, invocation: this.fact.cleanupInvocationSha256, output: this.fact.cleanupOutputSha256 };
    this.check();
    const observed = observeCutPreviewFile(path.join(this.directory, `${kind}.json`), BOUNDS[kind], true, this.check);
    if (observed.sha256 !== hashes[kind]) throw new Error(`Cleanup attempt ${kind} original raw SHA differs`);
    const value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes));
    const held = freezeSourceColorValue(structuredClone(value)); this.check(); return held;
  }
}
