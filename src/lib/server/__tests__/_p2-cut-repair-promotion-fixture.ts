import fs from "node:fs";
import path from "node:path";
import type { CutRestoreSpeechV1 } from
  "@/lib/producer/contracts/cut-restore-speech-v1";
import { canonicalJsonSha256, fileSha256 } from "../auto-edit-hash";

const hash = (value: string): string => value.repeat(64);

function stagedMedia(producer: string): {
  fragmentPath: string;
  fragmentHash: string;
  compositePath: string;
  compositeHash: string;
} {
  const directory = path.join(
    producer, ".sniper-cut-repair-staging", "proof-fixture");
  fs.mkdirSync(directory, { recursive: true });
  const fragmentPath = path.join(directory, "fragment.mov");
  const compositePath = path.join(directory, "composite.mov");
  fs.writeFileSync(fragmentPath, "decoded fragment fixture\n");
  fs.writeFileSync(compositePath, "decoded composite fixture\n");
  return {
    fragmentPath,
    fragmentHash: fileSha256(fragmentPath)!,
    compositePath,
    compositeHash: fileSha256(compositePath)!,
  };
}

export function promotionEvidence(
  operationHash: string,
  compositeHash: string,
): Record<string, unknown> {
  const common = (kind: string, status: string) => ({
    schemaVersion: 1,
    kind,
    status,
    operationHash,
    candidateCompositeSha256: compositeHash,
  });
  const item = (receipt: Record<string, unknown>) => ({
    status: receipt.status,
    receiptHash: canonicalJsonSha256(receipt),
    candidateCompositeSha256: compositeHash,
    receipt,
  });
  const alignment = {
    ...common("cut-repair-alignment-qc", "bounded-pass"),
    alignmentProtocol: "deterministic-source-waveform-v1",
    evidenceSemantics:
      "transcript-bound-source-waveform-presence-not-audibility",
    runtimeSha256: hash("1"), implementationSha256: hash("2"),
    policySha256: hash("3"), sourceMediaSha256: hash("4"),
    candidateWaveSha256: hash("5"), referenceWaveSha256: hash("6"),
    targetWordIds: ["word-1"], observedOccurrenceCount: 1,
    sourceSpanBoundaryMatch: true, bestScorePpm: 990_000,
    minimumScorePpm: 850_000,
    matchStartSampleInCandidateWindow: 48_000,
    boundaryToleranceSamples: 240, referenceSampleCount: 24_000,
  };
  const vad = {
    ...common("cut-repair-vad-qc", "bounded-pass"),
    runtimeSha256: hash("7"), speechContinuityPassed: true,
    unintendedSpeechGapCount: 0,
  };
  const retranscription = {
    ...common("cut-repair-retranscription-qc", "bounded-pass"),
    runtimeSha256: hash("8"), modelSha256: hash("9"),
    targetPhraseHash: hash("a"), observedOccurrenceCount: 1,
    wordOrderPreserved: true,
  };
  const seam = {
    ...common("cut-repair-seam-qc", "bounded-pass"),
    runtimeSha256: hash("b"), clickFree: true, duplicateFree: true,
    roomToneContinuous: true,
    lipSyncDisposition: "not-applicable-audio-only",
  };
  const audition = {
    ...common(
      "cut-repair-audition-qc", "operator-approved-candidate"),
    operatorReceiptId: "operator-receipt-1",
    approvalPolicyHash: hash("c"),
    reviewedAt: "2026-07-29T12:00:00.000Z",
    decision: "approved",
    reportedDamageResolved: true,
  };
  return {
    schemaVersion: 1,
    kind: "cut-repair-promotion-evidence",
    operationHash,
    candidateCompositeSha256: compositeHash,
    alignment: item(alignment),
    vad: item(vad),
    retranscription: item(retranscription),
    seam: item(seam),
    audition: item(audition),
  };
}

