/** Shared rules for typed native review submissions and the typed inspection their records carry.
 * Still-frame inspection, normal-speed motion playback and audio listening are separate kinds, each bound to
 * the exact bytes it covered. Still frames name the exact frames looked at and cover only those: sparse stills
 * are a sampled picture review, never complete coverage, and an unseen frame supports no note or claim. Motion
 * and audio approvals need their kind over every reviewed frame; still frames never establish motion, and signal
 * checks never establish listening. Records without typed inspection are historical: readers report them as
 * untyped and never upgrade them. */
import path from "node:path";
import { exactKeys, objectValue, sha256, stringValue } from "@/lib/producer/contracts/validation";

export interface ReviewSubmissionPaths { packet: string; observations: string; output: string }

/** The three typed evidence kinds: sampled stills, continuous normal-speed playback, listening to the actual audio. */
export const INSPECTION_KINDS = ["still-frames", "motion-playback", "audio-listening"] as const;
/** What a passing verdict can approve; each needs its own evidence kind (see assertApprovals). */
export const REVIEW_ASPECTS = ["picture", "motion", "audio"] as const;
/** Typed evidence is declared by the reviewer; hashes bind what it names, nothing proves it was seen or heard. */
export const INSPECTION_AUTHENTICITY = "declared-not-authenticated" as const;
/** The only fixture scope whose TEST-declared inspection a gate reader can admit, and only for that fixture's project. */
export const TEST_FIXTURE_SCOPE = "TEST-native-route-canary-fixture" as const;
export type InspectionKind = (typeof INSPECTION_KINDS)[number];
export type ReviewAspect = (typeof REVIEW_ASPECTS)[number];
export type InspectionSpan = "whole" | { frames: [number, number] } | { seconds: [number, number] };
export interface InspectedArtifact { path: string; sha256: string }
export interface InspectionEntry {
  /** still-frames only: the exact frames looked at, ascending; program frames of a reviewed rendering, else seconds. */
  kind: InspectionKind; artifact: InspectedArtifact; span: InspectionSpan; method: string; samples?: number[];
}
/** A route-canary TEST declaration: which TEST fixture manifest and project it may exercise (never production). */
export interface TestFixture { scope: typeof TEST_FIXTURE_SCOPE; manifest: InspectedArtifact; project: string }
export interface Inspection { schemaVersion: 1; entries: InspectionEntry[]; approves: ReviewAspect[]; fixture?: TestFixture }
/** A rendering under review (a preview window clip or the checked MP4) and the program frames it shows. */
export interface ReviewTarget extends InspectedArtifact { startFrame: number; endFrameExclusive: number }
/** complete: every reviewed frame; sampled: some frames of every reviewed rendering; partial: some typed evidence
 * of that kind; untyped: a historical record. */
export type EvidenceLevel = "complete" | "sampled" | "partial" | "none" | "untyped";

const APPROVAL_KINDS: Record<ReviewAspect, InspectionKind[]> = {
  picture: ["still-frames", "motion-playback"], motion: ["motion-playback"], audio: ["audio-listening"] };
const NEEDS: Record<ReviewAspect, string> = {
  picture: "still-frame inspection or motion playback",
  motion: "normal-speed motion playback (still frames never establish motion)",
  audio: "listening to the actual audio (decode, loudness and sample checks are not listening)" };
const ENTRY_KEYS = ["kind", "artifact", "span", "method", "samples"];
const MAX_ENTRIES = 256;
const MAX_SAMPLES = 100_000;
/** What a reader reports for a record without typed inspection: nothing typed, nothing upgraded. */
export const UNTYPED_EVIDENCE: Readonly<Record<InspectionKind, EvidenceLevel>> = Object.freeze({
  "still-frames": "untyped", "motion-playback": "untyped", "audio-listening": "untyped" });

