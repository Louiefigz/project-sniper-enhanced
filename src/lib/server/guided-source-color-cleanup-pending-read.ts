/** Explicit current or retained pending journal evidence, never retirement, selection or approval. */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { sha256 } from "@/lib/producer/contracts/validation";
import { parsePreparedSourceColorCleanupFact } from "@/lib/producer/contracts/guided-source-color-cleanup-facts";
import { parseCurrentOpeningCleanupResult } from "@/lib/producer/contracts/guided-opening-cleanup-v2";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { readGuidedObject } from "./guided-cut-v2-store";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import { autoEditJobPath, parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { readRetainedOpeningExecutionClaim } from "./guided-opening-claim";
import { buildSourceColorCleanupPendingJob } from "./guided-source-color-cleanup-pending-job";
import { readSourceColorCleanupAttempt, assertSourceColorCleanupAttemptMetadata } from "./guided-source-color-cleanup-attempt-read";
import { CleanupPendingReadHold, type SourceColorCleanupPendingReadInput } from "./guided-source-color-cleanup-pending-hold";
import { freezeSourceColorValue } from "./guided-source-color-staging-hold";

export type { SourceColorCleanupPendingReadInput } from "./guided-source-color-cleanup-pending-hold";
/** Only code can supply TEST original-claim/native leaves; neither dependency is reconstructed from JSON. */
export const sourceColorCleanupPendingReadDependencies = { claim: readRetainedOpeningExecutionClaim, attempt: readSourceColorCleanupAttempt };
type Dependencies = typeof sourceColorCleanupPendingReadDependencies;
type PendingScope = "current-pending-source-color-cleanup-not-retirement-or-approval"
  | "retained-pending-source-color-cleanup-not-retirement-or-approval";
const metadataHolds = new WeakMap<object, () => void>();
const remainingHolds = new WeakMap<object, () => number>();

function same(actual: unknown, expected: unknown, label: string): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error(`Cleanup pending ${label} differs from original evidence`);
}
function objectPath(dir: string, hash: string): string {
  return path.join(dir, ".sniper-authority-v1/objects/receipts", `${sha256(hash, "cleanup object hash")}.json`);
}
/** The explicit snapshot SHA is raw-byte identity; it never selects or falls back to the current journal. */
function retainedPendingJob(dir: string, hash: string) {
  const observed = readCutPreviewObject(path.join(dir, "human-cut-job-snapshots", `${hash}.json`));
  same(observed.sha256, hash, "retained pending raw journal SHA");
  const job = parseAutoEditJobRecord(observed.value);
  same(job.ctx.dir, dir, "retained pending producer directory");
  return { ...observed, job };
}

