import assert from "node:assert/strict";
import {
  runCutRepairApproval,
  type CutRepairApprovalServices,
} from "@/app/api/producer/ai-edit/cut-repair-approve-runner";
import {
  runCutRepairReview,
  type CutRepairReviewServices,
} from "@/app/api/producer/ai-edit/cut-repair-review-runner";
import { storeCutRepairAuditionReceiptSync } from
  "@/lib/server/cut-repair-audition-store";
import { stageCutRepairReviewSync, recoverCutRepairReviewSync } from
  "@/lib/server/cut-repair-review-store";
import { resolveProducerAuthorityHeadSync } from
  "@/lib/server/producer-revision-head";
import {
  cleanRevisionFixture,
} from "@/lib/server/__tests__/_producer-revision-fixture";
import {
  fixtureSha,
} from "./_cut-restore-speech-fixture";
import {
  orchestrationFixture,
  type OrchestrationFixture,
} from "./_p2-cut-repair-orchestration-fixture";

function reviewServices(
  value: OrchestrationFixture,
  qc: unknown,
  staged: { count: number },
): CutRepairReviewServices {
  return {
    loadPreparation: () => value.stored,
    obtainQc: async () => qc as OrchestrationFixture["qc"],
    admitReview: () => undefined,
    stageReview: (input) => {
      staged.count += 1;
      return stageCutRepairReviewSync(input);
    },
  };
}

function blockedQc(value: OrchestrationFixture) {
  return {
    ok: false,
    status: "automated-qc-blocked",
    preparationHash: value.stored.packageHash,
    candidateDescriptorHash:
      value.stored.package.reviewCandidateDescriptorHash,
    operationHash:
      value.stored.package.proposedReviewAction.operationHash,
    candidateCompositeSha256:
      value.stored.package.reviewCandidateMediaSha256,
    blockers: {
      alignment: { code: "NO_ALIGNER", message: "not configured" },
    },
    operatorAuditionProduced: false,
  } as const;
}

async function reviewBoundary(): Promise<OrchestrationFixture> {
  const value = orchestrationFixture();
  const staged = { count: 0 };
  const blocked = reviewServices(value, blockedQc(value), staged);
  await assert.rejects(
    runCutRepairReview(
      value.revision.producer, "/manifest", value.reviewDirective, blocked),
    /AUTOMATED_QC_BLOCKED/,
  );
  assert.equal(staged.count, 0, "blocked QC must not stage CUT_REVIEW");
  const substituted = {
    ...value.qc,
    candidateCompositeSha256: fixtureSha("f"),
  };
  await assert.rejects(
    runCutRepairReview(
      value.revision.producer,
      "/manifest",
      value.reviewDirective,
      reviewServices(value, substituted, staged),
    ),
    /another full-plan candidate/,
  );
  assert.equal(staged.count, 0);
  await assert.rejects(
    runCutRepairReview(
      value.revision.producer,
      "/manifest",
      { ...value.reviewDirective, packageHash: fixtureSha("0") },
      reviewServices(value, value.qc, staged),
    ),
    /targets another phrase occurrence/,
  );
  const first = await runCutRepairReview(
    value.revision.producer,
    "/manifest",
    value.reviewDirective,
    reviewServices(value, value.qc, staged),
  );
  assert.equal(first.routeStatus, "cut-review-staged");
  assert.equal(staged.count, 1);
  const replay = await runCutRepairReview(
    value.revision.producer,
    "/manifest",
    value.reviewDirective,
    reviewServices(value, value.qc, staged),
  );
  assert.equal(replay.replayed, true);
  assert.equal(replay.reviewRevisionHash, first.reviewRevisionHash);
  return value;
}

