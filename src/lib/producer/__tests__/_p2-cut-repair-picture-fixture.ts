import {
  parseCutRestoreSpeechV1,
  type CutRestoreSpeechV1,
} from "@/lib/producer/contracts/cut-restore-speech-v1";
import { CUT_REPAIR_SELECTION_ORDER } from
  "@/lib/producer/contracts/cut-repair-review-transition";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { cutRestoreAction, fixtureSha } from "./_cut-restore-speech-fixture";

export interface PictureFixture {
  operation: CutRestoreSpeechV1;
  plan: Record<string, unknown>;
  childTimelineMapHash: string;
  authority: Record<string, unknown>;
}

function pictureOperation(): CutRestoreSpeechV1 {
  const value = cutRestoreAction();
  delete value.replacedAudioSampleRanges;
  delete value.replaceableAudioEvidenceHash;
  Object.assign(value, {
    method: "extend-and-reclaim-silence",
    sourceVideoFrameRange: { startFrame: 42, endFrameExclusive: 44 },
    sourceFrameRate: { numerator: "30", denominator: "1" },
    reclaimedSilence: {
      silenceId: "silence-0001",
      sourceSampleRange: {
        startSample: 96_000, endSampleExclusive: 98_400,
      },
      outputFrameRange: { startFrame: 45, endFrameExclusive: 47 },
    },
    pictureDirtyWindows: [{ startFrame: 45, endFrameExclusive: 47 }],
    quantizationResidualSamples: 0,
    residualPolicy: "reclaimed-proved-silence",
    unchangedPictureMappingRanges: [
      { startFrame: 0, endFrameExclusive: 45 },
      { startFrame: 47, endFrameExclusive: 360 },
    ],
  });
  return parseCutRestoreSpeechV1(value);
}

export function pictureTimelineMap() {
  return {
    outputDuration: 12,
    segments: [{
      index: 0, source_id: "raw-1",
      src_start: 0, src_end: 12, speed: 1,
      out_start: 0, out_end: 12, audio_lead_s: 0,
    }],
  };
}

function timelineMapHash(): string {
  return canonicalJsonSha256({
    quantization: "millionths-half-up-v1",
    outputDuration: 12_000_000,
    segments: [{
      index: 0, source_id: "raw-1",
      src_start: 0, src_end: 12_000_000, speed: 1_000_000,
      out_start: 0, out_end: 12_000_000, audio_lead_s: 0,
    }],
  });
}

export function sealPictureAuthority(
  core: Record<string, unknown>,
): Record<string, unknown> {
  return { ...core, authorityHash: canonicalJsonSha256(core) };
}

function mappingProof(
  operation: CutRestoreSpeechV1,
  childTimelineMapHash: string,
) {
  return {
    schemaVersion: 1,
    parentTimelineMapHash: operation.parentTimelineMapHash,
    childTimelineMapHash,
    authorizedDirtyWindows: [operation.pictureDirtyWindows[0]],
    unchangedRanges: [{
      frameRange: { startFrame: 0, endFrameExclusive: 45 },
      mapping: ["raw-1", 0, 1],
    }],
  };
}

export function pictureFixture(): PictureFixture {
  const operation = pictureOperation();
  const childTimelineMapHash = timelineMapHash();
  const parent = {
    id: "seg-0001", sourceId: "raw-1", start: 0, end: 12,
    speed: 1, audioLeadMs: 0, generation: 1,
  };
  const child = { ...parent, end: 12.05, generation: 2 };
  const dirty = operation.pictureDirtyWindows[0];
  const proof = mappingProof(operation, childTimelineMapHash);
  const core = {
    schemaVersion: 1,
    kind: "cut-repair-picture-plan-authority",
    operationHash: canonicalJsonSha256(operation),
    parentPlanObjectHash: fixtureSha("c"),
    parentTimelineMapHash: operation.parentTimelineMapHash,
    childTimelineMapHash,
    target: {
      index: 0, segmentId: "seg-0001",
      parentElementVersion: 1, childElementVersion: 2,
    },
    parentCutRow: parent,
    parentCutRowHash: canonicalJsonSha256(parent),
    childCutRow: child,
    childCutRowHash: canonicalJsonSha256(child),
    sourceExtension: operation.sourceExtension,
    reclaimedSilence: operation.reclaimedSilence!.sourceSampleRange,
    dirtyFrameRange: dirty,
    mappingProof: proof,
    mappingProofHash: canonicalJsonSha256(proof),
    reversion: {
      action: "restore-parent-cut-row",
      index: 0, segmentId: "seg-0001",
      expectedChildCutRowHash: canonicalJsonSha256(child),
      restoreParentCutRowHash: canonicalJsonSha256(parent),
    },
  };
  const authority = sealPictureAuthority(core);
  return {
    operation, childTimelineMapHash, authority,
    plan: {
      planVersion: 1, target: { mode: "longform" },
      cutTrack: [child], cutRepairPicturePlanAuthority: authority,
    },
  };
}

export function picturePreparedMedia(
  value: PictureFixture,
): Record<string, unknown> {
  const policy = {
    schemaVersion: 1,
    kind: "cut-repair-selection-policy",
    order: [...CUT_REPAIR_SELECTION_ORDER],
  };
  const planHash = canonicalJsonSha256(value.plan);
  const receipt = (kind: string, hash: string) => ({
    schemaVersion: 1, kind,
    operationHash: canonicalJsonSha256(value.operation),
    exactOutputDurationPreserved: true,
    output: { path: `/private/${kind}.mov`, sha256: hash },
  });
  return {
    schemaVersion: 1,
    kind: "cut-repair-prepared-media",
    parentRevisionHash: fixtureSha("1"),
    contextAuthorityHash: fixtureSha("2"),
    operation: value.operation,
    operationHash: canonicalJsonSha256(value.operation),
    selectionPolicy: policy,
    selectionPolicyHash: canonicalJsonSha256(policy),
    projectSampleRate: 48_000,
    reviewPlan: value.plan,
    reviewPlanHash: planHash,
    reviewProjection: {
      schemaVersion: 1,
      kind: "compatibility-timeline-projection",
      approvedCutPlanHash: planHash,
      cutTrackDigest: fixtureSha("3"),
      cutDecisionsDigest: fixtureSha("4"),
      compilerHash: fixtureSha("5"),
      timelineMap: pictureTimelineMap(),
      timelineMapHash: value.childTimelineMapHash,
    },
    reviewTimelineMapHash: value.childTimelineMapHash,
    fragmentReceipt: receipt("cut-repair-fragment", fixtureSha("6")),
    compositeReceipt: receipt("cut-repair-composite", fixtureSha("7")),
  };
}
