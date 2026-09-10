/** Final cleanup/history evidence only. Its observation budget is not a renewed work/cleanup clock or lease. */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { sha256, uuid } from "@/lib/producer/contracts/validation";
import { parseFinalSourceColorCleanupFact, parseSourceColorRetirementAck } from "@/lib/producer/contracts/guided-source-color-cleanup-facts";
import { readCutPreviewObject, observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { autoEditJobPath, parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { readGuidedObject, strictGuidedTimestamp } from "./guided-cut-v2-store";
import type { observeHumanCutJob } from "./human-cut-acceptance-store";
import type { AutoEditJob } from "./auto-edit-job-types";
import { CleanupPendingReadHold } from "./guided-source-color-cleanup-pending-hold";
import { readRetainedSourceColorCleanupPending, assertSourceColorCleanupPendingMetadata } from "./guided-source-color-cleanup-pending-read";
import { buildSourceColorCleanupRetiredJob } from "./guided-source-color-cleanup-retired-job";
import { freezeSourceColorValue } from "./guided-source-color-staging-hold";

export interface SourceColorFinalCleanupReadInput {
  dir: string; journal: { path: string; observed: ReturnType<typeof observeHumanCutJob> };
  guard: () => void; remainingMs: () => number;
}
/** TEST native/claim leaves may be supplied only through an actual authenticated retained reader. */
export const sourceColorFinalCleanupReadDependencies = { history: readRetainedSourceColorCleanupPending };
type Dependencies = typeof sourceColorFinalCleanupReadDependencies;
type Pending = ReturnType<typeof readRetainedSourceColorCleanupPending>;
const metadataHolds = new WeakMap<object, () => void>();

function same(actual: unknown, expected: unknown, label: string): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error(`Final source color cleanup ${label} differs from original evidence`);
}
function objectPath(dir: string, hash: string): string {
  return path.join(dir, ".sniper-authority-v1/objects/receipts", `${sha256(hash, "cleanup object hash")}.json`);
}
function stableJob(job: AutoEditJob) {
  const { updatedAt, message, nextEventId, events, ...stable } = job;
  const { openingMediaSelectionHash, openingApprovalHash, ...pointer } = stable.guidedHandoffV2!;
  void updatedAt; void message; void nextEventId; void events; void openingMediaSelectionHash; void openingApprovalHash;
  return { ...stable, guidedHandoffV2: pointer };
}
function assertOuterJob(current: AutoEditJob, expected: AutoEditJob): void {
  const pointer = current.guidedHandoffV2!;
  if (Object.hasOwn(pointer, "openingMediaSelectionHash") || Object.hasOwn(pointer, "openingApprovalHash")) {
    same(stableJob(current), stableJob(expected), "complete stable selected/approved job"); return;
  }
  same(current, expected, "entire deterministic final job");
}

/** Bound the acknowledgement to this producer before opening it, then join the actual claim namespace later. */
function ackPath(dir: string, fact: ReturnType<typeof parseFinalSourceColorCleanupFact>): string {
  const root = path.join(dir, "guided-v2-operations"), parts = path.relative(root, fact.retirementAck.path).split(path.sep);
  const request = uuid(parts[0], "retirement acknowledgement request");
  same(parts, [request, "executions", fact.executionId, "cleanup-attempts", fact.cleanupAttemptId, "retirement-ack.json"], "acknowledgement namespace");
  return fact.retirementAck.path;
}

/** Capture outer records before caller callbacks; the actual pending reader captures its own complete chain next. */
class FinalRead {
  private readonly original;
  private readonly hold;
  private readonly observed;
  private readonly factHash;
  private readonly fact;
  private readonly ack;
  private pending: Pending | undefined;
  private budget: { started: number; remaining: number } | undefined;
  constructor(readonly input: SourceColorFinalCleanupReadInput, readonly controls: Dependencies) {
    this.original = { ...input, observed: input.journal.observed };
    this.hold = new CleanupPendingReadHold(input); this.hold.retain(() => input.journal);
    this.observed = input.journal.observed;
    const hash = sha256(this.observed.sha256, "outer cleanup journal hash"), file = input.journal.path;
    if (![autoEditJobPath(input.dir), path.join(input.dir, "human-cut-job-snapshots", `${hash}.json`)].includes(file)) {
      throw new Error("Final cleanup journal path is not its exact current or explicitly retained snapshot");
    }
    const raw = this.hold.observe(file, () => readCutPreviewObject(file));
    same([raw.sha256, raw.sizeBytes, raw.bytes, raw.value], [hash, this.observed.sizeBytes, this.observed.bytes, this.observed.value], "outer raw journal return");
    same(this.observed.job, parseAutoEditJobRecord(raw.value), "outer parsed job");
    same(this.observed.job.ctx.dir, input.dir, "outer producer directory");
    this.factHash = sha256(this.observed.job.guidedHandoffV2?.openingCleanupHash, "final cleanup hash");
    const value = this.hold.observe(objectPath(input.dir, this.factHash), () => readGuidedObject(input.dir, this.factHash));
    this.fact = this.hold.retain(() => parseFinalSourceColorCleanupFact(value));
    same(canonicalJsonSha256(this.fact), this.factHash, "actual final fact hash");
    const ackFile = ackPath(input.dir, this.fact);
    const ack = this.hold.observe(ackFile, () => observeCutPreviewFile(ackFile, 128 * 1024, true, this.metadata));
    same([ack.sha256, ack.sizeBytes], [this.fact.retirementAck.sha256, this.fact.retirementAck.sizeBytes], "acknowledgement raw reference");
    this.ack = this.hold.retain(() => parseSourceColorRetirementAck(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(ack.bytes))));
    this.metadata();
  }
  metadata = (): void => {
    if (this.input.journal !== this.original.journal || this.input.journal.observed !== this.original.observed) {
      throw new Error("Final cleanup original outer journal context changed");
    }
    this.hold.metadata(); if (this.pending) assertSourceColorCleanupPendingMetadata(this.pending); this.hold.metadata();
  };
  private guard = (): void => { this.metadata(); this.original.guard(); this.metadata(); };
  private remaining = (): number => {
    this.metadata(); const started = performance.now(), remaining = this.original.remainingMs(); this.metadata();
    if (!Number.isFinite(remaining) || remaining <= 0 || remaining > 30_000) throw new Error("Final cleanup read-only proof remainder is invalid");
    this.budget = { started, remaining }; return this.remainingCaptured();
  };
  private remainingCaptured(): number {
    if (!this.budget) throw new Error("Final cleanup reader omitted its original observation remainder");
    const elapsed = performance.now() - this.budget.started, remaining = this.budget.remaining - elapsed;
    if (!Number.isFinite(elapsed) || elapsed < 0 || remaining <= 0) throw new Error("Final cleanup read-only observation budget expired");
    return remaining;
  }
  private validate(): void {
    const pending = this.pending!, fact = this.fact, ack = this.ack;
    assertSourceColorCleanupPendingMetadata(pending);
    if (pending.scope !== "retained-pending-source-color-cleanup-not-retirement-or-approval") throw new Error("Final cleanup needs explicit retained pending history");
    same([pending.pendingJournalHash, pending.factHash], [fact.pendingJournalHash, fact.preparedFactHash], "exact pending parent");
    const expected = buildSourceColorCleanupRetiredJob({ job: pending.job, pendingJournalHash: pending.pendingJournalHash, prepared: pending.fact }, fact);
    assertOuterJob(this.observed.job, expected);
    same(fact.retirementAck.path, path.join(path.dirname(pending.held.claimPath), "cleanup-attempts", fact.cleanupAttemptId, "retirement-ack.json"), "actual held acknowledgement path");
    same(ack, { schemaVersion: 1, kind: "guided-opening-source-color-retirement",
      scope: "exact-reservation-retirement-not-process-cleanup-or-approval", claimHash: fact.claimHash,
      executionId: fact.executionId, cleanupAttemptId: fact.cleanupAttemptId, preparedFactHash: pending.factHash,
      pendingJournalHash: pending.pendingJournalHash, reservation: pending.fact.reservation, archive: pending.fact.archive,
      observedAt: ack.observedAt, disposition: ack.disposition, mediaSelected: false, openingApproved: false, deliveryApproved: false }, "acknowledgement bindings");
    const stamps = [pending.fact.createdAt, ack.observedAt, fact.createdAt, this.observed.job.updatedAt].map(strictGuidedTimestamp);
    if (stamps.some((stamp, index) => index > 0 && stamp < stamps[index - 1])) throw new Error("Final cleanup acknowledgement/journal clocks are not chronological");
  }
  private assertCurrent = (): void => {
    this.metadata(); this.pending!.assertCurrent(); this.validate(); this.metadata(); this.remainingCaptured();
  };
  read() {
    this.pending = this.controls.history({ dir: this.original.dir, guard: this.guard, remainingMs: this.remaining }, this.fact.pendingJournalHash);
    this.validate(); this.metadata(); this.remainingCaptured();
    const attempt = this.pending.attempt;
    const result = Object.freeze({ ...this.observed, held: this.pending.held,
      receipt: freezeSourceColorValue(structuredClone(this.fact)), cleanupHash: this.factHash,
      evidence: Object.freeze({ start: attempt.start, output: attempt.output, result: attempt.result, stop: attempt.stop }),
      pending: this.pending, retirementAck: freezeSourceColorValue(structuredClone(this.ack)),
      observationScope: "historical-exact-resource-cleanup-not-current-media-approval" as const,
      readBudgetScope: "bounded-proof-read-not-render-cleanup-or-lease-authority" as const,
      mediaSelected: false as const, openingApproved: false as const, deliveryApproved: false as const, assertCurrent: this.assertCurrent });
    this.metadata(); this.remainingCaptured(); metadataHolds.set(result, this.metadata); return result;
  }
}

/** The supplied observation and 30s enclosing proof budget confer no lease, cleanup, unlink or media authority. */
export function readFinalSourceColorCleanupForJournal(input: SourceColorFinalCleanupReadInput,
  dependencies: Dependencies = sourceColorFinalCleanupReadDependencies) {
  return new FinalRead(input, Object.freeze({ ...dependencies })).read();
}

/** Actual final-read identity and finite metadata only; never resurrects retired resource or work ownership. */
export function assertSourceColorFinalCleanupMetadata(value: ReturnType<typeof readFinalSourceColorCleanupForJournal>): void {
  const check = metadataHolds.get(value);
  if (!check) throw new Error("Final cleanup metadata needs its actual original read evidence");
  check();
}
