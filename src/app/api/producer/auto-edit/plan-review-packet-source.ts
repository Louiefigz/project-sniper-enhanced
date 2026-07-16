import { existsSync, lstatSync, readFileSync, realpathSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import type { AutoEditCtx } from "./stream";
import { AutoEditError } from "./stream";

export interface PacketCutSegment {
  index: number;
  sourceId: string;
  sourceStart: number;
  sourceEnd: number;
  speed: number;
  outputStart: number;
  outputEnd: number;
}

export interface PacketSourceWord {
  word: string;
  sourceStart: number;
  sourceEnd: number;
  confidence?: number;
}

export interface PacketKeptWord extends PacketSourceWord {
  sourceId: string;
  segmentIndex: number;
  sourceOriginalEnd: number;
  outputStart: number;
  outputEnd: number;
}

export interface PacketBoundaryEvidence {
  segmentIndex: number;
  sourceId: string;
  edge: "in" | "out";
  sourceTime: number;
  before: PacketSourceWord | null;
  after: PacketSourceWord | null;
}

export interface PacketUtterance {
  start: number;
  end: number;
  text: string;
}

export interface PacketTranscriptEvidence {
  sourceId: string;
  byteHash: string;
  utteranceCount: number;
  sourceWordCount: number;
  utterances: PacketUtterance[];
}

export interface PacketSpeechEvidence {
  transcripts: PacketTranscriptEvidence[];
  missingTranscriptSourceIds: string[];
  keptWords: PacketKeptWord[];
  boundaryNeighbors: PacketBoundaryEvidence[];
}

interface ParsedTranscript {
  evidence: PacketTranscriptEvidence;
  words: PacketSourceWord[];
}

interface ManifestSource {
  id: string;
  transcriptPath: string | null;
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new AutoEditError(`${label} must be a JSON object`);
  }
  return value as Record<string, unknown>;
}

function finite(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new AutoEditError(`${label} must be a finite number`);
  }
  return value;
}

function round4(value: number): number {
  const rounded = Math.round(value * 10_000) / 10_000;
  return Object.is(rounded, -0) ? 0 : rounded;
}

export function packetCutSegments(planValue: unknown): PacketCutSegment[] {
  const plan = object(planValue, "edit plan");
  const track = plan.cutTrack ?? [];
  if (!Array.isArray(track)) throw new AutoEditError("edit plan cutTrack must be an array");
  let outputStart = 0;
  return track.map((raw, index) => {
    const item = object(raw, `cutTrack[${index}]`);
    const sourceId = item.sourceId;
    const sourceStart = finite(item.start, `cutTrack[${index}].start`);
    const sourceEnd = finite(item.end, `cutTrack[${index}].end`);
    const speed = item.speed === undefined ? 1 : finite(item.speed, `cutTrack[${index}].speed`);
    if (typeof sourceId !== "string" || !sourceId || sourceEnd <= sourceStart || speed <= 0) {
      throw new AutoEditError(`cutTrack[${index}] has an invalid source or time range`);
    }
    const outputEnd = outputStart + (sourceEnd - sourceStart) / speed;
    const segment = {
      index, sourceId, sourceStart, sourceEnd, speed,
      outputStart: round4(outputStart), outputEnd: round4(outputEnd),
    };
    outputStart = outputEnd;
    return segment;
  });
}

function manifestSources(manifestValue: unknown): ManifestSource[] {
  const manifest = object(manifestValue, "asset manifest");
  if (!Array.isArray(manifest.sources)) {
    throw new AutoEditError("asset manifest sources must be an array");
  }
  const seen = new Set<string>();
  return manifest.sources.map((raw, index) => {
    const source = object(raw, `manifest.sources[${index}]`);
    if (typeof source.id !== "string" || !source.id || seen.has(source.id)) {
      throw new AutoEditError(`manifest.sources[${index}] has a missing or duplicate id`);
    }
    seen.add(source.id);
    if (source.transcriptPath !== null && source.transcriptPath !== undefined
        && typeof source.transcriptPath !== "string") {
      throw new AutoEditError(`manifest.sources[${index}].transcriptPath is invalid`);
    }
    const transcriptPath = typeof source.transcriptPath === "string" ? source.transcriptPath : null;
    return { id: source.id, transcriptPath };
  });
}

function safeTranscriptPath(root: string, requested: string): string {
  if (requested.split(/[\\/]/).includes("..")) {
    throw new AutoEditError(`transcript path traversal is forbidden: ${requested}`);
  }
  const candidate = path.isAbsolute(requested) ? requested : path.resolve(root, requested);
  const lexicalRelative = path.relative(path.resolve(root), path.resolve(candidate));
  if (!lexicalRelative || lexicalRelative.startsWith("..") || path.isAbsolute(lexicalRelative)) {
    throw new AutoEditError(`transcript resolves outside its source directory: ${requested}`);
  }
  let cursor = path.resolve(root);
  for (const part of lexicalRelative.split(path.sep)) {
    cursor = path.join(cursor, part);
    if (existsSync(cursor) && lstatSync(cursor).isSymbolicLink()) {
      throw new AutoEditError(`transcript path contains a symlink: ${requested}`);
    }
  }
  if (!existsSync(candidate) || !lstatSync(candidate).isFile()) {
    throw new AutoEditError(`transcript must be a regular non-symlink file: ${requested}`);
  }
  const resolvedRoot = realpathSync(root);
  const resolvedFile = realpathSync(candidate);
  const relative = path.relative(resolvedRoot, resolvedFile);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new AutoEditError(`transcript resolves outside its source directory: ${requested}`);
  }
  return resolvedFile;
}

