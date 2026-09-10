import { parsePositiveRationalV1 } from "./positive-rational";
import type {
  DialogueMapEntryV1,
  DialogueMapV1,
  DialogueTrackSegmentV1,
  DialogueTrackV1,
} from "./dialogue-authority-types";
import {
  deriveDialogueMappingV1,
  parseDialogueHeaderV1,
} from "./dialogue-exact-samples";
import {
  parseDialogueSampleRangeV1,
  parseDialogueTrackSegmentV1,
  parseDialogueTrackV1,
  validateDialogueSegmentsV1,
} from "./dialogue-track-v1";
import { exactKeys, objectValue, sha256 } from "./validation";

const MAP_KEYS = [
  "schemaVersion", "kind", "dialogueTrackHash", "sourceSnapshotSetHash",
  "pictureTimelineMapHash", "projectFps", "projectSampleRate",
  "totalOutputFrames", "totalOutputSamples", "maxAbsoluteSpeedDeviation",
  "entries",
] as const;

function mapEntry(
  segment: DialogueTrackSegmentV1,
  normalizedSourceSampleRange: DialogueMapEntryV1["normalizedSourceSampleRange"],
  effectiveSpeed: DialogueMapEntryV1["effectiveSpeed"],
): DialogueMapEntryV1 {
  const {
    role,
    seamSample,
    coveredByCutSegmentId,
    ...prefix
  } = segment;
  return {
    ...prefix,
    normalizedSourceSampleRange,
    effectiveSpeed,
    role,
    ...(role === "primary" ? {} : { seamSample, coveredByCutSegmentId }),
  };
}

function parseMapEntry(
  value: unknown,
  label: string,
  projectRate: number,
  tolerance: DialogueMapV1["maxAbsoluteSpeedDeviation"],
): DialogueMapEntryV1 {
  const row = objectValue(value, label);
  const segment = parseDialogueTrackSegmentV1(value, label, true);
  const normalizedSourceSampleRange = parseDialogueSampleRangeV1(
    row.normalizedSourceSampleRange,
    `${label}.normalizedSourceSampleRange`,
  );
  const effectiveSpeed = parsePositiveRationalV1(row.effectiveSpeed);
  const claimed = mapEntry(
    segment, normalizedSourceSampleRange, effectiveSpeed);
  const derived = deriveDialogueMappingV1(segment, projectRate, tolerance);
  const expected = mapEntry(
    segment, derived.normalizedSourceSampleRange, derived.effectiveSpeed);
  if (JSON.stringify(claimed) !== JSON.stringify(expected)) {
    throw new Error("DialogueMapV1 contains a stale derived sample mapping");
  }
  return claimed;
}

export function deriveDialogueMapV1(
  value: unknown,
  dialogueTrackHash: string,
): DialogueMapV1 {
  const track = parseDialogueTrackV1(value);
  const hash = sha256(dialogueTrackHash, "DialogueTrackV1 content hash");
  return {
    schemaVersion: 1,
    kind: "dialogue-map",
    dialogueTrackHash: hash,
    sourceSnapshotSetHash: track.sourceSnapshotSetHash,
    pictureTimelineMapHash: track.pictureTimelineMapHash,
    projectFps: track.projectFps,
    projectSampleRate: track.projectSampleRate,
    totalOutputFrames: track.totalOutputFrames,
    totalOutputSamples: track.totalOutputSamples,
    maxAbsoluteSpeedDeviation: track.maxAbsoluteSpeedDeviation,
    entries: track.segments.map((segment) => {
      const derived = deriveDialogueMappingV1(
        segment,
        track.projectSampleRate,
        track.maxAbsoluteSpeedDeviation,
      );
      return mapEntry(
        segment,
        derived.normalizedSourceSampleRange,
        derived.effectiveSpeed,
      );
    }),
  };
}

export function parseDialogueMapV1(value: unknown): DialogueMapV1 {
  const row = objectValue(value, "DialogueMapV1");
  exactKeys(row, MAP_KEYS, MAP_KEYS, "DialogueMapV1");
  const header = parseDialogueHeaderV1(row, "dialogue-map");
  if (!Array.isArray(row.entries)) {
    throw new Error("DialogueMapV1.entries must be an array");
  }
  const entries = row.entries.map((item, index) => parseMapEntry(
    item,
    `entries[${index}]`,
    header.projectSampleRate,
    header.maxAbsoluteSpeedDeviation,
  ));
  validateDialogueSegmentsV1(entries, header.totalOutputSamples);
  return {
    schemaVersion: 1,
    kind: "dialogue-map",
    dialogueTrackHash: sha256(
      row.dialogueTrackHash, "DialogueMapV1.dialogueTrackHash"),
    ...header,
    entries,
  };
}

export function validateDialogueAuthorityV1(
  trackValue: unknown,
  mapValue: unknown,
  dialogueTrackHash: string,
): { track: DialogueTrackV1; dialogueMap: DialogueMapV1 } {
  const track = parseDialogueTrackV1(trackValue);
  const dialogueMap = parseDialogueMapV1(mapValue);
  const expected = deriveDialogueMapV1(track, dialogueTrackHash);
  if (JSON.stringify(dialogueMap) !== JSON.stringify(expected)) {
    throw new Error("DialogueMapV1 does not exactly bind DialogueTrackV1");
  }
  return { track, dialogueMap };
}

export type {
  DialogueMapEntryV1,
  DialogueMapV1,
} from "./dialogue-authority-types";
