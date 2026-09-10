/** Same-live cancellation only. Never resumes from files, invokes children, or invents process/cleanup facts. */
import { isDeepStrictEqual } from "node:util";
import { commitGuidedJob } from "./guided-cut-v2";
import { retainGenerationClockObservation } from "./generation-clock-watermark";
import { freezeSourceColorValue } from "./guided-source-color-staging-hold";
import { PrelaunchCancellationHold } from "./guided-source-color-prelaunch-cancel-hold";
import { prelaunchCancellationIntent, prelaunchCancellationAck, prelaunchCancelledJob,
  type PrelaunchCancellationIntent, type PrelaunchCancellationAck, type CancellationRecordReferences } from "./guided-source-color-prelaunch-cancel-records";
import type { SourceColorPrelaunchOwner } from "./guided-source-color-prelaunch-owner";
import type { SourceColorFileRef } from "./guided-source-color-expectations";
import type { AutoEditJob } from "./auto-edit-job-types";
import type { OpeningControllerLifecycle } from "./guided-opening-controller-lifecycle";
import type { ProjectMutationLease } from "./project-mutation-lease";

export interface SourceColorPrelaunchCancellation {
  readonly scope: "same-live-prelaunch-cancellation-not-cold-recovery";
}
export interface SourceColorPrelaunchCancelled {
  readonly scope: "actual-prelaunch-cancellation-terminal-not-process-cleanup-or-approval";
  readonly claimedJournalHash: string; readonly cancelledJournalHash: string;
  readonly intent: SourceColorFileRef; readonly acknowledgement: SourceColorFileRef;
  readonly claimRetained: false; readonly mediaSelected: false; readonly openingApproved: false; readonly deliveryApproved: false;
}
/** Fault callbacks cannot supply records, clocks, CAS results, leases or terminal proof. */
export interface SourceColorPrelaunchCancellationFaults {
  afterArchive?: () => void; afterIntent?: () => void; afterUnlink?: () => void; afterAck?: () => void;
  beforeCasGuard?: (invocation: number) => void; afterCas?: () => void; beforeReturn?: () => void;
}
interface Progress {
  owner: PrelaunchCancellationHold; busy: boolean; refs?: CancellationRecordReferences;
  intent?: { value: PrelaunchCancellationIntent; ref: SourceColorFileRef };
  ack?: { value: PrelaunchCancellationAck; ref: SourceColorFileRef };
  job?: AutoEditJob; casEntered: boolean; committed: boolean; result?: SourceColorPrelaunchCancelled;
}
const cancellations = new WeakMap<SourceColorPrelaunchCancellation, Progress>();
const terminals = new WeakMap<SourceColorPrelaunchCancelled, Progress>();

/** One original protected clock begins before transfer/setup; a failed constructor consumes no replacement allowance. */
export function beginSourceColorPrelaunchCancellation(prelaunch: SourceColorPrelaunchOwner): SourceColorPrelaunchCancellation {
  const owner = new PrelaunchCancellationHold(prelaunch);
  const token = Object.freeze({ scope: "same-live-prelaunch-cancellation-not-cold-recovery" as const });
  cancellations.set(token, { owner, busy: false, casEntered: false, committed: false }); return token;
}

function recordIntent(state: Progress, faults: SourceColorPrelaunchCancellationFaults): void {
  const o = state.owner; o.prepareDirectory();
  if (!state.refs) {
    const journalSnapshot = o.retainSnapshot();
    const archive = o.reservationBytes ? o.publish("reservation.json", o.reservationBytes) : null;
    if (archive && !isDeepStrictEqual([archive.sha256, archive.sizeBytes], [o.reservation!.sha256, o.reservation!.sizeBytes])) {
      throw new Error("Cancellation archive differs from the original retained reservation bytes");
    }
    state.refs = { reservation: o.reservation, archive, journalSnapshot }; faults.afterArchive?.(); o.check();
  }
  if (state.intent) return;
  const value = freezeSourceColorValue(prelaunchCancellationIntent(o.transfer, state.refs, o.receivedAt));
  const ref = o.publish("intent.json", value); state.intent = { value, ref }; faults.afterIntent?.(); o.check();
}

