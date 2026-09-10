import { packetCutSegments, packetSpeechEvidence, type PacketCutSegment, type PacketKeptWord, type PacketSpeechEvidence } from "@/app/api/producer/auto-edit/plan-review-packet-source";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { parsePositiveRationalV1 } from "@/lib/producer/contracts/positive-rational";
import { objectValue } from "@/lib/producer/contracts/validation";

/** Compact controller IDs, not provider-chosen paths/identifiers. Clip mask:1=head,2=tail. */
export type ProposalWordOccurrence = [occurrence: number, segment: number, sourceWord: number,
  startFrame: number, endFrameExclusive: number, text: string, clipMask: number];
export interface ProposalSpeechPartition { index: number; sourceId: string; startFrame: number; endFrameExclusive: number; text: string }
export interface ProposalSpeechInput { segments: PacketCutSegment[]; partitions: ProposalSpeechPartition[]; frameRate: string; totalFrames: number }

/** Picture spans alone cannot establish speech after a J-cut replaces an outgoing tail. */
export function assertProposalAudioWindows(parts: unknown[]): void {
  if (parts.some((value) => objectValue(value, "audio partition").nextAudioLeadS !== 0)) {
    throw new Error("J-cut proposal evidence is temporarily unsupported: qualified source-audio windows must include replaced tails and pre-in-point speech; picture-span words are not full-program audio evidence");
  }
}

function decimal(value: number): [bigint, bigint] {
  if (!Number.isFinite(value) || value < 0 || value > 1e9) throw new Error("Speech source time is outside the bounded decimal clock");
  const [mantissa, powerText] = String(value).toLowerCase().split("e"), [whole, fraction = ""] = mantissa.split(".");
  const power = Number(powerText ?? 0) - fraction.length;
  const numerator = BigInt(whole + fraction), scale = BigInt(10) ** BigInt(Math.abs(power));
  return power >= 0 ? [numerator * scale, BigInt(1)] : [numerator, scale];
}

/** Exact decimal subtraction before rational frame conversion; no floating-point epsilon policy. */
export function proposalRelativeFrame(input: { time: number; origin: number; frameRate: string; edge: "start" | "end" }): number {
  const [a, b] = decimal(input.time), [c, d] = decimal(input.origin), [numerator, denominator] = input.frameRate.split("/");
  const rate = parsePositiveRationalV1({ numerator, denominator });
  const top = (a * d - c * b) * BigInt(rate.numerator), bottom = b * d * BigInt(rate.denominator);
  if (top < BigInt(0)) throw new Error("Speech frame precedes its executed source partition");
  const frame = input.edge === "start" ? top / bottom : (top + bottom - BigInt(1)) / bottom;
  if (frame > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error("Speech frame exceeds safe integer range");
  return Number(frame);
}

/** Shared legacy parser reads each transcript once; its first-match mapping is NOT used as the actual cut. */
export function readProposalSourceSpeech(ctx: AutoEditCtx, manifest: Record<string, unknown>, segments: PacketCutSegment[]) {
  const used = new Set(segments.map((segment) => segment.sourceId));
  if (!Array.isArray(manifest.sources)) throw new Error("Proposal manifest has no source inventory");
  const coverage = manifest.sources.flatMap((value) => {
    const row = objectValue(value, "source");
    if (typeof row.id !== "string" || !used.has(row.id)) return [];
    if (typeof row.duration !== "number" || !Number.isFinite(row.duration) || row.duration <= 0
        || row.duration > 1e9 || segments.some((segment) => segment.sourceId === row.id && segment.sourceEnd > Number(row.duration))) {
      throw new Error("Used speech source lacks an admitted complete duration");
    }
    return [{ sourceId: row.id, start: 0, end: row.duration, speed: 1 }];
  });
  const speech = packetSpeechEvidence(ctx, manifest, packetCutSegments({ cutTrack: coverage }));
  assertProposalUsedSpeech(segments, speech); return speech;
}

/** Missing/empty used source cannot disappear because another source has words. Unused silence is allowed. */
export function assertProposalUsedSpeech(segments: PacketCutSegment[], speech: PacketSpeechEvidence): void {
  const used = new Set(segments.map((segment) => segment.sourceId));
  if (speech.keptWords.length > 60_000 || !speech.keptWords.length || speech.missingTranscriptSourceIds.some((id) => used.has(id))
      || [...used].some((id) => !speech.transcripts.some((row) => row.sourceId === id && row.sourceWordCount > 0)
        || !speech.keptWords.some((word) => word.sourceId === id))) {
    throw new Error("Proposal requires complete bounded speech evidence for every used source; nonspeech use needs explicit independent classification");
  }
}

function occurrence(input: ProposalSpeechInput, word: PacketKeptWord, segment: PacketCutSegment, sourceWord: number) {
  const start = Math.max(word.sourceStart, segment.sourceStart), end = Math.min(word.sourceOriginalEnd, segment.sourceEnd);
  if (end <= start) return null;
  const part = input.partitions[segment.index];
  if (!part || part.index !== segment.index || part.sourceId !== segment.sourceId || segment.speed !== 1) throw new Error("Speech occurrence partition differs from executed cut");
  const frame = (time: number, edge: "start" | "end") => part.startFrame + Math.min(part.endFrameExclusive - part.startFrame,
    proposalRelativeFrame({ time, origin: segment.sourceStart, frameRate: input.frameRate, edge }));
  const startFrame = frame(start, "start"), endFrame = frame(end, "end");
  if (endFrame <= startFrame) throw new Error("Retained source word collapses on the executed frame clock");
  const mask = (word.sourceStart < start ? 1 : 0) | (word.sourceOriginalEnd > end ? 2 : 0);
  return { tuple: [0, segment.index, sourceWord, startFrame, endFrame, word.word, mask] as ProposalWordOccurrence,
    sourceEnd: word.sourceOriginalEnd, sourceId: segment.sourceId };
}

function firstOverlappingWord(words: PacketKeptWord[], start: number) {
  let low = 0, high = words.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (words[middle].sourceOriginalEnd <= start) low = middle + 1; else high = middle;
  }
  return low;
}

