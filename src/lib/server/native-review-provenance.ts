/** Submission provenance, timing and approved content for typed review records.
 * A typed record names the exact role packet it answered, when that packet was resolved and when the record was
 * submitted. The submission helper and every gate reader check that the claimed normal-speed playback and listening
 * fit inside that interval, so a hand-built record cannot claim more than one reviewer could have watched or heard.
 * For a batch-bound packet the interval is measured on the batch authority's clock, from the packet resolution the
 * authority recorded (`studio.production.packets`) to the submission; a packet's own `resolvedAt` and file times are
 * never trusted for it. An unbound packet keeps its author-written resolution time, labelled
 * `declared-not-authenticated`. A batch-bound record's submission is itself recorded in the batch trail
 * (`review-submitted`: the record's canonical SHA-256, role, clip and its stated `submittedElapsed`), and every reader
 * requires that event for the record's own bytes, so a record edited or assembled after submission is refused. Every
 * admitting reader re-derives the approved content from the authority's current approval
 * (`native-review-given-check.ts`) and admits only the record that still equals it; `check-final` reads it as of the
 * recorded submission (the approval then in force, also after the batch closed) and reports a later superseding
 * approval. Timing is a lower bound, never proof that anything was seen or heard, and a deliberately delayed
 * submission is indistinguishable from a slow review. */
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { exactKeys, objectValue, sha256, stringValue, type JsonRecord } from "@/lib/producer/contracts/validation";
import { canonicalJson, canonicalJsonSha256 } from "./auto-edit-hash";
import { AS_SUBMITTED_STATUSES, approvedContentBlock, readApprovedContent,
  type ApprovedContent } from "./native-review-approved-content";
import { currentGiven, type AsSubmitted, type BatchClock, type CurrentGiven,
  type SubmittedEvent } from "./native-review-given-check";
import { framesOn, INSPECTION_AUTHENTICITY, unionLength, type Inspection, type InspectionKind,
  type ReviewTarget } from "./native-review-submission-shared";

/** A program frame clock: frames per second and the program length in frames. */
export interface FrameClock { fps: number; totalFrames: number }
export interface TimingContext { targets: ReviewTarget[]; fps: number; elapsedSeconds: number }
interface Binding { path: string; sha256: string }
/** The measured interval: the batch authority's clock for a batch-bound packet, else the packet's own declared time. */
export type SubmissionTiming =
  | { basis: "batch-authority"; batchId: string; clipId: string; resolvedElapsed: number; submittedElapsed: number }
  | { basis: "declared-not-authenticated" };
/** The packet and times a typed record binds; the times are the helper's clock, the packet is hash-bound evidence. */
export interface Submission {
  schemaVersion: 2; role: string; rolePacket: Binding; packetResolvedAt: string; submittedAt: string;
  authenticity: typeof INSPECTION_AUTHENTICITY; timing: SubmissionTiming;
}
/** What a reader needs to re-check a record's provenance against its own evidence, reviewer, verdict, inspection
 * and recorded approved content. `record` is the typed record (a motion bundle's own row) whose canonical bytes the
 * submission recorded; `asSubmitted` reads it as of that submission (read-only check-final, never an admission). */
export interface SubmissionCheck {
  role: string; evidence: Binding[]; inspection: Inspection; targets: ReviewTarget[]; fps: number;
  reviewer: unknown; verdict: string; approvedContent: unknown; subject: ReviewedSubject; record: JsonRecord;
  asSubmitted?: boolean;
}
/** A re-checked submission: its block, its approved content and, when read as submitted, the approval then. */
export interface CheckedSubmission { submission: Submission; approvedContent: ApprovedContent; asSubmitted: AsSubmitted | null }
/** What the answered packet must have reviewed: the record's own plan digest, preview record or checked MP4. */
export type ReviewedSubject = { plan: string } | { preview: Binding } | { video: Binding };
const KEYS = ["schemaVersion", "role", "rolePacket", "packetResolvedAt", "submittedAt", "authenticity", "timing"];
const BATCH_TIMING_KEYS = ["basis", "batchId", "clipId", "resolvedElapsed", "submittedElapsed"];
const OBSERVATION_KIND: Record<string, string> = { "plan-critic": "native-plan-review-observations",
  "motion-critic": "native-motion-review-observations", "final-critic": "native-final-review-observations" };

