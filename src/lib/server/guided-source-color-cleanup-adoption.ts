/** Explicit completed-but-uncommitted recovery. Never launches native cleanup or releases ownership. */
import fs from "node:fs";
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { workspaceRoot } from "@/app/api/_lib/workspace";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { uuid } from "@/lib/producer/contracts/validation";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { autoEditJobPath } from "./auto-edit-job-persistence";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import { readGuidedOpeningExecutionClaim } from "./guided-opening-claim";
import { strictGuidedTimestamp } from "./guided-cut-v2-store";
import { directoryIdentity, fileIdentity } from "./guided-source-color-cleanup-attempt-hold";
import { readSourceColorCleanupHistory, assertSourceColorCleanupHistoryMetadata,
  type SourceColorCleanupHistoryEvidence } from "./guided-source-color-cleanup-history";
import { sourceColorCleanupAttemptReadDependencies } from "./guided-source-color-cleanup-attempt-read";
import { holdSourceColorCleanupReservation, assertSourceColorCleanupReservationMetadata,
  type HeldSourceColorCleanupReservation } from "./guided-source-color-cleanup-hold";
import { snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import type { HeldOpeningClaim } from "./guided-opening-process";
import type { SourceColorCleanupClock } from "./guided-source-color-cleanup-attempt";
import type { ProjectMutationLease } from "./project-mutation-lease";
import type { HeldGradeObservationResource } from "./grade-observation-resource";

export interface CompletedSourceColorCleanupInput {
  held: HeldOpeningClaim; projectLease: ProjectMutationLease; resource: HeldGradeObservationResource;
  attemptId: string; clock: SourceColorCleanupClock;
}
/** Only original namespace/claim/native observation leaves; no replacement history reader or success flag. */
export const sourceColorCleanupAdoptionDependencies = { workspace: workspaceRoot,
  claim: readGuidedOpeningExecutionClaim, get history() { return sourceColorCleanupAttemptReadDependencies; } };
type Dependencies = typeof sourceColorCleanupAdoptionDependencies;
type Attempt = SourceColorCleanupHistoryEvidence["attempts"][number];
const adopted = new WeakMap<object, AdoptionOwner>();

function same(actual: unknown, expected: unknown, label: string): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error(`Cleanup adoption original ${label} changed`);
}
function bounded(started: number, remaining: number): number {
  const elapsed = performance.now() - started, result = remaining - elapsed;
  if (!Number.isFinite(remaining) || remaining > 300_000 || !Number.isFinite(elapsed) || elapsed < 0 || result <= 0) {
    throw new Error("Cleanup adoption exhausted its original protected remainder");
  }
  return result;
}

