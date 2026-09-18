import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { planObjectContentHash } from "../auto-edit-authority";
import { parseCutRestoreSpeechV1 } from
  "@/lib/producer/contracts/cut-restore-speech-v1";
import { parseProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import {
  cutRestoreAction,
  fixtureSha,
} from "@/lib/producer/__tests__/_cut-restore-speech-fixture";
import {
  promoteCutRepairReviewSync,
  recoverCutRepairPromotionSync,
} from "../cut-repair-promotion-store";
import {
  recoverCutRepairReviewSync,
  stageCutRepairReviewSync,
} from "../cut-repair-review-store";
import type { CutRepairTransitionBoundary } from
  "../cut-repair-transition-store";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
  writeAuthorityObjectSync,
} from "../producer-authority-files";
import { resolveProducerAuthorityHeadSync } from "../producer-revision-head";
import { assertNoPendingCutRepairTransitionSync } from
  "../cut-repair-transition-reconciliation";
import {
  bootstrapRevisionFixture,
  cleanRevisionFixture,
  revisionCommitInput,
} from "./_producer-revision-fixture";
import { cutRepairProofFixture } from
  "./_p2-cut-repair-promotion-fixture";

const ORDER = [
  "audio-only-before-picture",
  "fewest-picture-dirty-frames",
  "fewest-audio-dirty-frames",
  "shortest-source-extension",
  "operation-hash-tiebreak",
];
const BOUNDARIES: CutRepairTransitionBoundary[] = [
  "after-materialized",
  "after-receipt-proved",
  "after-local-commit-intent",
  "after-advance",
  "after-head",
  "after-committed",
];

function uuid(variant: string): string {
  return `7${variant}000000-0000-4000-8000-000000000001`;
}

function setup(variant: string) {
  const fixture = bootstrapRevisionFixture();
  const base = revisionCommitInput(fixture.producer, fixture.genesis, "c");
  const action = parseCutRestoreSpeechV1(cutRestoreAction(
    base.batch.base.pictureLockHash,
    base.batch.base.timelineMapHash,
  ));
  const paths = producerAuthorityPaths(fixture.producer);
  const planValue = {
    planVersion: 2,
    cutTrack: [{ id: "repaired-segment", sourceId: "raw" }],
  };
  const plan = writeAuthorityObjectSync(paths.objects.plans, planValue);
  const graph = writeAuthorityObjectSync(paths.objects.graphs, base.renderGraph);
  const policy = {
    schemaVersion: 1,
    kind: "cut-repair-selection-policy",
    order: ORDER,
  };
  const reviewAction = {
    schemaVersion: 1,
    kind: "cut-repair-review-action",
    idempotencyKey: uuid(variant),
    expectedParentRevisionHash: fixture.genesis,
    operation: action,
    operationHash: canonicalJsonSha256(action),
    selectionPolicy: policy,
    selectionPolicyHash: canonicalJsonSha256(policy),
    reviewPlanObjectHash: plan.hash,
    reviewPlanContentHash: planObjectContentHash(planValue),
    reviewTimelineMapHash: fixtureSha(variant),
    reviewRenderGraphHash: graph.hash,
    reviewProjectionReceiptHash: null,
    workflowPolicy: "cut-first",
    requestedAt: "2026-07-29T12:00:00.000Z",
  } as const;
  return { fixture, action, paths, plan, reviewAction };
}

function promotion(value: ReturnType<typeof setup>, reviewHash: string) {
  const review = parseProjectRevision(assertObjectHashSync(
    value.paths.objects.revisions, reviewHash));
  const selectedApproval = {
    approver: "operator" as const,
    approvalPolicyHash: fixtureSha("2"),
    approvalReceiptHash: fixtureSha("3"),
  };
  const proof = cutRepairProofFixture(
    value.fixture.producer,
    value.action,
    value.reviewAction.reviewTimelineMapHash,
    {
      approvedCutRevisionHash: reviewHash,
      planContentHash: review.planContentHash,
      sourceSnapshotSetHash: review.sourceSnapshotSetHash,
      transcriptTimingHash: review.transcriptTimingHash,
      workflowPolicy: "cut-first",
      selectedApproval,
    },
  );
  const candidate = proof.proof.candidate as Record<string, unknown>;
  const evidence = proof.proof.promotionEvidence;
  const action = {
    schemaVersion: 1,
    kind: "cut-repair-promotion-action",
    idempotencyKey: uuid("f"),
    expectedReviewRevisionHash: reviewHash,
    reviewActionHash: canonicalJsonSha256(value.reviewAction),
    operationHash: canonicalJsonSha256(value.action),
    selectionPolicyHash: value.reviewAction.selectionPolicyHash,
    selectedApproval,
    childPictureLockHash: candidate.childPictureLockHash,
    candidateHash: canonicalJsonSha256(candidate),
    promotionEvidenceHash: canonicalJsonSha256(evidence),
    requestedAt: "2026-07-29T12:01:00.000Z",
  };
  return { action, proof: proof.proof };
}

function state(value: ReturnType<typeof setup>, hash: string): string {
  return parseProjectRevision(assertObjectHashSync(
    value.paths.objects.revisions, hash)).workflowState;
}

