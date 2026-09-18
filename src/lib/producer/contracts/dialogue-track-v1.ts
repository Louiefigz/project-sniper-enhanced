import { parsePositiveRationalV1 } from "./positive-rational";
import type {
  DialogueSampleRangeV1,
  DialogueSegmentRoleV1,
  DialogueTrackSegmentV1,
  DialogueTrackV1,
} from "./dialogue-authority-types";
import {
  deriveDialogueMappingV1,
  dialogueSafeInteger,
  parseDialogueHeaderV1,
} from "./dialogue-exact-samples";
import {
  exactKeys,
  objectValue,
  stableId,
} from "./validation";

const ROLES = ["primary", "j-cut-handle", "l-cut-handle"] as const;
const ROLE_ORDER: Record<DialogueSegmentRoleV1, number> = {
  primary: 0,
  "j-cut-handle": 1,
  "l-cut-handle": 2,
};
const SEGMENT_KEYS = [
  "dialogueSegmentId", "cutSegmentId", "elementVersion", "sourceId",
  "sourceSampleRate", "sourceSampleRange", "outputSampleRange", "speed",
  "role", "seamSample", "coveredByCutSegmentId",
] as const;
const SEGMENT_REQUIRED = SEGMENT_KEYS.filter((key) =>
  !["seamSample", "coveredByCutSegmentId"].includes(key));
const TRACK_KEYS = [
  "schemaVersion", "kind", "sourceSnapshotSetHash", "pictureTimelineMapHash",
  "projectFps", "projectSampleRate", "totalOutputFrames",
  "totalOutputSamples", "maxAbsoluteSpeedDeviation", "segments",
] as const;

export function parseDialogueSampleRangeV1(
  value: unknown,
  label: string,
): DialogueSampleRangeV1 {
  const row = objectValue(value, label);
  const keys = ["startSample", "endSampleExclusive"] as const;
  exactKeys(row, keys, keys, label);
  const startSample = dialogueSafeInteger(
    row.startSample, `${label}.startSample`);
  const endSampleExclusive = dialogueSafeInteger(
    row.endSampleExclusive, `${label}.endSampleExclusive`, 1);
  if (endSampleExclusive <= startSample) throw new Error(`${label} is empty`);
  return { startSample, endSampleExclusive };
}

function segmentRole(value: unknown, label: string): DialogueSegmentRoleV1 {
  if (typeof value !== "string" || !ROLES.includes(
    value as DialogueSegmentRoleV1,
  )) {
    throw new Error(`${label}.role is unsupported`);
  }
  return value as DialogueSegmentRoleV1;
}

function handleFields(
  row: Record<string, unknown>,
  role: DialogueSegmentRoleV1,
  label: string,
): Pick<DialogueTrackSegmentV1, "seamSample" | "coveredByCutSegmentId"> {
  const hasSeam = Object.hasOwn(row, "seamSample");
  const hasCover = Object.hasOwn(row, "coveredByCutSegmentId");
  if (role === "primary" && (hasSeam || hasCover)) {
    throw new Error(`${label} primary cannot carry handle fields`);
  }
  if (role !== "primary" && (!hasSeam || !hasCover)) {
    throw new Error(`${label} handle fields are required`);
  }
  if (role === "primary") return {};
  return {
    seamSample: dialogueSafeInteger(row.seamSample, `${label}.seamSample`),
    coveredByCutSegmentId: stableId(
      row.coveredByCutSegmentId, `${label}.coveredByCutSegmentId`),
  };
}

export function parseDialogueTrackSegmentV1(
  value: unknown,
  label: string,
  compiled = false,
): DialogueTrackSegmentV1 {
  const row = objectValue(value, label);
  const derived = ["normalizedSourceSampleRange", "effectiveSpeed"] as const;
  const allowed = compiled ? [...SEGMENT_KEYS, ...derived] : SEGMENT_KEYS;
  const required = compiled ? [...SEGMENT_REQUIRED, ...derived] : SEGMENT_REQUIRED;
  exactKeys(row, allowed, required, label);
  const role = segmentRole(row.role, label);
  return {
    dialogueSegmentId: stableId(
      row.dialogueSegmentId, `${label}.dialogueSegmentId`),
    cutSegmentId: stableId(row.cutSegmentId, `${label}.cutSegmentId`),
    elementVersion: dialogueSafeInteger(
      row.elementVersion, `${label}.elementVersion`, 1),
    sourceId: stableId(row.sourceId, `${label}.sourceId`),
    sourceSampleRate: dialogueSafeInteger(
      row.sourceSampleRate, `${label}.sourceSampleRate`, 1),
    sourceSampleRange: parseDialogueSampleRangeV1(
      row.sourceSampleRange, `${label}.sourceSampleRange`),
    outputSampleRange: parseDialogueSampleRangeV1(
      row.outputSampleRange, `${label}.outputSampleRange`),
    speed: parsePositiveRationalV1(row.speed),
    role,
    ...handleFields(row, role, label),
  };
}

