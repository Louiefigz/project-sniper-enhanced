/** Occurrence-specific caption display corrections preserve source speech and its clock. */
import { captionDisplayTextWithinLimit, captionTextWithinLimit, trimCaptionText } from "@/app/api/producer/ai-edit/caption-text-contract-v1";
import { exactKeys, objectValue } from "@/lib/producer/contracts/validation";
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
export interface NativeCaptionDisplayInput {
  occurrences: ProposalWordOccurrence[];
  captionCorrections?: NativeCaptionDisplayCorrection[];
  captionMode?: "native" | "source-burned";
  captionViews: Array<{ startFrame: number; endFrame: number }>;
  pictureViews: Array<{ startFrame: number; endFrame: number }>;
  totalFrames: number;
}

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

/** Declare who owns visible captions; source pixels still require visual review. */
export function assertNativeCaptionPresentation(input: NativeCaptionDisplayInput): void {
  if (input.captionMode !== undefined && !["native", "source-burned"].includes(input.captionMode)) {
    throw new Error("Native caption mode is unsupported");
  }
  if (!Array.isArray(input.captionViews)) throw new Error("Native caption views must be an array");
  if (input.captionMode === "source-burned") {
    if (input.captionViews.length) throw new Error("Source-burned captions cannot add native caption views");
    if (input.captionCorrections !== undefined && (!Array.isArray(input.captionCorrections) || input.captionCorrections.length)) {
      throw new Error("Source-burned captions cannot apply native caption corrections");
    }
    assertSourceCaptionCoverage(input);
    return;
  }
  let next = 0;
  for (const view of input.captionViews) {
    if (view.startFrame !== next) throw new Error("Native caption views must partition the complete Short");
    next = view.endFrame;
  }
  if (next !== input.totalFrames) throw new Error("Native caption views omit part of the Short");
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
        || /[\u0000-\u001f\u007f]/u.test(row.displayText)
        || row.displayText === word[5]) throw new Error("Native caption correction needs changed, bounded display text without controls");
    if (!captionTextWithinLimit(row.reason, 500) || /[\u0000-\u001f\u007f]/u.test(row.reason)) {
      throw new Error("Native caption correction needs a bounded review reason");
    }
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