function sourceWord(value: unknown, label: string): PacketSourceWord {
  const raw = object(value, label);
  const start = finite(raw.start, `${label}.start`);
  const end = finite(raw.end, `${label}.end`);
  if (typeof raw.word !== "string" || end < start) {
    throw new AutoEditError(`${label} has invalid word text or timing`);
  }
  const confidence = raw.confidence === undefined || raw.confidence === null
    ? undefined : finite(raw.confidence, `${label}.confidence`);
  return {
    word: raw.word, sourceStart: start, sourceEnd: end,
    ...(confidence === undefined ? {} : { confidence }),
  };
}

function transcriptRows(value: unknown, sourceId: string): {
  utterances: PacketUtterance[];
  words: PacketSourceWord[];
} {
  const transcript = object(value, `transcript ${sourceId}`).transcript;
  if (!Array.isArray(transcript)) {
    throw new AutoEditError(`transcript ${sourceId} has no transcript utterance array`);
  }
  const words: PacketSourceWord[] = [];
  const utterances = transcript.map((value, utteranceIndex) => {
    const raw = object(value, `transcript ${sourceId} utterance ${utteranceIndex}`);
    if (!Array.isArray(raw.words) || typeof raw.text !== "string") {
      throw new AutoEditError(`transcript ${sourceId} utterance ${utteranceIndex} is incomplete`);
    }
    const rowWords = raw.words.map((word, wordIndex) =>
      sourceWord(word, `transcript ${sourceId} word ${utteranceIndex}.${wordIndex}`));
    words.push(...rowWords);
    const start = finite(raw.start, `transcript ${sourceId} utterance ${utteranceIndex}.start`);
    const end = finite(raw.end, `transcript ${sourceId} utterance ${utteranceIndex}.end`);
    if (end < start) throw new AutoEditError(`transcript ${sourceId} utterance timing is invalid`);
    return { start, end, text: raw.text };
  });
  return { utterances, words };
}

function parsedTranscript(root: string, source: ManifestSource): ParsedTranscript {
  const transcriptPath = safeTranscriptPath(root, source.transcriptPath!);
  const bytes = readFileSync(transcriptPath);
  let value: unknown;
  try {
    value = JSON.parse(bytes.toString("utf8")) as unknown;
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new AutoEditError(`transcript ${source.id} is invalid JSON: ${detail}`);
  }
  const { utterances, words } = transcriptRows(value, source.id);
  const byteHash = createHash("sha256").update(bytes).digest("hex");
  return {
    evidence: {
      sourceId: source.id, byteHash,
      utteranceCount: utterances.length, sourceWordCount: words.length, utterances,
    },
    words,
  };
}

function keptWord(
  sourceId: string,
  word: PacketSourceWord,
  segments: PacketCutSegment[],
): PacketKeptWord | null {
  const segment = segments.find((item) => item.sourceId === sourceId
    && item.sourceStart <= word.sourceStart && word.sourceStart <= item.sourceEnd);
  if (!segment) return null;
  const sourceEnd = Math.min(word.sourceEnd, segment.sourceEnd);
  if (sourceEnd <= word.sourceStart + 1e-6) return null;
  return {
    ...word, sourceId, segmentIndex: segment.index,
    sourceOriginalEnd: word.sourceEnd, sourceEnd,
    outputStart: round4(segment.outputStart + (word.sourceStart - segment.sourceStart) / segment.speed),
    outputEnd: round4(segment.outputStart + (sourceEnd - segment.sourceStart) / segment.speed),
  };
}

function boundaryWord(word: PacketSourceWord | undefined): PacketSourceWord | null {
  return word ? { ...word } : null;
}

function segmentBoundaries(
  segment: PacketCutSegment,
  words: PacketSourceWord[],
): PacketBoundaryEvidence[] {
  return (["in", "out"] as const).map((edge) => {
    const sourceTime = edge === "in" ? segment.sourceStart : segment.sourceEnd;
    const before = [...words].reverse().find((word) => word.sourceStart < sourceTime);
    const after = words.find((word) => word.sourceStart >= sourceTime);
    return {
      segmentIndex: segment.index, sourceId: segment.sourceId, edge, sourceTime,
      before: boundaryWord(before), after: boundaryWord(after),
    };
  });
}

export function packetSpeechEvidence(
  ctx: AutoEditCtx,
  manifestValue: unknown,
  segments: PacketCutSegment[],
): PacketSpeechEvidence {
  const sources = manifestSources(manifestValue);
  const sourceIds = new Set(sources.map((source) => source.id));
  const used = new Set(segments.map((segment) => segment.sourceId));
  for (const sourceId of used) {
    if (!sourceIds.has(sourceId)) throw new AutoEditError(`cutTrack references unknown source ${sourceId}`);
  }
  const parsed = new Map<string, ParsedTranscript>();
  const missingTranscriptSourceIds: string[] = [];
  for (const source of sources) {
    if (!source.transcriptPath) {
      missingTranscriptSourceIds.push(source.id);
      if (used.has(source.id)) throw new AutoEditError(`kept source ${source.id} has no transcript`);
      continue;
    }
    parsed.set(source.id, parsedTranscript(ctx.transcriptsDir, source));
  }
  const keptWords = [...parsed.entries()].flatMap(([sourceId, transcript]) =>
    transcript.words.flatMap((word) => {
      const kept = keptWord(sourceId, word, segments);
      return kept ? [kept] : [];
    })).sort((left, right) => left.outputStart - right.outputStart
      || left.segmentIndex - right.segmentIndex || left.sourceStart - right.sourceStart);
  const boundaryNeighbors = segments.flatMap((segment) =>
    segmentBoundaries(segment, parsed.get(segment.sourceId)?.words ?? []));
  return {
    transcripts: [...parsed.values()].map((item) => item.evidence),
    missingTranscriptSourceIds,
    keptWords,
    boundaryNeighbors,
  };
}