/** Inputs the helper resolved to a different canonical path, e.g. /var/folders → /private/var/folders. */
export function canonicalizedInputs(paths: ReviewSubmissionPaths, canonical: [string, string, string]) {
  return (["packet", "observations", "output"] as const).flatMap((key, index) => path.resolve(paths[key]) === canonical[index]
    ? [] : [{ input: key, given: paths[key], canonical: canonical[index] }]);
}

function pair(value: unknown, label: string, integer: boolean): [number, number] {
  if (!Array.isArray(value) || value.length !== 2) throw new Error(`${label} must be [start, end]`);
  const [start, end] = value as unknown[];
  const valid = integer ? Number.isSafeInteger(start) && Number.isSafeInteger(end)
    : typeof start === "number" && typeof end === "number" && Number.isFinite(start) && Number.isFinite(end);
  if (!valid || (start as number) < 0 || (end as number) <= (start as number)) {
    throw new Error(`${label} must be ${integer ? "integer frames" : "seconds"} with 0 ≤ start < end`);
  }
  return [start as number, end as number];
}

function span(value: unknown, label: string): InspectionSpan {
  if (value === "whole") return "whole";
  const row = objectValue(value, label), keys = Object.keys(row);
  if (keys.length !== 1 || (keys[0] !== "frames" && keys[0] !== "seconds")) {
    throw new Error(`${label} must be "whole", {"frames": [start, endExclusive]} or {"seconds": [start, end]}`);
  }
  return keys[0] === "frames" ? { frames: pair(row.frames, `${label}.frames`, true) }
    : { seconds: pair(row.seconds, `${label}.seconds`, false) };
}

function artifact(value: unknown, label: string): InspectedArtifact {
  const row = objectValue(value, label);
  exactKeys(row, ["path", "sha256"], ["path", "sha256"], label);
  const file = stringValue(row.path, `${label}.path`, 4096);
  if (!path.isAbsolute(file) || path.resolve(file) !== file) throw new Error(`${label}.path must be the absolute canonical path`);
  return { path: file, sha256: sha256(row.sha256, `${label}.sha256`) };
}

function entry(value: unknown, label: string): InspectionEntry {
  const row = objectValue(value, label);
  exactKeys(row, ENTRY_KEYS, ENTRY_KEYS.slice(0, 4), label);
  const kind = row.kind as InspectionKind;
  if (!INSPECTION_KINDS.includes(kind)) throw new Error(`${label}.kind must be one of ${INSPECTION_KINDS.join(", ")}`);
  const result: InspectionEntry = { kind, artifact: artifact(row.artifact, `${label}.artifact`),
    span: span(row.span, `${label}.span`), method: stringValue(row.method, `${label}.method`, 1000) };
  if ((kind === "still-frames") !== (row.samples !== undefined)) {
    throw new Error(`${label}.samples (the exact frames looked at) belongs to still-frames entries only`);
  }
  return kind === "still-frames" ? { ...result, samples: samples(row.samples, `${label}.samples`) } : result;
}

function samples(value: unknown, label: string): number[] {
  const valid = Array.isArray(value) && value.length > 0 && value.length <= MAX_SAMPLES && value.every((item, index) =>
    typeof item === "number" && Number.isFinite(item) && item >= 0 && (index === 0 || item > (value[index - 1] as number)));
  if (!valid) throw new Error(`${label} must list 1–${MAX_SAMPLES} distinct ascending frames (or seconds) that were looked at`);
  return value as number[];
}

/** Typed entries in the shape critics write them and records keep them. */
export function inspectionEntries(value: unknown, label: string): InspectionEntry[] {
  if (!Array.isArray(value) || value.length > MAX_ENTRIES) throw new Error(`${label} must be an array of at most ${MAX_ENTRIES} typed entries`);
  return value.map((row, index) => entry(row, `${label}[${index}]`));
}