/** A rational frame rate such as "30/1" or "30000/1001". */
export function frameClock(rate: unknown, totalFrames: unknown): FrameClock {
  const match = typeof rate === "string" ? /^(\d+)\/(\d+)$/u.exec(rate) : null;
  if (!match || !Number(match[2]) || !Number.isSafeInteger(totalFrames) || (totalFrames as number) < 1) {
    throw new Error("Frame clock is invalid");
  }
  return { fps: Number(match[1]) / Number(match[2]), totalFrames: totalFrames as number };
}

/** Seconds of one kind claimed on one artifact: program frames on a reviewed rendering, else declared seconds. */
function claimedSeconds(value: Inspection, kind: InspectionKind, file: string, context: TimingContext): number {
  const rows = value.entries.filter(row => row.kind === kind && row.artifact.path === file);
  const target = context.targets.find(item => item.path === file);
  if (target) return unionLength(framesOn(rows, target, [kind])) / context.fps;
  return unionLength(rows.flatMap(row => typeof row.span === "object" && "seconds" in row.span ? [row.span.seconds] : []));
}

/** Normal-speed seconds one reviewer needs: per artifact the longer of playback and listening (they can run
 * together), summed over artifacts (one reviewer attends to one artifact at a time). */
export function requiredSeconds(value: Inspection, context: TimingContext): number {
  const files = [...new Set(value.entries.filter(row => row.kind !== "still-frames").map(row => row.artifact.path))];
  return files.reduce((total, file) => total + Math.max(claimedSeconds(value, "motion-playback", file, context),
    claimedSeconds(value, "audio-listening", file, context)), 0);
}

/** Refuse playback or listening that could not fit between packet resolution and submission. */
export function assertPlausibleTiming(value: Inspection, context: TimingContext): void {
  if (!Number.isFinite(context.elapsedSeconds) || context.elapsedSeconds < 0) {
    throw new Error("Timing inconsistency: the submission time precedes the role packet's resolution time (a clock "
      + "moved backward or a time is malformed); re-resolve the role packet and submit again");
  }
  const needed = requiredSeconds(value, context);
  if (needed > context.elapsedSeconds) {
    throw new Error(`Implausible completion: the inspection claims ${needed.toFixed(1)} s of normal-speed playback or `
      + `listening (summed over artifacts), but only ${context.elapsedSeconds.toFixed(1)} s passed between resolving the `
      + "role packet and submitting");
  }
}

/** The provenance block a submission writes; `submittedAt` is the helper's clock, `clock` the batch authority's. */
export function submissionBlock(packet: { role: string; path: string; sha256: string; resolvedAt: string },
  submittedAt: Date, clock: BatchClock | null): Submission {
  const timing: SubmissionTiming = clock ? { basis: "batch-authority", batchId: clock.batchId, clipId: clock.clipId,
    resolvedElapsed: clock.resolvedElapsed, submittedElapsed: clock.nowElapsed } : { basis: "declared-not-authenticated" };
  return { schemaVersion: 2, role: packet.role, rolePacket: { path: packet.path, sha256: packet.sha256 },
    packetResolvedAt: packet.resolvedAt, submittedAt: submittedAt.toISOString(), authenticity: INSPECTION_AUTHENTICITY, timing };
}

/** The SHA-256 of a typed record's canonical JSON (a motion bundle's own row): what `review-submitted` names. */
export function recordDigest(record: unknown): string {
  return canonicalJsonSha256(JSON.parse(JSON.stringify(record)));
}

/** Seconds between packet resolution and submission, on the batch clock when the packet is batch-bound. */
export function submissionSeconds(value: Submission): number {
  if (value.timing.basis === "batch-authority") return value.timing.submittedElapsed - value.timing.resolvedElapsed;
  return (Date.parse(value.submittedAt) - Date.parse(value.packetResolvedAt)) / 1000;
}

