/** Private live release gate only. No failed-state, missing-file or serialized token proves cold settlement. */
import path from "node:path";
import { lstatSync } from "node:fs";
import { isDeepStrictEqual } from "node:util";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { mutationProjectRoot } from "@/app/api/_lib/project-mutation";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { readOpeningLaunchIntent, readOpeningLaunchActivation, assertOpeningControllerSelf } from "./guided-opening-launch-store";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import { autoEditJobPath } from "./auto-edit-job-persistence";
import { capturePublication, assertPublication } from "./guided-source-color-cleanup-pending-commit";
import { snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import { readCommittedOpeningCleanup } from "./guided-opening-cleanup-store";
import { holdOpeningControllerCleanup } from "./guided-opening-controller-cleanup";
import { holdSourceColorPrelaunchCancellationTerminal, type SourceColorPrelaunchCancelled } from "./guided-source-color-prelaunch-cancel";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import type { claimGuidedOpeningExecution } from "./guided-opening-claim";
import type { ProjectMutationLease } from "./project-mutation-lease";

type Launch = NonNullable<ReturnType<typeof readOpeningLaunchIntent>>;
type Activation = NonNullable<ReturnType<typeof readOpeningLaunchActivation>>;
type Execution = Parameters<typeof claimGuidedOpeningExecution>[0];
type Claim = ReturnType<typeof claimGuidedOpeningExecution>;
interface ControllerInput { launch: Launch; activation: Activation; lease: ProjectMutationLease }
export interface OpeningControllerLifecycle { readonly scope: "live-controller-release-not-cold-recovery-or-approval" }
const controllers = new WeakMap<OpeningControllerLifecycle, Controller>();

function same(actual: unknown, expected: unknown): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error("Opening controller original lifecycle binding changed");
}
function execution(input: Execution) {
  return { dir: input.proposal.job.ctx.dir, before: input.proposal.sha256, executionId: input.operation.executionId,
    directory: input.operation.execution, submission: input.operation.record.submission, inputPath: input.invocation.inputPath,
    inputSha256: input.invocation.inputSha256, executionInputHash: input.invocation.input.executionInputHash,
    budgetAdmissionHash: input.budgetAdmissionHash, clockHash: input.proposal.clock.hash,
    generationStartedAt: input.proposal.generationStartedAt };
}

