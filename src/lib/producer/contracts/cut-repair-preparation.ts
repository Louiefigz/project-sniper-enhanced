import {
  parseCutRepairReviewActionV1,
  type CutRepairReviewActionV1,
} from "./cut-repair-review-transition";
import {
  exactKeys,
  isoDate,
  objectValue,
  sha256,
  uniqueStrings,
  uuid,
} from "./validation";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";

export const CUT_REPAIR_PREPARATION_BLOCKERS = [
  "alignment-qc",
  "vad-qc",
  "retranscription-qc",
  "seam-qc",
  "cut-review-staging",
  "operator-audition",
  "promotion-package-sealing",
  "final-media-activation",
] as const;

export interface CutRepairPreparationPackageV1 {
  schemaVersion: 1;
  kind: "cut-repair-preparation-package";
  status: "rendered-plan-candidate-prepared";
  idempotencyKey: string;
  targetDirectiveHash: string;
  contextAuthorityHash: string;
  contextObjectHash: string;
  analysisObjectHash: string;
  parentRevisionHash: string;
  proposedReviewAction: CutRepairReviewActionV1;
  reviewProjectionHash: string;
  renderInvalidationStrategy:
    | "dialogue-stem"
    | "base-segment-fallback"
    | "picture-surgical-terminal";
  fragmentReceipt: Record<string, unknown>;
  compositeReceipt: Record<string, unknown>;
  fragmentMediaSha256: string;
  compositeMediaSha256: string;
  reviewRenderGraphReceiptHash: string;
  reviewRenderGraphCandidatePointerHash: string;
  reviewCandidateMediaSha256: string;
  reviewCandidatePath: string;
  reviewCandidateDescriptorHash: string;
  reviewCandidateDescriptorPath: string;
  previousRenderGraphHash: string | null;
  previousRenderGraphReceiptHash: string | null;
  blockingRequirements: string[];
  preparedAt: string;
}

const KEYS = [
  "schemaVersion", "kind", "status", "idempotencyKey",
  "targetDirectiveHash", "contextAuthorityHash", "contextObjectHash",
  "analysisObjectHash", "parentRevisionHash", "proposedReviewAction",
  "reviewProjectionHash", "renderInvalidationStrategy",
  "fragmentReceipt", "compositeReceipt", "fragmentMediaSha256",
  "compositeMediaSha256", "reviewRenderGraphReceiptHash",
  "reviewRenderGraphCandidatePointerHash", "reviewCandidateMediaSha256",
  "reviewCandidatePath", "reviewCandidateDescriptorHash",
  "reviewCandidateDescriptorPath", "previousRenderGraphHash",
  "previousRenderGraphReceiptHash", "blockingRequirements", "preparedAt",
] as const;

function nullableHash(value: unknown, label: string): string | null {
  return value === null ? null : sha256(value, label);
}

interface MediaReceiptExpectation {
  kind: string;
  operationHash: string;
  expectedHash: string;
  label: string;
}

function mediaReceipt(
  value: unknown,
  expected: MediaReceiptExpectation,
): Record<string, unknown> {
  const receipt = objectValue(value, expected.label);
  const output = objectValue(
    receipt.output, `${expected.label}.output`);
  if (receipt.schemaVersion !== 1 || receipt.kind !== expected.kind
      || receipt.operationHash !== expected.operationHash
      || receipt.exactOutputDurationPreserved !== true
      || output.sha256 !== expected.expectedHash
      || typeof output.path !== "string") {
    throw new Error(`${expected.label} does not bind the prepared media`);
  }
  return receipt;
}

function mediaFields(
  row: Record<string, unknown>,
  action: CutRepairReviewActionV1,
) {
  const fragmentHash = sha256(
    row.fragmentMediaSha256, "preparation fragment media");
  const compositeHash = sha256(
    row.compositeMediaSha256, "preparation composite media");
  return {
    fragmentReceipt: mediaReceipt(row.fragmentReceipt, {
      kind: "cut-repair-fragment", operationHash: action.operationHash,
      expectedHash: fragmentHash, label: "preparation fragment receipt",
    }),
    compositeReceipt: mediaReceipt(row.compositeReceipt, {
      kind: "cut-repair-composite", operationHash: action.operationHash,
      expectedHash: compositeHash, label: "preparation composite receipt",
    }),
    fragmentMediaSha256: fragmentHash,
    compositeMediaSha256: compositeHash,
  };
}

