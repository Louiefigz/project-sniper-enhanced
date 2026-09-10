/** Bounded original all-attempt metadata lifetime, not a clock, lease or settlement authority. */
import fs from "node:fs";
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { uuid } from "@/lib/producer/contracts/validation";
import { openingAbsolutePath } from "@/lib/producer/contracts/guided-opening-media-v1";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { directoryIdentity, fileIdentity } from "./guided-source-color-cleanup-attempt-hold";
import { CLEANUP_MEDIA_ROLES, cleanupMediaReference, type CleanupMediaReference, type CleanupMediaRole,
  type captureSourceColorCleanupMedia } from "./guided-source-color-cleanup-attempt-media";
import { freezeSourceColorValue, snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import type { HeldOpeningClaim } from "./guided-opening-process";
import type { SourceColorFileRef } from "./guided-source-color-expectations";

export interface SourceColorCleanupHistoryInput {
  held: HeldOpeningClaim; guard: () => void; remainingMs: () => number;
}
const MAX_BYTES = 64 * 1024 * 1024;
const LIMITS = { "prepared.json": 128 * 1024, "start.json": 128 * 1024, "invocation.json": 128 * 1024,
  "output.json": 4 * 1024 * 1024, "reservation.json": 8 * 1024 * 1024, "owned-process-ledger.cleanup.jsonl": 32 * 1024 * 1024 };
const FILES = Object.keys(LIMITS).sort();

function same(actual: unknown, expected: unknown, label: string): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error(`Cleanup history original ${label} changed`);
}
function privateDirectory(directory: string): void {
  const identity = directoryIdentity(directory);
  if (identity[3] !== BigInt(process.getuid!()) || (identity[2] & BigInt(0o077)) !== BigInt(0)) {
    throw new Error("Cleanup history requires existing private owned directories");
  }
}
function readEntryNames(handle: fs.Dir, maximum: number): string[] {
  const names: string[] = [];
  for (let entry = handle.readSync(); entry; entry = handle.readSync()) {
    names.push(entry.name);
    if (names.length > maximum) throw new Error("Cleanup history entry count exceeds its bound");
  }
  return names.sort();
}
function entries(directory: string, maximum: number): string[] {
  const handle = fs.opendirSync(directory);
  try { return readEntryNames(handle, maximum); }
  finally { handle.closeSync(); }
}
function rootFor(held: HeldOpeningClaim): string {
  const claim = held.claim, producer = openingAbsolutePath(held.job.ctx.dir);
  const expected = path.join(producer, "guided-v2-operations", uuid(claim.requestId, "requestId"),
    "executions", uuid(claim.executionId, "executionId"), "execution-claim.json");
  if (openingAbsolutePath(held.claimPath) !== expected) throw new Error("Cleanup history original claim namespace differs");
  return path.join(path.dirname(expected), "cleanup-attempts");
}

