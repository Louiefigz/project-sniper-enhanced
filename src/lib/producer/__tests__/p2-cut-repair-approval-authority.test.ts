import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {
  storeCutRepairAuditionReceiptSync,
} from "@/lib/server/cut-repair-audition-store";
import {
  loadCutRepairExecutionPackageSync,
  storeCutRepairExecutionPackageSync,
} from "@/lib/server/cut-repair-execution-package-store";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
} from "@/lib/server/producer-authority-files";
import { canonicalJsonSha256, fileSha256 } from
  "@/lib/server/auto-edit-hash";
import { cutRepairRenderedProofFixture } from
  "@/lib/server/__tests__/_p2-cut-repair-rendered-promotion-fixture";
import { cleanRevisionFixture } from
  "@/lib/server/__tests__/_producer-revision-fixture";
import { fixtureSha } from "./_cut-restore-speech-fixture";
import { orchestrationFixture } from
  "./_p2-cut-repair-orchestration-fixture";

function run(): void {
  const value = orchestrationFixture();
  try {
    const producer = value.revision.producer;
    const preparation = value.stored;
    const action = preparation.package.proposedReviewAction;
    const candidatePath = path.join(
      producer,
      ".sniper-cut-repair-staging",
      "approval-authority",
      "full-plan-candidate.mp4",
    );
    fs.mkdirSync(path.dirname(candidatePath), { recursive: true });
    fs.writeFileSync(candidatePath, "exact approved full-plan candidate\n");
    const candidateSha256 = fileSha256(candidatePath)!;
    const baseAttestation = {
      preparationHash: preparation.packageHash,
      candidateDescriptorHash:
        preparation.package.reviewCandidateDescriptorHash,
      candidateSha256,
      operatorReceiptId: "approval-authority-operator-1",
      reviewedAt: "2026-07-29T12:01:00.000Z",
      decision: "approved" as const,
      reportedDamageResolved: true,
    };
    assert.throws(
      () => storeCutRepairAuditionReceiptSync({
        producerDir: producer,
        operationHash: action.operationHash,
        expected: {
          preparationHash: preparation.packageHash,
          candidateDescriptorHash:
            preparation.package.reviewCandidateDescriptorHash,
          candidateSha256,
        },
        attestation: {
          ...baseAttestation,
          operatorReceiptId: "approval-authority-rejection",
          decision: "rejected",
          reportedDamageResolved: false,
        },
      }),
      /operator rejected/,
    );
    const audition = storeCutRepairAuditionReceiptSync({
      producerDir: producer,
      operationHash: action.operationHash,
      expected: {
        preparationHash: preparation.packageHash,
        candidateDescriptorHash:
          preparation.package.reviewCandidateDescriptorHash,
        candidateSha256,
      },
      attestation: baseAttestation,
    });
    assert.equal(audition.replayed, false);
    assert.equal(
      storeCutRepairAuditionReceiptSync({
        producerDir: producer,
        operationHash: action.operationHash,
        expected: {
          preparationHash: preparation.packageHash,
          candidateDescriptorHash:
            preparation.package.reviewCandidateDescriptorHash,
          candidateSha256,
        },
        attestation: baseAttestation,
      }).replayed,
      true,
    );
    const selectedApproval = {
      approver: "operator" as const,
      approvalPolicyHash: audition.approvalPolicyHash,
      approvalReceiptHash: audition.receiptHash,
    };
    const proof = cutRepairRenderedProofFixture(
      producer,
      action.operation,
      action.reviewTimelineMapHash,
      {
        approvedCutRevisionHash: fixtureSha("4"),
        planObjectHash: action.reviewPlanObjectHash,
        planContentHash: action.reviewPlanContentHash,
        renderGraphHash: action.reviewRenderGraphHash,
        renderGraphReceiptHash: fixtureSha("5"),
        candidatePointerHash: fixtureSha("6"),
        candidatePath,
        sourceSnapshotSetHash: fixtureSha("7"),
        transcriptTimingHash: fixtureSha("8"),
        workflowPolicy: action.workflowPolicy,
        selectedApproval,
      },
    );
    const candidate = proof.proof.candidate as Record<string, unknown>;
    const evidence = proof.proof.promotionEvidence;
    const promotionAction = {
      schemaVersion: 1,
      kind: "cut-repair-promotion-action",
      idempotencyKey: "78000000-0000-4000-8000-000000000001",
      expectedReviewRevisionHash: fixtureSha("4"),
      reviewActionHash: canonicalJsonSha256(action),
      operationHash: action.operationHash,
      selectionPolicyHash: action.selectionPolicyHash,
      selectedApproval,
      childPictureLockHash: candidate.childPictureLockHash,
      candidateHash: canonicalJsonSha256(candidate),
      promotionEvidenceHash: canonicalJsonSha256(evidence),
      requestedAt: "2026-07-29T12:02:00.000Z",
    };
    const packageValue = {
      schemaVersion: 1,
      kind: "cut-repair-execution-package",
      targetDirectiveHash: preparation.package.targetDirectiveHash,
      contextAuthorityHash: preparation.package.contextAuthorityHash,
      parentRevisionHash: preparation.package.parentRevisionHash,
      reviewAction: action,
      promotionAction,
      candidate,
      promotionEvidence: evidence,
    };
    const first = storeCutRepairExecutionPackageSync({
      producerDir: producer,
      preparationHash: preparation.packageHash,
      value: packageValue,
    });
    assert.notEqual(first.packageHash, first.promotionActionHash);
    const paths = producerAuthorityPaths(producer);
    assert.deepEqual(
      assertObjectHashSync(
        paths.objects.cutRepairs, first.promotionActionHash),
      promotionAction,
    );
    assert.equal(
      loadCutRepairExecutionPackageSync(producer, first.packageHash)
        .promotionAction.candidateHash,
      canonicalJsonSha256(candidate),
    );
    const replay = storeCutRepairExecutionPackageSync({
      producerDir: producer,
      preparationHash: preparation.packageHash,
      value: packageValue,
    });
    assert.equal(replay.replayed, true);
    assert.equal(replay.packageHash, first.packageHash);
    assert.throws(
      () => storeCutRepairExecutionPackageSync({
        producerDir: producer,
        preparationHash: fixtureSha("9"),
        value: packageValue,
      }),
      /another package|immutable authority conflict/,
    );
    assert.throws(
      () => storeCutRepairExecutionPackageSync({
        producerDir: producer,
        preparationHash: preparation.packageHash,
        value: {
          ...packageValue,
          candidate: { ...candidate, status: "substituted" },
        },
      }),
      /stale phase bindings/,
    );
    assert.throws(
      () => storeCutRepairAuditionReceiptSync({
        producerDir: producer,
        operationHash: action.operationHash,
        expected: {
          preparationHash: preparation.packageHash,
          candidateDescriptorHash:
            preparation.package.reviewCandidateDescriptorHash,
          candidateSha256: fixtureSha("a"),
        },
        attestation: {
          ...baseAttestation,
          candidateSha256: fixtureSha("a"),
        },
      }),
      /another audition|immutable authority conflict/,
    );
  } finally {
    cleanRevisionFixture(value.revision.root);
  }
}

run();
console.log("p2 cut-repair approval authority tests passed");