function blockers(row: Record<string, unknown>): string[] {
  const parsed = uniqueStrings(
    row.blockingRequirements,
    "preparation blocking requirements",
    (item, label) => {
      if (typeof item !== "string"
          || !CUT_REPAIR_PREPARATION_BLOCKERS.includes(
            item as typeof CUT_REPAIR_PREPARATION_BLOCKERS[number])) {
        throw new Error(`${label} is unsupported`);
      }
      return item;
    },
  );
  if (JSON.stringify(parsed)
      !== JSON.stringify(CUT_REPAIR_PREPARATION_BLOCKERS)) {
    throw new Error("cut repair preparation blockers are incomplete");
  }
  return parsed;
}

function strategy(
  row: Record<string, unknown>,
): CutRepairPreparationPackageV1["renderInvalidationStrategy"] {
  if (row.renderInvalidationStrategy !== "dialogue-stem"
      && row.renderInvalidationStrategy !== "base-segment-fallback"
      && row.renderInvalidationStrategy !== "picture-surgical-terminal") {
    throw new Error("cut repair render invalidation strategy is unsupported");
  }
  return row.renderInvalidationStrategy;
}

function renderFields(row: Record<string, unknown>) {
  const previousGraphHash = nullableHash(
    row.previousRenderGraphHash, "preparation previous render graph");
  const previousReceiptHash = nullableHash(
    row.previousRenderGraphReceiptHash,
    "preparation previous render graph receipt");
  if ((previousGraphHash === null) !== (previousReceiptHash === null)
      || typeof row.reviewCandidatePath !== "string"
      || !row.reviewCandidatePath
      || typeof row.reviewCandidateDescriptorPath !== "string"
      || !row.reviewCandidateDescriptorPath) {
    throw new Error("cut repair prepared render ancestry is malformed");
  }
  return {
    reviewRenderGraphReceiptHash: sha256(
      row.reviewRenderGraphReceiptHash,
      "preparation review render graph receipt"),
    reviewRenderGraphCandidatePointerHash: sha256(
      row.reviewRenderGraphCandidatePointerHash,
      "preparation review render graph candidate pointer"),
    reviewCandidateMediaSha256: sha256(
      row.reviewCandidateMediaSha256, "preparation review candidate media"),
    reviewCandidatePath: row.reviewCandidatePath,
    reviewCandidateDescriptorHash: sha256(
      row.reviewCandidateDescriptorHash,
      "preparation review candidate descriptor"),
    reviewCandidateDescriptorPath: row.reviewCandidateDescriptorPath,
    previousRenderGraphHash: previousGraphHash,
    previousRenderGraphReceiptHash: previousReceiptHash,
  };
}

function identityFields(row: Record<string, unknown>) {
  return {
    idempotencyKey: uuid(
      row.idempotencyKey, "preparation idempotency key"),
    targetDirectiveHash: sha256(
      row.targetDirectiveHash, "preparation target directive"),
    contextAuthorityHash: sha256(
      row.contextAuthorityHash, "preparation context authority"),
    contextObjectHash: sha256(
      row.contextObjectHash, "preparation context object"),
    analysisObjectHash: sha256(
      row.analysisObjectHash, "preparation analysis object"),
    parentRevisionHash: sha256(
      row.parentRevisionHash, "preparation parent revision"),
    reviewProjectionHash: sha256(
      row.reviewProjectionHash, "preparation projection"),
  };
}

/** Parse a private full-plan candidate that still requires every QC gate. */
export function parseCutRepairPreparationPackageV1(
  value: unknown,
): CutRepairPreparationPackageV1 {
  const row = objectValue(value, "CutRepairPreparationPackageV1");
  exactKeys(row, KEYS, KEYS, "CutRepairPreparationPackageV1");
  if (row.schemaVersion !== 1
      || row.kind !== "cut-repair-preparation-package"
      || row.status !== "rendered-plan-candidate-prepared") {
    throw new Error("cut repair preparation package version is unsupported");
  }
  const action = parseCutRepairReviewActionV1(row.proposedReviewAction);
  if (action.expectedParentRevisionHash !== row.parentRevisionHash
      || canonicalJsonSha256(action.operation) !== action.operationHash) {
    throw new Error("cut repair preparation proposed review is stale");
  }
  return {
    schemaVersion: 1,
    kind: "cut-repair-preparation-package",
    status: "rendered-plan-candidate-prepared",
    ...identityFields(row),
    proposedReviewAction: action,
    renderInvalidationStrategy: strategy(row),
    ...mediaFields(row, action),
    ...renderFields(row),
    blockingRequirements: blockers(row),
    preparedAt: isoDate(row.preparedAt, "preparation preparedAt"),
  };
}
