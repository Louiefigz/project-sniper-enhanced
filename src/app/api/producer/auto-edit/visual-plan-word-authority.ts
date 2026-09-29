import { createHash } from "node:crypto";
import { existsSync, lstatSync, realpathSync } from "node:fs";
import path from "node:path";
import { atomicWriteJsonSync } from "@/lib/server/atomic-file";
import { fileSha256 } from "@/lib/server/auto-edit-hash";
import { stableAuthorityHash } from "@/lib/server/auto-edit-authority-snapshot";
import { readBoundedAuthoringFile } from "./initial-authoring-capture";
import type { AutoEditCtx } from "./stream";
import type { VisualPlanProjectAuthority } from "./visual-plan-context";

const MAX_JSON_BYTES = 16 * 1024 * 1024;
const MAX_TOTAL_TRANSCRIPT_BYTES = 64 * 1024 * 1024;
const MAX_AUTHORITY_WORDS = 200_000;

export interface VisualPlanAuthorityPin {
  schemaVersion: 1;
  path: string;
  sha256: string;
  digest: string;
}

interface Segment {
  sourceId: string;
  start: number;
  end: number;
  speed: number;
  outputStart: number;
  index: number;
}

interface SourceWord {
  text: string;
  start: number;
  end: number;
  index: number;
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function jsonFile(file: string, label: string): {
  bytes: Buffer; value: Record<string, unknown>;
} {
  const bytes = readBoundedAuthoringFile(file, label, MAX_JSON_BYTES);
  try {
    return { bytes, value: object(JSON.parse(bytes.toString("utf8")), label) };
  } catch (error) {
    throw new Error(`${label} must be valid UTF-8 JSON: ${(error as Error).message}`);
  }
}

function finite(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} must be finite`);
  }
  return value;
}

function segments(plan: Record<string, unknown>): Segment[] {
  if (!Array.isArray(plan.cutTrack) || !plan.cutTrack.length) {
    throw new Error("accepted program needs a nonempty cutTrack");
  }
  let outputStart = 0;
  return plan.cutTrack.map((raw, index) => {
    const row = object(raw, `cutTrack[${index}]`);
    const start = finite(row.start, `cutTrack[${index}].start`);
    const end = finite(row.end, `cutTrack[${index}].end`);
    const speed = row.speed === undefined ? 1 : finite(row.speed, `cutTrack[${index}].speed`);
    if (typeof row.sourceId !== "string" || !row.sourceId || end <= start || speed <= 0) {
      throw new Error(`cutTrack[${index}] has invalid source timing`);
    }
    const result = { sourceId: row.sourceId, start, end, speed, outputStart, index };
    outputStart += (end - start) / speed;
    return result;
  });
}

function canonicalTranscriptPath(root: string, requested: string): string {
  if (!requested || requested.includes("\0") || requested.split(/[\\/]/u).includes("..")) {
    throw new Error("transcript path is invalid");
  }
  const candidate = path.resolve(root, requested);
  if (!existsSync(candidate) || lstatSync(candidate).isSymbolicLink()) {
    throw new Error(`transcript must be a regular non-symlink file: ${requested}`);
  }
  const canonicalRoot = realpathSync(root);
  const canonical = realpathSync(candidate);
  const relative = path.relative(canonicalRoot, canonical);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(`transcript resolves outside its authority root: ${requested}`);
  }
  return canonical;
}

function transcriptWords(value: Record<string, unknown>, sourceId: string): SourceWord[] {
  const utterances = value.transcript;
  if (!Array.isArray(utterances)) throw new Error(`transcript ${sourceId} has no utterances`);
  const words: SourceWord[] = [];
  for (const [utteranceIndex, raw] of utterances.entries()) {
    const row = object(raw, `transcript ${sourceId} utterance ${utteranceIndex}`);
    if (!Array.isArray(row.words)) throw new Error(`transcript ${sourceId} utterance lacks words`);
    for (const [wordIndex, rawWord] of row.words.entries()) {
      const word = object(rawWord, `transcript ${sourceId} word ${utteranceIndex}.${wordIndex}`);
      const start = finite(word.start, "transcript word start");
      const end = finite(word.end, "transcript word end");
      const text = typeof word.word === "string" ? word.word.trim() : "";
      if (!text || text.length > 256 || start < 0 || end < start) {
        throw new Error(`transcript ${sourceId} contains an invalid word`);
      }
      words.push({ text, start, end, index: words.length });
      if (words.length > MAX_AUTHORITY_WORDS) throw new Error("transcript word authority exceeds its bound");
    }
  }
  return words;
}

function wordsBySource(ctx: AutoEditCtx): Map<string, SourceWord[]> {
  const manifest = jsonFile(ctx.manifestPath, "asset manifest");
  const sources = manifest.value.sources;
  if (!Array.isArray(sources)) throw new Error("asset manifest sources must be an array");
  const result = new Map<string, SourceWord[]>();
  let totalBytes = manifest.bytes.length;
  for (const [index, raw] of sources.entries()) {
    const source = object(raw, `manifest source ${index}`);
    if (typeof source.id !== "string" || !source.id || result.has(source.id)) {
      throw new Error(`manifest source ${index} has a missing or duplicate ID`);
    }
    if (typeof source.transcriptPath !== "string") continue;
    const file = canonicalTranscriptPath(ctx.transcriptsDir, source.transcriptPath);
    const transcript = jsonFile(file, `transcript ${source.id}`);
    totalBytes += transcript.bytes.length;
    if (totalBytes > MAX_TOTAL_TRANSCRIPT_BYTES) throw new Error("transcript authority exceeds its total byte bound");
    result.set(source.id, transcriptWords(transcript.value, source.id));
  }
  return result;
}

function frameFloor(seconds: number, fps: number): number {
  return Math.max(0, Math.floor(seconds * fps + 1e-7));
}

function frameCeil(seconds: number, fps: number, start: number): number {
  return Math.max(start + 1, Math.ceil(seconds * fps - 1e-7));
}

function authorityWord(segment: Segment, word: SourceWord, fps: number,
                       programSha256: string): Record<string, unknown> | null {
  const sourceStart = Math.max(word.start, segment.start);
  const sourceEnd = Math.min(word.end, segment.end);
  if (sourceEnd <= sourceStart || word.start >= segment.end || word.end <= segment.start) return null;
  const outputStart = segment.outputStart + (sourceStart - segment.start) / segment.speed;
  const outputEnd = segment.outputStart + (sourceEnd - segment.start) / segment.speed;
  const sourceStartFrame = frameFloor(sourceStart, fps);
  const sourceEndFrameExclusive = frameCeil(sourceEnd, fps, sourceStartFrame);
  const outputStartFrame = frameFloor(outputStart, fps);
  const outputEndFrameExclusive = frameCeil(outputEnd, fps, outputStartFrame);
  const identity = { version: 1, programSha256, sourceId: segment.sourceId,
    segmentIndex: segment.index, sourceWordIndex: word.index, text: word.text,
    sourceStart, sourceEnd, outputStart, outputEnd };
  const id = `word:${createHash("sha256").update(stableAuthorityHash(identity)).digest("hex").slice(0, 24)}`;
  return { id, ordinal: 0, text: word.text, sourceId: segment.sourceId,
    segmentIndex: segment.index, sourceWordIndex: word.index,
    sourceStartFrame, sourceEndFrameExclusive, outputStartFrame, outputEndFrameExclusive };
}

function acceptedWords(ctx: AutoEditCtx, project: VisualPlanProjectAuthority): Record<string, unknown>[] {
  const plan = jsonFile(ctx.planPath, "accepted edit plan").value;
  const sourceWords = wordsBySource(ctx);
  const fps = project.fps.numerator / project.fps.denominator;
  const words = segments(plan).flatMap((segment) => {
    const rows = sourceWords.get(segment.sourceId);
    if (!rows) throw new Error(`accepted source ${segment.sourceId} has no word transcript`);
    return rows.flatMap((word) => {
      const value = authorityWord(segment, word, fps, project.acceptedProgramSha256);
      if (!value) return [];
      const start = Number(value.outputStartFrame);
      const end = Math.min(Number(value.outputEndFrameExclusive), project.durationFrames);
      return start < end ? [{ ...value, outputEndFrameExclusive: end }] : [];
    });
  });
  if (!words.length || words.length > MAX_AUTHORITY_WORDS) {
    throw new Error("accepted program has no bounded word authority");
  }
  return words.map((word, ordinal) => ({ ...word, ordinal }));
}

/** Freeze every accepted spoken word with source and output-frame timing. */
export function prepareVisualTranscriptAuthority(
  ctx: AutoEditCtx,
  project: VisualPlanProjectAuthority,
  destination: string,
): VisualPlanAuthorityPin {
  const words = acceptedWords(ctx, project);
  const core = { schemaVersion: 1 as const, kind: "visual-plan-transcript-authority" as const,
    project: { acceptedProgramSha256: project.acceptedProgramSha256,
      transcriptSha256: project.transcriptSha256, durationFrames: project.durationFrames,
      fps: project.fps }, wordCount: words.length, words };
  const value = { ...core, digest: stableAuthorityHash(core) };
  atomicWriteJsonSync(destination, value);
  const sha256 = fileSha256(destination);
  if (!sha256) throw new Error("transcript authority was not materialized");
  return { schemaVersion: 1, path: realpathSync(destination), sha256, digest: value.digest };
}