function acknowledge(state: Progress, faults: SourceColorPrelaunchCancellationFaults): void {
  if (state.ack) return;
  const o = state.owner; o.unlink(); faults.afterUnlink?.(); o.check();
  const value = freezeSourceColorValue(prelaunchCancellationAck(state.intent!.value, state.intent!.ref, new Date().toISOString()));
  const ref = o.publish("ack.json", value); state.ack = { value, ref }; faults.afterAck?.(); o.check();
}

function commitCancellation(state: Progress, faults: SourceColorPrelaunchCancellationFaults): void {
  if (state.committed) return;
  if (state.casEntered) throw new Error("Cancellation journal write is unresolved; no blind CAS retry");
  const o = state.owner, claim = o.transfer.original.claim.claim;
  const job = prelaunchCancelledJob(o.transfer, { intent: state.intent!.value, ack: state.ack!.value, ackRef: state.ack!.ref }, new Date().toISOString());
  let invocation = 0;
  const guard = () => {
    faults.beforeCasGuard?.(++invocation); o.check();
    const observedAt = new Date().toISOString();
    if (observedAt < job.updatedAt) throw new Error("Cancellation wall clock moved backwards before CAS");
    retainGenerationClockObservation({ dir: o.journal.job.ctx.dir, origin: { clockHash: claim.clockHash, startedAt: claim.generationStartedAt },
      executionId: claim.executionId, observedAt }, o.check); o.check();
  };
  state.casEntered = true; commitGuidedJob({ beforeHash: o.journal.sha256, job, guard });
  o.acceptJournal(job); state.job = job; state.committed = true; faults.afterCas?.(); o.check();
}

/** Only this exact token can continue after its own observed unlink, on its one original clock. */
export function finishSourceColorPrelaunchCancellation(token: SourceColorPrelaunchCancellation,
  testOnly?: SourceColorPrelaunchCancellationFaults): SourceColorPrelaunchCancelled {
  const state = cancellations.get(token);
  if (!state || state.busy) throw new Error("Cancellation requires its actual non-reentrant same-live token");
  const faults = { ...testOnly }; state.busy = true;
  try {
    state.owner.check(); recordIntent(state, faults); acknowledge(state, faults); commitCancellation(state, faults);
    faults.beforeReturn?.(); state.owner.terminal();
    const result = state.result ?? Object.freeze({ scope: "actual-prelaunch-cancellation-terminal-not-process-cleanup-or-approval" as const,
      claimedJournalHash: state.owner.journal.sha256, cancelledJournalHash: state.owner.journalHash(),
      intent: state.intent!.ref, acknowledgement: state.ack!.ref, claimRetained: false as const,
      mediaSelected: false as const, openingApproved: false as const, deliveryApproved: false as const });
    state.owner.finite(); terminals.set(result, state); state.result = result; return result;
  } finally { state.busy = false; }
}

/** Internal exact controller join. The returned closure is derived only from privately authenticated terminal evidence. */
export function holdSourceColorPrelaunchCancellationTerminal(value: SourceColorPrelaunchCancelled,
  binding: { controller: OpeningControllerLifecycle; claim: unknown; lease: ProjectMutationLease }) {
  const state = terminals.get(value), original = state?.owner.transfer.original;
  if (!state || !original || original.controller !== binding.controller || original.claim !== binding.claim || original.projectLease !== binding.lease) {
    throw new Error("Controller cancellation release requires its actual exact terminal proof");
  }
  state.owner.terminal();
  return Object.freeze({ check: () => state.owner.terminal(), releaseResource: () => state.owner.releaseResource(),
    afterResourceRelease: () => state.owner.afterResourceRelease(),
    afterProjectRelease: () => state.owner.afterResourceRelease() });
}
