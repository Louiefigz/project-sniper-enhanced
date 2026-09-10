import type { CutRepairAutomatedQcPass } from
  "@/app/api/producer/ai-edit/cut-repair-candidate-qc-runner";
import type { CutRepairDirectiveV1 } from
  "@/app/api/producer/ai-edit/cut-repair-route-policy";
import { parseCutRestoreSpeechV1 } from
  "@/lib/producer/contracts/cut-restore-speech-v1";
import {
  cutRestoreAction,
  fixtureSha,
} from "./_cut-restore-speech-fixture";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { planObjectContentHash } from "@/lib/server/auto-edit-authority";
import type { StoredCutRepairPreparation } from
  "@/lib/server/cut-repair-preparation-store";
import {
  producerAuthorityPaths,
  writeAuthorityObjectSync,
} from "@/lib/server/producer-authority-files";
import {
  bootstrapRevisionFixture,
  revisionCommitInput,
} from "@/lib/server/__tests__/_producer-revision-fixture";

const TARGET = { phrase: "the exact clipped phrase", occurrence: 1 };
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
} as const;

function targetHash(): string {
  return canonicalJsonSha256({
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    target: TARGET,
  });
}

function receipt(
  kind: string,
  operationHash: string,
  candidateHash: string,
  fields: Record<string, unknown>,
) {
  return {
    schemaVersion: 1,
    kind,
    status: "bounded-pass",
    operationHash,
    candidateCompositeSha256: candidateHash,
    ...fields,
  };
}

function lane(
  value: Record<string, unknown>,
  candidateHash: string,
) {
  return {
    status: "bounded-pass" as const,
    receiptHash: canonicalJsonSha256(value),
    candidateCompositeSha256: candidateHash,
    receipt: value,
  };
}

function qc(
  packageHash: string,
  descriptorHash: string,
  operationHash: string,
  candidateHash: string,
): CutRepairAutomatedQcPass {
  const alignment = receipt(
    "cut-repair-alignment-qc", operationHash, candidateHash, {
      alignmentProtocol: "deterministic-source-waveform-v1",
      evidenceSemantics:
        "transcript-bound-source-waveform-presence-not-audibility",
      runtimeSha256: fixtureSha("1"),
      implementationSha256: fixtureSha("2"),
      policySha256: fixtureSha("3"),
      sourceMediaSha256: fixtureSha("4"),
      candidateWaveSha256: fixtureSha("5"),
      referenceWaveSha256: fixtureSha("6"),
      targetWordIds: ["word-1"],
      observedOccurrenceCount: 1,
      sourceSpanBoundaryMatch: true,
      bestScorePpm: 990_000,
      minimumScorePpm: 850_000,
      matchStartSampleInCandidateWindow: 48_000,
      boundaryToleranceSamples: 240,
      referenceSampleCount: 24_000,
    });
  const vad = receipt(
    "cut-repair-vad-qc", operationHash, candidateHash, {
      runtimeSha256: fixtureSha("7"),
      speechContinuityPassed: true,
      unintendedSpeechGapCount: 0,
    });
  const retranscription = receipt(
    "cut-repair-retranscription-qc", operationHash, candidateHash, {
      runtimeSha256: fixtureSha("8"),
      modelSha256: fixtureSha("9"),
      targetPhraseHash: fixtureSha("a"),
      observedOccurrenceCount: 1,
      wordOrderPreserved: true,
    });
  const seam = receipt(
    "cut-repair-seam-qc", operationHash, candidateHash, {
      runtimeSha256: fixtureSha("b"),
      clickFree: true,
      duplicateFree: true,
      roomToneContinuous: true,
      lipSyncDisposition: "not-applicable-audio-only",
    });
  return {
    ok: true,
    status: "automated-qc-passed",
    preparationHash: packageHash,
    candidateDescriptorHash: descriptorHash,
    operationHash,
    candidateCompositeSha256: candidateHash,
    automatedQcBundleHash: fixtureSha("c"),
    automatedQcBundlePath: "/controller/automated-qc.json",
    alignment: lane(alignment, candidateHash),
    vad: lane(vad, candidateHash),
    retranscription: lane(retranscription, candidateHash),
    seam: lane(seam, candidateHash),
    operatorAuditionProduced: false,
  };
}

