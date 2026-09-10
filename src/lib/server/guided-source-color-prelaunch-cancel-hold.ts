/** Same-live cancellation lifetime. No source/native observation, cold absence inference or replacement adoption. */
import fs from "node:fs";
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { observeCutPreviewFile, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { atomicCreateFileSync } from "./atomic-file";
import { autoEditJobPath } from "./auto-edit-job-persistence";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { createOpeningProtectedCleanupClock } from "./guided-opening-cleanup";
import { createOpeningRecord } from "./guided-opening-process-activation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { prelaunchCancellationIntent, prelaunchCancellationAck, prelaunchCancelledJob } from "./guided-source-color-prelaunch-cancel-records";
import { fileIdentity, directoryIdentity } from "./guided-source-color-cleanup-attempt-hold";
import { freezeSourceColorValue, snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import { claimSourceColorPrelaunchCancellation, type SourceColorPrelaunchOwner } from "./guided-source-color-prelaunch-owner";
import type { SourceColorFileRef } from "./guided-source-color-expectations";

export function cancellationAbsent(file: string): void {
  try { fs.lstatSync(file); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return; throw error; }
  throw new Error("Prelaunch cancellation contradictory or unowned entry is retained");
}
function present(file: string): boolean {
  try { fs.lstatSync(file); return true; }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return false; throw error; }
}
function same(actual: unknown, expected: unknown): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error("Prelaunch cancellation original evidence changed");
}
function syncDirectory(directory: string): void {
  const descriptor = fs.openSync(directory, fs.constants.O_RDONLY);
  try { fs.fsyncSync(descriptor); } finally { fs.closeSync(descriptor); }
}

