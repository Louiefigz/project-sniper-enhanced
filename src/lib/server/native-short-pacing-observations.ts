/** Measurements on the existing kept-word clock, never a semantic pace classifier. */
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { assertNativeCaptionGroups, nativeCaptionGroupEnd } from "./guided-native-captions";
import type { NativeCanvasInput, NativeWindow } from "./native-short-composition";
import type { NativeShortProjectInput } from "./native-short-project";
import { nativeCaptionDisplayMap, nativeCaptionPhraseText } from "./native-caption-display";

export interface PacingVisualWindow extends NativeWindow {
  id: string; requiredHold: boolean;
}

/** Bind both the delivery clock and the actual treatment, including custom scenes. */
export function nativePacingBindings(input: NativeShortProjectInput) {
  const c = input.canvas, display = nativeCaptionDisplayMap(c);
  return {
    timingHash: canonicalJsonSha256({ source: c.sourceFile, cuts: c.cuts, segments: c.segments,
      frameRate: c.frameRate, totalFrames: c.totalFrames, occurrences: c.occurrences, captionGroups: c.captionGroups }),
    visualHash: canonicalJsonSha256({ pictureViews: c.pictureViews, captionViews: c.captionViews,
      ...(c.captionMode === "source-burned" ? { captionMode: c.captionMode } : {}),
      ...(display.size ? { captionCorrections: c.captionCorrections } : {}),
      text: c.text, shapes: c.shapes, motion: c.motion, titleCard: c.titleCard ?? null,
      extension: input.extension ?? null, scenes: input.strategy.scenes,
      supporting: input.strategy.supportingSearch.candidates.filter(row => row.selected),
      assets: input.assets.map(({ file, sha256, role }) => ({ file, sha256, role })) }),
  };
}

/** Require an ordered finite frame clock before measuring even an unbuilt plan. */
function frameRate(canvas: NativeCanvasInput): number {
  const [num, den] = canvas.frameRate.split("/").map(Number), fps = num / den;
  if (!/^\d+\/\d+$/u.test(canvas.frameRate) || !Number.isFinite(fps) || fps < 1 || fps > 60
      || !Number.isSafeInteger(canvas.totalFrames) || canvas.totalFrames < 1 || canvas.totalFrames > 60000
      || !Array.isArray(canvas.occurrences) || !canvas.occurrences.length || canvas.occurrences.length > 20000) {
    throw new Error("Pacing observations need a bounded native word/frame clock");
  }
  assertNativeCaptionGroups(canvas.captionGroups, canvas);
  canvas.occurrences.forEach((word, index) => {
    if (word[0] !== index || !Number.isSafeInteger(word[3]) || !Number.isSafeInteger(word[4])
        || word[3] < 0 || word[4] <= word[3] || word[4] > canvas.totalFrames
        || (index > 0 && word[3] < canvas.occurrences[index - 1][3])) {
      throw new Error("Pacing word windows are invalid or out of order");
    }
  });
  return fps;
}

/** Count overlapping ASR windows once; preserve actual gaps, including endpoints. */
function speechWindows(canvas: NativeCanvasInput) {
  const speech: NativeWindow[] = [];
  for (const word of canvas.occurrences) {
    const previous = speech.at(-1);
    if (previous && word[3] <= previous.endFrame) previous.endFrame = Math.max(previous.endFrame, word[4]);
    else speech.push({ startFrame: word[3], endFrame: word[4] });
  }
  const gaps: NativeWindow[] = [];
  let cursor = 0;
  for (const window of speech) {
    if (window.startFrame > cursor) gaps.push({ startFrame: cursor, endFrame: window.startFrame });
    cursor = window.endFrame;
  }
  if (cursor < canvas.totalFrames) gaps.push({ startFrame: cursor, endFrame: canvas.totalFrames });
  return { speech, gaps };
}

/** Reuse caption membership and the renderer's next-phrase clamp, without regrouping words. */
export function measureNativeShortPacing(canvas: NativeCanvasInput) {
  const fps = frameRate(canvas), { speech, gaps } = speechWindows(canvas), display = nativeCaptionDisplayMap(canvas);
  const phrases = canvas.captionGroups.map((ids, index) => {
    const first = canvas.occurrences[ids[0]], endFrame = nativeCaptionGroupEnd(canvas, index);
    if (endFrame <= first[3]) throw new Error("Pacing caption phrase has no visible reading interval");
    return { occurrenceIds: ids, startFrame: first[3], endFrame,
      ...nativeCaptionPhraseText(canvas, ids, display),
      durationSeconds: (endFrame - first[3]) / fps,
      wordsPerMinute: ids.length * 60 * fps / (endFrame - first[3]) };
  });
  return { schemaVersion: 1, scope: "timing-observations-not-energy-or-comprehension", fps,
    ...(canvas.captionMode === "source-burned" ? { captionMode: canvas.captionMode,
      captionTimingScope: "transcript-groups-only-burned-caption-timing-unmeasured" } : {}),
    totalFrames: canvas.totalFrames, durationSeconds: canvas.totalFrames / fps,
    wordCount: canvas.occurrences.length, wordsPerMinute: canvas.occurrences.length * 60 * fps / canvas.totalFrames,
    speechCoverageFrames: speech.reduce((sum, row) => sum + row.endFrame - row.startFrame, 0),
    gaps, phrases, cutFrames: canvas.segments.slice(1).map(row => row.startFrame),
    knownMotion: canvas.motion.map(({ id, startFrame, durationFrames }) => ({ id, startFrame, durationFrames })) };
}

/** Inventory static timing from the same generated HTML used for assembly. */
export function nativePacingVisualWindows(input: NativeShortProjectInput, html: string): PacingVisualWindow[] {
  const [num, den] = input.canvas.frameRate.split("/").map(Number), fps = num / den;
  const required = new Set(input.canvas.text.map(row => row.id));
  if (input.canvas.titleCard) required.add("native-title-card");
  const customIds = new Set([...(input.extension?.markup ?? "").matchAll(/\sid="([^"]+)"/gu)].map(row => row[1]));
  const windows: PacingVisualWindow[] = [];
  for (const match of html.matchAll(/<[a-z][a-z0-9-]*\b[^>]*>/gu)) {
    const tag = match[0], id = /\sid="([^"]+)"/u.exec(tag)?.[1];
    if (!id || !/\sclass="[^"]*\bclip\b[^"]*"/u.test(tag)) continue;
    const start = /\sdata-start="([^"]+)"/u.exec(tag)?.[1];
    const duration = /\sdata-duration="([^"]+)"/u.exec(tag)?.[1];
    const left = Number(start) * fps, right = left + Number(duration) * fps;
    if (start === undefined || duration === undefined || !Number.isFinite(left) || !Number.isFinite(right)
        || Math.abs(left - Math.round(left)) > .00001 || Math.abs(right - Math.round(right)) > .00001
        || left < 0 || right <= left || right > input.canvas.totalFrames + .00001) {
      throw new Error(`Pacing target ${id} has no exact executable frame window`);
    }
    windows.push({ id, startFrame: Math.round(left), endFrame: Math.round(right),
      requiredHold: required.has(id) || customIds.has(id) });
  }
  return windows;
}
