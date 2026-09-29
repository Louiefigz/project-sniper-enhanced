/** Occurrence-specific display corrections and reasoned suppressions preserve source speech and its clock. */
import { CAPTION_DIRECTIONAL_CONTROLS, captionDisplayTextWithinLimit, captionTextWithinLimit,
  trimCaptionText } from "@/app/api/producer/ai-edit/caption-text-contract-v1";
import { exactKeys, objectValue } from "@/lib/producer/contracts/validation";
import { assertNativeCaptionGroups, nativeCaptionGroupEnd, type NativeCaptionGroups } from "./guided-native-captions";
import type { ProposalWordOccurrence } from "./guided-proposal-speech";

export interface NativeCaptionDisplayCorrection {
  occurrenceId: number;
  /** Original ASR spelling is an exact guard, never overwritten by this correction. */
  expectedSourceText: string;
  /** All displayed words share this occurrence's existing frame/highlight window. */
  displayText: string;
  /** Describes the actual editorial basis; validation cannot establish that someone listened. */
  reason: string;
}
/**
 * Output frames on which no native caption draws, e.g. while the opening title card holds.
 * Words, phrase groups and the frame clock are unchanged; caption views resume at `endFrame`.
 */
export interface NativeCaptionSuppression {
  /** First output frame without a native caption. */
  startFrame: number;
  /** Exclusive output frame; the next caption view starts here. */
  endFrame: number;
  /** The actual editorial basis; validation checks frames and bounds, not whether it is true. */
  reason: string;
}
export interface NativeCaptionDisplayInput {
  occurrences: ProposalWordOccurrence[];
  captionGroups: NativeCaptionGroups;
  captionCorrections?: NativeCaptionDisplayCorrection[];
  captionSuppressions?: NativeCaptionSuppression[];
  captionMode?: "native" | "source-burned";
  captionViews: Array<{ startFrame: number; endFrame: number }>;
  pictureViews: Array<{ startFrame: number; endFrame: number }>;
  totalFrames: number;
}

const CONTROLS = /[\u0000-\u001f\u007f]/u;
const REASON_CONTROLS = /[\u0000-\u001f\u007f-\u009f]/u;
const READABLE = /[\p{L}\p{N}\p{P}\p{S}]/u;
const SUPPRESSION_KEYS = ["startFrame", "endFrame", "reason"];

/** A reviewer-readable reason: bounded, with visible text and no C0/C1 or directional controls. */
function readableReason(value: unknown): value is string {
  return captionTextWithinLimit(value, 500) && !REASON_CONTROLS.test(value)
    && !CAPTION_DIRECTIONAL_CONTROLS.test(value) && READABLE.test(value);
}

/** Frames of `window` outside every suppression window; windows are sorted and disjoint. */
export function unsuppressedFragments(window: { startFrame: number; endFrame: number },
  hidden: NativeCaptionSuppression[]): Array<{ startFrame: number; endFrame: number }> {
  const parts: Array<{ startFrame: number; endFrame: number }> = [];
  let cursor = window.startFrame;
  for (const row of hidden) {
    if (row.endFrame <= cursor || row.startFrame >= window.endFrame) continue;
    if (row.startFrame > cursor) parts.push({ startFrame: cursor, endFrame: row.startFrame });
    cursor = row.endFrame;
  }
  if (cursor < window.endFrame) parts.push({ startFrame: cursor, endFrame: window.endFrame });
  return parts;
}

const frameCount = (parts: Array<{ startFrame: number; endFrame: number }>) =>
  parts.reduce((sum, part) => sum + part.endFrame - part.startFrame, 0);

/** Burned captions require continuously displayed source; overlay clearance is visual QA. */
function assertSourceCaptionCoverage(input: NativeCaptionDisplayInput): void {
  if (!Array.isArray(input.pictureViews) || input.pictureViews.length > 128) throw new Error("Source-burned captions need bounded source views");
  let next = 0;
  for (const view of [...input.pictureViews].sort((left, right) => left.startFrame - right.startFrame)) {
    if (![view.startFrame, view.endFrame].every(Number.isSafeInteger) || view.startFrame < 0
        || view.endFrame <= view.startFrame || view.endFrame > input.totalFrames || view.startFrame > next) {
      throw new Error("Source-burned captions need continuous source picture coverage");
    }
    next = Math.max(next, view.endFrame);
  }
  if (next !== input.totalFrames) throw new Error("Source-burned captions need continuous source picture coverage");
}

