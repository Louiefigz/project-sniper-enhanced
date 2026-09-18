import {
  exactKeys,
  isoDate,
  objectValue,
  sha256,
  stableId,
} from "./validation";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";

export interface PalmierSagaCandidateProofV1 {
  schemaVersion: 1;
  ok: true;
  status: "saga-candidate-proved";
  projectId: string;
  expectedParentId: string;
  expectedParentTimelineHash: string;
  candidateId: string;
  candidateHash: string;
  timelineHash: string;
  approvalDigest: string;
  manifestHash: string;
  inputAuthorityDigest: string;
  transcriptTimingHash: string;
  nativePlanHash: string;
  canvasProfileHash: string;
  provedAt: string;
}

export interface PalmierSagaObservationV1 {
  schemaVersion: 1;
  ok: true;
  status: "saga-head-observed";
  headId: string;
  candidateHash: string | null;
  timelineHash: string | null;
  observedAt: string;
}

const PROOF_KEYS = [
  "schemaVersion", "ok", "status", "projectId", "expectedParentId",
  "expectedParentTimelineHash", "candidateId", "candidateHash",
  "timelineHash", "approvalDigest", "manifestHash",
  "inputAuthorityDigest", "transcriptTimingHash", "nativePlanHash",
  "canvasProfileHash", "provedAt",
] as const;
const OBSERVATION_KEYS = [
  "schemaVersion", "ok", "status", "headId", "candidateHash",
  "timelineHash", "observedAt",
] as const;

function exactEnvelope(
  value: unknown,
  keys: readonly string[],
  status: string,
  label: string,
): Record<string, unknown> {
  const row = objectValue(value, label);
  exactKeys(row, keys, keys, label);
  if (row.schemaVersion !== 1 || row.ok !== true || row.status !== status) {
    throw new Error(`${label} has an unsupported envelope`);
  }
  return row;
}

function nullableHash(value: unknown, label: string): string | null {
  return value === null ? null : sha256(value, label);
}

export function palmierCandidateReservationValue(
  proof: Omit<PalmierSagaCandidateProofV1,
    "candidateHash" | "provedAt" | "ok" | "status">,
): Record<string, unknown> {
  return {
    schemaVersion: proof.schemaVersion,
    projectId: proof.projectId,
    expectedParentId: proof.expectedParentId,
    expectedParentTimelineHash: proof.expectedParentTimelineHash,
    candidateId: proof.candidateId,
    timelineHash: proof.timelineHash,
    approvalDigest: proof.approvalDigest,
    manifestHash: proof.manifestHash,
    inputAuthorityDigest: proof.inputAuthorityDigest,
    transcriptTimingHash: proof.transcriptTimingHash,
    nativePlanHash: proof.nativePlanHash,
    canvasProfileHash: proof.canvasProfileHash,
  };
}

/** Parse and independently re-hash one live candidate proof event. */
export function parsePalmierSagaCandidateProofV1(
  value: unknown,
): PalmierSagaCandidateProofV1 {
  const row = exactEnvelope(
    value, PROOF_KEYS, "saga-candidate-proved",
    "PalmierSagaCandidateProofV1",
  );
  const stable = {
    schemaVersion: 1 as const,
    projectId: stableId(row.projectId, "projectId"),
    expectedParentId: stableId(row.expectedParentId, "expectedParentId"),
    expectedParentTimelineHash: sha256(
      row.expectedParentTimelineHash, "expectedParentTimelineHash"),
    candidateId: stableId(row.candidateId, "candidateId"),
    timelineHash: sha256(row.timelineHash, "timelineHash"),
    approvalDigest: sha256(row.approvalDigest, "approvalDigest"),
    manifestHash: sha256(row.manifestHash, "manifestHash"),
    inputAuthorityDigest: sha256(
      row.inputAuthorityDigest, "inputAuthorityDigest"),
    transcriptTimingHash: sha256(
      row.transcriptTimingHash, "transcriptTimingHash"),
    nativePlanHash: sha256(row.nativePlanHash, "nativePlanHash"),
    canvasProfileHash: sha256(row.canvasProfileHash, "canvasProfileHash"),
  };
  const candidateHash = sha256(row.candidateHash, "candidateHash");
  if (candidateHash !== canonicalJsonSha256(
    palmierCandidateReservationValue(stable))) {
    throw new Error("Palmier candidate proof hash does not match its reservation");
  }
  return {
    ...stable,
    ok: true,
    status: "saga-candidate-proved",
    candidateHash,
    provedAt: isoDate(row.provedAt, "provedAt"),
  };
}

/** Parse one active-head observation; partial hashes remain explicit. */
export function parsePalmierSagaObservationV1(
  value: unknown,
): PalmierSagaObservationV1 {
  const row = exactEnvelope(
    value, OBSERVATION_KEYS, "saga-head-observed",
    "PalmierSagaObservationV1",
  );
  return {
    schemaVersion: 1,
    ok: true,
    status: "saga-head-observed",
    headId: stableId(row.headId, "headId"),
    candidateHash: nullableHash(row.candidateHash, "candidateHash"),
    timelineHash: nullableHash(row.timelineHash, "timelineHash"),
    observedAt: isoDate(row.observedAt, "observedAt"),
  };
}
