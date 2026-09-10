/** Live pre-dispatch state and retained metadata only. No cancellation, cleanup, lease release or cold recovery. */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { autoEditJobPath } from "./auto-edit-job-persistence";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import { capturePublication, assertPublication } from "./guided-source-color-cleanup-pending-commit";
import { assertOpeningControllerClaimBinding, type OpeningControllerLifecycle } from "./guided-opening-controller-lifecycle";
import { assertStagedSourceColorMetadata, type StagedSourceColorInput } from "./guided-source-color-staging";
import { SourceColorStagingRead, assertSourceColorStagingMetadata, snapshotSourceColorMetadata,
  freezeSourceColorValue, holdSourceColorStagingCancellationMetadata,
  type SourceColorStagingContext, type SourceColorStagingPublication } from "./guided-source-color-staging-hold";
import type { claimGuidedOpeningExecution } from "./guided-opening-claim";
import type { ProjectMutationLease } from "./project-mutation-lease";
import type { SourceColorFileRef } from "./guided-source-color-expectations";

type Claim = ReturnType<typeof claimGuidedOpeningExecution>;
type Phase = "held" | "staging" | "staged" | "dispatch-entered" | "cancel-entered";
export interface SourceColorPrelaunchInput {
  controller: OpeningControllerLifecycle; claim: Claim; projectLease: ProjectMutationLease; staging: SourceColorStagingContext;
}
export interface SourceColorPrelaunchOwner {
  readonly scope: "live-source-color-prelaunch-not-cancellation-cleanup-or-dispatch-authority";
}
const owners = new WeakMap<SourceColorPrelaunchOwner, Prelaunch>();
const claims = new WeakSet<Claim>();

function same(actual: unknown, expected: unknown): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error("Source color prelaunch original metadata changed");
}

/** The object is never exposed: callers receive only its WeakMap-authenticated single-use token. */
class Prelaunch {
  private phase: Phase = "held";
  private busy = false;
  private readonly original;
  private readonly fixed;
  private readonly reader;
  private readonly current;
  private readonly journal;
  private readonly project;
  private readonly resource;
  private readonly publications: SourceColorFileRef[] = [];
  private reservation: SourceColorStagingPublication | undefined;
  private staged: StagedSourceColorInput | undefined;
  private pendingWrite: string | undefined;
  constructor(private readonly input: SourceColorPrelaunchInput) {
    const c = input.staging;
    this.original = { ...input, release: input.projectLease.release, resource: c.resource, lease: c.resource.lease,
      releaseResource: c.resource.lease.release, resourceGuard: c.resource.assertResource, guard: c.guard,
      expectations: c.expectations, expectationGuard: c.expectations.assertCurrent };
    this.fixed = snapshotSourceColorMetadata(input.claim);
    this.journal = capturePublication(autoEditJobPath(c.producerDir), input.claim.journalHash);
    this.reader = new SourceColorStagingRead(c, Object.freeze({ check: () => this.stagingCheck(),
      publishing: (file: string) => this.publishing(file),
      published: (value: SourceColorStagingPublication) => this.retain(value) }));
    this.current = this.reader.check;
    this.project = cutPreviewLeaseGuard(c.producerDir, input.projectLease);
    this.resource = cutPreviewLeaseGuard(c.resource.resource, c.resource.lease);
    if (c.opening.claim !== input.claim.claim || c.opening.claimPath !== input.claim.claimPath
        || c.opening.claimSha256 !== input.claim.claimSha256 || path.basename(c.resource.resource) !== ".sniper-color-resource") {
      throw new Error("Source color prelaunch needs its original claimed execution and resource");
    }
    this.metadata();
  }
  private identity(): void {
    const i = this.input, o = this.original;
    if (i.controller !== o.controller || i.claim !== o.claim || i.projectLease !== o.projectLease || i.staging !== o.staging
        || i.projectLease.release !== o.release || i.staging.resource !== o.resource || o.resource.lease !== o.lease
        || o.lease.release !== o.releaseResource || o.resource.assertResource !== o.resourceGuard
        || i.staging.guard !== o.guard || i.staging.expectations !== o.expectations || o.expectations.assertCurrent !== o.expectationGuard) {
      throw new Error("Source color prelaunch original caller or lease changed");
    }
    same(i.claim, this.fixed);
  }
  private metadata(): void {
    this.identity(); assertPublication(this.journal);
    assertSourceColorStagingMetadata(this.original.staging, this.current);
  }
  check(): void {
    this.metadata();
    assertOpeningControllerClaimBinding(this.original.controller, this.original.claim, this.original.projectLease);
    this.project(); this.original.resourceGuard(); this.resource(); this.project(); this.metadata();
  }
  private stagingCheck(): void {
    if (this.phase === "held" || this.phase === "cancel-entered") throw new Error("Source color prelaunch no longer permits staging");
    this.metadata(); this.project(); this.resource(); this.metadata();
  }
  private retain(publication: SourceColorStagingPublication): void {
    // No arbitrary callbacks between the publisher's original inode capture and this detached retention.
    if (this.phase !== "staging" || this.pendingWrite !== publication.reference.path || this.publications.length >= 386
        || this.publications.some(row => row.path === publication.reference.path)) {
      throw new Error("Source color prelaunch cannot replace or replay a publication");
    }
    this.publications.push(freezeSourceColorValue(snapshotSourceColorMetadata(publication.reference)));
    if (publication.reference.path === path.join(this.original.resource.resource, "active.json")) {
      this.reservation = freezeSourceColorValue(snapshotSourceColorMetadata(publication));
    }
    this.pendingWrite = undefined;
    this.metadata();
  }
  private publishing(file: string): void {
    if (this.phase !== "staging" || this.pendingWrite) throw new Error("Source color publication has unresolved original write ownership");
    this.pendingWrite = file;
  }
  private transition(phase: Phase, work: () => void): void {
    if (this.busy) throw new Error("Source color prelaunch transition is already in progress");
    this.phase = phase; this.busy = true;
    try { work(); } finally { this.busy = false; }
  }
  start(context: SourceColorStagingContext): SourceColorStagingRead {
    if (context !== this.original.staging || this.phase !== "held") throw new Error("Source color prelaunch staging cannot replay or change context");
    this.transition("staging", () => this.check()); return this.reader;
  }
  finish(context: SourceColorStagingContext, staged: StagedSourceColorInput): void {
    if (context !== this.original.staging || this.phase !== "staging") throw new Error("Source color prelaunch staging completion changed");
    assertStagedSourceColorMetadata(context, staged);
    const refs = [staged.reservation, ...staged.jobs.flatMap(row => [row.implementation, row.input, row.launchClaim]), staged.input];
    same(refs, this.publications);
    this.staged = staged; this.transition("staged", () => this.check());
  }
  dispatch(staged: StagedSourceColorInput): void {
    if (this.phase !== "staged" || staged !== this.staged) throw new Error("Source color dispatch needs the same actual completed staging");
    this.transition("dispatch-entered", () => {
      this.check(); this.original.guard(); this.original.expectationGuard(); this.check();
    });
  }
  cancel(): void {
    if (!["held", "staging", "staged"].includes(this.phase)) throw new Error("Source color prelaunch cancellation entry cannot replay or follow dispatch");
    // State only: do not invoke the expired render callback or invent a cancellation work allowance.
    this.transition("cancel-entered", () => this.check());
  }
  cancellation() {
    if (this.pendingWrite) throw new Error("Cancellation cannot resolve a publisher without its original inode handoff");
    this.cancel();
    const metadata = holdSourceColorStagingCancellationMetadata(this.original.staging, this.current);
    const journal = observeHumanCutJob(this.original.staging.producerDir); this.check();
    if (journal.sha256 !== this.original.claim.journalHash) throw new Error("Cancellation original claimed journal differs");
    const check = () => {
      this.identity(); metadata.check();
      assertOpeningControllerClaimBinding(this.original.controller, this.original.claim, this.original.projectLease);
      this.original.resourceGuard(); this.resource(); this.project(); metadata.check(); this.identity();
    };
    return Object.freeze({ original: Object.freeze({ ...this.original }), active: metadata.active, directories: metadata.directories,
      journal, reservation: this.reservation, publications: Object.freeze([...this.publications]), check,
      metadata: () => { this.identity(); metadata.check(); } });
  }
  record() {
    this.check();
    const value = snapshotSourceColorMetadata({ phase: this.phase,
      reservation: this.reservation ?? null,
      publications: this.publications, cancellationComplete: false, cleanupVerified: false, dispatchAuthorized: false });
    this.metadata(); return freezeSourceColorValue(value);
  }
}

