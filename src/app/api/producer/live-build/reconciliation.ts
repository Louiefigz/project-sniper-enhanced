import { fileSha256 } from "@/lib/server/auto-edit-hash";
import type { TimelineIdentity } from "./authority";
import {
  appendLiveBuildHead,
  latestLiveBuildHead,
  liveBuildJournalCounts,
  operationsAfterHead,
  readStrictLiveBuildJournal,
  verifiedLiveBuildOperations,
  type LiveBuildJournalLedger,
} from "./journal";
import {
  liveBuildJournalPath,
  patchLiveBuildState,
  type LiveBuildReconciliation,
  type LiveBuildResumeAuthority,
  type LiveBuildState,
} from "./state";

export class LiveBuildReconciliationError extends Error {}

export interface ReconciledLiveBuildResume {
  ledger: LiveBuildJournalLedger;
  state: LiveBuildState;
  restartSession: boolean;
}

interface PauseInput {
  reason: string;
  expectedFingerprint: string | null;
  observedFingerprint: string | null;
  operationIds: string[];
}

function pauseValue(input: PauseInput): LiveBuildReconciliation {
  return {
    schemaVersion: 1,
    status: "paused",
    reason: input.reason,
    expectedFingerprint: input.expectedFingerprint,
    observedFingerprint: input.observedFingerprint,
    operationIds: [...new Set(input.operationIds)].sort(),
    resolutionOwner: "external-operator",
    automaticResumeAllowed: false,
    resolutionActions: [
      "external-adopt-visible-head",
      "external-adopt-visible-head-and-fork-candidate",
    ],
  };
}

/** Preserve the visible head and require explicit adoption/fork semantics. */
export function pauseLiveBuildReconciliation(
  dir: string,
  input: PauseInput,
): never {
  const reconciliation = pauseValue(input);
  patchLiveBuildState(dir, {
    status: "reconciliation_required",
    reconciliation,
    error: `Palmier live build paused: ${input.reason}`,
  });
  throw new LiveBuildReconciliationError(
    "Palmier live build paused before replay. This route cannot adopt the "
      + "visible head automatically; external operator adoption or an "
      + "external adopted-head fork is required.");
}

function readLedgerOrPause(
  dir: string,
  state: LiveBuildState,
  observed: TimelineIdentity,
): LiveBuildJournalLedger {
  try {
    return readStrictLiveBuildJournal(dir);
  } catch (error) {
    return pauseLiveBuildReconciliation(dir, {
      reason: `journal-unreadable: ${(error as Error).message}`,
      expectedFingerprint: state.latestFingerprint,
      observedFingerprint: observed.fingerprint,
      operationIds: [],
    });
  }
}

function identitiesMatch(
  state: LiveBuildState,
  observed: TimelineIdentity,
): boolean {
  return state.projectId === observed.projectId
    && state.candidateTimelineId === observed.timelineId;
}

function changedHeadReason(
  operations: ReturnType<typeof operationsAfterHead>,
): string {
  if (!operations.length) return "manual-or-foreign-candidate-drift";
  if (operations.some((operation) => operation.status === "applying")) {
    return "applying-operation-has-ambiguous-visible-effect";
  }
  return "uncheckpointed-operation-or-manual-drift";
}

function resumeAuthority(
  dir: string,
  ledger: LiveBuildJournalLedger,
  fingerprint: string,
  resolved: string[],
): LiveBuildResumeAuthority {
  const journalHash = fileSha256(liveBuildJournalPath(dir));
  if (!journalHash) {
    throw new LiveBuildReconciliationError(
      "Palmier live-build journal disappeared after reconciliation.");
  }
  return {
    schemaVersion: 1,
    journalHash,
    headFingerprint: fingerprint,
    verifiedOperations: verifiedLiveBuildOperations(ledger),
    resolvedNotAppliedIds: [...resolved].sort(),
  };
}

function stateFingerprintWasJournaled(
  state: LiveBuildState,
  ledger: LiveBuildJournalLedger,
): boolean {
  return ledger.heads.some(
    (head) => head.fingerprint === state.latestFingerprint);
}

function resumeHead(
  dir: string,
  state: LiveBuildState,
  observed: TimelineIdentity,
  ledger: LiveBuildJournalLedger,
): NonNullable<ReturnType<typeof latestLiveBuildHead>> {
  const head = latestLiveBuildHead(ledger);
  if (head && stateFingerprintWasJournaled(state, ledger)
      && identitiesMatch(state, observed)) return head;
  return pauseLiveBuildReconciliation(dir, {
    reason: !head
      ? "journal-has-no-controller-readback-head"
      : "retained-state-or-candidate-identity-is-foreign",
    expectedFingerprint: head?.fingerprint ?? state.latestFingerprint,
    observedFingerprint: observed.fingerprint,
    operationIds: [],
  });
}

/** Reconcile journal lifecycle with fresh readback before receipt refresh. */
export function reconcileLiveBuildResume(
  dir: string,
  state: LiveBuildState,
  observed: TimelineIdentity,
): ReconciledLiveBuildResume {
  if (state.status === "reconciliation_required") {
    throw new LiveBuildReconciliationError(
      "Palmier live build remains blocked for external operator adoption.");
  }
  const ledger = readLedgerOrPause(dir, state, observed);
  const head = resumeHead(dir, state, observed, ledger);
  const afterHead = operationsAfterHead(ledger);
  if (observed.fingerprint !== head.fingerprint) {
    return pauseLiveBuildReconciliation(dir, {
      reason: changedHeadReason(afterHead),
      expectedFingerprint: head.fingerprint,
      observedFingerprint: observed.fingerprint,
      operationIds: afterHead.map((operation) => operation.operationId),
    });
  }
  const noDelta = afterHead.filter(
    (operation) => operation.status === "applied");
  if (noDelta.length) {
    return pauseLiveBuildReconciliation(dir, {
      reason: "applied-operation-produced-no-candidate-delta",
      expectedFingerprint: head.fingerprint,
      observedFingerprint: observed.fingerprint,
      operationIds: noDelta.map((operation) => operation.operationId),
    });
  }
  const resolved = afterHead
    .filter((operation) => ["applying", "failed"].includes(operation.status))
    .map((operation) => operation.operationId);
  appendLiveBuildHead(dir, ledger, observed.fingerprint, resolved);
  const counts = liveBuildJournalCounts(ledger);
  const authority = resumeAuthority(
    dir, ledger, observed.fingerprint, resolved);
  const next = patchLiveBuildState(dir, {
    latestFingerprint: observed.fingerprint,
    operationsSeen: counts.operationsSeen,
    operationsCompleted: counts.operationsCompleted,
    resumeAuthority: authority,
    reconciliation: undefined,
    error: undefined,
  });
  return { ledger, state: next, restartSession: resolved.length > 0 };
}

export function pauseLiveBuildRuntimeViolation(
  dir: string,
  state: LiveBuildState,
  error: unknown,
  operationIds: string[],
): never {
  return pauseLiveBuildReconciliation(dir, {
    reason: `runtime-journal-conflict: ${(error as Error).message}`,
    expectedFingerprint: state.latestFingerprint,
    observedFingerprint: null,
    operationIds,
  });
}

export function pauseLiveBuildNoDelta(
  dir: string,
  state: LiveBuildState,
  observedFingerprint: string,
  operationIds: string[],
): never {
  return pauseLiveBuildReconciliation(dir, {
    reason: "applied-operation-produced-no-candidate-delta",
    expectedFingerprint: state.latestFingerprint,
    observedFingerprint,
    operationIds,
  });
}
