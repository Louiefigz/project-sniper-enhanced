import { createHash } from "node:crypto";
import type { EditPlan } from "@/lib/producer/edit-plan";

export interface SourceCaptionWordV1 {
  wordId: string;
  text: string;
  sourceId: string;
  sourceOrdinal: number;
  sourceStart: number;
  sourceEnd: number;
  speaker?: string | number;
}

export interface CaptionIndexedWordV1 extends SourceCaptionWordV1 {
  outputStart: number;
  outputEnd: number;
  sourceWordId?: string;
  occurrence?: number;
  cutSegmentIndex?: number;
}

export interface CaptionCutSegmentV1 {
  index: number;
  sourceId: string;
  sourceStart: number;
  sourceEnd: number;
  speed: number;
  outputStart: number;
}

function rounded(value: number): number {
  return Math.round(value * 10_000) / 10_000;
}

export function stableCaptionWordId(
  sourceId: string,
  ordinal: number,
): string {
  const digest = createHash("sha256")
    .update(`sniper-caption-word-v1\0${sourceId}\0${ordinal}`)
    .digest("hex").slice(0, 16);
  return `w-${digest}`;
}

export function occurrenceCaptionWordId(
  sourceWordId: string,
  occurrence: number,
): string {
  const digest = createHash("sha256")
    .update(
      `sniper-dialogue-caption-occurrence-v1\0${sourceWordId}\0${occurrence}`,
    )
    .digest("hex").slice(0, 16);
  return `w-${digest}`;
}

export function captionCutSegments(plan: EditPlan): CaptionCutSegmentV1[] {
  let cursor = 0;
  return (plan.cutTrack ?? []).map((row, index) => {
    const speed = row.speed ?? 1;
    if (!row.sourceId || !Number.isFinite(row.start)
        || !Number.isFinite(row.end) || !Number.isFinite(speed)
        || row.end <= row.start || speed <= 0) {
      throw new Error(`cutTrack[${index}] is invalid for caption indexing`);
    }
    const result = {
      index, sourceId: row.sourceId,
      sourceStart: row.start, sourceEnd: row.end,
      speed, outputStart: rounded(cursor),
    };
    cursor += (row.end - row.start) / speed;
    return result;
  });
}

function overlap(
  word: SourceCaptionWordV1,
  segment: CaptionCutSegmentV1,
): [number, number] | null {
  const start = Math.max(word.sourceStart, segment.sourceStart);
  const end = Math.min(word.sourceEnd, segment.sourceEnd);
  return start < end ? [start, end] : null;
}

function candidates(
  word: SourceCaptionWordV1,
  track: CaptionCutSegmentV1[],
): CaptionCutSegmentV1[] {
  const rows = track.filter((row) =>
    row.sourceId === word.sourceId && overlap(word, row) !== null);
  const onset = rows.filter((row) =>
    row.sourceStart <= word.sourceStart && word.sourceStart < row.sourceEnd);
  if (onset.length) return onset;
  const length = word.sourceEnd - word.sourceStart;
  return rows.filter((row) => {
    const kept = overlap(word, row)!;
    return (kept[1] - kept[0]) * 2 >= length;
  });
}

function mapped(
  word: SourceCaptionWordV1,
  segment: CaptionCutSegmentV1,
): CaptionIndexedWordV1 | null {
  const kept = overlap(word, segment);
  if (!kept || kept[1] - kept[0] < 0.04) return null;
  const output = (value: number) => rounded(
    segment.outputStart + (value - segment.sourceStart) / segment.speed,
  );
  return {
    ...word,
    outputStart: output(kept[0]),
    outputEnd: output(kept[1]),
  };
}

export function mapCaptionWordOccurrences(
  word: SourceCaptionWordV1,
  track: CaptionCutSegmentV1[],
): CaptionIndexedWordV1[] {
  const rows = candidates(word, track).flatMap((segment) => {
    const value = mapped(word, segment);
    return value ? [{ value, segment }] : [];
  });
  if (rows.length === 1) return [rows[0].value];
  return rows.map(({ value, segment }, index) => ({
    ...value,
    wordId: occurrenceCaptionWordId(word.wordId, index + 1),
    sourceWordId: word.wordId,
    occurrence: index + 1,
    cutSegmentIndex: segment.index,
  }));
}