/** Capture current journal and cold marker before the history reader enters ANY original callback. */
class AdoptionOwner {
  readonly original;
  readonly controls;
  readonly journal;
  readonly active;
  private readonly fixed;
  private readonly files = new Map<string, bigint[]>();
  private readonly parents = new Map<string, bigint[]>();
  private readonly projectGuard;
  private readonly resourceGuard;
  private checking = false;
  history: SourceColorCleanupHistoryEvidence | undefined;
  reservation: HeldSourceColorCleanupReservation | undefined;
  constructor(readonly input: CompletedSourceColorCleanupInput, readonly dependencies: Dependencies) {
    this.original = { ...input, releaseProject: input.projectLease.release, resourcePath: input.resource.resource,
      resourceLease: input.resource.lease, releaseResource: input.resource.lease.release, resourceCheck: input.resource.assertResource,
      remaining: input.clock.remainingMs, elapsed: input.clock.elapsedMs, receivedAt: input.clock.receivedAt };
    this.controls = { ...dependencies, history: { ...dependencies.history } };
    this.fixed = snapshotSourceColorMetadata(input.held);
    strictGuidedTimestamp(this.original.receivedAt);
    if (uuid(input.attemptId, "cleanup adoption attemptId")[14] !== "4" || input.held.submission.schemaVersion !== 2) {
      throw new Error("Cleanup adoption requires an explicit completed V2 attempt");
    }
    this.journal = autoEditJobPath(input.held.job.ctx.dir); this.active = path.join(input.resource.resource, "active.json");
    for (const file of [this.journal, this.active, input.held.claimPath, input.held.claim.inputPath]) this.capture(file);
    this.projectGuard = cutPreviewLeaseGuard(input.held.job.ctx.dir, input.projectLease);
    this.resourceGuard = cutPreviewLeaseGuard(input.resource.resource, input.resource.lease);
    this.guard();
  }
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
  private unchanged(): void {
    const i = this.input, o = this.original;
    if (i.held !== o.held || i.projectLease !== o.projectLease || i.projectLease.release !== o.releaseProject
        || i.resource !== o.resource || i.resource.resource !== o.resourcePath || i.resource.lease !== o.resourceLease
        || i.resource.lease.release !== o.releaseResource || i.resource.assertResource !== o.resourceCheck
        || i.attemptId !== o.attemptId || i.clock !== o.clock || i.clock.remainingMs !== o.remaining
        || i.clock.elapsedMs !== o.elapsed || i.clock.receivedAt !== o.receivedAt
        || this.dependencies.workspace !== this.controls.workspace || this.dependencies.claim !== this.controls.claim
        || Object.keys(this.controls.history).some(key => this.dependencies.history[key as keyof Dependencies["history"]]
          !== this.controls.history[key as keyof Dependencies["history"]])) {
      throw new Error("Cleanup adoption original caller or dependency identity changed");
    }
    same(i.held, this.fixed, "full held claim metadata");
  }
  /** After CAS the obsolete current journal is deliberately excluded; all retained evidence stays original. */
  metadata = (): void => {
    this.unchanged();
    for (const [directory, identity] of this.parents) same(directoryIdentity(directory), identity, "parent identity");
    for (const [file, identity] of this.files) {
      if (file !== this.journal) same(fileIdentity(file), identity, "file identity");
    }
    if (this.history) assertSourceColorCleanupHistoryMetadata(this.history);
    if (this.reservation) assertSourceColorCleanupReservationMetadata(this.reservation);
    this.unchanged();
  };
  guard = (): void => {
    this.metadata(); this.projectGuard(); this.resourceGuard();
    same(fileIdentity(this.journal), this.files.get(this.journal), "current journal identity");
    const current = observeHumanCutJob(this.fixed.job.ctx.dir);
    same({ sha256: current.sha256, bytes: current.bytes, job: current.job },
      { sha256: this.fixed.sha256, bytes: this.fixed.bytes, job: this.fixed.job }, "current precleanup journal");
    if (current.job.guidedHandoffV2?.openingCleanupHash) throw new Error("Cleanup adoption cannot replace pending or final cleanup");
    same(fileIdentity(this.journal), this.files.get(this.journal), "current journal identity"); this.metadata();
  };
  remaining = (): number => {
    this.unchanged(); const started = performance.now(), remaining = this.original.remaining.call(this.original.clock);
    this.guard(); return bounded(started, remaining);
  };
  bindHistory(): Attempt {
    this.history = readSourceColorCleanupHistory({ held: this.original.held, guard: this.guard, remainingMs: this.remaining }, this.controls.history);
    const selected = this.history.attempts.find(row => row.attemptId === this.original.attemptId);
    if (!selected) throw new Error("Cleanup adoption selected attempt is not in its complete original history");
    const workspace = fs.realpathSync(this.controls.workspace()); this.guard();
    if (this.original.resourcePath !== path.join(workspace, ".sniper-color-resource")) throw new Error("Cleanup adoption resource namespace differs");
    const current = this.controls.claim(this.fixed.job.ctx.dir); this.guard(); same(current, this.fixed, "actual current claim");
    this.reservation = holdSourceColorCleanupReservation({ held: this.original.held, reference: selected.evidence.stop.sourceColor!,
      resourceDir: this.original.resourcePath, guard: this.guard, remainingMs: this.remaining });
    this.reservation.assertResult(selected.evidence.result);
    const raw = observeCutPreviewFile(this.active, 8 * 1024 * 1024, true, this.guard);
    same({ path: this.active, sha256: raw.sha256, sizeBytes: raw.sizeBytes }, selected.fact.reservation, "active reservation reference");
    same(this.reservation.containerNames, selected.evidence.containerNames, "complete reserved names");
    this.check(); return selected;
  }
  check = (): number => {
    if (this.checking) throw new Error("Cleanup adoption cannot reenter its original completion lifetime");
    this.checking = true;
    try {
      const started = performance.now(), remaining = this.remaining();
      this.history!.assertCurrent(); this.reservation!.assertCurrent(); this.metadata();
      return bounded(started, remaining);
    } finally { this.checking = false; }
  };
}

export interface AdoptedSourceColorCleanupCompletion extends Pick<Attempt, "fact" | "factHash" | "evidence" | "preparedRef"> {
  readonly scope: "completed-history-adoption-not-native-replay-retirement-or-approval";
}

/** Both actual leases and one caller-created recovery clock are prerequisites, not proof of worker absence.
 * Every prior attempt must independently prove complete normal return before this selected attempt is adopted.
 * Failure retains all evidence and both leases. No new attempt, journal write, native work or release occurs.
 */
export function holdCompletedSourceColorCleanup(input: CompletedSourceColorCleanupInput,
  dependencies: Dependencies = sourceColorCleanupAdoptionDependencies): AdoptedSourceColorCleanupCompletion {
  const owner = new AdoptionOwner(input, dependencies), row = owner.bindHistory();
  const result = Object.freeze({ fact: row.fact, factHash: row.factHash, evidence: row.evidence, preparedRef: row.preparedRef,
    scope: "completed-history-adoption-not-native-replay-retirement-or-approval" as const });
  owner.check(); adopted.set(result, owner); return result;
}
function ownerFor(value: AdoptedSourceColorCleanupCompletion): AdoptionOwner {
  const owner = adopted.get(value);
  if (!owner) throw new Error("Cleanup adoption requires its actual authenticated historical completion");
  return owner;
}
export function heldAdoptedSourceColorCleanup(value: AdoptedSourceColorCleanupCompletion): HeldOpeningClaim {
  const owner = ownerFor(value); owner.check(); return owner.original.held;
}
export function remainingAdoptedSourceColorCleanup(value: AdoptedSourceColorCleanupCompletion): number {
  return ownerFor(value).check();
}
/** Metadata only after CAS; never the obsolete current-journal callback, a clock or retirement authority. */
export function assertAdoptedSourceColorCleanupMetadata(value: AdoptedSourceColorCleanupCompletion): void {
  ownerFor(value).metadata();
}
