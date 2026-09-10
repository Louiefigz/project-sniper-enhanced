import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { sealCutRepairPromotionPackage } from
  "@/app/api/producer/ai-edit/cut-repair-approval-sealer";
import { storeCutRepairAuditionReceiptSync } from
  "@/lib/server/cut-repair-audition-store";
import {
  loadCutRepairExecutionPackageSync,
  storeCutRepairExecutionPackageSync,
} from "@/lib/server/cut-repair-execution-package-store";
import type { StoredCutRepairPreparation } from
  "@/lib/server/cut-repair-preparation-store";
import { canonicalJsonSha256, fileSha256 } from
  "@/lib/server/auto-edit-hash";
import { cutRepairRenderedProofFixture } from
  "@/lib/server/__tests__/_p2-cut-repair-rendered-promotion-fixture";
import { cleanRevisionFixture } from
  "@/lib/server/__tests__/_producer-revision-fixture";
import { fixtureSha } from "./_cut-restore-speech-fixture";
import { orchestrationFixture } from
  "./_p2-cut-repair-orchestration-fixture";

async function run(): Promise<void> {
  const value = orchestrationFixture();
  try {
    const producer = value.revision.producer;
    const action = value.stored.package.proposedReviewAction;
    const candidatePath = path.join(
      producer,
      ".sniper-cut-repair-staging",
      "approval-sealer",
      "full-plan-candidate.mp4",
    );
    fs.mkdirSync(path.dirname(candidatePath), { recursive: true });
    fs.writeFileSync(candidatePath, "sealer exact full-plan candidate\n");
    const candidateSha256 = fileSha256(candidatePath)!;
    const authority = {
      approvedCutRevisionHash: value.revision.genesis,
      planObjectHash: action.reviewPlanObjectHash,
      planContentHash: action.reviewPlanContentHash,
      renderGraphHash: action.reviewRenderGraphHash,
      renderGraphReceiptHash: fixtureSha("4"),
      candidatePointerHash: fixtureSha("5"),
      candidatePath,
      sourceSnapshotSetHash: fixtureSha("6"),
      transcriptTimingHash: fixtureSha("7"),
      workflowPolicy: action.workflowPolicy,
    };
    const preliminary = cutRepairRenderedProofFixture(
      producer,
      action.operation,
      action.reviewTimelineMapHash,
      {
        ...authority,
        selectedApproval: {
          approver: "operator",
          approvalPolicyHash: fixtureSha("1"),
          approvalReceiptHash: fixtureSha("2"),
        },
      },
    );
    const preliminaryCandidate =
      preliminary.proof.candidate as Record<string, unknown>;
    const descriptorHash = canonicalJsonSha256(
      preliminaryCandidate.renderedCandidate);
    const audition = storeCutRepairAuditionReceiptSync({
      producerDir: producer,
      operationHash: action.operationHash,
      expected: {
        preparationHash: value.stored.packageHash,
        candidateDescriptorHash: descriptorHash,
        candidateSha256,
      },
      attestation: {
        preparationHash: value.stored.packageHash,
        candidateDescriptorHash: descriptorHash,
        candidateSha256,
        operatorReceiptId: "approval-sealer-operator",
        reviewedAt: "2026-07-29T12:01:00.000Z",
        decision: "approved",
        reportedDamageResolved: true,
      },
    });
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
        ...authority,
        selectedApproval,
      },
    );
    const candidate = proof.proof.candidate as Record<string, unknown>;
    const rendered = candidate.renderedCandidate as Record<string, unknown>;
    assert.equal(canonicalJsonSha256(rendered), descriptorHash);
    const stored = {
      ...value.stored,
      package: {
        ...value.stored.package,
        reviewCandidateDescriptorHash: descriptorHash,
        reviewCandidateMediaSha256: candidateSha256,
      },
    } as StoredCutRepairPreparation;
    const evidence = proof.proof.promotionEvidence as Record<string, unknown>;
    const directive = {
      ...value.approveDirective,
      audition: {
        ...value.approveDirective.audition!,
        candidateDescriptorHash: descriptorHash,
        candidateSha256,
      },
    };
    const sealed = await sealCutRepairPromotionPackage({
      producerDir: producer,
      directive,
      stored,
      reviewed: {
        revisionHash: value.revision.genesis,
        receiptHash: fixtureSha("8"),
      },
      audition,
      evidence,
      services: {
        buildProof: async () => candidate,
        storePackage: storeCutRepairExecutionPackageSync,
      },
    });
    const reopened = loadCutRepairExecutionPackageSync(
      producer, sealed.packageHash);
    assert.equal(reopened.candidate.schemaVersion, 2);
    assert.equal(
      reopened.promotionAction.selectedApproval.approvalReceiptHash,
      audition.receiptHash,
    );
    assert.equal(
      reopened.promotionAction.candidateHash,
      canonicalJsonSha256(candidate),
    );
    await assert.rejects(
      sealCutRepairPromotionPackage({
        producerDir: producer,
        directive: {
          ...directive,
          idempotencyKey: "79000000-0000-4000-8000-000000000001",
        },
        stored,
        reviewed: {
          revisionHash: value.revision.genesis,
          receiptHash: fixtureSha("8"),
        },
        audition,
        evidence,
        services: {
          buildProof: async () => ({
            ...candidate,
            renderedCandidate: {
              ...rendered,
              candidateSha256: fixtureSha("9"),
            },
          }),
          storePackage: storeCutRepairExecutionPackageSync,
        },
      }),
      /substituted the reviewed full-plan media/,
    );
  } finally {
    cleanRevisionFixture(value.revision.root);
  }
}

run()
  .then(() => console.log("p2 cut-repair approval sealer tests passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
