/** Submission-time re-check of the shared source evidence a role packet bound (unit B1).
 * One implementation of the rule: the engine's own `context.py --evidence-check`, which re-observes the sealed record,
 * its manifest, transcripts and bound files, its recorded location and whether a later version supersedes it. The
 * review is refused unless that check reports the same record the packet bound.
 * Schema version 2 (P2-07) adds speaker certainty, basis, face regions, coverage and protected caption phrases. The
 * readers below give P2-08 typed facts from a sealed record the check has passed; version 1 intervals get a
 * read-only mapped certainty. */
import { spawnSync } from "node:child_process";
import path from "node:path";
import { pythonInterpreter, SCRIPTS_DIR } from "@/app/api/_lib/spawn-python";
import { enumValue, objectValue, sha256, stringValue, type JsonRecord } from "@/lib/producer/contracts/validation";

const CONTEXT = path.join(SCRIPTS_DIR, "producer", "context.py");
const TIMEOUT_MS = 120_000;
const RECORD_KIND = "sniper-shared-source-evidence";

/** Speaker certainty, P2-07's names verbatim (X53). The one definition is `role_packet_evidence_speakers.CERTAINTIES`;
 * this mirrors it for TypeScript readers. */
export const SPEAKER_CERTAINTIES = ["established", "probable", "unresolved"] as const;
/** Speaker basis, P2-07's names verbatim (X53); mirrors `role_packet_evidence_speakers.BASES`. */
export const SPEAKER_BASES = ["listening", "operator-statement", "visual-and-stereo", "transcript-only"] as const;
export type SpeakerCertainty = (typeof SPEAKER_CERTAINTIES)[number];
export type SpeakerBasis = (typeof SPEAKER_BASES)[number];

/** A person and, when authored, the horizontal source-pixel region their face is mapped through. */
export interface SharedPerson { id: string; faceRegion: { source: string; xRange: [number, number] } | null }
/** One interval; `basis` is null only for a version 1 record that did not listen (version 1 recorded no basis). */
export interface SharedSpeakerInterval {
  source: string; startSeconds: number; endSeconds: number; speaker: string | null; visible: string[];
  certainty: SpeakerCertainty; basis: SpeakerBasis | null;
}
/** A covered clip, as the speaker observations also record it. */
export interface SharedCoverageClip { clipId: string; scriptIdentity: string; wordRanges: [number, number][] }
/** The published speaker-observation inspection reference (`SPEAKER-OBSERVATIONS.json`). */
export interface SharedObservationsReference { path: string; sha256: string; owner: string; ownerSha256: string }
/** The sealed speaker facts. `clips` and `observations` are null for version 1 and for a record without intervals. */
export interface SharedSpeakerFacts {
  schemaVersion: 1 | 2; listening: boolean; people: SharedPerson[]; intervals: SharedSpeakerInterval[];
  clips: SharedCoverageClip[] | null; observations: SharedObservationsReference | null;
}
/** A protected caption phrase: the inclusive source word indexes and the display text decided for them. */
export interface SharedCaptionPhrase {
  source: string; sourceWordIndexes: [number, number]; display: string; decidedBy: "operator" | "coordinator";
}

/** Runs the evidence check for one record path and returns its JSON report. */
export type EvidenceChecker = (recordPath: string) => JsonRecord;

