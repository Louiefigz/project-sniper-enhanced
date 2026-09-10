/** Literal reservation history, never process settlement, cleanup or retirement authority.
 * The writer requires an actual live hold. The reader never consults active.json:
 * its enclosing historical guard owns original claim/process authentication.
 */
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import { exactKeys, objectValue, sha256, uuid } from "@/lib/producer/contracts/validation";
import { openingAbsolutePath } from "@/lib/producer/contracts/guided-opening-media-v1";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { atomicCreateFileSync } from "./atomic-file";
import { privateDirectory } from "./grade-observation-store";
import { freezeSourceColorValue, snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import { parseOpeningSourceColorProcessReference, type OpeningSourceColorProcessReference } from "./guided-source-color-process-binding";
import { copySourceColorCleanupReservation, sourceColorCleanupReservationNames,
  type HeldSourceColorCleanupReservation } from "./guided-source-color-cleanup-hold";
import type { HeldOpeningClaim } from "./guided-opening-process";
import type { SourceColorFileRef } from "./guided-source-color-expectations";

interface ArchiveContext {
  held: HeldOpeningClaim; attemptId: string; guard: () => void; remainingMs: () => number;
}
export interface WriteSourceColorReservationArchive extends ArchiveContext {
  reservation: HeldSourceColorCleanupReservation;
}
export interface ReadSourceColorReservationArchive extends ArchiveContext {
  reference: OpeningSourceColorProcessReference; archive: SourceColorFileRef;
}
type Context = WriteSourceColorReservationArchive | ReadSourceColorReservationArchive;
const MAX_BYTES = 8 * 1024 * 1024;

function same(actual: unknown, expected: unknown, label: string): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error(`Source color archive original ${label} changed`);
}
function reference(context: Context): OpeningSourceColorProcessReference {
  return "reservation" in context ? context.reservation.reference : context.reference;
}
function metadata(context: Context) {
  return { held: context.held, attemptId: context.attemptId, reference: reference(context),
    archive: "archive" in context ? context.archive : null };
}
function expectedArchive(context: Context): SourceColorFileRef {
  const original = reference(context), resource = path.dirname(openingAbsolutePath(original.reservation.path));
  if (path.basename(resource) !== ".sniper-color-resource") throw new Error("Source color archive original resource namespace differs");
  parseOpeningSourceColorProcessReference(original, context.held.claim, resource);
  const attemptId = uuid(context.attemptId, "cleanup attemptId");
  if (attemptId[14] !== "4") throw new Error("Source color archive requires an exact UUIDv4 attempt");
  const file = path.join(path.dirname(openingAbsolutePath(context.held.claimPath)), "cleanup-attempts", attemptId, "reservation.json");
  const expected = { path: file, sha256: original.reservation.sha256, sizeBytes: original.reservation.sizeBytes };
  if (!("archive" in context)) return expected;
  const row = objectValue(context.archive, "reservation archive reference");
  exactKeys(row, ["path", "sha256", "sizeBytes"], ["path", "sha256", "sizeBytes"], "reservation archive reference");
  openingAbsolutePath(row.path); sha256(row.sha256, "reservation archive SHA");
  same(row, expected, "archive path/raw reference"); return expected;
}
function directoryIdentity(directory: string): bigint[] {
  const stat = fs.lstatSync(directory, { bigint: true });
  if (!stat.isDirectory() || fs.realpathSync(directory) !== directory) throw new Error("Source color archive parent is not canonical");
  return [stat.dev, stat.ino, stat.mode, stat.uid];
}
function fileIdentity(file: string): bigint[] {
  const stat = fs.lstatSync(file, { bigint: true });
  if (!stat.isFile() || stat.nlink !== BigInt(1) || stat.uid !== BigInt(process.getuid!()) || (stat.mode & BigInt(0o077)) !== BigInt(0)) {
    throw new Error("Source color archive must be an owned private single-link regular file");
  }
  return [stat.dev, stat.ino, stat.mode, stat.uid, stat.nlink, stat.size, stat.mtimeNs, stat.ctimeNs];
}
function absent(file: string): void {
  try { fs.lstatSync(file); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return; throw error; }
  throw new Error("Source color archive is new-only; the target already exists");
}

