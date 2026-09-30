/** The sealed shared evidence a native plan binds (P2-08), read for the build's picture and phrase rules.
 * The record is read only after the engine's own check (`recheckSharedEvidence`, which re-observes it, its inputs,
 * its coverage and its bound speaker observations with the owner digest) and only at the bytes that check reported;
 * the speaker-observation record (P2-06) is read through the sealed reference at its recorded sha256. Split from
 * native-short-speaker-picture.ts for the 300-line rule: reading, the plan's source, protected-phrase obligations
 * and the plan's picture decisions live here; the SP rules live there. */
import { createHash } from "node:crypto";
import { lstatSync, readFileSync } from "node:fs";
import { objectValue, sha256, stringValue, type JsonRecord } from "@/lib/producer/contracts/validation";
import { NativeCheckError } from "./native-check-error";
import type { NativeBox, NativeCanvasInput } from "./native-short-composition";
import type { NativeShortProjectInput } from "./native-short-project";
import { recheckSharedEvidence, sharedCaptionPhrases, sharedSpeakerFacts, type SharedCaptionPhrase,
  type SharedCoverageClip, type SharedSpeakerFacts } from "./native-review-shared-evidence";

/** Sealed records and observation records are bounded like every inspection result (`cut_preview_io.MAX_JSON`). */
const MAX_JSON_BYTES = 16 * 1024 * 1024;
/** P2-08 decision kinds, verbatim. */
export const SPEAKER_PICTURE_KINDS = ["two-shot", "supporting-visual", "listener-reaction", "exit-cover", "accepted-exit"] as const;
/** A plan's binding of one sealed shared-evidence record (the fields `recheckSharedEvidence` compares). */
export interface NativeSharedEvidenceBinding { path: string; sha256: string; contentSha256: string; version: number }
/** An authored picture decision over output frames `[startFrame, endFrame)`; `reason` is judged by the critic. */
export interface NativeSpeakerPictureDecision {
  startFrame: number; endFrame: number; kind: (typeof SPEAKER_PICTURE_KINDS)[number]; reason: string;
}
/** One detected face in source pixels, above FACE_TRACK's score threshold (P2-06 `face_rows`). */
export interface SpeakerFace { x: number; y: number; w: number; h: number; score: number }
/** One sampled source frame: its index, its time on the transcript clock and whether it is a dense sample. */
export interface SpeakerSampledFrame { frame: number; t: number; dense: boolean }
/** The speaker-observation record (P2-06, `inspection/result.json`), the fields P2-08 reads (U-R1, from L-D's record).
 * `faces` has one row per `sampling.frames` row, in the same order; `words` are the retained words' stereo rows. */
export interface SpeakerObservations {
  schemaVersion: 1; kind: "sniper-speaker-observations";
  source: { id: string; sourceSha256: string; transcriptSha256: string };
  scripts: SharedCoverageClip[]; rate: string;
  words: Array<{ sourceWord: number; start: number; end: number }>;
  faces: Array<{ frame: number; t: number; faces: SpeakerFace[] }>;
  sampling: { frames: SpeakerSampledFrame[] };
}
/** A bound record after the engine check: its version, record, typed speaker facts and the plan's source in it. */
export interface SealedSharedEvidence {
  version: number; record: JsonRecord; facts: SharedSpeakerFacts; source: { id: string; sourceSha256: string };
}

/** Bytes of a regular bounded file whose sha256 equals `digest`, parsed as JSON. */
function sealedJson(file: string, digest: string, label: string): unknown {
  const metadata = lstatSync(file);
  if (!metadata.isFile() || metadata.size > MAX_JSON_BYTES) throw new Error(`${label} ${file} is not a regular file of at most 16 MiB`);
  const bytes = readFileSync(file);
  if (createHash("sha256").update(bytes).digest("hex") !== digest) throw new Error(`${label} ${file} differs from its recorded sha256`);
  return JSON.parse(bytes.toString("utf8"));
}

/** The source asset's sha256, as the plan binds it (the Python reader's `planned_source`). */
export function nativePlanSourceSha256(input: NativeShortProjectInput): string | undefined {
  return input.assets?.find((row) => row.file === input.canvas.sourceFile && row.role === "source")?.sha256;
}

/** The record's source row for the plan's source; the Python `same_production` refusal text otherwise. */
function planSource(input: NativeShortProjectInput, record: JsonRecord): { id: string; sourceSha256: string } {
  const planned = nativePlanSourceSha256(input), rows = Array.isArray(record.sources) ? record.sources as JsonRecord[] : [];
  const match = rows.filter((row) => row?.sourceSha256 === planned && typeof row.id === "string");
  if (match.length !== 1) {
    const described = [...new Set(rows.map((row) => String(row?.sourceSha256)))].sort();
    throw new Error(`shared evidence describes sources ${JSON.stringify(described)}, not this plan's source ${planned}`);
  }
  return { id: match[0].id as string, sourceSha256: planned! };
}

