import { createHash } from "node:crypto";
import {
  existsSync, lstatSync, readFileSync, realpathSync,
} from "node:fs";
import path from "node:path";
import type { EditPlan } from "@/lib/producer/edit-plan";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import {
  captionCutSegments,
  mapCaptionWordOccurrences,
  stableCaptionWordId,
  type CaptionCutSegmentV1,
  type CaptionIndexedWordV1,
  type SourceCaptionWordV1,
} from "./caption-word-occurrences-v1";
export type { CaptionIndexedWordV1 } from "./caption-word-occurrences-v1";
export interface CaptionWordIndexV1 {
  schemaVersion: 1;
  kind: "caption-kept-word-index";
  planHash: string;
  manifestHash: string;
  transcripts: Array<{ sourceId: string; sha256: string }>;
  words: CaptionIndexedWordV1[];
  authorityHash: string;
}
export interface CaptionRequestAnchorV1 {
  phrase: string;
  status: "resolved" | "ambiguous" | "not-found" | "timestamp-mismatch";
  wordIds: string[];
  candidates: Array<{
    wordIds: string[];
    outputStart: number;
    outputEnd: number;
  }>;
}
export interface CaptionWordIndexInput {
  plan: EditPlan;
  manifestPath: string;
  transcriptsDir: string;
}
interface QuotedPhrase {
  phrase: string;
  start: number;
  end: number;
}
interface JsonFile {
  value: unknown;
  sha256: string;
}
export const CAPTION_TIMESTAMP_TOLERANCE_S = 2;

function object(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be a JSON object`);
  }
  return value as Record<string, unknown>;
}

function finite(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} must be finite`);
  }
  return value;
}

function regularJson(filePath: string, label: string): JsonFile {
  const before = lstatSync(filePath);
  if (!before.isFile() || before.isSymbolicLink()) {
    throw new Error(`${label} must be a regular non-symlink file`);
  }
  const bytes = readFileSync(filePath);
  const after = lstatSync(filePath);
  if (before.dev !== after.dev || before.ino !== after.ino
      || before.size !== after.size || before.mtimeMs !== after.mtimeMs) {
    throw new Error(`${label} changed while it was read`);
  }
  return {
    value: JSON.parse(bytes.toString("utf8")) as unknown,
    sha256: createHash("sha256").update(bytes).digest("hex"),
  };
}

function safeTranscriptPath(
  input: CaptionWordIndexInput,
  requested: string,
): string {
  const base = path.dirname(path.resolve(input.manifestPath));
  const candidate = path.isAbsolute(requested)
    ? path.resolve(requested) : path.resolve(base, requested);
  const root = realpathSync(input.transcriptsDir);
  if (!existsSync(candidate)) throw new Error(`caption transcript is missing: ${requested}`);
  const resolved = realpathSync(candidate);
  const relative = path.relative(root, resolved);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(`caption transcript escapes its source directory: ${requested}`);
  }
  let cursor = root;
  for (const part of relative.split(path.sep)) {
    cursor = path.join(cursor, part);
    if (lstatSync(cursor).isSymbolicLink()) {
      throw new Error(`caption transcript path contains a symlink: ${requested}`);
    }
  }
  return resolved;
}

function transcriptWords(
  value: unknown,
  sourceId: string,
): SourceCaptionWordV1[] {
  const top = Array.isArray(value) ? value : object(value, "caption transcript").transcript;
  if (!Array.isArray(top)) throw new Error(`caption transcript ${sourceId} has no transcript list`);
  const rows = Array.isArray(value)
    ? top : top.flatMap((raw, index) => {
      const utterance = object(raw, `caption utterance ${index}`);
      if (!Array.isArray(utterance.words)) {
        throw new Error(`caption utterance ${index} has no words`);
      }
      return utterance.words.map((word) => ({
        ...object(word, `caption utterance ${index} word`),
        ...(utterance.speaker === undefined ? {} : { speaker: utterance.speaker }),
      }));
    });
  return rows.map((raw, sourceOrdinal) => {
    const row = object(raw, `caption source word ${sourceOrdinal}`);
    const text = row.word;
    const sourceStart = finite(row.start, `caption source word ${sourceOrdinal}.start`);
    const sourceEnd = finite(row.end, `caption source word ${sourceOrdinal}.end`);
    if (typeof text !== "string" || !text.trim() || sourceEnd <= sourceStart) {
      throw new Error(`caption source word ${sourceOrdinal} is invalid`);
    }
    const speaker = row.speaker;
    return {
      wordId: stableCaptionWordId(sourceId, sourceOrdinal),
      text, sourceId, sourceOrdinal, sourceStart, sourceEnd,
      ...((typeof speaker === "string" || typeof speaker === "number")
        ? { speaker } : {}),
    };
  });
}

function indexedSource(
  input: CaptionWordIndexInput,
  source: Record<string, unknown>,
  track: CaptionCutSegmentV1[],
): { transcript: { sourceId: string; sha256: string }; words: CaptionIndexedWordV1[] } {
  if (typeof source.id !== "string" || !source.id) throw new Error("manifest source has no id");
  if (typeof source.transcriptPath !== "string" || !source.transcriptPath) {
    if (track.some((row) => row.sourceId === source.id)) {
      throw new Error(`kept source ${source.id} has no caption transcript`);
    }
    return { transcript: { sourceId: source.id, sha256: "0".repeat(64) }, words: [] };
  }
  const loaded = regularJson(
    safeTranscriptPath(input, source.transcriptPath),
    `caption transcript ${source.id}`,
  );
  const words = transcriptWords(loaded.value, source.id)
    .flatMap((word) => mapCaptionWordOccurrences(word, track));
  return {
    transcript: { sourceId: source.id, sha256: loaded.sha256 },
    words,
  };
}

