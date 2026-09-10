import { parsePositiveRationalV1 } from "./positive-rational";
import type {
  CutRestoreSpeechV1,
  FrameRangeV1,
  SampleRangeV1,
} from "./cut-restore-speech-types";
import {
  enumValue,
  exactKeys,
  objectValue,
  sha256,
  stableId,
  uniqueStrings,
} from "./validation";

export type {
  CutRestoreSpeechV1,
  FrameRangeV1,
  SampleRangeV1,
} from "./cut-restore-speech-types";

const KEYS = [
  "schemaVersion", "operation", "target", "parentPictureLockHash",
  "parentTimelineMapHash", "segment", "sourceExtension", "sourceSampleRate",
  "sourceVideoFrameRange", "sourceFrameRate", "speed", "extensionFrames",
  "preserveUnrelated",
  "totalOutputFramesBefore", "totalOutputFramesAfter", "method",
  "reclaimedSilence", "pictureDirtyWindows", "audioDirtyWindows",
  "audioDirtySampleRanges", "replacedAudioSampleRanges",
  "replaceableAudioEvidenceHash", "extensionOutputSamples",
  "quantizationResidualSamples", "residualPolicy",
  "unchangedPictureMappingRanges", "revalidatedDependentIds",
  "unchangedDependentIds",
] as const;
const REQUIRED = KEYS.filter((key) => ![
  "reclaimedSilence", "replacedAudioSampleRanges",
  "replaceableAudioEvidenceHash", "quantizationResidualSamples",
  "residualPolicy", "sourceVideoFrameRange", "sourceFrameRate",
].includes(key));

function integer(value: unknown, label: string, minimum: number): number {
  if (!Number.isSafeInteger(value) || Number(value) < minimum) {
    throw new Error(`${label} must be a safe integer >= ${minimum}`);
  }
  return Number(value);
}

function frameRange(value: unknown, label: string): FrameRangeV1 {
  const row = objectValue(value, label);
  exactKeys(
    row,
    ["startFrame", "endFrameExclusive"],
    ["startFrame", "endFrameExclusive"],
    label,
  );
  const startFrame = integer(row.startFrame, `${label}.startFrame`, 0);
  const endFrameExclusive = integer(
    row.endFrameExclusive,
    `${label}.endFrameExclusive`,
    1,
  );
  if (endFrameExclusive <= startFrame) throw new Error(`${label} is empty`);
  return { startFrame, endFrameExclusive };
}

function sampleRange(value: unknown, label: string): SampleRangeV1 {
  const row = objectValue(value, label);
  exactKeys(
    row,
    ["startSample", "endSampleExclusive"],
    ["startSample", "endSampleExclusive"],
    label,
  );
  const startSample = integer(row.startSample, `${label}.startSample`, 0);
  const endSampleExclusive = integer(
    row.endSampleExclusive,
    `${label}.endSampleExclusive`,
    1,
  );
  if (endSampleExclusive <= startSample) throw new Error(`${label} is empty`);
  return { startSample, endSampleExclusive };
}

function ranges<T>(
  value: unknown,
  label: string,
  parser: (item: unknown, itemLabel: string) => T,
  allowEmpty = false,
): T[] {
  if (!Array.isArray(value) || (!allowEmpty && !value.length)) {
    throw new Error(`${label} must be a ${allowEmpty ? "" : "non-empty "}array`);
  }
  return value.map((item, index) => parser(item, `${label}[${index}]`));
}

function target(value: unknown): CutRestoreSpeechV1["target"] {
  const row = objectValue(value, "CutRestoreSpeechV1.target");
  const keys = [
    "kind", "sourceId", "wordIds", "occurrence",
    "sourceSampleRange", "transcriptTimingHash",
  ] as const;
  exactKeys(row, keys, keys, "CutRestoreSpeechV1.target");
  if (row.kind !== "word-range") throw new Error("restore target must be word-range");
  const wordIds = uniqueStrings(
    row.wordIds,
    "restore target wordIds",
    (item, label) => {
      if (typeof item !== "string" || !/^w-[0-9a-f]{16}$/u.test(item)) {
        throw new Error(`${label} is not a stable word id`);
      }
      return item;
    },
  );
  if (!wordIds.length) throw new Error("restore target wordIds cannot be empty");
  return {
    kind: "word-range",
    sourceId: stableId(row.sourceId, "restore target sourceId"),
    wordIds,
    occurrence: integer(row.occurrence, "restore target occurrence", 1),
    sourceSampleRange: sampleRange(
      row.sourceSampleRange,
      "restore target sourceSampleRange",
    ),
    transcriptTimingHash: sha256(
      row.transcriptTimingHash,
      "restore target transcriptTimingHash",
    ),
  };
}

function segment(value: unknown): CutRestoreSpeechV1["segment"] {
  const row = objectValue(value, "CutRestoreSpeechV1.segment");
  const keys = ["segmentId", "elementVersion", "edge"] as const;
  exactKeys(row, keys, keys, "CutRestoreSpeechV1.segment");
  return {
    segmentId: stableId(row.segmentId, "restore segmentId"),
    elementVersion: integer(row.elementVersion, "restore elementVersion", 1),
    edge: enumValue(row.edge, ["start", "end"] as const, "restore segment edge"),
  };
}