/** Re-check the plan's bound record with the engine check, then read exactly the bytes it reported. */
export function readSealedSharedEvidence(input: NativeShortProjectInput): SealedSharedEvidence {
  const bound = recheckSharedEvidence(objectValue(input.sharedEvidence, "sharedEvidence"))!;
  const record = objectValue(sealedJson(String(bound.path), String(bound.sha256), "Shared evidence"), "shared evidence record");
  return { version: input.sharedEvidence!.version, record, facts: sharedSpeakerFacts(record), source: planSource(input, record) };
}

/** A finite JSON number or a named refusal. */
function finite(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new Error(`Speaker observations: ${label} must be a finite number`);
  return value;
}

/** A non-negative integer or a named refusal. */
function index(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) throw new Error(`Speaker observations: ${label} must be a frame or word index`);
  return value as number;
}

/** A JSON array or a named refusal. */
function list(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`Speaker observations: ${label} must be an array`);
  return value;
}

/** One face box: finite, with a positive size. */
function face(value: unknown, label: string): SpeakerFace {
  const row = objectValue(value, label), box = { x: finite(row.x, `${label}.x`), y: finite(row.y, `${label}.y`),
    w: finite(row.w, `${label}.w`), h: finite(row.h, `${label}.h`), score: finite(row.score, `${label}.score`) };
  if (box.w <= 0 || box.h <= 0) throw new Error(`Speaker observations: ${label} has no area`);
  return box;
}

/** Sampled frames and their face rows, which must name the same frames at the same times, in order. */
function sampled(record: JsonRecord): Pick<SpeakerObservations, "faces" | "sampling"> {
  const frames = list(objectValue(record.sampling, "sampling").frames, "sampling.frames").map((value, at) => {
    const row = objectValue(value, `sampling.frames[${at}]`), dense = row.dense;
    if (typeof dense !== "boolean") throw new Error(`Speaker observations: sampling.frames[${at}].dense must be true or false`);
    return { frame: index(row.frame, `sampling.frames[${at}].frame`), t: finite(row.t, `sampling.frames[${at}].t`), dense };
  });
  const faces = list(record.faces, "faces").map((value, at) => {
    const row = objectValue(value, `faces[${at}]`), label = `faces[${at}]`;
    return { frame: index(row.frame, `${label}.frame`), t: finite(row.t, `${label}.t`),
      faces: list(row.faces, `${label}.faces`).map((item, number) => face(item, `${label}.faces[${number}]`)) };
  });
  if (faces.length !== frames.length || faces.some((row, at) => row.frame !== frames[at].frame || row.t !== frames[at].t)) {
    throw new Error("Speaker observations: face rows and sampled frames differ");
  }
  return { faces, sampling: { frames } };
}

/** True when at least half of the face's box lies inside the crop (P2-08's "in the picture"). */
export function faceInCrop(face: SpeakerFace, [x, y, w, h]: NativeBox): boolean {
  const overlap = (a: number, size: number, b: number, span: number) => Math.max(0, Math.min(a + size, b + span) - Math.max(a, b));
  return overlap(face.x, face.w, x, w) * overlap(face.y, face.h, y, h) >= 0.5 * face.w * face.h;
}

/** The one person whose inclusive region holds the face's centre x (L-Q's `face_owner`), else null (unmapped). */
export function faceOwner(face: SpeakerFace, regions: ReadonlyArray<{ id: string; xRange: [number, number] }>): string | null {
  const centre = face.x + face.w / 2, owners = regions.filter(({ xRange: [low, high] }) => low <= centre && centre <= high);
  return owners.length === 1 ? owners[0].id : null;
}

/** The observation record's fields P2-08 reads, validated; anything else about it is refused, never assumed. */
export function speakerObservations(value: unknown): SpeakerObservations {
  const record = objectValue(value, "speaker observations"), source = objectValue(record.source, "source");
  if (record.schemaVersion !== 1 || record.kind !== "sniper-speaker-observations" || typeof record.rate !== "string") {
    throw new Error("Speaker observations: not a schema-1 sniper-speaker-observations record");
  }
  const words = list(record.words, "words").map((item, at) => {
    const row = objectValue(item, `words[${at}]`);
    return { sourceWord: index(row.sourceWord, `words[${at}].sourceWord`), start: finite(row.start, `words[${at}].start`),
      end: finite(row.end, `words[${at}].end`) };
  });
  const scripts = list(record.scripts, "scripts").map((item, at) => {
    const row = objectValue(item, `scripts[${at}]`);
    return { clipId: stringValue(row.clipId, `scripts[${at}].clipId`, 256), scriptIdentity: sha256(row.scriptIdentity, `scripts[${at}].scriptIdentity`),
      wordRanges: list(row.wordRanges, `scripts[${at}].wordRanges`).map((pair, number) => {
        const ends = list(pair, `scripts[${at}].wordRanges[${number}]`);
        return [index(ends[0], "wordRanges first"), index(ends[1], "wordRanges last")] as [number, number];
      }) };
  });
  return { schemaVersion: 1, kind: "sniper-speaker-observations", rate: record.rate, words, scripts, ...sampled(record),
    source: { id: stringValue(source.id, "source.id", 256), sourceSha256: sha256(source.sourceSha256, "source.sourceSha256"),
      transcriptSha256: sha256(source.transcriptSha256, "source.transcriptSha256") } };
}