class Controller {
  private phase: "preclaim" | "claim-entered" | "cleanup-proved" | "released" = "preclaim";
  private readonly original;
  private readonly fixed;
  private readonly guard;
  private readonly publications;
  private readonly journal;
  private readonly lock;
  private run?: { input: Execution; value: ReturnType<typeof execution>; remaining: Execution["remainingMs"] };
  private claim?: { value: Claim; fixed: Claim };
  private cleanup?: ReturnType<typeof holdOpeningControllerCleanup>;
  private cancellation?: ReturnType<typeof holdSourceColorPrelaunchCancellationTerminal>;
  private releasing = false;
  private cancellationEntering = false;
  private cancellationProjectReleaseEntered = false;
  constructor(private readonly input: ControllerInput) {
    this.original = { ...input, release: input.lease.release };
    this.fixed = snapshotSourceColorMetadata({ launch: input.launch, activation: input.activation });
    const { dir, submission } = input.launch.intent;
    this.guard = cutPreviewLeaseGuard(dir, input.lease);
    const lockPath = path.join(mutationProjectRoot(dir), ".sniper-project-mutation.lock"), stat = lstatSync(lockPath);
    this.lock = { path: lockPath, dev: stat.dev, ino: stat.ino };
    this.publications = ["intent.json", "activation.json", "released.json", "controller-started.json"].map(name => {
      const file = path.join(input.launch.root, name); return capturePublication(file, readCutPreviewObject(file).sha256);
    });
    this.journal = capturePublication(autoEditJobPath(dir), submission.expectedJournalHash);
    same(observeHumanCutJob(dir).sha256, submission.expectedJournalHash);
    this.current(); assertPublication(this.journal);
  }
  private metadata(): void {
    if (this.input.launch !== this.original.launch || this.input.activation !== this.original.activation
        || this.input.lease !== this.original.lease || this.input.lease.release !== this.original.release) {
      throw new Error("Opening controller original lifecycle owner changed");
    }
    same({ launch: this.input.launch, activation: this.input.activation }, this.fixed);
    if (this.run) {
      same(execution(this.run.input), this.run.value);
      if (this.run.input.lease !== this.original.lease || this.run.input.remainingMs !== this.run.remaining) {
        throw new Error("Opening controller original execution owner changed");
      }
    }
    if (this.claim) same(this.claim.value, this.claim.fixed);
    for (const publication of this.publications) assertPublication(publication);
  }
  private current(): void {
    this.metadata(); this.guard();
    const { launch, activation } = this.original;
    same(readOpeningLaunchIntent(launch.intent.dir, launch.intent.submission.expectedJournalHash), this.fixed.launch);
    same(readOpeningLaunchActivation(launch), this.fixed.activation); assertOpeningControllerSelf(activation.activation);
    this.guard(); this.metadata();
  }
  begin(input: Execution): void {
    if (this.phase !== "preclaim") throw new Error("Opening controller claim phase cannot replay");
    this.phase = "claim-entered"; // Set BEFORE every publication/callback in claimGuidedOpeningExecution.
    const value = snapshotSourceColorMetadata(execution(input)); this.run = { input, value, remaining: input.remainingMs };
    this.current(); assertPublication(this.journal);
    const original = this.original.launch.intent;
    same(value.submission, original.submission);
    if (value.dir !== original.dir || value.before !== original.submission.expectedJournalHash
        || value.clockHash !== original.origin.clockHash || value.generationStartedAt !== original.origin.startedAt
        || value.directory !== path.join(original.dir, "guided-v2-operations", original.submission.idempotencyKey, "executions", value.executionId)
        || value.inputPath !== path.join(value.directory, "media-input/input.json")) {
      throw new Error("Opening controller claim differs from its original launch");
    }
  }
  bind(value: Claim): void {
    if (this.phase !== "claim-entered" || !this.run || this.claim) throw new Error("Opening controller has no unbound original claim entry");
    this.claim = { value, fixed: snapshotSourceColorMetadata(value) }; this.current();
    const expected = this.run.value, claim = value.claim;
    if (claim.beforeJournalHash !== expected.before || claim.executionId !== expected.executionId
        || claim.requestId !== this.original.launch.intent.submission.idempotencyKey
        || claim.inputPath !== expected.inputPath || claim.inputSha256 !== expected.inputSha256
        || claim.executionInputHash !== expected.executionInputHash || claim.clockHash !== expected.clockHash
        || claim.generationStartedAt !== expected.generationStartedAt || claim.budgetAdmissionHash !== expected.budgetAdmissionHash
        || value.claimPath !== path.join(expected.directory, "execution-claim.json")
        || value.claimHash !== value.claimSha256 || canonicalJsonSha256(claim) !== value.claimHash
        || readCutPreviewObject(value.claimPath).sha256 !== value.claimSha256) {
      throw new Error("Opening controller returned claim lost its original execution binding");
    }
  }
  assertClaim(value: Claim, lease: ProjectMutationLease): void {
    if (this.phase !== "claim-entered" || this.claim?.value !== value || lease !== this.original.lease) {
      throw new Error("Opening prelaunch requires the same actual bound controller claim and lease");
    }
    this.current();
  }
  cleaned(expected: { claimHash: string; cleanupHash: string }) {
    if (this.phase !== "claim-entered" || !this.claim) throw new Error("Opening controller has no original claim for cleanup");
    this.current(); const observed = readCommittedOpeningCleanup(this.original.launch.intent.dir);
    if (observed.cleanupHash !== expected.cleanupHash || observed.held.claimHash !== expected.claimHash
        || expected.claimHash !== this.claim.fixed.claimHash || observed.receipt.claimRetained !== false
        || observed.job.guidedHandoffV2?.openingExecutionClaimHash) throw new Error("Opening controller exact cleanup is not terminal");
    same(observed.held.claim, this.claim.fixed.claim);
    same([observed.held.claimPath, observed.held.claimSha256], [this.claim.fixed.claimPath, this.claim.fixed.claimSha256]);
    const cleanup = holdOpeningControllerCleanup(observed); this.current(); cleanup.metadata();
    this.cleanup = cleanup; this.phase = "cleanup-proved"; return observed;
  }
  cancelled(controller: OpeningControllerLifecycle, proof: SourceColorPrelaunchCancelled): void {
    if (this.phase !== "claim-entered" || !this.claim || this.cancellation || this.cancellationEntering) throw new Error("Controller cancellation terminal cannot replay or replace cleanup");
    this.cancellationEntering = true;
    try {
      this.current();
      this.cancellation = holdSourceColorPrelaunchCancellationTerminal(proof, { controller, claim: this.claim.value, lease: this.original.lease });
      this.current(); this.cancellation.check();
    } finally { this.cancellationEntering = false; }
  }
  private finishRelease(): boolean {
    if (this.phase === "released") throw new Error("Opening controller lease release cannot replay");
    if (this.cancellationProjectReleaseEntered) throw new Error("Opening cancellation project release remains unverified; no blind re-release");
    if (this.phase === "claim-entered" && !this.cancellation) return false;
    this.current();
    if (this.phase === "preclaim") assertPublication(this.journal);
    else if (this.cancellation) this.cancellation.check();
    else this.cleanup!.check();
    this.current(); this.cleanup?.metadata();
    if (this.cancellation) {
      this.cancellation.releaseResource(); this.current(); this.cancellation.afterResourceRelease();
    }
    if (this.cancellation) this.cancellationProjectReleaseEntered = true;
    this.original.release.call(this.original.lease);
    let stat;
    try { stat = lstatSync(this.lock.path); }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
    if (stat?.dev === this.lock.dev && stat.ino === this.lock.ino) throw new Error("Opening controller original lease release is unverified");
    this.phase = "released"; // Original lease absence is irreversible, even if the cancellation tail fails.
    this.cancellation?.afterProjectRelease(); return true;
  }
  release(): boolean {
    if (this.releasing) throw new Error("Opening controller lease release cannot reenter");
    this.releasing = true;
    try { return this.finishRelease(); } finally { this.releasing = false; }
  }
}

