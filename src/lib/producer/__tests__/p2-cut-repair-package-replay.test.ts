import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { runCutRepairExecution } from
  "@/app/api/producer/ai-edit/cut-repair-execute-runner";
import { parseCutRestoreSpeechV1 } from
  "@/lib/producer/contracts/cut-restore-speech-v1";
import {
  cutRestoreAction,
  fixtureSha,
} from "./_cut-restore-speech-fixture";
import { canonicalJsonSha256, fileSha256 } from
  "@/lib/server/auto-edit-hash";
import { planObjectContentHash } from
  "@/lib/server/auto-edit-authority";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
  writeAuthorityObjectSync,
} from "@/lib/server/producer-authority-files";
import {
  recoverCutRepairReviewSync,
  stageCutRepairReviewSync,
} from
  "@/lib/server/cut-repair-review-store";
import {
  publishProducerAdvanceSync,
  resolveProducerAuthorityHeadSync,
} from
  "@/lib/server/producer-revision-head";
import { cutRepairTransitionChildSync } from
  "@/lib/server/cut-repair-transition-reconciliation";
import {
  bootstrapRevisionFixture,
  cleanRevisionFixture,
  revisionCommitInput,
} from "@/lib/server/__tests__/_producer-revision-fixture";
import { cutRepairProofFixture } from
  "@/lib/server/__tests__/_p2-cut-repair-promotion-fixture";
import { parseProjectRevision } from
  "@/lib/producer/contracts/project-revision";