function basicTransition(): void {
  const value = setup("4");
  try {
    const review = stageCutRepairReviewSync({
      producerDir: value.fixture.producer,
      action: value.reviewAction,
    });
    assert.equal(review.status, "committed");
    assert.equal(state(value, review.childRevisionHash), "CUT_REVIEW");
    assert.throws(
      () => assertNoPendingCutRepairTransitionSync(value.fixture.producer),
      /CUT_REVIEW head/,
    );
    const promotedInput = promotion(value, review.childRevisionHash);
    const promoted = promoteCutRepairReviewSync({
      producerDir: value.fixture.producer,
      action: promotedInput.action,
      proof: promotedInput.proof,
    });
    assert.equal(promoted.status, "committed");
    assert.equal(state(value, promoted.childRevisionHash), "PICTURE_LOCKED");
    assert.doesNotThrow(
      () => assertNoPendingCutRepairTransitionSync(value.fixture.producer));
    assert.equal(
      resolveProducerAuthorityHeadSync(value.fixture.producer),
      promoted.childRevisionHash,
    );
    fs.rmSync(path.join(
      value.fixture.producer, ".sniper-cut-repair-staging"), {
      recursive: true,
      force: true,
    });
    assert.equal(promoteCutRepairReviewSync({
      producerDir: value.fixture.producer,
      action: promotedInput.action,
      proof: promotedInput.proof,
    }).status, "replayed");
    assert.equal(recoverCutRepairReviewSync(
      value.fixture.producer,
      value.reviewAction.idempotencyKey,
    ).status, "replayed");
    assert.equal(recoverCutRepairPromotionSync(
      value.fixture.producer,
      promotedInput.action.idempotencyKey,
    ).status, "replayed");
  } finally {
    cleanRevisionFixture(value.fixture.root);
  }
}

function reviewCrashRecovery(): void {
  BOUNDARIES.forEach((boundary, index) => {
    const value = setup((index + 5).toString(16));
    try {
      assert.throws(() => stageCutRepairReviewSync({
        producerDir: value.fixture.producer,
        action: value.reviewAction,
      }, {
        after: (observed) => {
          if (observed === boundary) throw new Error(`crash:${boundary}`);
        },
      }), new RegExp(`crash:${boundary}`));
      const recovered = recoverCutRepairReviewSync(
        value.fixture.producer, value.reviewAction.idempotencyKey);
      assert.ok(["committed", "replayed"].includes(recovered.status));
      assert.equal(state(value, recovered.childRevisionHash), "CUT_REVIEW");
    } finally {
      cleanRevisionFixture(value.fixture.root);
    }
  });
}

function promotionCrashRecovery(): void {
  BOUNDARIES.forEach((boundary, index) => {
    const value = setup((index + 5).toString(16));
    try {
      const review = stageCutRepairReviewSync({
        producerDir: value.fixture.producer, action: value.reviewAction });
      const input = promotion(value, review.childRevisionHash);
      assert.throws(() => promoteCutRepairReviewSync({
        producerDir: value.fixture.producer,
        action: input.action,
        proof: input.proof,
      }, {
        after: (observed) => {
          if (observed === boundary) throw new Error(`crash:${boundary}`);
        },
      }), new RegExp(`crash:${boundary}`));
      const recovered = recoverCutRepairPromotionSync(
        value.fixture.producer, input.action.idempotencyKey);
      assert.ok(["committed", "replayed"].includes(recovered.status));
      assert.equal(state(value, recovered.childRevisionHash), "PICTURE_LOCKED");
    } finally {
      cleanRevisionFixture(value.fixture.root);
    }
  });
}

function staleCasAndApprovalFailures(): void {
  const value = setup("b");
  try {
    const review = stageCutRepairReviewSync({
      producerDir: value.fixture.producer,
      action: value.reviewAction,
    });
    const competing = {
      ...value.reviewAction,
      idempotencyKey: uuid("c"),
      reviewTimelineMapHash: fixtureSha("d"),
    };
    const lost = stageCutRepairReviewSync({
      producerDir: value.fixture.producer,
      action: competing,
    });
    assert.equal(lost.status, "aborted");
    assert.equal(
      resolveProducerAuthorityHeadSync(value.fixture.producer),
      review.childRevisionHash,
    );
    assert.throws(() => stageCutRepairReviewSync({
      producerDir: value.fixture.producer,
      action: {
        ...value.reviewAction,
        requestedAt: "2026-07-29T12:00:01.000Z",
      },
    }), /immutable authority conflict|idempotency key/);
    const input = promotion(value, review.childRevisionHash);
    assert.throws(() => promoteCutRepairReviewSync({
      producerDir: value.fixture.producer,
      action: {
        ...input.action,
        selectedApproval: {
          ...input.action.selectedApproval,
          approvalReceiptHash: fixtureSha("e"),
        },
      },
      proof: input.proof,
    }), /selected-policy approval|phase bindings/);
  } finally {
    cleanRevisionFixture(value.fixture.root);
  }
}

basicTransition();
reviewCrashRecovery();
promotionCrashRecovery();
staleCasAndApprovalFailures();
console.log("p2-cut-repair-two-step tests passed");