export function cutRepairProofFixture(
  producer: string,
  action: CutRestoreSpeechV1,
  childTimelineMapHash: string,
  lockAuthority?: {
    approvedCutRevisionHash: string;
    planContentHash: string;
    sourceSnapshotSetHash: string;
    transcriptTimingHash: string;
    workflowPolicy: "cut-first" | "autopilot";
    selectedApproval: {
      approver: "operator" | "system-policy";
      approvalPolicyHash: string;
      approvalReceiptHash: string;
    };
  },
): {
  proof: { candidate: unknown; promotionEvidence: unknown };
  hashes: Record<string, string>;
} {
  const operationHash = canonicalJsonSha256(action);
  const media = stagedMedia(producer);
  const fragment = {
    schemaVersion: 1,
    kind: "cut-repair-fragment",
    operationHash,
    exactOutputDurationPreserved: true,
    retime: {
      requestedSpeed: action.speed,
      sourceSampleRange: action.sourceExtension,
      sourceSampleRate: action.sourceSampleRate,
      normalizedSourceSampleRange: action.sourceExtension,
      outputSamples: action.extensionOutputSamples,
      effectiveRatio: action.speed,
    },
    output: { path: media.fragmentPath, sha256: media.fragmentHash },
    evidencePolicy:
      "alignment-and-vad-are-bounded-evidence-not-sole-audibility-proof",
  };
  const fragmentHash = canonicalJsonSha256(fragment);
  const composite = {
    schemaVersion: 1,
    kind: "cut-repair-composite",
    operationHash,
    fragmentReceiptHash: fragmentHash,
    exactOutputDurationPreserved: true,
    inputs: { fragmentSha256: media.fragmentHash },
    output: { path: media.compositePath, sha256: media.compositeHash },
    outsideDirtyOracle: { pictureMatches: true, pcmMatches: true },
  };
  const pictureLock = lockAuthority ? {
    schemaVersion: 1,
    approvedCutRevisionHash: lockAuthority.approvedCutRevisionHash,
    planContentHash: lockAuthority.planContentHash,
    timelineMapHash: childTimelineMapHash,
    sourceSnapshotSetHash: lockAuthority.sourceSnapshotSetHash,
    transcriptTimingHash: lockAuthority.transcriptTimingHash,
    cutApprovalReceiptHash: hash("0"),
    cutReviewApprovalReceiptHash: hash("a"),
    requiredCleanReviews: 2,
    workflowPolicy: lockAuthority.workflowPolicy,
    selectedApproval: lockAuthority.selectedApproval,
    parentPictureLockHash: action.parentPictureLockHash,
  } : {
    schemaVersion: 1,
    timelineMapHash: childTimelineMapHash,
    parentPictureLockHash: action.parentPictureLockHash,
  };
  const pictureLockHash = canonicalJsonSha256(pictureLock);
  const supersession = {
    schemaVersion: 1,
    repairOperationHash: operationHash,
    parentPictureLockHash: action.parentPictureLockHash,
    childPictureLockHash: pictureLockHash,
  };
  const caption = {
    schemaVersion: 1,
    kind: "caption-repair-revalidation",
    operationHash,
    status: "not-present",
    revalidationHash: hash("6"),
  };
  const palmier = {
    schemaVersion: 1,
    kind: "palmier-cut-repair-disposition",
    operationHash,
    selected: false,
    nativeStatus: "skipped",
    deliveryDisposition: "local-exact-only",
    reason: "Palmier was not selected; zero Palmier calls are authorized",
  };
  const parts = {
    fragment: fragmentHash,
    composite: canonicalJsonSha256(composite),
    pictureLock: pictureLockHash,
    supersession: canonicalJsonSha256(supersession),
    caption: canonicalJsonSha256(caption),
    palmier: canonicalJsonSha256(palmier),
  };
  const invariant = {
    schemaVersion: 1,
    kind: "cut-repair-invariant-proof",
    operationHash,
    fragmentReceiptHash: parts.fragment,
    childPictureLockHash: parts.pictureLock,
    supersessionHash: parts.supersession,
    palmierDispositionHash: parts.palmier,
    captionRevalidationHash: caption.revalidationHash,
    terminalCompositeProved: true,
    terminalCompositeReceiptHash: parts.composite,
    totalOutputFramesPreserved: true,
  };
  const candidate = {
    schemaVersion: 1,
    kind: "cut-repair-candidate",
    status: "candidate-proved",
    operationHash,
    fragmentReceipt: fragment,
    childPictureLock: pictureLock,
    childPictureLockHash: parts.pictureLock,
    supersessionReceipt: supersession,
    supersessionHash: parts.supersession,
    palmierDisposition: palmier,
    captionRevalidation: caption,
    compositeReceipt: composite,
    invariantProof: invariant,
    invariantProofHash: canonicalJsonSha256(invariant),
  };
  const evidence = promotionEvidence(operationHash, media.compositeHash);
  return {
    proof: { candidate, promotionEvidence: evidence },
    hashes: {
      ...parts,
      invariant: candidate.invariantProofHash,
      candidate: canonicalJsonSha256(candidate),
      promotion: canonicalJsonSha256(evidence),
      fragmentMedia: media.fragmentHash,
      compositeMedia: media.compositeHash,
    },
  };
}