/** Capture original context and canonical ancestry before the first arbitrary guard. */
class ArchiveLifetime {
  readonly archive;
  private readonly original;
  private readonly fixed;
  private readonly parents = new Map<string, bigint[]>();
  private file: bigint[] | undefined;
  constructor(readonly context: Context) {
    this.original = { held: context.held, reference: reference(context), guard: context.guard, remainingMs: context.remainingMs,
      reservation: "reservation" in context ? context.reservation : undefined, archive: "archive" in context ? context.archive : undefined };
    this.fixed = snapshotSourceColorMetadata(metadata(context)); this.archive = freezeSourceColorValue(expectedArchive(context));
    privateDirectory(path.dirname(this.archive.path));
    for (let directory = path.dirname(this.archive.path);;) {
      this.parents.set(directory, directoryIdentity(directory));
      const parent = path.dirname(directory); if (parent === directory) break;
      directory = parent;
    }
    if ("archive" in context) this.file = fileIdentity(this.archive.path);
    else absent(this.archive.path);
    this.unchanged();
  }
  private unchanged(): void {
    const c = this.context, o = this.original;
    if (c.held !== o.held || reference(c) !== o.reference || c.guard !== o.guard || c.remainingMs !== o.remainingMs
        || ("reservation" in c ? c.reservation : undefined) !== o.reservation
        || ("archive" in c ? c.archive : undefined) !== o.archive) throw new Error("Source color archive original caller identity changed");
    same(metadata(c), this.fixed, "claim/reference metadata");
  }
  check = (): void => {
    this.unchanged(); this.original.guard(); this.unchanged();
    const remaining = this.original.remainingMs(); this.unchanged();
    if (!Number.isFinite(remaining) || remaining <= 0 || remaining > 300_000) throw new Error("Source color archive original protected deadline is invalid");
    this.original.reservation?.assertCurrent(); this.unchanged();
    for (const [directory, identity] of this.parents) same(directoryIdentity(directory), identity, "parent");
    if (this.file) same(fileIdentity(this.archive.path), this.file, "file");
    else absent(this.archive.path);
    this.unchanged();
  };
  publish(bytes: Buffer): void {
    const hash = createHash("sha256").update(bytes).digest("hex");
    if (hash !== this.archive.sha256 || bytes.length !== this.archive.sizeBytes) throw new Error("Source color archive copy differs from original raw reference");
    this.check(); atomicCreateFileSync(this.archive.path, bytes);
    this.file = fileIdentity(this.archive.path); this.check();
  }
  read() {
    this.check(); const observed = observeCutPreviewFile(this.archive.path, MAX_BYTES, true, this.check);
    if (observed.sha256 !== this.archive.sha256 || observed.sizeBytes !== this.archive.sizeBytes) throw new Error("Source color archive original raw bytes differ");
    const value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes));
    const names = sourceColorCleanupReservationNames(value, { held: this.original.held, reference: this.original.reference });
    const result = Object.freeze({ archive: this.archive, reference: freezeSourceColorValue(structuredClone(this.original.reference)),
      containerNames: freezeSourceColorValue(names), assertCurrent: this.check });
    this.check(); return result;
  }
}

/** Existing attempt directory only. Any published archive is retained after failure;
 * no prior archive or active reservation is replaced, removed or redirected.
 */
export function writeSourceColorReservationArchive(context: WriteSourceColorReservationArchive) {
  const lifetime = new ArchiveLifetime(context);
  const bytes = copySourceColorCleanupReservation(context.reservation);
  lifetime.check();
  sourceColorCleanupReservationNames(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)),
    { held: context.held, reference: context.reservation.reference });
  lifetime.publish(bytes); return lifetime.read();
}

/** Archive-only historical read. The caller supplies its actual historical guard;
 * this metadata lifetime check is neither a hard timer nor present cleanup authority.
 * The enclosing owner separately checks its same remaining allowance before work.
 */
export function readSourceColorReservationArchive(context: ReadSourceColorReservationArchive) {
  return new ArchiveLifetime(context).read();
}