/** Distinct approved aspects; what a pass speaks for, never inferred from prose. */
export function approvals(value: unknown, label: string): ReviewAspect[] {
  if (!Array.isArray(value) || value.some(item => !REVIEW_ASPECTS.includes(item)) || new Set(value).size !== value.length) {
    throw new Error(`${label} must list distinct aspects from ${REVIEW_ASPECTS.join(", ")}`);
  }
  return value as ReviewAspect[];
}

/** A record's typed inspection block. A TEST-fixture declaration is readable only where `fixtures` admits it. */
export function readInspection(value: unknown, label = "inspection", fixtures = false): Inspection {
  const row = objectValue(value, label), keys = ["schemaVersion", "entries", "approves"];
  exactKeys(row, [...keys, "fixture"], keys, label);
  if (row.schemaVersion !== 1) throw new Error(`${label} must be schema 1`);
  const result: Inspection = { schemaVersion: 1, entries: inspectionEntries(row.entries, `${label}.entries`),
    approves: approvals(row.approves, `${label}.approves`) };
  if (row.fixture === undefined) return result;
  if (!fixtures) throw new Error(`${label} is a TEST route-canary declaration; only the moving-preview gate of that TEST fixture reads it`);
  const fixture = objectValue(row.fixture, `${label}.fixture`), fixtureKeys = ["scope", "manifest", "project"];
  exactKeys(fixture, fixtureKeys, fixtureKeys, `${label}.fixture`);
  if (fixture.scope !== TEST_FIXTURE_SCOPE) throw new Error(`${label}.fixture scope must be ${TEST_FIXTURE_SCOPE}`);
  return { ...result, fixture: { scope: TEST_FIXTURE_SCOPE, manifest: artifact(fixture.manifest, `${label}.fixture.manifest`),
    project: stringValue(fixture.project, `${label}.fixture.project`, 4096) } };
}

function isFrames(value: InspectionSpan): value is { frames: [number, number] } {
  return typeof value === "object" && "frames" in value;
}

/** Frames one entry showed on a target: each sampled still alone, or a played/listened span. */
function rangesOf(row: InspectionEntry, target: ReviewTarget): Array<[number, number]> {
  if (row.samples) return row.samples.map(frame => [frame, frame + 1]);
  if (row.span === "whole") return [[target.startFrame, target.endFrameExclusive]];
  return isFrames(row.span) ? [row.span.frames] : [];
}

/** Frames of `target` shown by entries of these kinds on its exact bytes. */
export function framesOn(entries: InspectionEntry[], target: ReviewTarget, kinds: readonly InspectionKind[]): Array<[number, number]> {
  return entries.filter(row => kinds.includes(row.kind) && row.artifact.path === target.path
      && row.artifact.sha256 === target.sha256).flatMap(row => rangesOf(row, target));
}

function covers(ranges: Array<[number, number]>, target: ReviewTarget): boolean {
  let reached = target.startFrame;
  for (const [start, end] of [...ranges].sort((a, b) => a[0] - b[0])) {
    if (start > reached) break;
    reached = Math.max(reached, end);
  }
  return reached >= target.endFrameExclusive;
}

/** Frame spans name program frames of a reviewed rendering; the same path with other bytes is stale. */
export function assertBoundToTargets(value: Inspection, targets: ReviewTarget[]): void {
  value.entries.forEach((row, index) => {
    const target = targets.find(item => item.path === row.artifact.path);
    if (target && target.sha256 !== row.artifact.sha256) {
      throw new Error(`Stale inspection: entry ${index} covered ${row.artifact.path} as sha256 ${row.artifact.sha256.slice(0, 12)}, `
        + `but the reviewed bytes are ${target.sha256.slice(0, 12)}; evidence from an older artifact cannot support this review`);
    }
    if (isFrames(row.span) !== Boolean(target) && row.span !== "whole") {
      throw new Error(target ? `Entry ${index}: a reviewed rendering is covered in program frames; use "whole" or frames for ${target.path}`
        : `Entry ${index}: frame spans are program frames of a reviewed rendering; use seconds or whole for ${row.artifact.path}`);
    }
    if (target && isFrames(row.span) && (row.span.frames[0] < target.startFrame || row.span.frames[1] > target.endFrameExclusive)) {
      throw new Error(`Entry ${index}: frames ${row.span.frames[0]}–${row.span.frames[1]} lie outside `
        + `${target.startFrame}–${target.endFrameExclusive} of ${target.path}`);
    }
    const outside = row.samples?.find(sample => !sampleInside(sample, row.span, target));
    if (outside !== undefined) {
      throw new Error(`Entry ${index}: still sample ${outside} is not ${target ? "a program frame" : "a second"} inside the `
        + `entry's span of ${row.artifact.path}; name only frames that were looked at`);
    }
  });
}