export function buildCaptionWordIndex(input: CaptionWordIndexInput): CaptionWordIndexV1 {
  const manifest = regularJson(input.manifestPath, "asset manifest");
  const sources = object(manifest.value, "asset manifest").sources;
  if (!Array.isArray(sources)) throw new Error("asset manifest has no sources");
  const track = captionCutSegments(input.plan);
  const rows = sources.map((raw) => indexedSource(input, object(raw, "manifest source"), track));
  const sourceIds = rows.map((row) => row.transcript.sourceId);
  if (new Set(sourceIds).size !== sourceIds.length) throw new Error("manifest source ids repeat");
  const words = rows.flatMap((row) => row.words).sort((left, right) =>
    left.outputStart - right.outputStart || left.outputEnd - right.outputEnd
      || left.sourceId.localeCompare(right.sourceId) || left.wordId.localeCompare(right.wordId));
  const core = {
    schemaVersion: 1 as const, kind: "caption-kept-word-index" as const,
    planHash: canonicalJsonSha256(input.plan), manifestHash: manifest.sha256,
    transcripts: rows.map((row) => row.transcript), words,
  };
  return { ...core, authorityHash: canonicalJsonSha256(core) };
}

function normalizedTokens(value: string): string[] {
  return value.normalize("NFKC").toLocaleLowerCase()
    .split(/\s+/u)
    .map((token) => token.replace(/^[\p{P}\p{S}]+|[\p{P}\p{S}]+$/gu, ""))
    .filter(Boolean);
}

function requestTimestamp(request: string): number | null {
  const clock = request.match(/\b(?:at|@)\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\b/iu);
  if (clock) return clock[3]
    ? Number(clock[1]) * 3600 + Number(clock[2]) * 60 + Number(clock[3])
    : Number(clock[1]) * 60 + Number(clock[2]);
  const seconds = request.match(/\b(?:at|@)\s*(\d+(?:\.\d+)?)\s*(?:s|sec(?:ond)?s?)\b/iu);
  return seconds ? Number(seconds[1]) : null;
}

function quotedPhrases(request: string): QuotedPhrase[] {
  return [...request.matchAll(/["“]([^"”]{1,300})["”]/gu)]
    .map((match) => ({
      phrase: match[1].trim(),
      start: match.index ?? 0,
      end: (match.index ?? 0) + match[0].length,
    }))
    .filter((row) => row.phrase);
}

function correctionSourcePhrases(request: string): string[] {
  const quotes = quotedPhrases(request);
  const targets = new Set<number>();
  for (let index = 0; index < quotes.length - 1; index += 1) {
    const left = quotes[index];
    const right = quotes[index + 1];
    const between = request.slice(left.end, right.start);
    const prefix = request.slice(Math.max(0, left.start - 120), left.start);
    const correction = /\b(?:change|correct|fix|replace|rename|spell)\b/iu.test(prefix);
    const sourceFirst = /^\s*(?:(?:the\s+)?spelling\s+)?(?:to|with|as|so\s+it\s+(?:says|reads|displays)|should\s+(?:say|read|display))\s*$/iu;
    if (correction && sourceFirst.test(between)) targets.add(index + 1);
    if (/^\s+instead\s+of\s+$/iu.test(between)) targets.add(index);
  }
  return [...new Set(
    quotes.filter((_, index) => !targets.has(index)).map((row) => row.phrase),
  )];
}

function timestampDistance(
  timestamp: number,
  candidate: CaptionRequestAnchorV1["candidates"][number],
): number {
  if (timestamp < candidate.outputStart) return candidate.outputStart - timestamp;
  if (timestamp > candidate.outputEnd) return timestamp - candidate.outputEnd;
  return 0;
}

function phraseCandidates(
  phrase: string,
  words: CaptionIndexedWordV1[],
): CaptionRequestAnchorV1["candidates"] {
  const target = normalizedTokens(phrase);
  if (!target.length) return [];
  const searchable = words.map((word, index) => ({
    index, token: normalizedTokens(word.text)[0] ?? "",
  })).filter((row) => row.token);
  const candidates = [];
  for (let start = 0; start <= searchable.length - target.length; start += 1) {
    if (target.some((token, offset) => token !== searchable[start + offset].token)) continue;
    const first = searchable[start].index;
    const last = searchable[start + target.length - 1].index;
    const range = words.slice(first, last + 1);
    candidates.push({
      wordIds: range.map((word) => word.wordId),
      outputStart: range[0].outputStart,
      outputEnd: range.at(-1)!.outputEnd,
    });
  }
  return candidates;
}

export function resolveCaptionRequestAnchors(
  request: string,
  index: CaptionWordIndexV1,
): CaptionRequestAnchorV1[] {
  const phrases = correctionSourcePhrases(request);
  const timestamp = requestTimestamp(request);
  return phrases.map((phrase) => {
    let candidates = phraseCandidates(phrase, index.words);
    let timestampMismatch = false;
    if (timestamp !== null && candidates.length) {
      const distances = candidates.map((row) => timestampDistance(timestamp, row));
      const minimum = Math.min(...distances);
      timestampMismatch = minimum > CAPTION_TIMESTAMP_TOLERANCE_S;
      candidates = minimum <= CAPTION_TIMESTAMP_TOLERANCE_S
        ? candidates.filter((_, position) => distances[position] === minimum)
        : [];
    }
    const status = timestampMismatch ? "timestamp-mismatch"
      : candidates.length === 1
        ? "resolved" : candidates.length ? "ambiguous" : "not-found";
    return {
      phrase, status,
      wordIds: status === "resolved" ? candidates[0].wordIds : [],
      candidates,
    };
  });
}
