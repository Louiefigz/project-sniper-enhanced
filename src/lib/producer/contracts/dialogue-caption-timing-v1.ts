import type { PositiveRationalV1 } from "./positive-rational";
import { parsePositiveRationalV1 } from "./positive-rational";
import type {
  DialogueSampleRangeV1,
  DialogueSegmentRoleV1,
} from "./dialogue-authority-types";
import {
  assertDialogueCaptionWordBindings,
} from "./dialogue-caption-timing-map";
import { parseDialogueMapV1 } from "./dialogue-map-v1";
import {
  dialogueSafeInteger,
} from "./dialogue-exact-samples";
import {
  parseDialogueSampleRangeV1,
} from "./dialogue-track-v1";
import {
  exactKeys,
  objectValue,
  sha256,
  stableId,
  stringValue,
} from "./validation";

const WORD_ID = /^w-[0-9a-f]{16}$/u;
const ROLES = ["primary", "j-cut-handle", "l-cut-handle"] as const;
const WORD_KEYS = [
  "wordId", "sourceWordId", "occurrence", "text", "sourceId",
  "sourceSampleRate", "sourceSampleRange", "transcriptTimingHash",
  "ownerCutSegmentId", "ownerElementVersion", "dialogueSegmentIds",
  "dialogueRoles", "coveringCutSegmentIds", "startSample",
  "endSampleExclusive", "startFrame", "endFrameExclusive", "speaker",
] as const;
const WORD_REQUIRED = WORD_KEYS.filter((key) => key !== "speaker");
const TIMING_KEYS = [
  "schemaVersion", "kind", "dialogueMapHash", "dialogueTrackHash",
  "pictureTimelineMapHash", "fps", "sampleRate", "words",
] as const;

export interface ResolvedDialogueCaptionWordV1 {
  wordId: string;
  sourceWordId: string;
  occurrence: number;
  text: string;
  sourceId: string;
  sourceSampleRate: number;
  sourceSampleRange: DialogueSampleRangeV1;
  transcriptTimingHash: string;
  ownerCutSegmentId: string;
  ownerElementVersion: number;
  dialogueSegmentIds: string[];
  dialogueRoles: DialogueSegmentRoleV1[];
  coveringCutSegmentIds: string[];
  startSample: number;
  endSampleExclusive: number;
  startFrame: number;
  endFrameExclusive: number;
  speaker?: string | number;
}

export interface DialogueCaptionTimingV1 {
  schemaVersion: 1;
  kind: "dialogue-caption-timing";
  dialogueMapHash: string;
  dialogueTrackHash: string;
  pictureTimelineMapHash: string;
  fps: PositiveRationalV1;
  sampleRate: number;
  words: ResolvedDialogueCaptionWordV1[];
}

function wordId(value: unknown, label: string): string {
  if (typeof value !== "string" || !WORD_ID.test(value)) {
    throw new Error(`${label} must be a stable word ID`);
  }
  return value;
}

function stableIds(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || !value.length) {
    throw new Error(`${label} must be a non-empty array`);
  }
  const result = value.map((item, index) =>
    stableId(item, `${label}[${index}]`));
  if (new Set(result).size !== result.length) {
    throw new Error(`${label} must contain unique IDs`);
  }
  return result;
}

function roles(value: unknown, label: string): DialogueSegmentRoleV1[] {
  if (!Array.isArray(value) || !value.length) {
    throw new Error(`${label} must be a non-empty array`);
  }
  return value.map((item, index) => {
    if (typeof item !== "string" || !ROLES.includes(
      item as DialogueSegmentRoleV1,
    )) {
      throw new Error(`${label}[${index}] is unsupported`);
    }
    return item as DialogueSegmentRoleV1;
  });
}

function safeText(value: unknown, label: string): string {
  const result = stringValue(value, label, 500);
  if (/[\\\r\n]/u.test(result)) throw new Error(`${label} is unsafe`);
  return result;
}

function optionalSpeaker(value: unknown): { speaker?: string | number } {
  if (value === undefined) return {};
  if (typeof value !== "string"
      && (!Number.isSafeInteger(value) || typeof value === "boolean")) {
    throw new Error("dialogue caption speaker is invalid");
  }
  return { speaker: value as string | number };
}

