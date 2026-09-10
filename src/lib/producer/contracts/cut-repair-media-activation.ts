import {
  exactKeys,
  objectValue,
  sha256,
} from "./validation";

const KEYS = [
  "schemaVersion",
  "kind",
  "promotionActionHash",
  "promotedRevisionHash",
  "renderedCandidateHash",
  "candidateSha256",
  "graphHash",
  "graphReceiptHash",
  "activePointerHash",
] as const;

export interface CutRepairMediaActivationV1 {
  schemaVersion: 1;
  kind: "cut-repair-media-activation";
  promotionActionHash: string;
  promotedRevisionHash: string;
  renderedCandidateHash: string;
  candidateSha256: string;
  graphHash: string;
  graphReceiptHash: string;
  activePointerHash: string;
}

/** Parse the immutable receipt for one exact final/plan/graph activation. */
export function parseCutRepairMediaActivationV1(
  value: unknown,
): CutRepairMediaActivationV1 {
  const row = objectValue(value, "CutRepairMediaActivationV1");
  exactKeys(row, KEYS, KEYS, "CutRepairMediaActivationV1");
  if (row.schemaVersion !== 1
      || row.kind !== "cut-repair-media-activation") {
    throw new Error("cut repair media activation receipt is malformed");
  }
  return {
    schemaVersion: 1,
    kind: "cut-repair-media-activation",
    promotionActionHash: sha256(
      row.promotionActionHash, "activation promotion action"),
    promotedRevisionHash: sha256(
      row.promotedRevisionHash, "activation promoted revision"),
    renderedCandidateHash: sha256(
      row.renderedCandidateHash, "activation rendered candidate"),
    candidateSha256: sha256(row.candidateSha256, "activation final media"),
    graphHash: sha256(row.graphHash, "activation graph"),
    graphReceiptHash: sha256(
      row.graphReceiptHash, "activation graph receipt"),
    activePointerHash: sha256(
      row.activePointerHash, "activation active pointer"),
  };
}
