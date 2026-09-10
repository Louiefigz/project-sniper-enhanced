/** Original staging metadata lifetime; never source, process or cleanup authority. */
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import { deserialize, serialize } from "node:v8";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import type { GuidedOpeningExecutionClaimV1 } from "@/lib/producer/contracts/guided-opening-claim-v1";
import type { GuidedSourceColorV1 } from "@/lib/producer/contracts/guided-source-color-v1";
import { openingAbsolutePath } from "@/lib/producer/contracts/guided-opening-media-v1";
import type { HeldGradeObservationResource } from "./grade-observation-resource";
import type { HeldSourceColorExpectations, SourceColorFileRef } from "./guided-source-color-expectations";
import { writeRecord } from "./grade-observation-store";

export interface SourceColorStagingContext {
  opening: { claim: GuidedOpeningExecutionClaimV1; claimPath: string; claimSha256: string };
  expectations: HeldSourceColorExpectations; sourceColor: GuidedSourceColorV1;
  producerDir: string; resource: HeldGradeObservationResource; guard: () => void;
}
interface HeldFile { ref: SourceColorFileRef; identity: bigint[] }
interface HeldDirectory { path: string; identity: bigint[] }
export interface SourceColorStagingPublication { reference: SourceColorFileRef; value: unknown }
/** Private live-owner observers only; the existing absent-hooks path remains unchanged. */
export interface SourceColorStagingHooks {
  check(): void;
  publishing?(file: string): void;
  published(value: SourceColorStagingPublication): void;
}
const stagingMetadataReads = new WeakMap<() => void, { context: SourceColorStagingContext; check: () => void;
  cancellation: () => { active: HeldFile | undefined; directories: readonly string[]; check: () => void } }>();

/** Authenticate original staging metadata only, without invoking its possibly expired work guard or any clock. */
export function assertSourceColorStagingMetadata(context: SourceColorStagingContext, current: () => void): void {
  const held = stagingMetadataReads.get(current);
  if (!held || held.context !== context) throw new Error("Source color staging metadata requires its actual original reader");
  held.check();
}

/** Original finite metadata transfer only. The active marker stays separately held by the actual live canceller. */
export function holdSourceColorStagingCancellationMetadata(context: SourceColorStagingContext, current: () => void) {
  const held = stagingMetadataReads.get(current);
  if (!held || held.context !== context) throw new Error("Cancellation needs the actual original staging metadata");
  held.check(); return held.cancellation();
}

function fileIdentity(file: string): bigint[] {
  const row = fs.lstatSync(file, { bigint: true });
  if (!row.isFile() || row.nlink !== BigInt(1)) throw new Error("Source color staging requires single-link regular metadata");
  return [row.dev, row.ino, row.mode, row.uid, row.nlink, row.size, row.mtimeNs, row.ctimeNs];
}
function directoryIdentity(directory: string): bigint[] {
  const row = fs.lstatSync(directory, { bigint: true });
  if (!row.isDirectory() || fs.realpathSync(directory) !== directory) throw new Error("Source color staging parent is aliased");
  return [row.dev, row.ino, row.mode, row.uid];
}
export function freezeSourceColorValue<T>(value: T): T {
  if (value && typeof value === "object") { Object.values(value).forEach(freezeSourceColorValue); Object.freeze(value); }
  return value;
}

/** Detached private metadata, preserving Buffer bytes/types and repeated references.
 * Never a canonical receipt/hash format; caller-owned bytes remain unfrozen.
 */
export function snapshotSourceColorMetadata<T>(value: T): T {
  const snapshot = deserialize(serialize(value)) as T;
  if (!isDeepStrictEqual(value, snapshot)) throw new Error("Source color metadata snapshot changed its original types or values");
  return snapshot;
}

/** Shared exact original-claim join for staging and explicit process transport. */
export function sourceColorOpeningReference(context: Pick<SourceColorStagingContext, "opening">) {
  const { claim, claimPath, claimSha256 } = context.opening;
  return { claimPath, claimSha256, inputPath: claim.inputPath, inputSha256: claim.inputSha256,
    executionId: claim.executionId, executionInputHash: claim.executionInputHash, clockHash: claim.clockHash,
    generationStartedAt: claim.generationStartedAt, budgetAdmissionHash: claim.budgetAdmissionHash, beforeJournalHash: claim.beforeJournalHash };
}

