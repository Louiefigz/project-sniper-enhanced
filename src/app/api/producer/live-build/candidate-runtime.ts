import type { TimelineIdentity } from "./authority";
import {
  observeLiveBuildCandidate,
  prepareLiveBuildCandidate,
} from "./candidate";
import {
  appendLiveBuildHead,
  emptyLiveBuildJournal,
  type LiveBuildJournalLedger,
} from "./journal";
import type { LiveBuildPreflight } from "./preflight";
import { reconcileLiveBuildResume } from "./reconciliation";
import {
  assertLiveBuildRequest,
  prepareLiveBuildState,
  restartLiveBuildSession,
  type LiveBuildState,
} from "./state";

export interface LiveBuildCandidateRuntime {
  parent: TimelineIdentity;
  candidate: TimelineIdentity;
  state: LiveBuildState;
  ledger: LiveBuildJournalLedger;
}

function parentIdentity(input: LiveBuildPreflight): TimelineIdentity {
  return {
    projectId: input.projectId,
    timelineId: input.timelineId,
    fingerprint: input.timelineFingerprint,
  };
}

function sameIdentity(
  left: TimelineIdentity,
  right: TimelineIdentity,
): boolean {
  return left.projectId === right.projectId
    && left.timelineId === right.timelineId
    && left.fingerprint === right.fingerprint;
}

function stateInput(
  input: LiveBuildPreflight,
  parent: TimelineIdentity,
  candidate: TimelineIdentity,
) {
  return {
    dir: input.dir,
    planHash: input.planHash,
    doctrineHash: input.doctrineHash,
    projectId: input.projectId,
    projectPath: input.projectPath,
    parentTimelineId: parent.timelineId,
    parentFingerprint: parent.fingerprint,
    candidateTimelineId: candidate.timelineId,
    candidateFingerprint: candidate.fingerprint,
    priorSessionId: input.priorSessionId,
  };
}

function requestInput(
  input: LiveBuildPreflight,
  parent: TimelineIdentity,
) {
  return {
    dir: input.dir,
    planHash: input.planHash,
    doctrineHash: input.doctrineHash,
    projectId: input.projectId,
    projectPath: input.projectPath,
    parentTimelineId: parent.timelineId,
    parentFingerprint: parent.fingerprint,
  };
}

async function freshRuntime(
  input: LiveBuildPreflight,
  parent: TimelineIdentity,
  signal?: AbortSignal,
): Promise<LiveBuildCandidateRuntime> {
  const prepared = await prepareLiveBuildCandidate(input, false, signal);
  if (!sameIdentity(prepared.parent, parent)) {
    throw new Error(
      "Palmier changed between live-build preflight and candidate fork.");
  }
  const state = prepareLiveBuildState(
    stateInput(input, parent, prepared.candidate), false);
  const ledger = emptyLiveBuildJournal();
  appendLiveBuildHead(
    input.dir, ledger, prepared.candidate.fingerprint);
  return { parent, candidate: prepared.candidate, state, ledger };
}

async function resumedRuntime(
  input: LiveBuildPreflight,
  parent: TimelineIdentity,
  retained: LiveBuildState,
  signal?: AbortSignal,
): Promise<LiveBuildCandidateRuntime> {
  const observed = await observeLiveBuildCandidate(input, signal);
  if (!sameIdentity(observed.parent, parent)) {
    throw new Error(
      "Palmier parent changed before live-build resume reconciliation.");
  }
  const reconciled = reconcileLiveBuildResume(
    input.dir, retained, observed.candidate);
  const prepared = await prepareLiveBuildCandidate(
    input, true, signal, observed.candidate.fingerprint);
  if (!sameIdentity(prepared.parent, parent)
      || !sameIdentity(prepared.candidate, observed.candidate)) {
    throw new Error(
      "Palmier changed after live-build resume reconciliation.");
  }
  let state = prepareLiveBuildState(
    stateInput(input, parent, prepared.candidate), true);
  if (reconciled.restartSession) {
    state = restartLiveBuildSession(input.dir);
  }
  return {
    parent,
    candidate: prepared.candidate,
    state,
    ledger: reconciled.ledger,
  };
}

/** Fork or resume only after the exact retained journal/readback gate. */
export async function prepareLiveBuildCandidateRuntime(
  input: LiveBuildPreflight,
  resume: boolean,
  signal?: AbortSignal,
): Promise<LiveBuildCandidateRuntime> {
  const parent = parentIdentity(input);
  const retained = assertLiveBuildRequest(
    requestInput(input, parent), resume);
  if (!resume) return freshRuntime(input, parent, signal);
  if (!retained) {
    throw new Error("Palmier live-build retained state disappeared.");
  }
  return resumedRuntime(input, parent, retained, signal);
}

export { sameIdentity as sameLiveBuildTimelineIdentity };