/** Program frames of a reviewed rendering (end exclusive), or seconds of any other artifact (end inclusive). */
function sampleInside(sample: number, value: InspectionSpan, target: ReviewTarget | undefined): boolean {
  if (!target) return value === "whole" || isFrames(value) || (sample >= value.seconds[0] && sample <= value.seconds[1]);
  const [start, end] = isFrames(value) ? value.frames : [target.startFrame, target.endFrameExclusive];
  return Number.isSafeInteger(sample) && sample >= start && sample < end;
}

/** A pass approves picture at least. Picture needs someone to have looked at every reviewed rendering (sparse
 * stills approve it as a sampled review); motion and audio need their own kind over every reviewed frame.
 * A revise or block verdict approves nothing. */
export function assertApprovals(value: Inspection, targets: ReviewTarget[], verdict: string): void {
  if (verdict !== "pass") {
    if (value.approves.length) throw new Error(`A ${verdict} verdict approves nothing: approves must be []`);
    return;
  }
  if (!value.approves.includes("picture")) throw new Error(`A pass must approve picture: ${NEEDS.picture} of every reviewed frame`);
  for (const aspect of value.approves) {
    const gap = targets.find(target => aspect === "picture" ? !framesOn(value.entries, target, APPROVAL_KINDS.picture).length
      : !covers(framesOn(value.entries, target, APPROVAL_KINDS[aspect]), target));
    if (gap) {
      throw new Error(`approves ${aspect}, but frames ${gap.startFrame}–${gap.endFrameExclusive} of ${gap.path} lack ${NEEDS[aspect]} `
        + "on those exact bytes");
    }
  }
}

/** Per kind, what the typed entries establish over the reviewed renderings. */
export function evidenceLevels(value: Inspection, targets: ReviewTarget[]): Record<InspectionKind, EvidenceLevel> {
  const level = (kind: InspectionKind): EvidenceLevel => {
    if (targets.length && targets.every(target => covers(framesOn(value.entries, target, [kind]), target))) return "complete";
    if (targets.length && targets.every(target => framesOn(value.entries, target, [kind]).length)) return "sampled";
    return value.entries.some(row => row.kind === kind) ? "partial" : "none";
  };
  return { "still-frames": level("still-frames"), "motion-playback": level("motion-playback"),
    "audio-listening": level("audio-listening") };
}

/** Picture, motion or audio not covered over every reviewed frame is a gap the critic states in limitations. */
export function assertGapsStated(value: Inspection, targets: ReviewTarget[], limitations: string[]): void {
  const gaps = REVIEW_ASPECTS.filter(aspect => targets.some(target => !covers(framesOn(value.entries, target, APPROVAL_KINDS[aspect]), target)));
  if (gaps.length && !limitations.length) {
    throw new Error(`${gaps.join(", ")} not covered on every reviewed frame: state what was not done in limitations`);
  }
}

/** Visual evidence: sampled stills and playback. Listening never supports a visual or motion note or claim. */
export const VISUAL_KINDS: readonly InspectionKind[] = ["still-frames", "motion-playback"];

