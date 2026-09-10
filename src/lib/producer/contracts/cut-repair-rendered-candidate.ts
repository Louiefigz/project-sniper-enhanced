import {
  exactKeys,
  objectValue,
  sha256,
} from "./validation";

const KEYS = [
  "schemaVersion", "kind", "status", "operationHash",
  "reviewPlanObjectHash", "reviewPlanContentHash", "reviewTimelineMapHash",
  "reviewRenderGraphHash", "reviewRenderGraphReceiptHash",
  "reviewRenderGraphCandidatePointerHash", "candidatePath",
  "candidateSha256",
] as const;

export interface CutRepairRenderedCandidateV1 {
  schemaVersion: 1;
  kind: "cut-repair-rendered-plan-candidate";
  status: "candidate-proved";
  operationHash: string;
  reviewPlanObjectHash: string;
  reviewPlanContentHash: string;
  reviewTimelineMapHash: string;
  reviewRenderGraphHash: string;
  reviewRenderGraphReceiptHash: string;
  reviewRenderGraphCandidatePointerHash: string;
  candidatePath: string;
  candidateSha256: string;
}

/** Parse the exact full-plan media identity that downstream QC must review. */
export function parseCutRepairRenderedCandidateV1(
  value: unknown,
): CutRepairRenderedCandidateV1 {
  const row = objectValue(value, "CutRepairRenderedCandidateV1");
  exactKeys(row, KEYS, KEYS, "CutRepairRenderedCandidateV1");
  if (row.schemaVersion !== 1
      || row.kind !== "cut-repair-rendered-plan-candidate"
      || row.status !== "candidate-proved"
      || typeof row.candidatePath !== "string"
      || !row.candidatePath) {
    throw new Error("cut repair rendered candidate is malformed");
  }
  return {
    schemaVersion: 1,
    kind: "cut-repair-rendered-plan-candidate",
    status: "candidate-proved",
    operationHash: sha256(
      row.operationHash, "rendered candidate operation"),
    reviewPlanObjectHash: sha256(
      row.reviewPlanObjectHash, "rendered candidate plan object"),
    reviewPlanContentHash: sha256(
      row.reviewPlanContentHash, "rendered candidate plan content"),
    reviewTimelineMapHash: sha256(
      row.reviewTimelineMapHash, "rendered candidate timeline map"),
    reviewRenderGraphHash: sha256(
      row.reviewRenderGraphHash, "rendered candidate graph"),
    reviewRenderGraphReceiptHash: sha256(
      row.reviewRenderGraphReceiptHash, "rendered candidate graph receipt"),
    reviewRenderGraphCandidatePointerHash: sha256(
      row.reviewRenderGraphCandidatePointerHash,
      "rendered candidate graph pointer",
    ),
    candidatePath: row.candidatePath,
    candidateSha256: sha256(
      row.candidateSha256, "rendered candidate media"),
  };
}