/** Every attempt and shared media file is captured before the first original owner callback. */
export class CleanupHistoryHold {
  readonly directory;
  readonly attemptIds;
  readonly media = new Map<CleanupMediaRole, CleanupMediaReference>();
  private readonly original;
  private readonly fixed;
  private readonly parents = new Map<string, bigint[]>();
  private readonly files = new Map<string, { identity: bigint[]; maximum: number }>();
  private readonly refs = new Map<string, SourceColorFileRef>();
  private readonly entryStarted = performance.now();
  private firstRead = true;
  private budget: { started: number; remaining: number } | undefined;
  constructor(readonly input: SourceColorCleanupHistoryInput, media: typeof captureSourceColorCleanupMedia) {
    this.original = { ...input }; this.fixed = snapshotSourceColorMetadata(input.held);
    this.directory = rootFor(input.held); privateDirectory(this.directory);
    this.attemptIds = Object.freeze(entries(this.directory, 32));
    if (!this.attemptIds.length) throw new Error("Cleanup history requires 1..32 completed attempts");
    for (const id of this.attemptIds) this.captureAttempt(id);
    this.assertMetadata(); media(input.held, this.captureMedia);
    if (this.media.size !== CLEANUP_MEDIA_ROLES.length) throw new Error("Cleanup history original media coverage is incomplete");
    this.assertMetadata();
  }
  private captureAttempt(id: string): void {
    if (uuid(id, "cleanup attemptId")[14] !== "4") throw new Error("Cleanup history requires UUIDv4 attempt directories");
    const directory = path.join(this.directory, id); privateDirectory(directory);
    same(entries(directory, FILES.length), FILES, "completed attempt file set");
    for (const name of FILES) this.capture(path.join(directory, name), LIMITS[name as keyof typeof LIMITS]);
  }
  private capture(file: string, maximum: number): void {
    if (this.files.has(file)) throw new Error("Cleanup history original file repeats");
    const identity = fileIdentity(file), size = Number(identity[5]);
    if (size < 1 || size > maximum) throw new Error("Cleanup history file exceeds its original bound");
    this.files.set(file, { identity, maximum });
    if ([...this.files.values()].reduce((sum, row) => sum + Number(row.identity[5]), 0) > MAX_BYTES) {
      throw new Error("Cleanup history exceeds 64MiB of unique original metadata");
    }
    for (let directory = path.dirname(file);;) {
      const current = directoryIdentity(directory), previous = this.parents.get(directory);
      if (previous) same(current, previous, "parent during capture");
      this.parents.set(directory, current);
      const parent = path.dirname(directory); if (parent === directory) break;
      directory = parent;
    }
  }
  private captureMedia = (reference: CleanupMediaReference): Buffer => {
    const fixed = freezeSourceColorValue(structuredClone(reference)), maximum = cleanupMediaReference(fixed, this.original.held);
    if (this.media.has(fixed.role)) throw new Error("Cleanup history original media role repeats");
    this.capture(fixed.path, maximum);
    const observed = this.observe(fixed.path);
    if (observed.sha256 !== fixed.sha256) throw new Error("Cleanup history original media raw SHA differs");
    this.media.set(fixed.role, fixed); this.assertMetadata(); return observed.bytes;
  };
  private unchanged(): void {
    const i = this.input, o = this.original;
    if (i.held !== o.held || i.guard !== o.guard || i.remainingMs !== o.remainingMs) throw new Error("Cleanup history original caller identity changed");
    same(i.held, this.fixed, "complete held claim metadata");
  }
  /** Callback-free original-file checks only; never a lease or remaining-time claim. */
  assertMetadata = (): void => {
    this.unchanged(); same(entries(this.directory, 32), this.attemptIds, "attempt entry set");
    for (const id of this.attemptIds) same(entries(path.join(this.directory, id), FILES.length), FILES, "completed attempt file set");
    for (const [directory, identity] of this.parents) same(directoryIdentity(directory), identity, "parent identity");
    for (const [file, row] of this.files) same(fileIdentity(file), row.identity, "file identity");
    this.unchanged();
  };
  remaining = (): number => {
    if (!this.budget) throw new Error("Cleanup history has no active original remainder");
    const elapsed = performance.now() - this.budget.started, remaining = this.budget.remaining - elapsed;
    if (!Number.isFinite(elapsed) || elapsed < 0 || remaining <= 0) throw new Error("Cleanup history original protected deadline expired");
    return remaining;
  };
  check = (): void => { this.assertMetadata(); this.remaining(); };
  /** Count actual read byte lengths, once per unique original file, not declared JSON sizes. */
  observe(file: string) {
    const captured = this.files.get(file);
    if (!captured) throw new Error("Cleanup history cannot discover additional files");
    const check = this.budget ? this.check : this.assertMetadata;
    const observed = observeCutPreviewFile(file, captured.maximum, true, check);
    const ref = { path: file, sha256: observed.sha256, sizeBytes: observed.bytes.length }, previous = this.refs.get(file);
    if (ref.sizeBytes !== Number(captured.identity[5]) || ref.sizeBytes !== observed.sizeBytes) throw new Error("Cleanup history actual raw length differs");
    if (previous) same(ref, previous, "raw file reference");
    else this.refs.set(file, Object.freeze(ref));
    if ([...this.refs.values()].reduce((sum, row) => sum + row.sizeBytes, 0) > MAX_BYTES) throw new Error("Cleanup history actual bytes exceed 64MiB");
    check(); return { ...observed, ref };
  }
  observeAll(): void { for (const file of this.files.keys()) this.observe(file); }
  /** Initial capture and every child read spend this same callback allowance; no per-child reset. */
  run<T>(operation: () => T): T {
    if (this.budget) throw new Error("Cleanup history cannot reenter its original read lifetime");
    const started = this.firstRead ? this.entryStarted : performance.now(); this.firstRead = false;
    this.assertMetadata(); this.budget = { started, remaining: 0 };
    try {
      this.original.guard(); const remaining = this.original.remainingMs();
      if (!Number.isFinite(remaining) || remaining <= 0 || remaining > 300_000) throw new Error("Cleanup history original protected remainder is invalid");
      this.budget.remaining = remaining; this.check();
      const result = operation(); this.check(); return result;
    } finally { this.budget = undefined; }
  }
}