function actual(value: SourceColorPrelaunchOwner): Prelaunch {
  const owner = owners.get(value);
  if (!owner) throw new Error("Source color prelaunch requires its actual live owner, not copied metadata");
  return owner;
}

/** A failed original binding is not retried with a new owner; the same controller retains its lease. */
export function holdSourceColorPrelaunch(input: SourceColorPrelaunchInput): SourceColorPrelaunchOwner {
  if (claims.has(input.claim)) throw new Error("Source color prelaunch claim was already consumed");
  const owner = new Prelaunch(input); claims.add(input.claim); owner.check();
  const value = Object.freeze({ scope: "live-source-color-prelaunch-not-cancellation-cleanup-or-dispatch-authority" as const });
  owners.set(value, owner); return value;
}
/** Internal staging seam; the constructor retained the original reader before the first work callback. */
export function beginSourceColorPrelaunchStaging(owner: SourceColorPrelaunchOwner, context: SourceColorStagingContext): SourceColorStagingRead {
  return actual(owner).start(context);
}
export function finishSourceColorPrelaunchStaging(owner: SourceColorPrelaunchOwner, context: SourceColorStagingContext,
  staged: StagedSourceColorInput): void { actual(owner).finish(context, staged); }
/** Irreversible entry fence only; the actual worker and original budget checks remain mandatory. */
export function enterSourceColorPrelaunchDispatch(owner: SourceColorPrelaunchOwner, staged: StagedSourceColorInput): void { actual(owner).dispatch(staged); }
/** Irreversible entry fence only: no reservation deletion, acknowledgement, claim CAS or lease release. */
export function enterSourceColorPrelaunchCancel(owner: SourceColorPrelaunchOwner): void { actual(owner).cancel(); }
/** Detached bounded metadata, never a replacement owner or proof that cancellation completed. */
export function readSourceColorPrelaunchMetadata(owner: SourceColorPrelaunchOwner) { return actual(owner).record(); }
/** Internal one-time live transfer; its metadata cannot replace a cancellation token or authorize deletion. */
export function claimSourceColorPrelaunchCancellation(owner: SourceColorPrelaunchOwner) { return actual(owner).cancellation(); }