export interface OrchestrationFixture {
  revision: ReturnType<typeof bootstrapRevisionFixture>;
  stored: StoredCutRepairPreparation;
  qc: CutRepairAutomatedQcPass;
  reviewDirective: CutRepairDirectiveV1;
  approveDirective: CutRepairDirectiveV1;
}

/** Build enough real revision authority to exercise review/approve boundaries. */
export function orchestrationFixture(): OrchestrationFixture {
  const revision = bootstrapRevisionFixture();
  const base = revisionCommitInput(
    revision.producer, revision.genesis, "c");
  const operation = parseCutRestoreSpeechV1(cutRestoreAction(
    base.batch.base.pictureLockHash,
    base.batch.base.timelineMapHash,
  ));
  const paths = producerAuthorityPaths(revision.producer);
  const planValue = {
    planVersion: 2,
    target: { fps: { numerator: "30", denominator: "1" } },
    cutTrack: [{ id: "repaired", sourceId: "raw" }],
  };
  const plan = writeAuthorityObjectSync(paths.objects.plans, planValue);
  const graph = writeAuthorityObjectSync(paths.objects.graphs, base.renderGraph);
  const reviewAction = {
    schemaVersion: 1,
    kind: "cut-repair-review-action",
    idempotencyKey: "76000000-0000-4000-8000-000000000001",
    expectedParentRevisionHash: revision.genesis,
    operation,
    operationHash: canonicalJsonSha256(operation),
    selectionPolicy: POLICY,
    selectionPolicyHash: canonicalJsonSha256(POLICY),
    reviewPlanObjectHash: plan.hash,
    reviewPlanContentHash: planObjectContentHash(planValue),
    reviewTimelineMapHash: fixtureSha("a"),
    reviewRenderGraphHash: graph.hash,
    reviewProjectionReceiptHash: null,
    workflowPolicy: "cut-first",
    requestedAt: "2026-07-29T12:00:00.000Z",
  } as const;
  const packageHash = fixtureSha("b");
  const descriptorHash = fixtureSha("c");
  const candidateHash = fixtureSha("d");
  const stored = {
    packageHash,
    package: {
      targetDirectiveHash: targetHash(),
      contextAuthorityHash: fixtureSha("e"),
      parentRevisionHash: revision.genesis,
      proposedReviewAction: reviewAction,
      reviewCandidateDescriptorHash: descriptorHash,
      reviewCandidateMediaSha256: candidateHash,
    },
  } as unknown as StoredCutRepairPreparation;
  const reviewDirective: CutRepairDirectiveV1 = {
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    mode: "review",
    packageHash,
    target: TARGET,
  };
  const approveDirective: CutRepairDirectiveV1 = {
    ...reviewDirective,
    mode: "approve",
    idempotencyKey: "77000000-0000-4000-8000-000000000001",
    requestedAt: "2026-07-29T12:02:00.000Z",
    audition: {
      schemaVersion: 1,
      kind: "cut-repair-operator-audition-attestation",
      preparationHash: packageHash,
      candidateDescriptorHash: descriptorHash,
      candidateSha256: candidateHash,
      operatorReceiptId: "operator-session-1",
      reviewedAt: "2026-07-29T12:01:00.000Z",
      decision: "approved",
      reportedDamageResolved: true,
    },
  };
  return {
    revision,
    stored,
    qc: qc(
      packageHash, descriptorHash, reviewAction.operationHash, candidateHash),
    reviewDirective,
    approveDirective,
  };
}