/** Derive and hold all four outer records before the first arbitrary caller guard. */
class PendingRead {
  readonly hold;
  readonly current;
  readonly fact;
  readonly factHash;
  readonly held;
  readonly result;
  private attempt: ReturnType<typeof readSourceColorCleanupAttempt> | undefined;
  constructor(readonly input: SourceColorCleanupPendingReadInput, readonly controls: Dependencies, retainedHash?: string) {
    this.hold = new CleanupPendingReadHold(input);
    const journal = retainedHash === undefined ? autoEditJobPath(input.dir)
      : path.join(input.dir, "human-cut-job-snapshots", `${retainedHash}.json`);
    this.current = this.hold.observe(journal, () => retainedHash === undefined
      ? observeHumanCutJob(input.dir) : retainedPendingJob(input.dir, retainedHash));
    this.factHash = sha256(this.current.job.guidedHandoffV2?.openingCleanupHash, "pending cleanup fact hash");
    const rawFact = this.hold.observe(objectPath(input.dir, this.factHash), () => readGuidedObject(input.dir, this.factHash));
    this.fact = this.hold.retain(() => parsePreparedSourceColorCleanupFact(rawFact));
    const file = path.join(input.dir, "human-cut-job-snapshots", `${this.fact.beforeJournalHash}.json`);
    const prior = this.hold.observe(file, () => readCutPreviewObject(file));
    same(prior.sha256, this.fact.beforeJournalHash, "precleanup raw journal SHA");
    this.result = this.hold.observe(objectPath(input.dir, this.fact.cleanupResultHash), () => readGuidedObject(input.dir, this.fact.cleanupResultHash));
    this.held = this.hold.retain(() => controls.claim(input.dir, this.fact.beforeJournalHash));
    same(this.held.sha256, prior.sha256, "actual retained journal SHA");
    same([this.held.bytes, this.held.sizeBytes, this.held.value], [prior.bytes, prior.sizeBytes, prior.value], "actual retained raw journal return");
    same(this.held.job, parseAutoEditJobRecord(prior.value), "actual retained full job");
    this.validate(); this.hold.metadata();
  }
  private validate(): void {
    same(canonicalJsonSha256(this.fact), this.factHash, "prepared fact hash");
    same(this.current.job, buildSourceColorCleanupPendingJob(this.held, this.fact), "entire deterministic pending job");
    const result = parseCurrentOpeningCleanupResult(this.result);
    if (result.schemaVersion !== 2) throw new Error("Cleanup pending result must retain all-source V2 evidence");
    same(canonicalJsonSha256(result), this.fact.cleanupResultHash, "stored result hash");
    if (!this.attempt) return;
    same(this.attempt.fact, this.fact, "actual attempt prepared fact");
    same(result, this.attempt.result, "stored result versus actual attempt");
  }
  metadata = (): void => {
    this.hold.metadata(); if (this.attempt) assertSourceColorCleanupAttemptMetadata(this.attempt); this.hold.metadata();
  };
  private remaining = (): number => {
    let capturedAt = 0;
    const sampled = this.hold.run(() => {
      this.attempt!.assertCurrent(); this.validate(); this.metadata();
      const result = this.hold.remaining(); capturedAt = performance.now(); return result;
    });
    const elapsed = performance.now() - capturedAt, result = sampled - elapsed;
    if (!Number.isFinite(elapsed) || elapsed < 0 || result <= 0) throw new Error("Cleanup pending original protected deadline expired after bookkeeping");
    return result;
  };
  read<S extends PendingScope>(scope: S) {
    return this.hold.runAfterCapture(() => {
      this.attempt = this.controls.attempt({ held: this.held, fact: this.fact, guard: this.hold.enterAfterCapture, remainingMs: this.hold.remaining });
      this.hold.check(); this.validate(); this.metadata(); this.hold.remaining();
      const result = Object.freeze({ scope,
        pendingJournalHash: this.current.sha256, job: freezeSourceColorValue(structuredClone(this.current.job)),
        fact: freezeSourceColorValue(structuredClone(this.fact)), factHash: this.factHash, held: this.held, attempt: this.attempt,
        result: freezeSourceColorValue(structuredClone(this.result)), retirementObserved: false as const,
        mediaSelected: false as const, openingApproved: false as const, deliveryApproved: false as const,
        assertCurrent: () => this.hold.run(() => { this.attempt!.assertCurrent(); this.validate(); this.metadata(); this.hold.remaining(); }) });
      this.metadata(); this.hold.remaining(); metadataHolds.set(result, this.metadata); remainingHolds.set(result, this.remaining); return result;
    });
  }
}

/** Observe only the actual current pending job; no historical fallback, CAS, unlink or lease acquisition. */
export function readSourceColorCleanupPending(input: SourceColorCleanupPendingReadInput,
  dependencies: Dependencies = sourceColorCleanupPendingReadDependencies) {
  return new PendingRead(input, Object.freeze({ ...dependencies })).read("current-pending-source-color-cleanup-not-retirement-or-approval");
}

/** Read one explicitly named retained pending snapshot; no current journal, fallback or retirement authority. */
export function readRetainedSourceColorCleanupPending(input: SourceColorCleanupPendingReadInput, pendingJournalHash: string,
  dependencies: Dependencies = sourceColorCleanupPendingReadDependencies) {
  const hash = sha256(pendingJournalHash, "retained pending journal hash");
  return new PendingRead(input, Object.freeze({ ...dependencies }), hash).read("retained-pending-source-color-cleanup-not-retirement-or-approval");
}

export type SourceColorCleanupPendingEvidence = ReturnType<typeof readSourceColorCleanupPending>
  | ReturnType<typeof readRetainedSourceColorCleanupPending>;

/** Actual read identity plus finite metadata only; caller separately proves its live clock and ownership. */
export function assertSourceColorCleanupPendingMetadata(value: SourceColorCleanupPendingEvidence): void {
  const check = metadataHolds.get(value);
  if (!check) throw new Error("Cleanup pending metadata requires its actual original read evidence");
  check();
}

/** Same original caller allowance only, with final bookkeeping charged; JSON/spread cannot acquire a new clock. */
export function remainingSourceColorCleanupPending(value: SourceColorCleanupPendingEvidence): number {
  const remaining = remainingHolds.get(value);
  if (!remaining) throw new Error("Cleanup pending remainder requires its actual original read evidence");
  return remaining();
}
