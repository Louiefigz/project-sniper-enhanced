/** Internal V3 ownership writer only. Public V2 media fences and Python argument-consumer qualification remain unchanged. */
import { isDeepStrictEqual } from "node:util";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { openingChildTools, assertToolsUnchanged, invokeOpeningChild, readStoppedOpeningProcess,
  type HeldOpeningClaim } from "./guided-opening-process";
import { readGuidedOpeningExecutionClaim } from "./guided-opening-claim";
import { readGuidedProposalReadiness } from "./guided-proposal-review-store";
import { assertOpeningSourceColorProcessMetadata, holdOpeningSourceColorProcess,
  type OpeningSourceColorProcessContext } from "./guided-source-color-process-binding";
import { observeOwnedWorkerLedger, ownedProcessLedgerPath } from "./guided-opening-process-ledger";
import { freezeSourceColorValue, snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { SourceColorMediaRecords } from "./guided-source-color-media-records";
import { withStageTimingContext } from "./stage-timing-context";
import { timedStage } from "./stage-timing";
import type { ProjectMutationLease } from "./project-mutation-lease";

export interface SourceColorMediaProcessInput {
  held: HeldOpeningClaim; lease: ProjectMutationLease; sourceColor: OpeningSourceColorProcessContext;
  /** Same original controller work callback; never called after the actual owned invocation settles. */
  remainingMs: () => number;
}
/** Only original readiness/claim/tool/native leaves; actual records, CAS, ledger and V3 stopped parser stay mandatory. */
export const sourceColorMediaProcessDependencies = { readiness: readGuidedProposalReadiness, tools: openingChildTools,
  toolsUnchanged: assertToolsUnchanged, invoke: invokeOpeningChild, claim: readGuidedOpeningExecutionClaim };
type Dependencies = typeof sourceColorMediaProcessDependencies;
const consumedStaging = new WeakSet<object>();

/** Actual project/resource guards are separate from staging's possibly expired media-work callback. */
class MediaLifetime {
  readonly original;
  readonly records: SourceColorMediaRecords;
  readonly binding;
  private readonly projectGuard: () => void;
  private readonly resourceGuard: () => void;
  private readonly actualResourceGuard: () => void;
  private readonly returned: Array<{ value: unknown; fixed: unknown }> = [];
  private toolCheck: (() => void) | undefined;
  private tools: ReturnType<typeof openingChildTools> | undefined;
  private settlement: MediaOutcome | undefined;
  private workEnd = Infinity;
  constructor(readonly input: SourceColorMediaProcessInput) {
    const context = input.sourceColor, resource = context.staging.resource;
    this.original = { ...input, resource, releaseProject: input.lease.release, releaseResource: resource.lease.release,
      assertResource: resource.assertResource, submission: snapshotSourceColorMetadata(context.submission) };
    this.records = new SourceColorMediaRecords(input.held);
    if (input.held.submission.schemaVersion !== 2 || !isDeepStrictEqual(input.held.submission, context.submission)
        || context.submission.expectedToken !== input.held.job.token
        || context.submission.proposalReadinessHash !== input.held.job.guidedHandoffV2?.proposalReadinessHash
        || context.submission.treatmentDraftRevisionHash !== input.held.job.guidedHandoffV2?.treatmentDraftRevisionHash
        || !isDeepStrictEqual(context.staging.opening.claim, input.held.claim)
        || context.staging.opening.claimPath !== input.held.claimPath || context.staging.opening.claimSha256 !== input.held.claimSha256) {
      throw new Error("Source color media differs from the complete original V2 claim/submission");
    }
    this.projectGuard = cutPreviewLeaseGuard(input.held.job.ctx.dir, input.lease); this.resourceGuard = resource.assertResource;
    this.actualResourceGuard = cutPreviewLeaseGuard(resource.resource, resource.lease);
    this.binding = holdOpeningSourceColorProcess(context); this.metadata(); this.owners();
  }
  metadata = (): void => {
    const i = this.input, o = this.original;
    if (i.held !== o.held || i.lease !== o.lease || i.sourceColor !== o.sourceColor || i.remainingMs !== o.remainingMs
        || i.lease.release !== o.releaseProject || i.sourceColor.staging.resource !== o.resource
        || o.resource.lease.release !== o.releaseResource || o.resource.assertResource !== o.assertResource
        || !isDeepStrictEqual(i.sourceColor.submission, o.submission)) throw new Error("Source color media original caller/clock/lease changed");
    assertOpeningSourceColorProcessMetadata(this.binding); this.records.check();
    if (this.returned.some(row => !isDeepStrictEqual(row.value, row.fixed))) throw new Error("Source color media original returned metadata changed");
  };
  owners = (): void => {
    this.metadata(); this.resourceGuard(); this.toolCheck?.(); this.projectGuard(); this.actualResourceGuard(); this.metadata();
  };
  capture<T>(value: T): T {
    const fixed = snapshotSourceColorMetadata(value); this.returned.push({ value, fixed }); return fixed;
  }
  bindTools(tools: ReturnType<typeof openingChildTools>, check: typeof assertToolsUnchanged): void {
    if (this.toolCheck) throw new Error("Source color media cannot replace its original tool binding");
    this.tools = tools; this.toolCheck = () => check(tools); this.owners();
  }
  /** Charge original callbacks and finite checks; retain the shortest observed local work cutoff. */
  remaining = (): number => {
    this.metadata(); const started = performance.now(), remaining = this.original.remainingMs();
    this.binding.assertCurrent(); this.owners(); this.records.assertUnstarted(); const now = performance.now();
    const bounded = Math.floor(remaining - (now - started));
    if (!Number.isFinite(remaining) || remaining > 1_500_000 || !Number.isFinite(now) || now < started || bounded <= 250) {
      throw new Error("Source color media original work allowance is insufficient");
    }
    this.workEnd = Math.min(this.workEnd, now + bounded);
    const result = Math.floor(this.workEnd - now);
    if (result <= 250) throw new Error("Source color media original captured work cutoff expired");
    return result;
  };
  withinCapturedWork(): void {
    if (performance.now() >= this.workEnd) throw new Error("Source color media settled after its original captured work cutoff");
  }
  /** No caller work callbacks; the shared runner charges this finite frontier after all ancestor deadline callbacks. */
  beforeSpawn = (): void => {
    this.metadata(); this.projectGuard(); this.actualResourceGuard(); assertToolsUnchanged(this.tools!);
    this.records.assertUnstarted(); this.metadata(); this.withinCapturedWork();
  };
  /** Actual runner settlement, before its ancestor callbacks; no work-clock or replaceable owner callback is invoked. */
  afterSettled = (details: Readonly<CutPreviewProcessError["details"]>): void => {
    if (this.settlement) throw new Error("Source color media cannot replace its original settlement");
    this.settlement = { ...failedOutcome(), ...this.capture(details) };
    captureReturnedLedger(this, this.settlement, this.tools!);
    this.metadata(); this.projectGuard(); this.actualResourceGuard(); this.metadata();
  };
  ledgerFor(outcome: MediaOutcome): boolean {
    const held = this.settlement;
    if (!held) { outcome.error += "\nOriginal owned settlement capture is absent"; return false; }
    if (held.stdout !== outcome.stdout || held.stderr !== outcome.stderr || held.groupStopped !== outcome.groupStopped
        || held.forcedStop !== outcome.forcedStop || (held.timedOut && !outcome.timedOut)) {
      throw new Error("Source color actual stop/output facts differ from original settlement");
    }
    outcome.ledgerSha256 = held.ledgerSha256; outcome.error = `${outcome.error}${held.error}`.slice(0, 4000);
    return held.ledgerSha256 !== null;
  }
}

interface MediaOutcome {
  status: "complete" | "failed"; error: string; timedOut: boolean; groupStopped: boolean; forcedStop: boolean;
  stdout: string; stderr: string; ledgerSha256: string | null;
}
function failedOutcome(): MediaOutcome {
  return { status: "failed", error: "", timedOut: false, groupStopped: false, forcedStop: false, stdout: "", stderr: "", ledgerSha256: null };
}

/** Hold the actual returned wrapper ledger before the first subsequent caller/tool callback, never a repaired later version. */
function captureReturnedLedger(owner: MediaLifetime, outcome: MediaOutcome, tools: ReturnType<typeof openingChildTools>): boolean {
  if (!outcome.groupStopped || outcome.forcedStop) return false;
  try {
    const hash = observeOwnedWorkerLedger(owner.records.root, "media", tools.script);
    owner.records.capture(ownedProcessLedgerPath(owner.records.root, "media"), hash); outcome.ledgerSha256 = hash; return true;
  } catch (error) {
    outcome.status = "failed"; outcome.error = `${outcome.error}\n${String(error)}`.slice(0, 4000); return false;
  }
}

/** Capture actual normal return or exact runner exception before any later owner/tool callback. */
async function ownedOutcome(owner: MediaLifetime, tools: ReturnType<typeof openingChildTools>, controls: Dependencies): Promise<MediaOutcome> {
  const outcome = failedOutcome(), ref = owner.binding.reference, staged = owner.original.sourceColor.staging;
  try {
    const result = await controls.invoke({ held: owner.original.held, tools, kind: "media", remainingMs: owner.remaining,
      beforeSpawn: owner.beforeSpawn, afterSettled: owner.afterSettled,
      extraArgs: ["--source-color-input", ref.input.path, "--source-color-input-sha256", ref.input.sha256,
        "--source-color-producer-dir", staged.producerDir, "--source-color-resource-dir", staged.resource.resource] });
    const fixed = owner.capture(result);
    outcome.stdout = fixed.stdout; outcome.stderr = fixed.stderr; outcome.groupStopped = true;
    const ledgerHeld = owner.ledgerFor(outcome);
    owner.owners(); controls.toolsUnchanged(tools); owner.owners(); owner.withinCapturedWork();
    if (ledgerHeld) outcome.status = "complete";
    if (!isDeepStrictEqual(result, fixed)) throw new Error("Source color actual owned output changed after return");
  } catch (error) {
    outcome.status = "failed"; outcome.error = String(error).slice(0, 4000);
    if (error instanceof CutPreviewProcessError) {
      const details = owner.capture(error.details);
      outcome.groupStopped = details.groupStopped; outcome.forcedStop = details.forcedStop; outcome.timedOut = details.timedOut;
      outcome.stdout = details.stdout; outcome.stderr = details.stderr;
      owner.ledgerFor(outcome);
    }
  }
  return outcome;
}

/** No missing-intent/ledger conclusion is settlement; this is only a live, single-use staging dispatch, never cold recovery. */
export async function runSourceColorOpeningMedia(input: SourceColorMediaProcessInput,
  dependencies: Dependencies = sourceColorMediaProcessDependencies) {
  const startedAt = new Date().toISOString(), began = performance.now(), controls = { ...dependencies }, owner = new MediaLifetime(input);
  if (consumedStaging.has(input.sourceColor.staged)) throw new Error("Source color media staging was already consumed; no replay");
  owner.remaining(); controls.readiness(input.held.job.ctx.dir); owner.remaining(); owner.binding.assertUnstarted();
  const tools = freezeSourceColorValue(owner.capture(controls.tools(input.held, "media")));
  owner.bindTools(tools, controls.toolsUnchanged); owner.remaining();
  const intent = owner.records.publish("media-process-intent.json", { schemaVersion: 3, kind: "guided-opening-process-intent",
    claimHash: input.held.claimHash, inputSha256: input.held.claim.inputSha256, executionId: input.held.claim.executionId,
    journalHash: input.held.sha256, clockHash: input.held.claim.clockHash, generationStartedAt: input.held.claim.generationStartedAt,
    startedAt, tools, sourceColor: owner.binding.reference });
  consumedStaging.add(input.sourceColor.staged);
  const output = await withStageTimingContext({ runId: input.held.job.artifactToken ?? input.held.job.token,
    attemptId: `opening-source-color:${input.held.claim.executionId}`, attemptNo: input.held.job.attempts }, () =>
    timedStage(input.held.job.ctx.dir, "guided_opening_source_color_owned_media", () => ownedOutcome(owner, tools, controls)));
  const receipt = freezeSourceColorValue({ schemaVersion: 3, kind: "guided-opening-process-outcome",
    scope: "owned-process-stop-not-media-or-delivery-approval", intentHash: canonicalJsonSha256(intent.value),
    claimHash: input.held.claimHash, inputSha256: input.held.claim.inputSha256, executionId: input.held.claim.executionId,
    startedAt, finishedAt: new Date().toISOString(), elapsedMs: performance.now() - began, ...output });
  owner.owners(); const outcome = owner.records.publish("media-process-result.json", receipt);
  owner.records.activate(intent, outcome, owner.owners); owner.owners();
  const held = controls.claim(input.held.job.ctx.dir), fixed = owner.capture(held); owner.owners();
  owner.records.assertActivated(held);
  if (held.claimHash !== input.held.claimHash || !isDeepStrictEqual(held.submission, input.held.submission)) {
    throw new Error("Source color media activated another original claim/submission");
  }
  const stopped = receipt.groupStopped && (receipt.forcedStop || receipt.ledgerSha256) ? readStoppedOpeningProcess(held) : null;
  owner.capture(stopped);
  owner.owners(); if (!isDeepStrictEqual(held, fixed)) throw new Error("Source color media actual activated claim return changed");
  return Object.freeze({ held, receipt, receiptSha256: outcome.sha256, stopped,
    mediaSelected: false as const, openingApproved: false as const, deliveryApproved: false as const });
}
