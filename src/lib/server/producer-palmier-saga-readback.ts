import type {
  PalmierActivationReadbackV1,
  PalmierCommitSagaV1,
} from "@/lib/producer/contracts/palmier-commit-saga";

export interface PalmierObservedHeadV1 {
  headId: string;
  candidateHash: string | null;
  timelineHash: string | null;
  observedAt: string;
}

export function exactPalmierReadback(
  saga: PalmierCommitSagaV1,
  observed: PalmierObservedHeadV1,
): PalmierActivationReadbackV1 | null {
  if (observed.headId !== saga.reservedPalmierCandidateId
      || observed.candidateHash !== saga.reservedPalmierCandidateHash
      || observed.timelineHash !== saga.reservedPalmierTimelineHash) return null;
  return {
    headId: observed.headId,
    candidateHash: observed.candidateHash,
    timelineHash: observed.timelineHash,
    observedAt: observed.observedAt,
  };
}

export function unreadableObservation(
  label: string,
  error: unknown,
): string {
  const detail = error instanceof Error ? error.message : String(error);
  return `${label} is unreadable: ${detail}`.slice(0, 2_000);
}