/** Bounded, exact, ordered and reasoned windows; malformed rows never reach the renderer. */
function suppressionRows(input: NativeCaptionDisplayInput): NativeCaptionSuppression[] {
  const rows = input.captionSuppressions;
  if (rows === undefined) return [];
  if (!Array.isArray(rows) || rows.length > 128) throw new Error("Native caption suppressions are unbounded or malformed");
  let previous = 0;
  for (const value of rows) {
    const row = objectValue(value, "native caption suppression");
    exactKeys(row, SUPPRESSION_KEYS, SUPPRESSION_KEYS, "native caption suppression");
    const start = row.startFrame as number, end = row.endFrame as number;
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || end <= start
        || end > input.totalFrames) throw new Error("Native caption suppression needs exact in-range output frames");
    if (start < previous) throw new Error("Native caption suppressions overlap or are out of order");
    if (!readableReason(row.reason)) throw new Error("Native caption suppression needs a bounded, readable editorial reason");
    previous = end;
  }
  return rows;
}

const OMITTED = "Native caption views omit part of the Short; caption-free frames need a reasoned captionSuppressions window";
const OVERLAPPED = "Native caption views and suppressions must partition the complete Short";

/** Visible caption views and reasoned suppressions together partition the output clock. */
function assertCaptionCoverage(input: NativeCaptionDisplayInput, hidden: NativeCaptionSuppression[]): void {
  let next = 0, index = 0;
  const skipSuppressed = () => { while (hidden[index]?.startFrame === next) next = hidden[index++].endFrame; };
  for (const view of input.captionViews) {
    skipSuppressed();
    if (view.startFrame > next) throw new Error(OMITTED);
    if (view.startFrame !== next) throw new Error(OVERLAPPED);
    next = view.endFrame;
  }
  skipSuppressed();
  if (index !== hidden.length) throw new Error(OVERLAPPED);
  if (next !== input.totalFrames) throw new Error(OMITTED);
}

/** Each phrase's rendered window on the shared next-phrase clamp, index-aligned with its group. */
function phraseWindows(input: NativeCaptionDisplayInput) {
  return input.captionGroups.map((group, index) => ({ startFrame: input.occurrences[group[0]][3],
    endFrame: nativeCaptionGroupEnd(input, index) }));
}

/**
 * A word spoken wholly outside every window must reach the screen, so its phrase keeps a visible
 * frame. A word only partly inside (a tail running past the resume frame, common at rounded phrase
 * boundaries) is allowed and reported as uncaptioned. Phrases the clamp never shows are historical.
 */
function assertHeardWordsCaptioned(input: NativeCaptionDisplayInput, hidden: NativeCaptionSuppression[]): void {
  phraseWindows(input).forEach((phrase, index) => {
    if (phrase.endFrame <= phrase.startFrame || frameCount(unsuppressedFragments(phrase, hidden))) return;
    const outside = input.captionGroups[index].find(id => {
      const word = { startFrame: input.occurrences[id][3], endFrame: input.occurrences[id][4] };
      return frameCount(unsuppressedFragments(word, hidden)) === word.endFrame - word.startFrame;
    });
    if (outside !== undefined) {
      throw new Error(`Native caption suppression hides word ${outside}'s whole phrase although the word is spoken wholly outside every window`);
    }
  });
}

/** Each window must hide some phrase frame, at least one phrase frame stays visible, heard words show. */
function assertSuppressionEffect(input: NativeCaptionDisplayInput, hidden: NativeCaptionSuppression[]): void {
  if (!hidden.length) return;
  assertNativeCaptionGroups(input.captionGroups, input);
  const phrases = phraseWindows(input).filter(row => row.endFrame > row.startFrame);
  if (hidden.some(row => !phrases.some(phrase => phrase.startFrame < row.endFrame && phrase.endFrame > row.startFrame))) {
    throw new Error("Native caption suppression hides no caption phrase; remove it or correct its frames");
  }
  if (!phrases.some(phrase => frameCount(unsuppressedFragments(phrase, hidden)))) {
    throw new Error("Native caption suppressions cannot hide every caption phrase");
  }
  assertHeardWordsCaptioned(input, hidden);
}