function readTiming(value: unknown): SubmissionTiming {
  const row = objectValue(value, "review submission timing");
  if (row.basis === "declared-not-authenticated") {
    exactKeys(row, ["basis"], ["basis"], "review submission timing");
    return { basis: "declared-not-authenticated" };
  }
  exactKeys(row, BATCH_TIMING_KEYS, BATCH_TIMING_KEYS, "review submission timing");
  const [resolved, submitted] = [row.resolvedElapsed, row.submittedElapsed];
  if (row.basis !== "batch-authority" || typeof resolved !== "number" || typeof submitted !== "number"
      || !Number.isFinite(resolved) || !Number.isFinite(submitted) || resolved < 0 || submitted < resolved) {
    throw new Error("Review submission timing must be batch-clock seconds with submission after resolution");
  }
  return { basis: "batch-authority", batchId: stringValue(row.batchId, "timing batch", 64),
    clipId: stringValue(row.clipId, "timing clip", 64), resolvedElapsed: resolved, submittedElapsed: submitted };
}

function readBlock(value: unknown): Submission {
  const row = objectValue(value, "review submission");
  exactKeys(row, KEYS, KEYS, "review submission");
  const packet = objectValue(row.rolePacket, "review submission rolePacket");
  exactKeys(packet, ["path", "sha256"], ["path", "sha256"], "review submission rolePacket");
  if (row.schemaVersion === 1) {
    throw new Error("This review was recorded before batch-clock packet timing and gate-time approval re-checks (submission "
      + "schema 1); resolve a new role packet and submit the review again");
  }
  if (row.schemaVersion !== 2 || row.authenticity !== INSPECTION_AUTHENTICITY) throw new Error("Review submission block is invalid");
  const times = [row.packetResolvedAt, row.submittedAt].map((time, index) => stringValue(time, `submission time ${index}`, 64));
  if (times.some(time => !Number.isFinite(Date.parse(time)))) throw new Error("Review submission times are not timestamps");
  return { schemaVersion: 2, role: stringValue(row.role, "submission role", 64),
    rolePacket: { path: stringValue(packet.path, "submission packet path", 4096), sha256: sha256(packet.sha256, "packet hash") },
    packetResolvedAt: times[0], submittedAt: times[1], authenticity: INSPECTION_AUTHENTICITY, timing: readTiming(row.timing) };
}

/** The typed submission writes the observations file first in evidence; the record must repeat its reviewer, verdict,
 * typed inspection and answered packet exactly. A record assembled by hand disagrees here. */
function assertMatchesObservations(block: Submission, check: SubmissionCheck): JsonRecord {
  const file = check.evidence[0], observed = file && readCutPreviewObject(file.path);
  const value = observed && observed.sha256 === file.sha256 ? objectValue(observed.value, "bound observations") : null;
  const same = value !== null && value.kind === OBSERVATION_KIND[check.role] && value.rolePacketSha256 === block.rolePacket.sha256
    && value.verdict === check.verdict && canonicalJson(value.reviewer) === canonicalJson(check.reviewer)
    && canonicalJson(value.inspection) === canonicalJson(check.inspection.entries)
    && canonicalJson(value.approves) === canonicalJson(check.inspection.approves);
  if (!same) {
    throw new Error("The review record disagrees with the observations it binds (reviewer, verdict, typed inspection or "
      + "answered packet); typed records are written only by the typed submission");
  }
  return value;
}

function sameBinding(value: unknown, expected: Binding): boolean {
  const row = value !== null && typeof value === "object" ? value as Record<string, unknown> : {};
  return row.path === expected.path && row.sha256 === expected.sha256;
}

/** The packet a record answers reviewed the very plan, preview or MP4 the record admits (never another one). */
function assertReviewedSubject(packet: JsonRecord, expected: ReviewedSubject): void {
  const subject = objectValue(packet.subject, "bound role packet subject");
  const same = "plan" in expected ? objectValue(subject.plan, "bound packet plan").planHash === expected.plan
    : "preview" in expected ? sameBinding(subject.preview, expected.preview)
      : sameBinding(objectValue(subject.export, "bound packet export").video, expected.video);
  if (!same) throw new Error("The review record answers a role packet for another plan, preview or MP4 than the one it admits");
}

