/** Pure shape fixtures: all completion/replay claims here are TEST data, never native evidence. */
import { bodyMediaTestV2 } from "./_guided-body-media-v2-fixture";
import { BODY_SOURCE_COLOR_READBACK_SCOPE, BODY_SOURCE_COLOR_REPLAY_SCOPE,
  BODY_SOURCE_COLOR_READBACK_STAGES } from "../contracts/guided-body-result-v2";

const HASH = "a".repeat(64);
/** Exact declared original opening role, distinct from the later body's result directory. */
export function bodySourceReplayResult(root = "/private/tmp/TEST-body-result-v2") {
  const input = bodyMediaTestV2(root), replay = input.sourceColorReplay;
  const execution = replay.input.path.slice(0, -"source-color/input.json".length);
  return { schemaVersion: 1, kind: "guided-body-original-source-color-replay", scope: BODY_SOURCE_COLOR_REPLAY_SCOPE,
    sourceColorEvidence: { path: `${execution}media-output/source-color-evidence.json`, sha256: HASH, sizeBytes: 1, receiptHash: HASH },
    observationRecordHash: HASH, consumptionRecordHash: HASH, sourceColorRecordsReplayed: true, basePictureConsumptionVerified: true,
    gamutMeasured: false, gradeApplied: false, colorQualified: false, bodyApproved: false, deliveryApproved: false };
}

/** Closed actual-stdout shape only; later consumers must bind its separate raw result and invocation. */
export function bodySourceCompletion(root = "/private/tmp/TEST-body-result-v2") {
  const input = bodyMediaTestV2(root);
  return { schemaVersion: 2, kind: "guided-body-media-completion", status: "complete", executionId: input.executionId,
    inputSha256: HASH, executionActivationSha256: HASH, receiptPath: `${root}/body-media-output/body-result.json`,
    receiptSha256: HASH, receiptHash: HASH, sourceColorReplay: input.sourceColorReplay,
    sourceColorReadback: bodySourceReplayResult(root), bodyApproved: false, deliveryApproved: false };
}

/** Existing eight stage names are retained, with the explicit two replay stages after current pipeline. */
export function bodySourceReadback(root = "/private/tmp/TEST-body-result-v2") {
  return { ...bodySourceCompletion(root), kind: "guided-body-media-readback", status: "verified", scope: BODY_SOURCE_COLOR_READBACK_SCOPE,
    elapsedMs: 10, stages: BODY_SOURCE_COLOR_READBACK_STAGES.map(stage => ({ stage, status: "complete", elapsedMs: 1 })),
    processGroupAndDockerCleanup: "requires-separate-owned-controller-observation", currentJournalAndLease: "requires-separate-owned-controller-observation" };
}

/** Complete top-level raw envelope; opaque media fields deliberately carry no native proof in this fixture. */
export function bodySourceRawResult(root = "/private/tmp/TEST-body-result-v2") {
  const input = bodyMediaTestV2(root);
  return { schemaVersion: 2, kind: "guided-body-media-result", status: "complete", scope: "private-body-candidate-not-approval",
    profile: input.profile, executionId: input.executionId, inputPath: `${root}/body-media-input.json`, inputSha256: HASH,
    executionActivationPath: `${root}/body-execution-activation.json`, executionActivationSha256: HASH, references: input.references,
    pipeline: {}, workload: {}, templates: [], graphics: [], resolvedClips: [], composition: {}, programDeliveryReceipt: {}, media: {},
    stages: ["body-current-pipeline-and-claim", "body-original-source-color-observations", "body-original-base-picture-consumption",
      "body-original-whole-base-master"].map(stage => ({ stage, status: "complete", elapsedMs: 0 })),
    sourceColorReplay: input.sourceColorReplay, sourceColorReadback: bodySourceReplayResult(root), receiptHash: HASH,
    bodyApproved: false, deliveryApproved: false };
}

/** Strip only the V2 additions to exercise the historical parser's exact closed envelope. */
export function bodyLegacyCompletion() {
  const { sourceColorReplay: _replay, sourceColorReadback: _proof, ...row } = bodySourceCompletion(); void _replay; void _proof;
  return { ...row, schemaVersion: 1 };
}