function segmentOrder(left: DialogueTrackSegmentV1,
                      right: DialogueTrackSegmentV1): number {
  return left.outputSampleRange.startSample
    - right.outputSampleRange.startSample
    || ROLE_ORDER[left.role] - ROLE_ORDER[right.role]
    || left.dialogueSegmentId.localeCompare(right.dialogueSegmentId);
}

function validateHandle(
  row: DialogueTrackSegmentV1,
  primaries: Map<string, DialogueTrackSegmentV1>,
): void {
  const own = primaries.get(row.cutSegmentId);
  const covered = primaries.get(row.coveredByCutSegmentId ?? "");
  if (!own || !covered || own === covered) {
    throw new Error("each L/J handle must bind distinct owned and covering primaries");
  }
  const sameSource = row.elementVersion === own.elementVersion
    && row.sourceId === own.sourceId
    && row.sourceSampleRate === own.sourceSampleRate
    && JSON.stringify(row.speed) === JSON.stringify(own.speed);
  if (!sameSource) {
    throw new Error("an L/J handle must share source/version/speed with its primary");
  }
  const seam = row.seamSample;
  const valid = row.role === "j-cut-handle"
    ? row.outputSampleRange.endSampleExclusive === seam
      && own.outputSampleRange.startSample === seam
      && covered.outputSampleRange.endSampleExclusive === seam
      && row.outputSampleRange.startSample
        >= covered.outputSampleRange.startSample
      && row.sourceSampleRange.endSampleExclusive
        === own.sourceSampleRange.startSample
    : row.outputSampleRange.startSample === seam
      && own.outputSampleRange.endSampleExclusive === seam
      && covered.outputSampleRange.startSample === seam
      && row.outputSampleRange.endSampleExclusive
        <= covered.outputSampleRange.endSampleExclusive
      && row.sourceSampleRange.startSample
        === own.sourceSampleRange.endSampleExclusive;
  if (!valid) throw new Error("L/J handle boundaries do not share the declared seam");
}

export function validateDialogueSegmentsV1(
  rows: DialogueTrackSegmentV1[],
  totalSamples: number,
): void {
  if (!rows.length) throw new Error("dialogue segments must be non-empty");
  const sorted = [...rows].sort(segmentOrder);
  if (rows.some((row, index) => row.dialogueSegmentId
      !== sorted[index]?.dialogueSegmentId)) {
    throw new Error("dialogue segments are not canonically ordered");
  }
  if (new Set(rows.map((row) => row.dialogueSegmentId)).size !== rows.length) {
    throw new Error("dialogue segment IDs must be unique");
  }
  if (rows.some((row) => row.outputSampleRange.endSampleExclusive > totalSamples)) {
    throw new Error("dialogue segment exceeds program samples");
  }
  const primaryRows = rows.filter((row) => row.role === "primary");
  const primaries = new Map(primaryRows.map((row) => [row.cutSegmentId, row]));
  if (primaries.size !== primaryRows.length) {
    throw new Error("cut segments require one primary dialogue span");
  }
  const primaryOrder = [...primaryRows].sort(segmentOrder);
  if (primaryOrder.some((row, index) => index > 0
      && primaryOrder[index - 1]!.outputSampleRange.endSampleExclusive
        > row.outputSampleRange.startSample)) {
    throw new Error("primary dialogue spans cannot overlap");
  }
  const handles = rows.filter((row) => row.role !== "primary");
  const handleKeys = handles.map((row) => `${row.cutSegmentId}:${row.role}`);
  if (new Set(handleKeys).size !== handleKeys.length) {
    throw new Error("a cut segment cannot repeat one handle role");
  }
  handles.forEach((row) => validateHandle(row, primaries));
}

export function parseDialogueTrackV1(value: unknown): DialogueTrackV1 {
  const row = objectValue(value, "DialogueTrackV1");
  exactKeys(row, TRACK_KEYS, TRACK_KEYS, "DialogueTrackV1");
  const header = parseDialogueHeaderV1(row, "dialogue-track");
  if (!Array.isArray(row.segments)) {
    throw new Error("DialogueTrackV1.segments must be an array");
  }
  const segments = row.segments.map((item, index) =>
    parseDialogueTrackSegmentV1(item, `segments[${index}]`));
  validateDialogueSegmentsV1(segments, header.totalOutputSamples);
  segments.forEach((segment) => deriveDialogueMappingV1(
    segment,
    header.projectSampleRate,
    header.maxAbsoluteSpeedDeviation,
  ));
  return {
    schemaVersion: 1,
    kind: "dialogue-track",
    ...header,
    segments,
  };
}

export type {
  DialogueSampleRangeV1,
  DialogueTrackSegmentV1,
  DialogueTrackV1,
} from "./dialogue-authority-types";