function actual(value: OpeningControllerLifecycle): Controller {
  const held = controllers.get(value);
  if (!held) throw new Error("Opening controller needs its actual original live lifecycle, not copied metadata");
  return held;
}
/** Entry capture happens immediately after acquiring THIS controller's project lease. */
export function holdOpeningControllerLifecycle(input: ControllerInput): OpeningControllerLifecycle {
  const held = new Controller(input), value = Object.freeze({ scope: "live-controller-release-not-cold-recovery-or-approval" as const });
  controllers.set(value, held); return value;
}
export function beginOpeningControllerClaim(value: OpeningControllerLifecycle, input: Execution): void { actual(value).begin(input); }
export function bindOpeningControllerClaim(value: OpeningControllerLifecycle, claim: Claim): void { actual(value).bind(claim); }
/** Exact existing live claim binding only; no dispatch, cancellation, cleanup or release is authorized. */
export function assertOpeningControllerClaimBinding(value: OpeningControllerLifecycle, claim: Claim, lease: ProjectMutationLease): void {
  actual(value).assertClaim(claim, lease);
}
export function observeOpeningControllerCleanup(value: OpeningControllerLifecycle, expected: { claimHash: string; cleanupHash: string }) {
  return actual(value).cleaned(expected);
}
/** Distinct same-live cancellation proof; never a fabricated media outcome or cleanup pointer. */
export function observeOpeningControllerPrelaunchCancellation(value: OpeningControllerLifecycle, proof: SourceColorPrelaunchCancelled): void {
  actual(value).cancelled(value, proof);
}
/** False means retained uncertainty, never cleanup failure relabeled as settled. */
export function releaseOpeningControllerLease(value: OpeningControllerLifecycle): boolean { return actual(value).release(); }
