import type {
  DialogueMapEntryV1,
  DialogueMapV1,
} from "./dialogue-authority-types";
import type {
  ResolvedDialogueCaptionWordV1,
} from "./dialogue-caption-timing-v1";
import { dialogueSafeInteger } from "./dialogue-exact-samples";

function intersect(entry: DialogueMapEntryV1,
                   word: ResolvedDialogueCaptionWordV1): [number, number] {
  const start = Math.max(
    entry.sourceSampleRange.startSample,
    word.sourceSampleRange.startSample,
  );
  const end = Math.min(
    entry.sourceSampleRange.endSampleExclusive,
    word.sourceSampleRange.endSampleExclusive,
  );
  if (end <= start) throw new Error("word does not intersect bound dialogue span");
  return [start, end];
}

function mapPoint(entry: DialogueMapEntryV1,
                  sourceSample: number, projectRate: number): number {
  const normalized = BigInt(sourceSample) * BigInt(projectRate)
    / BigInt(entry.sourceSampleRate);
  const source = entry.normalizedSourceSampleRange;
  const output = entry.outputSampleRange;
  const sourceLength = BigInt(
    source.endSampleExclusive - source.startSample);
  const outputLength = BigInt(
    output.endSampleExclusive - output.startSample);
  const result = BigInt(output.startSample)
    + (normalized - BigInt(source.startSample)) * outputLength / sourceLength;
  return dialogueSafeInteger(Number(result), "mapped dialogue sample");
}

function containingFrame(sample: number, dialogueMap: DialogueMapV1): number {
  const numerator = BigInt(dialogueMap.projectFps.numerator);
  const denominator = BigInt(dialogueMap.projectFps.denominator);
  const divisor = BigInt(dialogueMap.projectSampleRate) * denominator;
  const value = BigInt(sample + 1) * numerator;
  const ceiling = (value + divisor - BigInt(1)) / divisor;
  return Number(ceiling > BigInt(0) ? ceiling - BigInt(1) : BigInt(0));
}

function assertWordMap(
  word: ResolvedDialogueCaptionWordV1,
  entries: DialogueMapEntryV1[],
  dialogueMap: DialogueMapV1,
): void {
  const pieces = entries.map((entry) => {
    const [start, end] = intersect(entry, word);
    return {
      entry, start, end,
      outputStart: mapPoint(entry, start, dialogueMap.projectSampleRate),
      outputEnd: mapPoint(entry, end, dialogueMap.projectSampleRate),
    };
  }).sort((left, right) => left.start - right.start);
  const transitions = new Set([
    "j-cut-handle:primary",
    "primary:l-cut-handle",
  ]);
  if (pieces[0]?.start !== word.sourceSampleRange.startSample
      || pieces.at(-1)?.end !== word.sourceSampleRange.endSampleExclusive
      || pieces.some((piece, index) =>
        piece.entry.dialogueSegmentId !== entries[index]?.dialogueSegmentId)
      || pieces.some((piece, index) => index > 0
        && (pieces[index - 1]!.end !== piece.start
          || pieces[index - 1]!.outputEnd !== piece.outputStart
          || !transitions.has(
            `${pieces[index - 1]!.entry.role}:${piece.entry.role}`)))) {
    throw new Error("dialogue caption word has incompatible split spans");
  }
  const start = pieces[0]!.outputStart;
  const end = pieces.at(-1)!.outputEnd;
  if (word.startSample !== start || word.endSampleExclusive !== end
      || word.startFrame !== containingFrame(start, dialogueMap)
      || word.endFrameExclusive
        !== containingFrame(end - 1, dialogueMap) + 1) {
    throw new Error("dialogue caption word has stale mapped timing");
  }
}

export function assertDialogueCaptionWordBindings(
  word: ResolvedDialogueCaptionWordV1,
  dialogueMap: DialogueMapV1,
): void {
  const byId = new Map(dialogueMap.entries.map((entry) => [
    entry.dialogueSegmentId, entry,
  ]));
  const entries = word.dialogueSegmentIds.map((id, index) => {
    const entry = byId.get(id);
    const covering = entry?.role === "primary"
      ? entry.cutSegmentId
      : entry?.coveredByCutSegmentId;
    if (!entry
        || entry.cutSegmentId !== word.ownerCutSegmentId
        || entry.elementVersion !== word.ownerElementVersion
        || entry.sourceId !== word.sourceId
        || entry.sourceSampleRate !== word.sourceSampleRate
        || entry.role !== word.dialogueRoles[index]
        || covering !== word.coveringCutSegmentIds[index]) {
      throw new Error("dialogue caption word binding is stale");
    }
    return entry;
  });
  assertWordMap(word, entries, dialogueMap);
}