function parseWord(value: unknown, label: string): ResolvedDialogueCaptionWordV1 {
  const row = objectValue(value, label);
  exactKeys(row, WORD_KEYS, WORD_REQUIRED, label);
  const dialogueSegmentIds = stableIds(
    row.dialogueSegmentIds, `${label}.dialogueSegmentIds`);
  const dialogueRoles = roles(row.dialogueRoles, `${label}.dialogueRoles`);
  const coveringCutSegmentIds = stableIds(
    row.coveringCutSegmentIds, `${label}.coveringCutSegmentIds`);
  if (dialogueSegmentIds.length !== dialogueRoles.length
      || dialogueRoles.length !== coveringCutSegmentIds.length) {
    throw new Error(`${label} dialogue binding arrays differ in length`);
  }
  const startSample = dialogueSafeInteger(
    row.startSample, `${label}.startSample`);
  const endSampleExclusive = dialogueSafeInteger(
    row.endSampleExclusive, `${label}.endSampleExclusive`, 1);
  const startFrame = dialogueSafeInteger(
    row.startFrame, `${label}.startFrame`);
  const endFrameExclusive = dialogueSafeInteger(
    row.endFrameExclusive, `${label}.endFrameExclusive`, 1);
  if (endSampleExclusive <= startSample || endFrameExclusive <= startFrame) {
    throw new Error(`${label} has an empty output range`);
  }
  return {
    wordId: wordId(row.wordId, `${label}.wordId`),
    sourceWordId: wordId(row.sourceWordId, `${label}.sourceWordId`),
    occurrence: dialogueSafeInteger(
      row.occurrence, `${label}.occurrence`, 1),
    text: safeText(row.text, `${label}.text`),
    sourceId: stableId(row.sourceId, `${label}.sourceId`),
    sourceSampleRate: dialogueSafeInteger(
      row.sourceSampleRate, `${label}.sourceSampleRate`, 1),
    sourceSampleRange: parseDialogueSampleRangeV1(
      row.sourceSampleRange, `${label}.sourceSampleRange`),
    transcriptTimingHash: sha256(
      row.transcriptTimingHash, `${label}.transcriptTimingHash`),
    ownerCutSegmentId: stableId(
      row.ownerCutSegmentId, `${label}.ownerCutSegmentId`),
    ownerElementVersion: dialogueSafeInteger(
      row.ownerElementVersion, `${label}.ownerElementVersion`, 1),
    dialogueSegmentIds,
    dialogueRoles,
    coveringCutSegmentIds,
    startSample,
    endSampleExclusive,
    startFrame,
    endFrameExclusive,
    ...optionalSpeaker(row.speaker),
  };
}

function validateWordOrder(words: ResolvedDialogueCaptionWordV1[]): void {
  const ordered = [...words].sort((left, right) =>
    left.startSample - right.startSample
    || left.endSampleExclusive - right.endSampleExclusive
    || left.wordId.localeCompare(right.wordId));
  if (words.some((word, index) => word.wordId !== ordered[index]?.wordId)) {
    throw new Error("dialogue caption words are not ordered");
  }
  if (new Set(words.map((word) => word.wordId)).size !== words.length) {
    throw new Error("dialogue caption occurrence IDs must be unique");
  }
  const grouped = new Map<string, ResolvedDialogueCaptionWordV1[]>();
  words.forEach((word) => grouped.set(
    word.sourceWordId,
    [...(grouped.get(word.sourceWordId) ?? []), word],
  ));
  for (const rows of grouped.values()) {
    if (rows.some((word, index) => word.occurrence !== index + 1)) {
      throw new Error("word occurrences do not follow exact output order");
    }
  }
}

export function parseDialogueCaptionTimingV1(
  value: unknown,
): DialogueCaptionTimingV1 {
  const row = objectValue(value, "DialogueCaptionTimingV1");
  exactKeys(row, TIMING_KEYS, TIMING_KEYS, "DialogueCaptionTimingV1");
  if (row.schemaVersion !== 1 || row.kind !== "dialogue-caption-timing") {
    throw new Error("DialogueCaptionTimingV1 version/kind is unsupported");
  }
  if (!Array.isArray(row.words) || !row.words.length) {
    throw new Error("DialogueCaptionTimingV1.words must be non-empty");
  }
  const words = row.words.map((item, index) =>
    parseWord(item, `words[${index}]`));
  validateWordOrder(words);
  return {
    schemaVersion: 1,
    kind: "dialogue-caption-timing",
    dialogueMapHash: sha256(
      row.dialogueMapHash, "DialogueCaptionTimingV1.dialogueMapHash"),
    dialogueTrackHash: sha256(
      row.dialogueTrackHash, "DialogueCaptionTimingV1.dialogueTrackHash"),
    pictureTimelineMapHash: sha256(
      row.pictureTimelineMapHash,
      "DialogueCaptionTimingV1.pictureTimelineMapHash",
    ),
    fps: parsePositiveRationalV1(row.fps),
    sampleRate: dialogueSafeInteger(
      row.sampleRate, "DialogueCaptionTimingV1.sampleRate", 1),
    words,
  };
}

export function validateDialogueCaptionTimingV1(
  value: unknown,
  mapValue: unknown,
  verifiedDialogueMapHash: string,
): DialogueCaptionTimingV1 {
  const timing = parseDialogueCaptionTimingV1(value);
  const dialogueMap = parseDialogueMapV1(mapValue);
  const mapHash = sha256(
    verifiedDialogueMapHash, "verified DialogueMapV1 hash");
  if (timing.dialogueMapHash !== mapHash
      || timing.dialogueTrackHash !== dialogueMap.dialogueTrackHash
      || timing.pictureTimelineMapHash !== dialogueMap.pictureTimelineMapHash
      || JSON.stringify(timing.fps) !== JSON.stringify(dialogueMap.projectFps)
      || timing.sampleRate !== dialogueMap.projectSampleRate) {
    throw new Error("DialogueCaptionTimingV1 does not bind DialogueMapV1");
  }
  timing.words.forEach((word) =>
    assertDialogueCaptionWordBindings(word, dialogueMap));
  return timing;
}