/** The evidence a located claim needs by its lane: listening for an audible ("audio") claim, looking for any other. */
export function claimKinds(lane: unknown): readonly InspectionKind[] {
  return lane === "audio" ? ["audio-listening"] : VISUAL_KINDS;
}

/** Frames of one reviewed rendering observed with these kinds (by default looked at: sampled stills and playback). */
export function observedSpans(value: Inspection, target: ReviewTarget,
  kinds: readonly InspectionKind[] = VISUAL_KINDS): Array<[number, number]> {
  return framesOn(value.entries, target, kinds);
}

/** A frame note describes what was seen: it must name a frame looked at (a sampled still or playback). */
export function assertFrameSeen(value: Inspection, target: ReviewTarget, frame: number, label: string): void {
  if (observedSpans(value, target).some(([start, end]) => frame >= start && frame < end)) return;
  throw new Error(`${label} notes frame ${frame}, but it was never looked at on ${target.path} (no sampled still or `
    + "playback covers it; listening supports audible claims only); an unseen frame cannot support a note");
}

/** A frame-located claim: its frame range, its label and the inspection kinds that can support it (visual by default). */
export interface LocatedClaim { range: [number, number]; label: string; kinds?: readonly InspectionKind[] }

/** A frame-located claim needs a frame inside its range observed with its modality on some reviewed rendering. */
export function assertRangeObserved(value: Inspection, targets: ReviewTarget[], claim: LocatedClaim): void {
  const { range, label } = claim, kinds = claim.kinds ?? VISUAL_KINDS;
  if (targets.some(target => observedSpans(value, target, kinds).some(([start, end]) => start < range[1] && range[0] < end))) return;
  const how = kinds.includes("audio-listening") ? "heard (an audible claim needs listening)"
    : "looked at (a visual or motion claim needs stills or playback; listening does not count)";
  throw new Error(`${label} locates frames ${range[0]}–${range[1]}, none of which was ${how}; an unobserved frame `
    + "cannot support a claim");
}

/** Honest picture coverage: how many reviewed frames were actually looked at (sampled stills or playback). */
export function pictureCoverage(value: Inspection, targets: ReviewTarget[]) {
  const looked = targets.map(target => unionLength(framesOn(value.entries, target, APPROVAL_KINDS.picture)));
  const reviewed = targets.reduce((total, target) => total + target.endFrameExclusive - target.startFrame, 0);
  const lookedAt = looked.reduce((total, frames) => total + frames, 0);
  const coverage: EvidenceLevel = !lookedAt ? "none" : lookedAt === reviewed ? "complete"
    : looked.every(Boolean) ? "sampled" : "partial";
  return { coverage, framesLookedAt: lookedAt, framesReviewed: reviewed };
}

/** Frames (or seconds) covered by a set of ranges, overlaps counted once. */
export function unionLength(ranges: Array<[number, number]>): number {
  let total = 0, reached = -Infinity;
  for (const [start, end] of [...ranges].sort((a, b) => a[0] - b[0])) {
    total += Math.max(0, end - Math.max(start, reached));
    reached = Math.max(reached, end);
  }
  return total;
}

/** What readers report for a typed record: levels per kind, honest picture coverage, the approved aspects and who
 * declared the evidence. It is the reviewer's declaration, never authenticated. */
export function typedEvidence(value: Inspection, targets: ReviewTarget[], reviewer: { identity: string; sessionId: string }) {
  return { typed: true as const, authenticity: INSPECTION_AUTHENTICITY, declaredBy: { identity: reviewer.identity,
    sessionId: reviewer.sessionId }, levels: evidenceLevels(value, targets), picture: pictureCoverage(value, targets),
    approves: value.approves };
}

/** What readers report for a historical record: its declarations are untyped and approve nothing further. */
export function untypedEvidence() {
  return { typed: false as const, authenticity: INSPECTION_AUTHENTICITY, declaredBy: null, levels: { ...UNTYPED_EVIDENCE },
    picture: null, approves: [] as ReviewAspect[] };
}
