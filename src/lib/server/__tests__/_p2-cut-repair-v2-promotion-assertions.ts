import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fixtureSha } from
  "@/lib/producer/__tests__/_cut-restore-speech-fixture";
import { parseCutRepairMediaActivationV1 } from
  "@/lib/producer/contracts/cut-repair-media-activation";
import { parseProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import { canonicalJsonSha256, fileSha256 } from "../auto-edit-hash";
import { observeCurrentRenderGraphAuthoritySync } from
  "../current-render-graph-authority";
import { promoteCutRepairReviewSync } from
  "../cut-repair-promotion-store";
import {
  assertObjectHashSync,
  authorityKey,
  readAuthorityJsonSync,
} from "../producer-authority-files";
import { cutRepairRenderedProofFixture } from
  "./_p2-cut-repair-rendered-promotion-fixture";
import { renderedPromotionReviewSetup } from
  "./_p2-cut-repair-v2-lifecycle-fixture";

type Setup = ReturnType<typeof renderedPromotionReviewSetup>;

export function promotionInput(value: Setup) {
  const selectedApproval = {
    approver: "operator" as const,
    approvalPolicyHash: fixtureSha("8"),
    approvalReceiptHash: fixtureSha("9"),
  };
  const proof = cutRepairRenderedProofFixture(
    value.fixture.producer,
    value.operation,
    value.reviewAction.reviewTimelineMapHash,
    {
      approvedCutRevisionHash: value.review.childRevisionHash,
      planObjectHash: value.plan.hash,
      planContentHash: value.revision.planContentHash,
      renderGraphHash: value.graph.hash,
      renderGraphReceiptHash: value.staged.receiptHash,
      candidatePointerHash: value.staged.candidatePointerHash,
      candidatePath: value.candidatePath,
      sourceSnapshotSetHash: value.revision.sourceSnapshotSetHash,
      transcriptTimingHash: value.revision.transcriptTimingHash,
      workflowPolicy: "cut-first",
      selectedApproval,
    },
  );
  const candidate = proof.proof.candidate as Record<string, unknown>;
  const evidence = proof.proof.promotionEvidence;
  return {
    proof,
    action: {
      schemaVersion: 1,
      kind: "cut-repair-promotion-action",
      idempotencyKey: "75000000-0000-4000-8000-000000000001",
      expectedReviewRevisionHash: value.review.childRevisionHash,
      reviewActionHash: canonicalJsonSha256(value.reviewAction),
      operationHash: value.reviewAction.operationHash,
      selectionPolicyHash: value.reviewAction.selectionPolicyHash,
      selectedApproval,
      childPictureLockHash: candidate.childPictureLockHash,
      candidateHash: canonicalJsonSha256(candidate),
      promotionEvidenceHash: canonicalJsonSha256(evidence),
      requestedAt: "2026-07-29T12:01:00.000Z",
    } as const,
  };
}

type Promotion = ReturnType<typeof promotionInput>;

export function assertSelectedArtifacts(
  value: Setup,
  input: Promotion,
  childRevisionHash: string,
): void {
  const revision = parseProjectRevision(assertObjectHashSync(
    value.paths.objects.revisions, childRevisionHash));
  assert.equal(revision.renderGraphHash, value.graph.hash);
  assert.equal(
    revision.authoritativeSidecars.cutRepairRenderedCandidate,
    input.proof.hashes.rendered,
  );
  assert.ok(fs.existsSync(path.join(
    value.paths.objects.media, `${input.proof.hashes.renderedMedia}.mp4`)));
  assert.equal(
    fileSha256(path.join(value.fixture.producer, "final.mp4")),
    input.proof.hashes.renderedMedia,
  );
  assert.equal(
    fileSha256(path.join(value.fixture.producer, "edit_plan.json")),
    value.plan.hash,
  );
  assert.deepEqual(
    JSON.parse(fs.readFileSync(path.join(
      value.fixture.producer, "edit_plan.json"), "utf8")),
    value.planValue,
    "graphics, music, captions, and prior disjoint repair must stay exact",
  );
  assert.doesNotThrow(() => observeCurrentRenderGraphAuthoritySync({
    producerDir: value.fixture.producer,
    expectedGraphHash: value.graph.hash,
    expectedFinalHash: input.proof.hashes.renderedMedia,
  }));
}

export function assertActivation(value: Setup, input: Promotion): void {
  const activation = parseCutRepairMediaActivationV1(
    readAuthorityJsonSync(path.join(
      value.paths.sagas,
      "cut-repair-media-activation",
      "records",
      `${authorityKey(input.action.idempotencyKey)}.json`,
    )),
  );
  assert.equal(
    activation.renderedCandidateHash, input.proof.hashes.rendered);
  assert.equal(
    activation.candidateSha256, input.proof.hashes.renderedMedia);
  assert.throws(
    () => parseCutRepairMediaActivationV1({
      ...activation,
      unexpected: true,
    }),
    /unsupported fields/,
  );
}

export function assertReplay(value: Setup, input: Promotion): void {
  fs.rmSync(path.join(
    value.fixture.producer, ".sniper-cut-repair-staging"), {
    recursive: true,
    force: true,
  });
  assert.equal(promoteCutRepairReviewSync({
    producerDir: value.fixture.producer,
    action: input.action,
    proof: input.proof.proof,
  }).status, "replayed");
}