/** The engine check (`context.py --evidence-check`); exit 0 with a JSON report, else a bounded error. */
export function runEvidenceCheck(recordPath: string): JsonRecord {
  const result = spawnSync(pythonInterpreter(), ["-B", CONTEXT, "--evidence-check", recordPath],
    { encoding: "utf8", timeout: TIMEOUT_MS, maxBuffer: 1024 * 1024 });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Shared evidence re-check failed: ${(result.stderr || result.stdout).trim().slice(0, 1024) || `exit ${result.status}`}`);
  }
  return objectValue(JSON.parse(result.stdout), "shared evidence check report");
}

/** The checker a submission uses; tests replace `run` with a TEST double through node:test mocking. */
export const evidenceCheck = { run: runEvidenceCheck };

/** Refuse when the evidence the packet bound is no longer the current, located, unsuperseded record. Version 1 and
 * version 2 records are re-checked alike: the engine check reads either version. */
export function recheckSharedEvidence(sharedEvidence: JsonRecord | null): JsonRecord | null {
  if (sharedEvidence === null) return null;
  const bound = { path: stringValue(sharedEvidence.path, "sharedEvidence.path", 4096),
    sha256: sha256(sharedEvidence.sha256, "sharedEvidence.sha256"),
    contentSha256: sha256(sharedEvidence.contentSha256, "sharedEvidence.contentSha256"), version: sharedEvidence.version };
  const report = evidenceCheck.run(bound.path);
  if (report.status !== "shared-evidence-current" || report.path !== bound.path || report.sha256 !== bound.sha256
      || report.contentSha256 !== bound.contentSha256 || report.version !== bound.version) {
    throw new Error("The shared evidence this role packet bound is no longer current (changed, moved or superseded); "
      + "re-resolve the role packet against the current sealed evidence");
  }
  return bound;
}

/** The record's schema version, after checking it is a sealed shared-evidence record. */
function recordVersion(record: JsonRecord): 1 | 2 {
  const version = record.schemaVersion;
  if (record.kind !== RECORD_KIND || (version !== 1 && version !== 2)) {
    throw new Error("Not a sealed shared-evidence record of schema version 1 or 2");
  }
  return version;
}

/** A JSON array, or a refusal naming the field. */
function rows(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  return value;
}

/** A finite JSON number, or a refusal naming the field. */
function finite(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new Error(`${label} must be a finite number`);
  return value;
}

/** Bounded text, or a refusal naming the field. */
function textValue(value: unknown, label: string): string {
  return stringValue(value, label, 4096);
}

/** A two-number [first, last] pair. */
function pair(value: unknown, label: string): [number, number] {
  const items = rows(value, label);
  if (items.length !== 2) throw new Error(`${label} must be [first, last]`);
  return [finite(items[0], `${label}[0]`), finite(items[1], `${label}[1]`)];
}

/** One person with their face region, when one was authored. */
function sharedPerson(value: unknown, label: string): SharedPerson {
  const row = objectValue(value, label);
  if (row.faceRegion === undefined) return { id: textValue(row.id, `${label}.id`), faceRegion: null };
  const region = objectValue(row.faceRegion, `${label}.faceRegion`);
  return { id: textValue(row.id, `${label}.id`), faceRegion: { source: textValue(region.source, `${label}.faceRegion.source`),
    xRange: pair(region.xRange, `${label}.faceRegion.xRange`) } };
}

/** One interval. Version 1 rows are mapped read-only: a null speaker is unresolved; otherwise established when the
 * record listened, else probable; the basis is listening when it listened, else null. */
function sharedInterval(value: unknown, label: string, version: 1 | 2, listening: boolean): SharedSpeakerInterval {
  const row = objectValue(value, label);
  const speaker = row.speaker === null ? null : textValue(row.speaker, `${label}.speaker`);
  const base = { source: textValue(row.source, `${label}.source`), speaker,
    startSeconds: finite(row.startSeconds, `${label}.startSeconds`), endSeconds: finite(row.endSeconds, `${label}.endSeconds`),
    visible: rows(row.visible, `${label}.visible`).map((item, index) => textValue(item, `${label}.visible[${index}]`)) };
  if (version === 1) {
    return { ...base, certainty: speaker === null ? "unresolved" : listening ? "established" : "probable",
      basis: listening ? "listening" : null };
  }
  const certainty = enumValue(row.certainty, SPEAKER_CERTAINTIES, `${label}.certainty`);
  if ((certainty === "unresolved") !== (speaker === null)) {
    throw new Error(`${label}: certainty is unresolved exactly when speaker is null`);
  }
  return { ...base, certainty, basis: enumValue(row.basis, SPEAKER_BASES, `${label}.basis`) };
}

/** A covered clip's identity and word ranges. */
function coverageClip(value: unknown, label: string): SharedCoverageClip {
  const row = objectValue(value, label);
  return { clipId: textValue(row.clipId, `${label}.clipId`), scriptIdentity: sha256(row.scriptIdentity, `${label}.scriptIdentity`),
    wordRanges: rows(row.wordRanges, `${label}.wordRanges`).map((item, index) => pair(item, `${label}.wordRanges[${index}]`)) };
}

/** The observation reference a version 2 record's coverage binds. */
function observationsReference(value: unknown): SharedObservationsReference {
  const row = objectValue(objectValue(value, "coverage.observations").reference, "coverage.observations.reference");
  return { path: textValue(row.path, "reference.path"), sha256: sha256(row.sha256, "reference.sha256"),
    owner: textValue(row.owner, "reference.owner"), ownerSha256: sha256(row.ownerSha256, "reference.ownerSha256") };
}

/** The sealed record's speaker facts for P2-08 (and P3a) readers; version 1 intervals carry a mapped certainty. */
export function sharedSpeakerFacts(record: JsonRecord): SharedSpeakerFacts {
  const version = recordVersion(record), speakers = objectValue(record.speakers, "speakers");
  const listening = speakers.listening;
  if (typeof listening !== "boolean") throw new Error("speakers.listening must be true or false");
  const coverage = version === 2 && record.coverage !== null ? objectValue(record.coverage, "coverage") : null;
  const clips = coverage === null ? null
    : rows(coverage.clips, "coverage.clips").map((item, index) => coverageClip(item, `coverage.clips[${index}]`));
  return { schemaVersion: version, listening, clips,
    people: rows(speakers.people, "speakers.people").map((item, index) => sharedPerson(item, `speakers.people[${index}]`)),
    intervals: rows(speakers.intervals, "speakers.intervals").map((item, index) =>
      sharedInterval(item, `speakers.intervals[${index}]`, version, listening)),
    observations: coverage === null ? null : observationsReference(coverage.observations) };
}

/** The sealed record's protected caption phrases; a version 1 record has none. */
export function sharedCaptionPhrases(record: JsonRecord): SharedCaptionPhrase[] {
  if (recordVersion(record) === 1) return [];
  return rows(record.captionPhrases, "captionPhrases").map((item, index) => {
    const label = `captionPhrases[${index}]`, row = objectValue(item, label);
    return { source: textValue(row.source, `${label}.source`), display: textValue(row.display, `${label}.display`),
      sourceWordIndexes: pair(row.sourceWordIndexes, `${label}.sourceWordIndexes`),
      decidedBy: enumValue(row.decidedBy, ["operator", "coordinator"] as const, `${label}.decidedBy`) };
  });
}