function reclaimed(value: unknown): NonNullable<CutRestoreSpeechV1["reclaimedSilence"]> {
  const row = objectValue(value, "CutRestoreSpeechV1.reclaimedSilence");
  const keys = ["silenceId", "sourceSampleRange", "outputFrameRange"] as const;
  exactKeys(row, keys, keys, "CutRestoreSpeechV1.reclaimedSilence");
  return {
    silenceId: stableId(row.silenceId, "reclaimed silenceId"),
    sourceSampleRange: sampleRange(
      row.sourceSampleRange,
      "reclaimed sourceSampleRange",
    ),
    outputFrameRange: frameRange(
      row.outputFrameRange,
      "reclaimed outputFrameRange",
    ),
  };
}

function optionalFields(
  row: Record<string, unknown>,
  parsed: CutRestoreSpeechV1,
): void {
  if (parsed.method === "audio-lj-overlap") {
    if (row.reclaimedSilence !== undefined
        || row.quantizationResidualSamples !== undefined
        || row.residualPolicy !== undefined
        || row.sourceVideoFrameRange !== undefined
        || row.sourceFrameRate !== undefined) {
      throw new Error("audio L/J repair cannot claim reclaimed-silence evidence");
    }
    parsed.replacedAudioSampleRanges = ranges(
      row.replacedAudioSampleRanges,
      "replacedAudioSampleRanges",
      sampleRange,
    );
    parsed.replaceableAudioEvidenceHash = sha256(
      row.replaceableAudioEvidenceHash,
      "replaceableAudioEvidenceHash",
    );
    if (parsed.pictureDirtyWindows.length) {
      throw new Error("audio L/J repair cannot dirty picture");
    }
    return;
  }
  if (row.replacedAudioSampleRanges !== undefined
      || row.replaceableAudioEvidenceHash !== undefined) {
    throw new Error("picture repair cannot claim audio replacement evidence");
  }
  parsed.reclaimedSilence = reclaimed(row.reclaimedSilence);
  parsed.sourceVideoFrameRange = frameRange(
    row.sourceVideoFrameRange,
    "sourceVideoFrameRange",
  );
  if (row.sourceFrameRate === undefined) {
    throw new Error("sourceFrameRate is required for picture repair");
  }
  parsed.sourceFrameRate = parsePositiveRationalV1(row.sourceFrameRate);
  parsed.quantizationResidualSamples = integer(
    row.quantizationResidualSamples,
    "quantizationResidualSamples",
    0,
  );
  if (row.residualPolicy !== "reclaimed-proved-silence") {
    throw new Error("picture repair residual policy is unsupported");
  }
  parsed.residualPolicy = "reclaimed-proved-silence";
}

function parsedRanges(row: Record<string, unknown>) {
  return {
    pictureDirtyWindows: ranges(
      row.pictureDirtyWindows, "pictureDirtyWindows", frameRange, true),
    audioDirtyWindows: ranges(
      row.audioDirtyWindows, "audioDirtyWindows", frameRange),
    audioDirtySampleRanges: ranges(
      row.audioDirtySampleRanges, "audioDirtySampleRanges", sampleRange),
    unchangedPictureMappingRanges: ranges(
      row.unchangedPictureMappingRanges,
      "unchangedPictureMappingRanges",
      frameRange,
    ),
  };
}

function parsedDependents(row: Record<string, unknown>) {
  return {
    revalidatedDependentIds: uniqueStrings(
      row.revalidatedDependentIds, "revalidatedDependentIds"),
    unchangedDependentIds: uniqueStrings(
      row.unchangedDependentIds, "unchangedDependentIds"),
  };
}

function commonAction(
  row: Record<string, unknown>,
  totalFrames: number,
): CutRestoreSpeechV1 {
  return {
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    target: target(row.target),
    parentPictureLockHash: sha256(row.parentPictureLockHash, "parentPictureLockHash"),
    parentTimelineMapHash: sha256(row.parentTimelineMapHash, "parentTimelineMapHash"),
    segment: segment(row.segment),
    sourceExtension: sampleRange(row.sourceExtension, "sourceExtension"),
    sourceSampleRate: integer(row.sourceSampleRate, "sourceSampleRate", 1),
    speed: parsePositiveRationalV1(row.speed),
    extensionFrames: integer(row.extensionFrames, "extensionFrames", 1),
    preserveUnrelated: true,
    totalOutputFramesBefore: totalFrames,
    totalOutputFramesAfter: totalFrames,
    method: enumValue(
      row.method,
      ["audio-lj-overlap", "extend-and-reclaim-silence"] as const,
      "restore method",
    ),
    ...parsedRanges(row),
    extensionOutputSamples: integer(
      row.extensionOutputSamples, "extensionOutputSamples", 1),
    ...parsedDependents(row),
  };
}

/** Parse the sole released P2 cut action and reject every open-ended field. */
export function parseCutRestoreSpeechV1(value: unknown): CutRestoreSpeechV1 {
  const row = objectValue(value, "CutRestoreSpeechV1");
  exactKeys(row, KEYS, REQUIRED, "CutRestoreSpeechV1");
  if (row.schemaVersion !== 1 || row.operation !== "cut.restoreSpeech"
      || row.preserveUnrelated !== true) {
    throw new Error("CutRestoreSpeechV1 version or preservation policy is unsupported");
  }
  const before = integer(row.totalOutputFramesBefore, "total frames before", 1);
  const after = integer(row.totalOutputFramesAfter, "total frames after", 1);
  if (before !== after) throw new Error("CutRestoreSpeechV1 must be non-ripple");
  const parsed = commonAction(row, before);
  optionalFields(row, parsed);
  const overlap = parsed.revalidatedDependentIds.some(
    (id) => parsed.unchangedDependentIds.includes(id),
  );
  if (overlap) throw new Error("dependent repair partitions overlap");
  return parsed;
}
