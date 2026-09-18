import type { PositiveRationalV1 } from "./positive-rational";

export interface DialogueSampleRangeV1 {
  startSample: number;
  endSampleExclusive: number;
}

export type DialogueSegmentRoleV1 =
  | "primary"
  | "j-cut-handle"
  | "l-cut-handle";

export interface DialogueTrackSegmentV1 {
  dialogueSegmentId: string;
  cutSegmentId: string;
  elementVersion: number;
  sourceId: string;
  sourceSampleRate: number;
  sourceSampleRange: DialogueSampleRangeV1;
  outputSampleRange: DialogueSampleRangeV1;
  speed: PositiveRationalV1;
  role: DialogueSegmentRoleV1;
  seamSample?: number;
  coveredByCutSegmentId?: string;
}

export interface DialogueTrackV1 {
  schemaVersion: 1;
  kind: "dialogue-track";
  sourceSnapshotSetHash: string;
  pictureTimelineMapHash: string;
  projectFps: PositiveRationalV1;
  projectSampleRate: number;
  totalOutputFrames: number;
  totalOutputSamples: number;
  maxAbsoluteSpeedDeviation: PositiveRationalV1;
  segments: DialogueTrackSegmentV1[];
}

export interface DialogueMapEntryV1 extends DialogueTrackSegmentV1 {
  normalizedSourceSampleRange: DialogueSampleRangeV1;
  effectiveSpeed: PositiveRationalV1;
}

export interface DialogueMapV1 {
  schemaVersion: 1;
  kind: "dialogue-map";
  dialogueTrackHash: string;
  sourceSnapshotSetHash: string;
  pictureTimelineMapHash: string;
  projectFps: PositiveRationalV1;
  projectSampleRate: number;
  totalOutputFrames: number;
  totalOutputSamples: number;
  maxAbsoluteSpeedDeviation: PositiveRationalV1;
  entries: DialogueMapEntryV1[];
}
