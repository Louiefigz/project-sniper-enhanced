import type { PositiveRationalV1 } from "./positive-rational";

export interface FrameRangeV1 {
  startFrame: number;
  endFrameExclusive: number;
}

export interface SampleRangeV1 {
  startSample: number;
  endSampleExclusive: number;
}

export interface CutRestoreSpeechV1 {
  schemaVersion: 1;
  operation: "cut.restoreSpeech";
  target: {
    kind: "word-range";
    sourceId: string;
    wordIds: string[];
    occurrence: number;
    sourceSampleRange: SampleRangeV1;
    transcriptTimingHash: string;
  };
  parentPictureLockHash: string;
  parentTimelineMapHash: string;
  segment: { segmentId: string; elementVersion: number; edge: "start" | "end" };
  sourceExtension: SampleRangeV1;
  sourceSampleRate: number;
  sourceVideoFrameRange?: FrameRangeV1;
  sourceFrameRate?: PositiveRationalV1;
  speed: PositiveRationalV1;
  extensionFrames: number;
  preserveUnrelated: true;
  totalOutputFramesBefore: number;
  totalOutputFramesAfter: number;
  method: "audio-lj-overlap" | "extend-and-reclaim-silence";
  reclaimedSilence?: {
    silenceId: string;
    sourceSampleRange: SampleRangeV1;
    outputFrameRange: FrameRangeV1;
  };
  pictureDirtyWindows: FrameRangeV1[];
  audioDirtyWindows: FrameRangeV1[];
  audioDirtySampleRanges: SampleRangeV1[];
  replacedAudioSampleRanges?: SampleRangeV1[];
  replaceableAudioEvidenceHash?: string;
  extensionOutputSamples: number;
  quantizationResidualSamples?: number;
  residualPolicy?: "reclaimed-proved-silence";
  unchangedPictureMappingRanges: FrameRangeV1[];
  revalidatedDependentIds: string[];
  unchangedDependentIds: string[];
}