function expandOccurrences(input: ProposalSpeechInput, bySource: Map<string, PacketKeptWord[]>) {
  const mapped: Array<NonNullable<ReturnType<typeof occurrence>>> = [];
  for (const words of bySource.values()) {
    if (words.some((word, index) => index > 0 && (word.sourceStart < words[index - 1].sourceStart || word.sourceOriginalEnd < words[index - 1].sourceOriginalEnd))) {
      throw new Error("Overlapping out-of-order transcript word endpoints need explicit normalization before proposal compilation");
    }
  }
  for (const segment of input.segments) {
    const words = bySource.get(segment.sourceId) ?? [];
    for (let index = firstOverlappingWord(words, segment.sourceStart); index < words.length && words[index].sourceStart < segment.sourceEnd; index += 1) {
      const value = occurrence(input, words[index], segment, index);
      if (value) mapped.push(value);
      if (mapped.length > 30_000) throw new Error("Proposal retained occurrences exceed the bounded 30000-word program");
    }
  }
  return mapped;
}

/** Half-open word spans: a punctuation endpoint crossed by another word is not a clean endpoint. */
function uncrossedEnds(candidates: number[], occurrences: ProposalWordOccurrence[]): number[] {
  let index = 0, maximumEnd = 0;
  return candidates.filter((end) => {
    while (index < occurrences.length && occurrences[index][3] < end) {
      maximumEnd = Math.max(maximumEnd, occurrences[index][4]); index += 1;
    }
    return maximumEnd <= end;
  });
}

/** Expand every source word to every retained occurrence, including repeated-payoff and trim-crossing words. */
export function mapProposalOccurrences(input: ProposalSpeechInput, speech: PacketSpeechEvidence) {
  assertProposalUsedSpeech(input.segments, speech);
  const wordsBySource = new Map<string, PacketKeptWord[]>();
  for (const word of speech.keptWords) { const rows = wordsBySource.get(word.sourceId) ?? []; rows.push(word); wordsBySource.set(word.sourceId, rows); }
  const mapped = expandOccurrences(input, wordsBySource);
  if (!mapped.length || mapped.length > 30_000) throw new Error("Proposal retained occurrences exceed the bounded 30000-word program");
  mapped.sort((left, right) => left.tuple[3] - right.tuple[3] || left.tuple[1] - right.tuple[1] || left.tuple[2] - right.tuple[2]);
  const occurrences = mapped.map((row, index) => { row.tuple[0] = index; return row.tuple; });
  const anchors = [...new Set([0, input.totalFrames, ...input.partitions.flatMap((part) => [part.startFrame, part.endFrameExclusive]),
    ...occurrences.flatMap((word) => [word[3], word[4]])])].sort((a, b) => a - b);
  if (anchors.length > 60_002) throw new Error("Proposal frame anchors exceed their bounded inventory");
  const utteranceEnds = new Map(speech.transcripts.map((row) => [row.sourceId, new Set(row.utterances.map((utterance) => utterance.end))]));
  const candidates = [...new Set(mapped.filter((row) => !(row.tuple[6] & 2) && (/[.!?]["')\]]*$/u.test(row.tuple[5].trim())
    || utteranceEnds.get(row.sourceId)?.has(row.sourceEnd)))
    .map((row) => row.tuple[4]))].sort((a, b) => a - b);
  const cleanEnds = uncrossedEnds(candidates, occurrences);
  return { occurrences, anchors, cleanEnds, wordTupleFields: ["occurrence", "segment", "sourceWord", "startFrame", "endFrameExclusive", "text", "clipMask"],
    wordTimingScope: "transcript-derived-floor-start-ceil-end-not-audibility-or-semantic-approval" as const };
}