const POLICY = {
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
const TARGET = { phrase: "the exact clipped phrase", occurrence: 1 };
const targetHash = canonicalJsonSha256({
  schemaVersion: 1,
  operation: "cut.restoreSpeech",
  target: TARGET,
});

async function run(): Promise<void> {
  const fixture = bootstrapRevisionFixture();
  try {
    const base = revisionCommitInput(fixture.producer, fixture.genesis, "c");
    const operation = parseCutRestoreSpeechV1(cutRestoreAction(
      base.batch.base.pictureLockHash,
      base.batch.base.timelineMapHash,
    ));
    const paths = producerAuthorityPaths(fixture.producer);
    const planValue = {
      planVersion: 2,
      cutTrack: [{ id: "repaired-segment", sourceId: "raw" }],
    };
    const plan = writeAuthorityObjectSync(paths.objects.plans, planValue);
    const graph = writeAuthorityObjectSync(
      paths.objects.graphs, base.renderGraph);
    const reviewAction = {
      schemaVersion: 1,
      kind: "cut-repair-review-action",
      idempotencyKey: "71000000-0000-4000-8000-000000000001",
      expectedParentRevisionHash: fixture.genesis,
      operation,
      operationHash: canonicalJsonSha256(operation),
      selectionPolicy: POLICY,
      selectionPolicyHash: canonicalJsonSha256(POLICY),
      reviewPlanObjectHash: plan.hash,
      reviewPlanContentHash: planObjectContentHash(planValue),
      reviewTimelineMapHash: fixtureSha("7"),
      reviewRenderGraphHash: graph.hash,
      reviewProjectionReceiptHash: null,
      workflowPolicy: "cut-first",
      requestedAt: "2026-07-29T12:00:00.000Z",
    } as const;
    assert.throws(() => stageCutRepairReviewSync({
      producerDir: fixture.producer,
      action: reviewAction,
    }, {
      after: (boundary) => {
        if (boundary === "after-materialized") {
          throw new Error("crash:review-not-staged");
        }
      },
    }), /crash:review-not-staged/);
    const reviewChild = cutRepairTransitionChildSync(
      fixture.producer, "review", reviewAction.idempotencyKey);
    assert.ok(reviewChild);
    const revision = parseProjectRevision(assertObjectHashSync(
      paths.objects.revisions, reviewChild));
    const selectedApproval = {
      approver: "operator" as const,
      approvalPolicyHash: fixtureSha("8"),
      approvalReceiptHash: fixtureSha("9"),
    };
    const proof = cutRepairProofFixture(
      fixture.producer,
      operation,
      reviewAction.reviewTimelineMapHash,
      {
        approvedCutRevisionHash: reviewChild,
        planContentHash: revision.planContentHash,
        sourceSnapshotSetHash: revision.sourceSnapshotSetHash,
        transcriptTimingHash: revision.transcriptTimingHash,
        workflowPolicy: "cut-first",
        selectedApproval,
      },
    ).proof;
    const candidate = proof.candidate as Record<string, unknown>;
    const promotionAction = {
      schemaVersion: 1,
      kind: "cut-repair-promotion-action",
      idempotencyKey: "72000000-0000-4000-8000-000000000001",
      expectedReviewRevisionHash: reviewChild,
      reviewActionHash: canonicalJsonSha256(reviewAction),
      operationHash: reviewAction.operationHash,
      selectionPolicyHash: reviewAction.selectionPolicyHash,
      selectedApproval,
      childPictureLockHash: candidate.childPictureLockHash,
      candidateHash: canonicalJsonSha256(candidate),
      promotionEvidenceHash: canonicalJsonSha256(proof.promotionEvidence),
      requestedAt: "2026-07-29T12:01:00.000Z",
    };
    const packageObject = writeAuthorityObjectSync(paths.objects.cutRepairs, {
      schemaVersion: 1,
      kind: "cut-repair-execution-package",
      targetDirectiveHash: targetHash,
      contextAuthorityHash: fixtureSha("a"),
      parentRevisionHash: fixture.genesis,
      reviewAction,
      promotionAction,
      candidate,
      promotionEvidence: proof.promotionEvidence,
    });
    const directive = {
      schemaVersion: 1 as const,
      operation: "cut.restoreSpeech" as const,
      mode: "execute" as const,
      packageHash: packageObject.hash,
      target: TARGET,
    };
    await assert.rejects(
      runCutRepairExecution(
        fixture.producer, "/not-needed-on-recovery", directive),
      /CUT_REVIEW_NOT_STAGED/,
    );
    assert.equal(
      resolveProducerAuthorityHeadSync(fixture.producer),
      fixture.genesis,
    );
    const review = recoverCutRepairReviewSync(
      fixture.producer, reviewAction.idempotencyKey);
    assert.equal(review.childRevisionHash, reviewChild);
    const competingReview = {
      ...reviewAction,
      idempotencyKey: "71000000-0000-4000-8000-000000000002",
      reviewTimelineMapHash: fixtureSha("b"),
    };
    assert.throws(() => stageCutRepairReviewSync({
      producerDir: fixture.producer,
      action: competingReview,
    }, {
      after: (boundary) => {
        if (boundary === "after-materialized") {
          throw new Error("crash:competing-package");
        }
      },
    }), /crash:competing-package/);
    await assert.rejects(
      runCutRepairExecution(
        fixture.producer, "/not-needed-on-recovery", directive),
      /belongs to another package/,
    );
    assert.equal(recoverCutRepairReviewSync(
      fixture.producer, competingReview.idempotencyKey).status, "aborted");
    const first = await runCutRepairExecution(
      fixture.producer, "/not-needed-on-recovery", directive);
    assert.equal(first.routeStatus, "two-step-promotion-committed");
    assert.equal(fileSha256(path.join(
      fixture.producer, "edit_plan.json")), plan.hash);
    fs.rmSync(path.join(
      fixture.producer, ".sniper-cut-repair-staging"), {
      recursive: true,
      force: true,
    });
    const replay = await runCutRepairExecution(
      fixture.producer, "/not-needed-on-recovery", directive);
    assert.equal(replay.promotedRevisionHash, first.promotedRevisionHash);
    await assert.rejects(
      runCutRepairExecution(
        fixture.producer,
        "/not-needed-on-recovery",
        { ...directive, target: { phrase: "another phrase" } },
      ),
      /targets another phrase occurrence/,
    );
    const promotedHash = first.promotedRevisionHash as string;
    const promotedRevision = parseProjectRevision(assertObjectHashSync(
      paths.objects.revisions, promotedHash));
    const descendant = writeAuthorityObjectSync(paths.objects.revisions, {
      ...promotedRevision,
      parentRevisionHash: promotedHash,
    });
    publishProducerAdvanceSync(paths, {
      schemaVersion: 1,
      expectedParentRevisionHash: promotedHash,
      childRevisionHash: descendant.hash,
      idempotencyKey: "73000000-0000-4000-8000-000000000001",
      requestDigest: fixtureSha("c"),
    });
    await assert.rejects(
      runCutRepairExecution(
        fixture.producer, "/not-needed-on-recovery", directive),
      /stale for the selected revision/,
    );
  } finally {
    cleanRevisionFixture(fixture.root);
  }
}

run()
  .then(() => console.log("p2-cut-repair-package-replay tests passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