/** Why a record without coverage (schema 1, or schema 2 without intervals) cannot satisfy P2-08. */
export function noCoverageText(sealed: SealedSharedEvidence): string {
  return `shared evidence v${sealed.version} (schema ${sealed.facts.schemaVersion}) seals no speaker coverage; a plan that `
    + "binds shared evidence needs a schema-2 record with speaker intervals";
}

/** The observations a sealed record's coverage binds; a record without them cannot satisfy P2-08 (plans need v2). */
export function readSpeakerObservations(sealed: SealedSharedEvidence): SpeakerObservations {
  const reference = sealed.facts.observations;
  if (!reference) throw new NativeCheckError("speaker-facts-missing", noCoverageText(sealed));
  return speakerObservations(sealedJson(reference.path, reference.sha256, "Speaker observations"));
}

/** Validated `speakerPictureDecisions`: exact keys, frames inside the Short, a known kind and a bounded reason. */
export function nativeSpeakerPictureDecisions(input: NativeShortProjectInput): NativeSpeakerPictureDecision[] {
  const rows = input.speakerPictureDecisions as unknown;
  if (rows === undefined) return [];
  if (!Array.isArray(rows) || rows.length > 256) throw new Error("speakerPictureDecisions must be a list of at most 256 decisions");
  return rows.map((value, at) => {
    const row = objectValue(value, `speakerPictureDecisions[${at}]`), keys = Object.keys(row).sort().join();
    if (keys !== "endFrame,kind,reason,startFrame" || !Number.isSafeInteger(row.startFrame) || !Number.isSafeInteger(row.endFrame)
        || (row.startFrame as number) < 0 || (row.endFrame as number) <= (row.startFrame as number)
        || (row.endFrame as number) > input.canvas.totalFrames || !SPEAKER_PICTURE_KINDS.includes(row.kind as never)) {
      throw new Error(`speakerPictureDecisions[${at}] needs exactly startFrame < endFrame inside the Short, a P2-08 kind and a reason`);
    }
    return { startFrame: row.startFrame as number, endFrame: row.endFrame as number, kind: row.kind as NativeSpeakerPictureDecision["kind"],
      reason: stringValue(row.reason, `speakerPictureDecisions[${at}].reason`, 1000) };
  });
}

/** Where a sealed phrase stands in a plan: none of its words kept, some kept, all kept but not protected, or protected. */
export type SealedPhraseStatus = "not-retained" | "partly-retained" | "dropped" | "kept";

/** A sealed phrase against the plan's kept words (`occurrences[*][2]`) and `canvas.captionProtectedPhrases`: every
 * output run that keeps its source words in order must be one protected entry, and a partial keep is its own status. */
export function sealedPhraseStatus(canvas: NativeCanvasInput, phrase: SharedCaptionPhrase): SealedPhraseStatus {
  const [first, last] = phrase.sourceWordIndexes, words = Array.from({ length: last - first + 1 }, (_, k) => first + k);
  const kept = new Set(canvas.occurrences.map((row) => row[2])), present = words.filter((word) => kept.has(word));
  if (!present.length) return "not-retained";
  if (present.length < words.length) return "partly-retained";
  const runs = canvas.occurrences.filter((_, at) => words.every((word, k) => canvas.occurrences[at + k]?.[2] === word)).map((row) => row[0]);
  const held = (start: number) => (canvas.captionProtectedPhrases ?? []).some((ids) => ids[0] === start && ids.length === words.length);
  return runs.length && runs.every(held) ? "kept" : "dropped";
}

/** Every sealed phrase on the plan's source that the plan keeps whole is a protected caption phrase (P2-08 (a)). */
export function assertSealedPhrasesKept(input: NativeShortProjectInput, sealed: SealedSharedEvidence): void {
  for (const phrase of sharedCaptionPhrases(sealed.record).filter((row) => row.source === sealed.source.id)) {
    const [first, last] = phrase.sourceWordIndexes, status = sealedPhraseStatus(input.canvas, phrase);
    if (status === "partly-retained") {
      throw new NativeCheckError("protected-phrase-partly-retained", `protected phrase '${phrase.display}' is only partly retained (source words ${first}-${last})`);
    }
    if (status === "dropped") {
      throw new NativeCheckError("protected-phrase-dropped", `Plan drops protected caption phrase '${phrase.display}' `
        + `(source words ${first}-${last}) sealed in shared evidence v${sealed.version}`);
    }
  }
}

/** Each sealed phrase on the plan's source with its status, for `measure` (never throws for a status). */
export function sealedPhraseReport(input: NativeShortProjectInput, sealed: SealedSharedEvidence) {
  return sharedCaptionPhrases(sealed.record).filter((row) => row.source === sealed.source.id).map((phrase) => ({
    display: phrase.display, sourceWordIndexes: phrase.sourceWordIndexes, status: sealedPhraseStatus(input.canvas, phrase) }));
}