function approvalServices(
  value: OrchestrationFixture,
  sealCount: { count: number },
): CutRepairApprovalServices {
  return {
    loadPreparation: () => value.stored,
    loadQc: async () => value.qc,
    recoverReview: recoverCutRepairReviewSync,
    storeAudition: storeCutRepairAuditionReceiptSync,
    sealPackage: async (input) => {
      assert.equal(input.stored.packageHash, value.stored.packageHash);
      assert.equal(
        input.evidence.candidateCompositeSha256,
        value.stored.package.reviewCandidateMediaSha256,
      );
      sealCount.count += 1;
      return {
        packageHash: fixtureSha("1"),
        promotionActionHash: fixtureSha("2"),
        package: {} as never,
        replayed: sealCount.count > 1,
      };
    },
  };
}

async function noReviewCannotApprove(): Promise<void> {
  const value = orchestrationFixture();
  try {
    const sealed = { count: 0 };
    await assert.rejects(
      runCutRepairApproval(
        value.revision.producer,
        "/manifest",
        value.approveDirective,
        approvalServices(value, sealed),
      ),
      /ENOENT|CUT_REVIEW_NOT_STAGED/,
    );
    assert.equal(sealed.count, 0);
  } finally {
    cleanRevisionFixture(value.revision.root);
  }
}

async function pendingReviewCannotApprove(): Promise<void> {
  const value = orchestrationFixture();
  try {
    assert.throws(() => stageCutRepairReviewSync({
      producerDir: value.revision.producer,
      action: value.stored.package.proposedReviewAction,
    }, {
      after: (boundary) => {
        if (boundary === "after-materialized") {
          throw new Error("crash:unsettled-review");
        }
      },
    }), /crash:unsettled-review/);
    const sealed = { count: 0 };
    await assert.rejects(
      runCutRepairApproval(
        value.revision.producer,
        "/manifest",
        value.approveDirective,
        approvalServices(value, sealed),
      ),
      /CUT_REVIEW_NOT_STAGED/,
    );
    assert.equal(sealed.count, 0);
    assert.equal(
      resolveProducerAuthorityHeadSync(value.revision.producer),
      value.revision.genesis,
    );
  } finally {
    cleanRevisionFixture(value.revision.root);
  }
}

async function approvalBoundary(value: OrchestrationFixture): Promise<void> {
  const sealed = { count: 0 };
  const services = approvalServices(value, sealed);
  await assert.rejects(
    runCutRepairApproval(
      value.revision.producer,
      "/manifest",
      value.approveDirective,
      { ...services, loadQc: async () => {
        throw new Error("NO_AUTOMATED_QC");
      } },
    ),
    /NO_AUTOMATED_QC/,
  );
  const rejected = {
    ...value.approveDirective,
    audition: {
      ...value.approveDirective.audition!,
      decision: "rejected" as const,
      reportedDamageResolved: false,
    },
  };
  await assert.rejects(
    runCutRepairApproval(
      value.revision.producer, "/manifest", rejected, services),
    /operator rejected/,
  );
  assert.equal(sealed.count, 0);
  const substituted = {
    ...value.approveDirective,
    audition: {
      ...value.approveDirective.audition!,
      candidateSha256: fixtureSha("3"),
    },
  };
  await assert.rejects(
    runCutRepairApproval(
      value.revision.producer, "/manifest", substituted, services),
    /another full-plan candidate/,
  );
  assert.equal(sealed.count, 0);
  const first = await runCutRepairApproval(
    value.revision.producer,
    "/manifest",
    value.approveDirective,
    services,
  );
  assert.equal(first.routeStatus, "promotion-package-sealed");
  assert.equal(first.executed, false);
  assert.equal(sealed.count, 1);
  const replay = await runCutRepairApproval(
    value.revision.producer,
    "/manifest",
    value.approveDirective,
    services,
  );
  assert.equal(replay.replayed, true);
  assert.equal(replay.packageHash, first.packageHash);
}

async function run(): Promise<void> {
  await noReviewCannotApprove();
  await pendingReviewCannotApprove();
  const value = await reviewBoundary();
  try {
    await approvalBoundary(value);
  } finally {
    cleanRevisionFixture(value.revision.root);
  }
}

run()
  .then(() => {
    console.log("p2 cut-repair review/approve orchestration tests passed");
  })
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
