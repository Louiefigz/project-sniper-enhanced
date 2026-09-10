/** Finite actual media ownership records; no worker, deadline, cleanup, selection or approval authority. */
import fs from "node:fs";
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { autoEditJobPath, parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { writeGuidedObject } from "./guided-cut-v2-store";
import { commitGuidedJob } from "./guided-cut-v2";
import { retainGenerationClockObservation } from "./generation-clock-watermark";
import { createOpeningRecord, type HeldOpeningRecord } from "./guided-opening-process-activation";
import { directoryIdentity, fileIdentity } from "./guided-source-color-cleanup-attempt-hold";
import { snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import type { HeldOpeningClaim } from "./guided-opening-process";

/** Capture original bytes/identities before callbacks; deliberately transition only the actual current journal after CAS. */
export class SourceColorMediaRecords {
  readonly root: string;
  private readonly original: HeldOpeningClaim;
  private readonly files = new Map<string, bigint[]>();
  private readonly parents = new Map<string, bigint[]>();
  private journal: ReturnType<typeof observeHumanCutJob>;
  private journalIdentity: bigint[];
  constructor(readonly held: HeldOpeningClaim) {
    this.original = snapshotSourceColorMetadata(held); this.root = path.dirname(held.claimPath);
    this.journal = observeHumanCutJob(held.job.ctx.dir); this.journalIdentity = fileIdentity(autoEditJobPath(held.job.ctx.dir));
    if (held.sha256 !== this.journal.sha256 || !isDeepStrictEqual(held.job, this.journal.job)
        || !Buffer.isBuffer(held.bytes) || !held.bytes.equals(this.journal.bytes) || held.job.guidedHandoffV2?.openingProcessOutcomeHash) {
      throw new Error("Source color media needs its exact original pre-outcome journal");
    }
    this.capture(held.claimPath, held.claimSha256); this.capture(held.claim.inputPath, held.claim.inputSha256);
    for (const name of ["media-process-intent.json", "media-process-result.json", "owned-process-ledger.media.jsonl"]) this.absent(name);
    this.check();
  }
  private absent(name: string): void {
    try { fs.lstatSync(path.join(this.root, name)); }
    catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return; throw error; }
    throw new Error("Source color media may already have started; no replay is permitted");
  }
  /** Only the actual pre-spawn frontier calls this; a running or settled worker may legitimately have a ledger. */
  assertUnstarted(): void { this.absent("media-process-result.json"); this.absent("owned-process-ledger.media.jsonl"); }
  capture(file: string, expected: string): void {
    const identity = fileIdentity(file);
    for (let directory = path.dirname(file);;) {
      const current = directoryIdentity(directory), original = this.parents.get(directory);
      if (original && !isDeepStrictEqual(current, original)) throw new Error("Source color media original parent changed");
      this.parents.set(directory, current); const parent = path.dirname(directory); if (parent === directory) break; directory = parent;
    }
    if (observeCutPreviewFile(file, 32 * 1024 * 1024).sha256 !== expected || !isDeepStrictEqual(fileIdentity(file), identity)) {
      throw new Error("Source color media original record bytes changed");
    }
    const prior = this.files.get(file);
    if (prior && !isDeepStrictEqual(prior, identity)) throw new Error("Source color media original file identity changed");
    this.files.set(file, identity);
  }
  /** No owner/work callbacks; actual leases are independently checked by the caller. */
  check = (): void => {
    if (!isDeepStrictEqual(this.held, this.original)) throw new Error("Source color media original held claim changed");
    for (const [file, original] of this.files) if (!isDeepStrictEqual(fileIdentity(file), original)) throw new Error("Source color media original file changed");
    for (const [directory, original] of this.parents) if (!isDeepStrictEqual(directoryIdentity(directory), original)) throw new Error("Source color media original parent changed");
    const file = autoEditJobPath(this.held.job.ctx.dir);
    if (!isDeepStrictEqual(fileIdentity(file), this.journalIdentity) || observeHumanCutJob(this.held.job.ctx.dir).sha256 !== this.journal.sha256) {
      throw new Error("Source color media exact current journal changed");
    }
  };
  publish(name: "media-process-intent.json" | "media-process-result.json", value: Record<string, unknown>): HeldOpeningRecord {
    this.check(); const record = createOpeningRecord(path.join(this.root, name), value);
    this.capture(record.path, record.sha256); this.check(); return record;
  }
  /** Bind the actual new claim-reader return to the original claim and the exact committed journal. */
  assertActivated(value: HeldOpeningClaim): void {
    this.check();
    if (value.sha256 !== this.journal.sha256 || !isDeepStrictEqual(value.job, this.journal.job)
        || !Buffer.isBuffer(value.bytes) || !value.bytes.equals(this.journal.bytes)
        || value.claimHash !== this.held.claimHash || value.claimPath !== this.held.claimPath
        || value.claimSha256 !== this.held.claimSha256 || !isDeepStrictEqual(value.claim, this.held.claim)) {
      throw new Error("Source color media actual activated claim differs from the original claim/current journal");
    }
  }
  /** Save original pre-CAS bytes, then compare the actual new journal to the exact intended transition before adopting it. */
  activate(intent: HeldOpeningRecord, outcome: HeldOpeningRecord, guard: () => void): void {
    const held = this.held, dir = held.job.ctx.dir, createdAt = new Date().toISOString(); guard(); this.check();
    const activation = { schemaVersion: 2, kind: "guided-opening-process-activation",
      scope: "actual-owned-process-outcome-not-media-or-delivery-approval", claimHash: held.claimHash,
      beforeJournalHash: held.sha256, executionId: held.claim.executionId, inputSha256: held.claim.inputSha256,
      intentSha256: intent.sha256, outcomeSha256: outcome.sha256, clockHash: held.claim.clockHash,
      generationStartedAt: held.claim.generationStartedAt, createdAt };
    const hash = writeGuidedObject(dir, activation);
    this.capture(path.join(dir, ".sniper-authority-v1/objects/receipts", `${hash}.json`), hash);
    saveHumanCutJobSnapshot(dir, held); this.capture(path.join(dir, "human-cut-job-snapshots", `${held.sha256}.json`), held.sha256);
    const job = parseAutoEditJobRecord({ ...held.job, updatedAt: createdAt,
      guidedHandoffV2: { ...held.job.guidedHandoffV2!, openingProcessOutcomeHash: hash } });
    const expected = snapshotSourceColorMetadata(job), beforeHash = held.sha256;
    const commitGuard = () => {
      guard(); this.check(); const observedAt = new Date().toISOString();
      if (observedAt < createdAt || createdAt < String(outcome.value.finishedAt)) throw new Error("Source color media outcome wall clock moved backwards");
      retainGenerationClockObservation({ dir, origin: { clockHash: held.claim.clockHash, startedAt: held.claim.generationStartedAt },
        executionId: held.claim.executionId, observedAt }, guard); this.check();
    };
    commitGuidedJob({ beforeHash, guard: commitGuard, job });
    const actual = observeHumanCutJob(dir);
    if (!isDeepStrictEqual(actual.job, expected) || !isDeepStrictEqual(job, expected)
        || !actual.bytes.equals(Buffer.from(`${JSON.stringify(expected, null, 1)}\n`))) throw new Error("Source color media activation CAS differs from its original transition");
    this.journal = actual; this.journalIdentity = fileIdentity(autoEditJobPath(dir)); guard(); this.check();
  }
}