/** Capture context identity before callbacks; hold exact raw files and parent inodes. */
export class SourceColorStagingRead {
  readonly #original;
  readonly #fixed;
  readonly #files = new Map<string, HeldFile>();
  readonly #directories = new Map<string, HeldDirectory>();
  readonly #hooks: SourceColorStagingHooks | undefined;
  #codeBatch: "new" | "reading" | "failed" | "complete" = "new";
  constructor(readonly context: SourceColorStagingContext, hooks?: SourceColorStagingHooks) {
    this.#hooks = hooks;
    this.#original = { opening: context.opening, claim: context.opening.claim, expectations: context.expectations,
      assertExpectations: context.expectations.assertCurrent, sourceColor: context.sourceColor, resource: context.resource,
      lease: context.resource.lease, release: context.resource.lease.release, assertResource: context.resource.assertResource, guard: context.guard,
      hooks, hookCheck: hooks?.check, hookPublishing: hooks?.publishing, hookPublished: hooks?.published };
    this.#fixed = structuredClone(this.metadata());
    this.capture(context.opening.claimPath, context.opening.claimSha256);
    this.capture(context.opening.claim.inputPath, context.opening.claim.inputSha256);
    const unchanged = SourceColorStagingRead.prototype.unchanged, files = SourceColorStagingRead.prototype.currentFiles;
    const metadata = SourceColorStagingRead.prototype.metadata, current = this.check;
    const cancellation = SourceColorStagingRead.prototype.cancellationMetadata;
    const methods = () => {
      if (this.context !== context || this.check !== current || this.unchanged !== unchanged || this.currentFiles !== files
          || this.metadata !== metadata || this.cancellationMetadata !== cancellation) {
        throw new Error("Source color staging original metadata reader methods changed");
      }
    };
    stagingMetadataReads.set(this.check, { context, cancellation: () => cancellation.call(this, methods), check: () => {
      methods();
      unchanged.call(this); files.call(this); unchanged.call(this);
    } });
  }
  private metadata() {
    const { opening, expectations, sourceColor, producerDir, resource } = this.context;
    return { opening, sources: expectations.sources, parents: expectations.parents, files: expectations.files,
      scope: expectations.scope, sourceColor, producerDir, resource: resource.resource };
  }
  private unchanged(): void {
    const c = this.context, o = this.#original;
    if (c.opening !== o.opening || c.opening.claim !== o.claim || c.expectations !== o.expectations
        || c.expectations.assertCurrent !== o.assertExpectations || c.sourceColor !== o.sourceColor || c.resource !== o.resource
        || c.resource.lease !== o.lease || c.resource.lease.release !== o.release || c.resource.assertResource !== o.assertResource
        || c.guard !== o.guard || this.#hooks !== o.hooks || this.#hooks?.check !== o.hookCheck
        || this.#hooks?.publishing !== o.hookPublishing || this.#hooks?.published !== o.hookPublished
        || !isDeepStrictEqual(this.metadata(), this.#fixed)) throw new Error("Source color original staging context changed");
  }
  holdDirectory(directory: string): void {
    this.#writable(); this.#captureDirectories(directory, this.#directories);
  }
  #captureDirectories(directory: string, directories: Map<string, HeldDirectory>): void {
    openingAbsolutePath(directory);
    for (;;) {
      const current = directoryIdentity(directory), previous = directories.get(directory);
      if (previous && !isDeepStrictEqual(current, previous.identity)) throw new Error("Source color original staging parent changed");
      if (!previous) directories.set(directory, { path: directory, identity: current });
      const parent = path.dirname(directory); if (parent === directory) return;
      directory = parent;
    }
  }
  private currentFiles(): void {
    for (const row of this.#directories.values()) {
      if (!isDeepStrictEqual(directoryIdentity(row.path), row.identity)) throw new Error("Source color staging directory changed");
    }
    for (const row of this.#files.values()) {
      if (!isDeepStrictEqual(fileIdentity(row.ref.path), row.identity)) throw new Error("Source color staging metadata changed");
    }
  }
  private cancellationMetadata(methods: () => void) {
    this.#writable();
    const files = snapshotSourceColorMetadata([...this.#files]), directories = snapshotSourceColorMetadata([...this.#directories]);
    const active = path.join(this.#original.resource.resource, "active.json");
    const check = () => {
      methods(); SourceColorStagingRead.prototype.unchanged.call(this);
      if (!isDeepStrictEqual([...this.#files], files) || !isDeepStrictEqual([...this.#directories], directories)) {
        throw new Error("Cancellation original staging inventory changed");
      }
      for (const [, row] of directories) {
        if (!isDeepStrictEqual(directoryIdentity(row.path), row.identity)) throw new Error("Cancellation original staging parent changed");
      }
      for (const [, row] of files) {
        if (row.ref.path !== active && !isDeepStrictEqual(fileIdentity(row.ref.path), row.identity)) throw new Error("Cancellation original staging file changed");
      }
      SourceColorStagingRead.prototype.unchanged.call(this);
    };
    check(); return Object.freeze({ active: freezeSourceColorValue(files.find(([file]) => file === active)?.[1]),
      directories: Object.freeze(directories.map(([directory]) => directory)), check });
  }
  private capture(file: string, expected: string): void {
    openingAbsolutePath(file); this.holdDirectory(path.dirname(file));
    const identity = fileIdentity(file), previous = this.#files.get(file);
    if (previous && (previous.ref.sha256 !== expected || !isDeepStrictEqual(previous.identity, identity))) {
      throw new Error("Source color metadata reference changed before capture");
    }
    this.#files.set(file, { ref: { path: file, sha256: expected, sizeBytes: Number(identity[5]) }, identity });
  }
  check = (): void => {
    this.unchanged(); this.#hooks?.check(); this.#original.guard(); this.#original.assertExpectations(); this.#original.assertResource();
    this.currentFiles(); this.unchanged(); this.#hooks?.check();
  };
  read(file: string, expected: string, maximum: number): Record<string, unknown> {
    this.#writable();
    openingAbsolutePath(file); this.holdDirectory(path.dirname(file));
    const before = fileIdentity(file), previous = this.#files.get(file);
    if (previous && (!isDeepStrictEqual(before, previous.identity) || previous.ref.sha256 !== expected)) {
      throw new Error("Source color metadata reference changed");
    }
    const observed = observeCutPreviewFile(file, maximum, true, this.check);
    if (observed.sha256 !== expected || !isDeepStrictEqual(fileIdentity(file), before)) throw new Error("Source color staging raw metadata differs");
    this.#files.set(file, { ref: { path: file, sha256: expected, sizeBytes: observed.sizeBytes }, identity: before });
    const value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes));
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Source color staging metadata must be an object");
    this.check(); return value;
  }
  holdCode(file: string): { path: string; sha256: string } {
    this.#writable();
    openingAbsolutePath(file); this.holdDirectory(path.dirname(file));
    const before = fileIdentity(file), observed = observeCutPreviewFile(file, 8 * 1024 * 1024, false, this.check);
    if (!isDeepStrictEqual(fileIdentity(file), before)) throw new Error("Source color staged implementation changed during capture");
    this.#files.set(file, { ref: { path: file, sha256: observed.sha256, sizeBytes: observed.sizeBytes }, identity: before });
    this.check(); return { path: file, sha256: observed.sha256 };
  }
  #writable(): void {
    if (this.#codeBatch === "reading" || this.#codeBatch === "failed") {
      this.#codeBatch = "failed";
      throw new Error("Source color code batch cannot reenter publication or transfer partial metadata");
    }
  }
  #prospectiveCode(files: readonly string[], directories: Map<string, HeldDirectory>): HeldFile[] {
    return files.map(file => {
      openingAbsolutePath(file); this.#captureDirectories(path.dirname(file), directories);
      const identity = fileIdentity(file), previous = this.#files.get(file);
      if (previous && !isDeepStrictEqual(previous.identity, identity)) throw new Error("Source color original code pin changed");
      return { ref: { path: file, sha256: "", sizeBytes: Number(identity[5]) }, identity };
    });
  }
  #batchGuard(current: () => void): void {
    if (this.#codeBatch !== "reading") throw new Error("Source color code batch was interrupted or reentered");
    assertSourceColorStagingMetadata(this.context, current); current();
    assertSourceColorStagingMetadata(this.context, current);
    if (this.#codeBatch !== "reading") throw new Error("Source color code batch was interrupted or reentered");
  }
  #hashCode(row: HeldFile, guard: () => void): HeldFile {
    const observed = observeCutPreviewFile(row.ref.path, 8 * 1024 * 1024, false, guard);
    const previous = this.#files.get(row.ref.path);
    if (!isDeepStrictEqual(fileIdentity(row.ref.path), row.identity) || observed.sizeBytes !== row.ref.sizeBytes
        || (previous && previous.ref.sha256 !== observed.sha256)) throw new Error("Source color prospective code pin changed");
    guard(); return { ref: { ...row.ref, sha256: observed.sha256 }, identity: row.identity };
  }
  #sameCode(rows: readonly HeldFile[], directories: Map<string, HeldDirectory>): void {
    for (const row of directories.values()) {
      if (!isDeepStrictEqual(directoryIdentity(row.path), row.identity)) throw new Error("Source color prospective parent changed");
    }
    for (const row of rows) {
      if (!isDeepStrictEqual(fileIdentity(row.ref.path), row.identity)) throw new Error("Source color prospective code pin changed");
    }
  }
  /** Unpublished pins stay private until the whole original batch validates. Their cross-pin
   * mutation detection is deferred to this boundary; original held files/checks are never deferred.
   * A failed/reentered batch cannot publish, retry, or transfer partial cancellation metadata.
   */
  holdCodeBatch(files: readonly string[]): Array<{ path: string; sha256: string }> {
    this.#writable();
    if (this.#codeBatch !== "new" || !Array.isArray(files) || !files.length || files.length > 4000
        || files.some(file => typeof file !== "string") || new Set(files).size !== files.length) {
      throw new Error("Source color code batch requires one bounded unique original inventory");
    }
    const original = [...files], current = this.check; this.#codeBatch = "reading";
    try {
      const directories = new Map(this.#directories), prospective = this.#prospectiveCode(original, directories);
      const guard = () => this.#batchGuard(current), rows = prospective.map(row => this.#hashCode(row, guard));
      this.#sameCode(rows, directories);
      for (const row of rows) this.#files.set(row.ref.path, row);
      for (const [directory, row] of directories) this.#directories.set(directory, row);
      guard(); this.#sameCode(rows, directories);
      this.#codeBatch = "complete"; return rows.map(row => ({ path: row.ref.path, sha256: row.ref.sha256 }));
    } catch (error) { this.#codeBatch = "failed"; throw error; }
  }
  publish(file: string, value: unknown): SourceColorFileRef {
    this.#writable();
    // Match writeRecord's literal pretty-JSON/newline domain, not canonical semantic hashes.
    const bytes = Buffer.from(`${JSON.stringify(value, null, 1)}\n`), expected = createHash("sha256").update(bytes).digest("hex");
    const original = this.#hooks ? snapshotSourceColorMetadata(value) : undefined;
    if (!bytes.length || bytes.length > 8 * 1024 * 1024) throw new Error("Source color staging record exceeds its byte budget");
    this.check(); this.holdDirectory(path.dirname(file));
    if (this.#hooks && !isDeepStrictEqual(value, original)) throw new Error("Source color publication changed before its original write");
    this.#hooks?.publishing?.(file);
    if (writeRecord(file, value) !== expected) throw new Error("Source color staging publication bytes differ");
    if (this.#hooks) {
      this.capture(file, expected);
      this.#hooks.published({ reference: { path: file, sha256: expected, sizeBytes: bytes.length }, value: original });
    }
    this.read(file, expected, 8 * 1024 * 1024);
    return freezeSourceColorValue({ path: file, sha256: expected, sizeBytes: bytes.length });
  }
}