/** Instances never escape the opaque-token registry. State advances only on original successful operations. */
export class PrelaunchCancellationHold {
  readonly transfer;
  readonly root;
  readonly directory;
  readonly activePath;
  readonly receivedAt;
  readonly journal;
  readonly reservation;
  readonly reservationBytes: Buffer | undefined;
  private readonly clock;
  private readonly files = new Map<string, { ref: SourceColorFileRef; identity: bigint[] }>();
  private readonly parents = new Map<string, bigint[]>();
  private readonly originalJournal;
  private currentJournal;
  private journalIdentity;
  private lastElapsed = 0;
  private enteredWrite = false;
  private created = false;
  private unlinked = false;
  private resourceReleased = false;
  private readonly resourceLock;
  constructor(owner: SourceColorPrelaunchOwner) {
    this.clock = createOpeningProtectedCleanupClock(); this.receivedAt = this.clock.receivedAt;
    this.transfer = claimSourceColorPrelaunchCancellation(owner);
    this.root = path.dirname(this.transfer.original.claim.claimPath);
    this.directory = path.join(this.root, "source-color-cancellation");
    this.activePath = path.join(this.transfer.original.resource.resource, "active.json");
    this.originalJournal = snapshotSourceColorMetadata(this.transfer.journal); this.journal = this.originalJournal;
    this.currentJournal = this.journal; this.journalIdentity = fileIdentity(autoEditJobPath(this.journal.job.ctx.dir));
    this.reservation = snapshotSourceColorMetadata(this.transfer.reservation?.reference ?? null);
    same(this.transfer.active?.ref ?? null, this.reservation);
    this.holdParents(this.root); this.holdParents(path.dirname(this.activePath)); cancellationAbsent(this.directory);
    this.resourceLock = fs.lstatSync(path.join(path.dirname(this.activePath), ".sniper-project-mutation.lock"));
    this.metadata();
    const observed = this.reservation ? observeCutPreviewFile(this.activePath, 8 * 1024 * 1024, true, this.finite) : undefined;
    if (observed) same([observed.sha256, observed.sizeBytes], [this.reservation!.sha256, this.reservation!.sizeBytes]);
    this.reservationBytes = observed && Buffer.from(observed.bytes); this.check();
  }
  private holdParents(directory: string): void {
    for (;;) {
      const identity = directoryIdentity(directory), previous = this.parents.get(directory);
      if (previous) same(identity, previous); else this.parents.set(directory, identity);
      const parent = path.dirname(directory); if (parent === directory) return; directory = parent;
    }
  }
  private artifacts(): void {
    for (const name of ["media-process-intent.json", "media-process-result.json", "owned-process-ledger.media.jsonl", "cleanup-attempts"]) {
      cancellationAbsent(path.join(this.root, name));
    }
    const output = this.transfer.original.claim.claim.outputRoot;
    if (present(output)) { directoryIdentity(output); same(fs.readdirSync(output), []); }
    const reservation = this.transfer.reservation?.value as { jobs: Array<{ directory: string; executionDir: string }> } | undefined;
    const paths = [path.join(this.root, "source-color"), ...(reservation?.jobs.map(row => row.directory) ?? [])];
    for (const directory of paths) this.originalDirectory(directory);
  }
  private originalDirectory(directory: string): void {
    if (!present(directory)) return;
    if (!this.transfer.directories.includes(directory)) throw new Error("Cancellation cannot adopt an unheld staging directory");
    directoryIdentity(directory);
    const expected = this.transfer.publications.filter(row => path.dirname(row.path) === directory).map(row => path.basename(row.path)).sort();
    same(fs.readdirSync(directory).sort(), expected);
  }
  metadata = (): void => {
    this.transfer.metadata(); same(this.transfer.journal, this.originalJournal);
    for (const [directory, identity] of this.parents) same(directoryIdentity(directory), identity);
    for (const { ref, identity } of this.files.values()) same(fileIdentity(ref.path), identity);
    if (this.reservation && !this.unlinked) same(fileIdentity(this.activePath), this.transfer.active!.identity);
    else cancellationAbsent(this.activePath);
    const file = autoEditJobPath(this.journal.job.ctx.dir);
    same(fileIdentity(file), this.journalIdentity); same(observeHumanCutJob(this.journal.job.ctx.dir), this.currentJournal);
    this.artifacts();
    if (this.created) same(fs.readdirSync(this.directory).sort(), [...this.files.keys()].filter(file => path.dirname(file) === this.directory).map(file => path.basename(file)).sort());
    else cancellationAbsent(this.directory);
  };
  finite = (): void => {
    this.metadata(); const elapsed = this.clock.elapsedMs(), remaining = this.clock.remainingMs();
    if (!Number.isFinite(elapsed) || elapsed < this.lastElapsed || !Number.isFinite(remaining) || remaining <= 0 || remaining > 300_000) {
      throw new Error("Prelaunch cancellation original protected clock expired or moved backwards");
    }
    this.lastElapsed = elapsed;
  };
  check = (): void => { this.finite(); this.transfer.check(); this.finite(); };
  prepareDirectory(): void {
    this.check();
    if (this.enteredWrite) throw new Error("Cancellation has an unresolved original publication");
    if (this.created) return;
    this.enteredWrite = true; fs.mkdirSync(this.directory, { mode: 0o700 }); this.holdParents(this.directory);
    this.created = true; this.enteredWrite = false; this.finite();
  }
  publish(name: "reservation.json" | "intent.json" | "ack.json", value: Buffer | Record<string, unknown>): SourceColorFileRef {
    this.check(); if (this.enteredWrite) throw new Error("Cancellation cannot adopt an interrupted publication");
    const file = path.join(this.directory, name); cancellationAbsent(file); this.enteredWrite = true;
    if (Buffer.isBuffer(value)) atomicCreateFileSync(file, value); else createOpeningRecord(file, value);
    const identity = fileIdentity(file), observed = observeCutPreviewFile(file, 8 * 1024 * 1024, true);
    same(fileIdentity(file), identity);
    const ref = freezeSourceColorValue({ path: file, sha256: observed.sha256, sizeBytes: observed.sizeBytes });
    this.files.set(file, { ref, identity }); this.enteredWrite = false; this.finite(); return ref;
  }
  retainSnapshot(): SourceColorFileRef {
    this.check();
    const directory = path.join(this.journal.job.ctx.dir, "human-cut-job-snapshots"), file = path.join(directory, `${this.journal.sha256}.json`);
    if (this.enteredWrite) throw new Error("Cancellation snapshot publication is unresolved");
    this.enteredWrite = true; saveHumanCutJobSnapshot(this.journal.job.ctx.dir, this.journal);
    this.holdParents(directory); const identity = fileIdentity(file), raw = readCutPreviewObject(file);
    same(raw.bytes, this.journal.bytes); same(fileIdentity(file), identity);
    const ref = freezeSourceColorValue({ path: file, sha256: raw.sha256, sizeBytes: raw.sizeBytes });
    this.files.set(file, { ref, identity }); this.enteredWrite = false; this.finite(); return ref;
  }
  private originalIntent() {
    const archive = this.files.get(path.join(this.directory, "reservation.json"))?.ref ?? null;
    const journalSnapshot = this.files.get(path.join(this.journal.job.ctx.dir, "human-cut-job-snapshots", `${this.journal.sha256}.json`))?.ref;
    const ref = this.files.get(path.join(this.directory, "intent.json"))?.ref;
    if (!ref || !journalSnapshot || Boolean(archive) !== Boolean(this.reservation)) throw new Error("Cancellation has no original durable intent and archive");
    if (archive) same([archive.sha256, archive.sizeBytes], [this.reservation!.sha256, this.reservation!.sizeBytes]);
    const value = prelaunchCancellationIntent(this.transfer, { reservation: this.reservation, archive, journalSnapshot }, this.receivedAt);
    same(canonicalJsonSha256(value), ref.sha256); return { value, ref };
  }
  unlink(): void {
    this.check(); this.originalIntent(); if (this.enteredWrite) throw new Error("Cancellation publication is unresolved");
    if (this.unlinked) { syncDirectory(path.dirname(this.activePath)); this.finite(); return; }
    if (this.reservation) fs.unlinkSync(this.activePath);
    this.unlinked = true; syncDirectory(path.dirname(this.activePath)); this.finite();
  }
  acceptJournal(expected: unknown): void {
    const current = observeHumanCutJob(this.journal.job.ctx.dir); same(current.job, expected);
    this.currentJournal = current; this.journalIdentity = fileIdentity(autoEditJobPath(current.job.ctx.dir)); this.finite();
  }
  terminal(): void {
    this.check(); if (!this.unlinked) throw new Error("Cancellation has no original reservation transition");
    const intent = this.originalIntent(), ackRef = this.files.get(path.join(this.directory, "ack.json"))?.ref;
    if (!ackRef || this.currentJournal.sha256 === this.journal.sha256) throw new Error("Cancellation has no original acknowledgement and journal transition");
    const observed = readCutPreviewObject(ackRef.path);
    const ack = prelaunchCancellationAck(intent.value, intent.ref, String(observed.value.observedAt));
    same(observed.sha256, ackRef.sha256); same(observed.value, ack);
    same(this.currentJournal.job, prelaunchCancelledJob(this.transfer, { intent: intent.value, ack, ackRef }, this.currentJournal.job.updatedAt));
    this.finite();
  }
  journalHash(): string { this.finite(); return this.currentJournal.sha256; }
  /** Only the actual terminal token can call this through its private registry. Project remains held. */
  releaseResource(): void {
    this.terminal(); if (this.resourceReleased) throw new Error("Cancellation resource release cannot replay");
    const original = this.transfer.original; original.releaseResource.call(original.lease); this.resourceReleased = true;
    this.afterResourceRelease();
  }
  afterResourceRelease = (): void => {
    if (!this.resourceReleased) throw new Error("Cancellation original resource release was not observed");
    this.finite();
    const file = path.join(path.dirname(this.activePath), ".sniper-project-mutation.lock");
    if (present(file)) {
      const current = fs.lstatSync(file);
      if (current.dev === this.resourceLock.dev && current.ino === this.resourceLock.ino) throw new Error("Cancellation original resource release is unverified");
      throw new Error("Cancellation resource was acquired by another owner before project release");
    }
    this.finite();
  };
}
