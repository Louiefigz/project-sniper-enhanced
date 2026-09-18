import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { cutRestoreAction } from "./_cut-restore-speech-fixture";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";

const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)), "../../../..");
const hash = (value: string): string => value.repeat(64);
const uuid = (value: string): string =>
  `${value}0000000-0000-4000-8000-000000000001`;
const operation = cutRestoreAction(hash("1"), hash("2"));
const policy = {
  schemaVersion: 1,
  kind: "cut-repair-selection-policy",
  order: [
    "audio-only-before-picture",
    "fewest-picture-dirty-frames",
    "fewest-audio-dirty-frames",
    "shortest-source-extension",
    "operation-hash-tiebreak",
  ],
};
const review = {
  schemaVersion: 1,
  kind: "cut-repair-review-action",
  idempotencyKey: uuid("3"),
  expectedParentRevisionHash: hash("4"),
  operation,
  operationHash: canonicalJsonSha256(operation),
  selectionPolicy: policy,
  selectionPolicyHash: canonicalJsonSha256(policy),
  reviewPlanObjectHash: hash("5"),
  reviewPlanContentHash: hash("0"),
  reviewTimelineMapHash: hash("6"),
  reviewRenderGraphHash: hash("7"),
  reviewProjectionReceiptHash: null,
  workflowPolicy: "cut-first",
  requestedAt: "2026-07-29T12:00:00.000Z",
};
const promotion = {
  schemaVersion: 1,
  kind: "cut-repair-promotion-action",
  idempotencyKey: uuid("8"),
  expectedReviewRevisionHash: hash("9"),
  reviewActionHash: canonicalJsonSha256(review),
  operationHash: review.operationHash,
  selectionPolicyHash: review.selectionPolicyHash,
  selectedApproval: {
    approver: "operator",
    approvalPolicyHash: hash("a"),
    approvalReceiptHash: hash("b"),
  },
  childPictureLockHash: hash("c"),
  candidateHash: canonicalJsonSha256({ candidate: true }),
  promotionEvidenceHash: canonicalJsonSha256({ approved: true }),
  requestedAt: "2026-07-29T12:01:00.000Z",
};
const receipt = {
  schemaVersion: 1,
  kind: "cut-repair-transition-receipt",
  status: "PICTURE_LOCKED_COMMITTED",
  idempotencyKey: promotion.idempotencyKey,
  actionHash: canonicalJsonSha256(promotion),
  expectedParentRevisionHash: promotion.expectedReviewRevisionHash,
  childRevisionHash: hash("d"),
  originalPictureLockedParentHash: review.expectedParentRevisionHash,
  operationHash: review.operationHash,
  selectionPolicyHash: review.selectionPolicyHash,
  childPictureLockHash: promotion.childPictureLockHash,
  recordedAt: promotion.requestedAt,
};
const packageValue = {
  schemaVersion: 1,
  kind: "cut-repair-execution-package",
  targetDirectiveHash: hash("e"),
  contextAuthorityHash: hash("f"),
  parentRevisionHash: review.expectedParentRevisionHash,
  reviewAction: review,
  promotionAction: promotion,
  candidate: { candidate: true },
  promotionEvidence: { approved: true },
};
const renderedCandidate = {
  schemaVersion: 1,
  kind: "cut-repair-rendered-plan-candidate",
  status: "candidate-proved",
  operationHash: review.operationHash,
  reviewPlanObjectHash: review.reviewPlanObjectHash,
  reviewPlanContentHash: review.reviewPlanContentHash,
  reviewTimelineMapHash: review.reviewTimelineMapHash,
  reviewRenderGraphHash: review.reviewRenderGraphHash,
  reviewRenderGraphReceiptHash: hash("6"),
  reviewRenderGraphCandidatePointerHash: hash("7"),
  candidatePath: "/private/review-candidate.mp4",
  candidateSha256: hash("8"),
};
const preparation = {
  schemaVersion: 1,
  kind: "cut-repair-preparation-package",
  status: "rendered-plan-candidate-prepared",
  idempotencyKey: review.idempotencyKey,
  targetDirectiveHash: hash("e"),
  contextAuthorityHash: hash("f"),
  contextObjectHash: hash("1"),
  analysisObjectHash: hash("2"),
  parentRevisionHash: review.expectedParentRevisionHash,
  proposedReviewAction: review,
  reviewProjectionHash: hash("3"),
  renderInvalidationStrategy: "dialogue-stem",
  fragmentReceipt: {},
  compositeReceipt: {},
  fragmentMediaSha256: hash("4"),
  compositeMediaSha256: hash("5"),
  reviewRenderGraphReceiptHash: renderedCandidate.reviewRenderGraphReceiptHash,
  reviewRenderGraphCandidatePointerHash:
    renderedCandidate.reviewRenderGraphCandidatePointerHash,
  reviewCandidateMediaSha256: renderedCandidate.candidateSha256,
  reviewCandidatePath: renderedCandidate.candidatePath,
  reviewCandidateDescriptorHash: hash("9"),
  reviewCandidateDescriptorPath: "/private/review-candidate.json",
  previousRenderGraphHash: null,
  previousRenderGraphReceiptHash: null,
  blockingRequirements: [
    "alignment-qc",
    "vad-qc",
    "retranscription-qc",
    "seam-qc",
    "cut-review-staging",
    "operator-audition",
    "promotion-package-sealing",
    "final-media-activation",
  ],
  preparedAt: review.requestedAt,
};
const rippleImpact = {
  exact: true,
  requiredDurationDeltaFrames: 12,
  newTotalOutputFrames: 312,
  rippleFromFrame: 150,
  reopensPictureLock: true,
  semanticClosureRequired: true,
  movedDependents: [{
    stableId: "graphic-after",
    elementKind: "graphic",
    from: { startFrame: 160, endFrameExclusive: 180 },
    to: { startFrame: 172, endFrameExclusive: 192 },
  }],
  invalidatedDependents: ["caption-crossing"],
  unchangedOutputLockedIds: ["title-output-locked"],
};
const rippleAnalysis = {
  schemaVersion: 1,
  operation: "cut.restoreSpeech",
  status: "NON_RIPPLE_IMPOSSIBLE",
  resolvedTarget: {
    kind: "word-range",
    sourceId: "raw",
    wordIds: ["w-1234567890abcdef"],
    occurrence: 1,
    sourceSampleRange: {
      startSample: 230_400,
      endSampleExclusive: 232_000,
    },
    transcriptTimingHash: hash("1"),
  },
  candidates: [],
  recommendedCandidate: null,
  rippleImpact,
  evidencePolicy: {
    alignment: "bounded-evidence-not-sole-audibility-proof",
    operatorReport: "ground-truth-when-audition-disagrees",
  },
  routeStatus: "analysis-only-no-mutation",
  contextAuthorityHash: hash("2"),
  parentRevisionHash: hash("3"),
};
const rippleTarget = {
  phrase: "the clipped phrase",
  sourceId: "raw",
  occurrence: 1,
};
const rippleAction = {
  schemaVersion: 1,
  kind: "cut-repair-ripple-reopen-action",
  idempotencyKey: uuid("7"),
  expectedParentRevisionHash: rippleAnalysis.parentRevisionHash,
  parentPictureLockHash: hash("4"),
  target: rippleTarget,
  targetHash: canonicalJsonSha256(rippleTarget),
  analysis: rippleAnalysis,
  analysisHash: canonicalJsonSha256(rippleAnalysis),
  impactHash: canonicalJsonSha256(rippleImpact),
  preservedPlanObjectHash: hash("5"),
  preservedPlanContentHash: hash("6"),
  preservedTimelineMapHash: hash("7"),
  preservedRenderGraphHash: hash("8"),
  preservedProjectionReceiptHash: hash("9"),
  requestedAt: "2026-07-30T12:00:00.000Z",
};
const rippleReceipt = {
  schemaVersion: 1,
  kind: "cut-repair-ripple-reopen-receipt",
  status: "CUT_DRAFT_REOPENED",
  idempotencyKey: rippleAction.idempotencyKey,
  actionHash: canonicalJsonSha256(rippleAction),
  expectedParentRevisionHash: rippleAction.expectedParentRevisionHash,
  childRevisionHash: hash("a"),
  originalPictureLockHash: rippleAction.parentPictureLockHash,
  analysisHash: rippleAction.analysisHash,
  impactHash: rippleAction.impactHash,
  preservedPlanObjectHash: rippleAction.preservedPlanObjectHash,
  preservedPlanContentHash: rippleAction.preservedPlanContentHash,
  preservedTimelineMapHash: rippleAction.preservedTimelineMapHash,
  preservedRenderGraphHash: rippleAction.preservedRenderGraphHash,
  preservedProjectionReceiptHash:
    rippleAction.preservedProjectionReceiptHash,
  affectedDependentIds: ["graphic-after", "caption-crossing"],
  unchangedOutputLockedIds: ["title-output-locked"],
  recordedAt: rippleAction.requestedAt,
};
const documents = [
  ["cut-repair-review-action-v1.schema.json", review],
  ["cut-repair-promotion-action-v1.schema.json", promotion],
  ["cut-repair-transition-receipt-v1.schema.json", receipt],
  ["cut-repair-execution-package-v1.schema.json", packageValue],
  ["cut-repair-rendered-candidate-v1.schema.json", renderedCandidate],
  ["cut-repair-preparation-package-v1.schema.json", preparation],
  ["cut-repair-ripple-impact-v1.schema.json", rippleImpact],
  ["cut-repair-ripple-analysis-v1.schema.json", rippleAnalysis],
  ["cut-repair-ripple-reopen-action-v1.schema.json", rippleAction],
  ["cut-repair-ripple-reopen-receipt-v1.schema.json", rippleReceipt],
] as const;
const cases = documents.flatMap(([schema, document]) => [
  { schema, document },
  { schema, document: { ...document, unexpected: true } },
]);
const python = spawnSync(
  path.join(root, ".venv", "bin", "python3"),
  [path.join(root, "scripts", "producer", "contracts", "schema_validator.py"),
    "--batch"],
  { cwd: root, input: JSON.stringify(cases), encoding: "utf8" },
);
assert.equal(python.status, 0, python.stderr);
const results = JSON.parse(python.stdout) as Array<{
  valid: boolean;
  error?: string;
}>;
for (let index = 0; index < results.length; index += 2) {
  assert.equal(results[index].valid, true, results[index].error);
  assert.equal(results[index + 1].valid, false);
}
console.log("p2-transition-schema-parity tests passed");