/** Declare who owns visible captions; source pixels still require visual review. */
export function assertNativeCaptionPresentation(input: NativeCaptionDisplayInput): void {
  if (input.captionMode !== undefined && !["native", "source-burned"].includes(input.captionMode)) {
    throw new Error("Native caption mode is unsupported");
  }
  if (!Array.isArray(input.captionViews)) throw new Error("Native caption views must be an array");
  const hidden = suppressionRows(input);
  if (input.captionMode === "source-burned") {
    if (input.captionViews.length) throw new Error("Source-burned captions cannot add native caption views");
    if (input.captionCorrections !== undefined && (!Array.isArray(input.captionCorrections) || input.captionCorrections.length)) {
      throw new Error("Source-burned captions cannot apply native caption corrections");
    }
    if (hidden.length) throw new Error("Source-burned captions cannot suppress native caption windows");
    assertSourceCaptionCoverage(input);
    return;
  }
  assertCaptionCoverage(input, hidden);
  assertSuppressionEffect(input, hidden);
}

/** Validated suppression windows; absent and empty both mean captions cover every view. */
export function nativeCaptionSuppressions(input: NativeCaptionDisplayInput): NativeCaptionSuppression[] {
  assertNativeCaptionPresentation(input);
  return suppressionRows(input);
}

/** Per phrase (index-aligned with groups): its rendered window and the fragments left on screen. */
export function nativeCaptionPhraseVisibility(input: NativeCaptionDisplayInput) {
  const hidden = nativeCaptionSuppressions(input);
  return phraseWindows(input).map(phrase => ({ ...phrase,
    fragments: phrase.endFrame > phrase.startFrame ? unsuppressedFragments(phrase, hidden) : [] }));
}

/** Validate a bounded ordered map; multiword display shares the original highlight window. */
export function nativeCaptionDisplayMap(input: NativeCaptionDisplayInput): Map<number, string> {
  assertNativeCaptionPresentation(input);
  const display = new Map<number, string>(), rows = input.captionCorrections;
  if (rows === undefined) return display;
  if (!Array.isArray(rows) || rows.length > 128) throw new Error("Native caption corrections are unbounded or malformed");
  let previous = -1;
  for (const value of rows) {
    const row = objectValue(value, "native caption correction");
    const keys = ["occurrenceId", "expectedSourceText", "displayText", "reason"];
    exactKeys(row, keys, keys, "native caption correction");
    const id = row.occurrenceId as number, word = input.occurrences[id];
    if (!Number.isSafeInteger(id) || id <= previous || !word || word[0] !== id
        || row.expectedSourceText !== word[5]) throw new Error("Native caption correction has a stale, duplicate or invalid source occurrence");
    if (!captionDisplayTextWithinLimit(row.displayText, 256)
        || row.displayText !== trimCaptionText(row.displayText)
        || CONTROLS.test(row.displayText)
        || row.displayText === word[5]) throw new Error("Native caption correction needs changed, bounded display text without controls");
    if (!readableReason(row.reason)) throw new Error("Native caption correction needs a bounded review reason");
    display.set(id, row.displayText);
    previous = id;
  }
  return display;
}

/** Preserve legacy phrase observations; show original text separately when display is corrected. */
export function nativeCaptionPhraseText(input: NativeCaptionDisplayInput, ids: number[], display: Map<number, string>) {
  const sourceText = ids.map(id => input.occurrences[id][5]).join(" ");
  if (!ids.some(id => display.has(id))) return { text: sourceText };
  const text = ids.map(id => display.get(id) ?? input.occurrences[id][5]).join(" ");
  return { text, sourceText, displayWordCount: text.split(/\s+/u).length };
}