/** A batch-bound packet's review is timed on the batch clock, from the resolution the authority recorded. */
function assertTimingBasis(block: Submission, clock: BatchClock | null): void {
  const timing = block.timing;
  if (timing.basis === "declared-not-authenticated") {
    if (clock) throw new Error("This review answers a batch-bound packet but is not timed on the batch clock; submit it again");
    return;
  }
  if (!clock || clock.batchId !== timing.batchId || clock.clipId !== timing.clipId || clock.resolvedElapsed !== timing.resolvedElapsed) {
    throw new Error("The record's batch-clock timing disagrees with the packet resolution the batch authority recorded");
  }
  if (timing.submittedElapsed > clock.nowElapsed) {
    throw new Error("Timing inconsistency: the record claims a submission time the batch clock has not reached yet");
  }
}

/** A batch-bound record admits only with the batch trail's `review-submitted` event for its own canonical bytes, at
 * exactly the submission time it states. */
function assertRecordedSubmission(block: Submission, submitted: SubmittedEvent | null, recordSha256: string): void {
  const timing = block.timing;
  if (timing.basis === "declared-not-authenticated") return;
  if (!submitted || submitted.recordSha256 !== recordSha256 || submitted.role !== block.role
      || submitted.clipId !== timing.clipId || submitted.elapsed !== timing.submittedElapsed) {
    throw new Error("The batch authority recorded no submission of this exact record at the time it states (review-submitted "
      + "event: record hash, role, clip, submittedElapsed); a record edited or assembled after submission is refused");
  }
}

/** The recorded approved content must equal what the authority's approval (current, or as submitted) yields. */
function currentApprovedContent(recorded: unknown, current: CurrentGiven, observations: JsonRecord,
  verdict: string): ApprovedContent {
  const statuses = current.asSubmitted ? AS_SUBMITTED_STATUSES : undefined;
  const stored = readApprovedContent(recorded, verdict), fresh = approvedContentBlock(current.given, observations, verdict, statuses);
  if (canonicalJson(stored) !== canonicalJson(fresh)) {
    throw new Error("The record's approved content is not what the batch authority's current approval yields for the "
      + "reviewed plan (the approval changed, a batch now holds the source, or the record was edited); obtain a review "
      + "against the current approval");
  }
  return stored;
}

/** Reader re-check: the record repeats its bound observations and the hash-bound packet of the right role and
 * resolution time, the submission is not in the future and (when batch-bound) is the one the trail recorded, the
 * typed claims fit the interval (batch clock when bound), and its approved content still equals what the authority's
 * current approval yields (or, read as submitted, the approval in force at its recorded submission). */
export function assertSubmission(value: unknown, check: SubmissionCheck): CheckedSubmission {
  const block = readBlock(value);
  if (block.role !== check.role) throw new Error(`Review submission is for ${block.role}, not ${check.role}`);
  if (!check.evidence.some(row => row.path === block.rolePacket.path && row.sha256 === block.rolePacket.sha256)) {
    throw new Error("Review submission names a role packet that its evidence does not bind");
  }
  const packet = objectValue(readCutPreviewObject(block.rolePacket.path).value, "bound role packet");
  if (packet.kind !== "sniper-role-packet" || packet.role !== check.role || packet.resolvedAt !== block.packetResolvedAt) {
    throw new Error("Review submission disagrees with its bound role packet (role or resolution time)");
  }
  assertReviewedSubject(packet, check.subject);
  const observations = assertMatchesObservations(block, check);
  if (Date.parse(block.submittedAt) > Date.now()) {
    throw new Error("Timing inconsistency: the review submission time is in the future; check the system clock");
  }
  const recordSha256 = recordDigest(check.record);
  const current = currentGiven(block.rolePacket, { recordSha256, asSubmitted: check.asSubmitted === true });
  assertTimingBasis(block, current.batchClock);
  assertRecordedSubmission(block, current.submitted, recordSha256);
  assertPlausibleTiming(check.inspection, { targets: check.targets, fps: check.fps, elapsedSeconds: submissionSeconds(block) });
  return { submission: block, approvedContent: currentApprovedContent(check.approvedContent, current, observations, check.verdict),
    asSubmitted: current.asSubmitted };
}
