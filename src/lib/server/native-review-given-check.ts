/** Gate-time re-check of approved content (requirement approved-content-production-2026-09-27).
 * One implementation of the rule: the engine's `context.py --given-check <packet>` (unit B1) re-derives the packet's
 * given block from the batch authority's CURRENT approval and the plan the packet froze — or, for a not-supplied or
 * absent block, re-runs the omission refusal — and, for a batch-bound packet, returns the batch-clock time at which
 * the authority recorded that exact packet's resolution. For an existing record it also returns the
 * `review-submitted` event the submission recorded for the record's own canonical bytes. The submission and every
 * typed gate reader call it, so an approval changed after a review, a batch started after it, or a given block edited
 * or copied into another packet never admits a build, a full render or an export. `check-final` reads an existing
 * record as submitted (`--as-submitted`): against the approval in force at its recorded submission time, which still
 * works after the batch closed, and reporting any later approval that superseded it. Nothing here reads the
 * authority itself. */
import { spawnSync } from "node:child_process";
import path from "node:path";
import { pythonInterpreter, SCRIPTS_DIR } from "@/app/api/_lib/spawn-python";
import { exactKeys, objectValue, sha256, stringValue, type JsonRecord } from "@/lib/producer/contracts/validation";

const CONTEXT = path.join(SCRIPTS_DIR, "producer", "context.py");
const TIMEOUT_MS = 120_000;
const CLOCK_KEYS = ["batchId", "clipId", "resolvedElapsed", "nowElapsed"];
const SUBMITTED_KEYS = ["clipId", "role", "recordSha256", "elapsed"];
const AS_OF_KEYS = ["submittedElapsed", "authorityStatus", "approvalIdentity", "approvalElapsed", "supersededBy"];

/** When the batch authority recorded a bound packet's resolution, and its clock now (batch-clock seconds). */
export interface BatchClock { batchId: string; clipId: string; resolvedElapsed: number; nowElapsed: number }
/** The `review-submitted` event the authority holds for one record's canonical bytes. */
export interface SubmittedEvent { clipId: string; role: string; recordSha256: string; elapsed: number }
/** The approval in force at a record's recorded submission, and a later one that superseded it (check-final only). */
export interface AsSubmitted {
  submittedElapsed: number; authorityStatus: string; approvalIdentity: string; approvalElapsed: number;
  supersededBy: { identity: string; elapsed: number } | null;
}
/** The packet's given block as the authority yields it; a batch clock exactly when it is bound. */
export interface CurrentGiven {
  given: JsonRecord; batchClock: BatchClock | null; submitted: SubmittedEvent | null; asSubmitted: AsSubmitted | null;
}
/** An existing record's re-check: its canonical SHA-256, and whether it is read as submitted (check-final). */
export interface RecordCheck { recordSha256: string; asSubmitted: boolean }

/** The context.py arguments of one given check. */
export function givenCheckArguments(packetPath: string, record?: RecordCheck): string[] {
  return ["--given-check", packetPath, ...(record ? ["--record-sha256", record.recordSha256] : []),
    ...(record?.asSubmitted ? ["--as-submitted"] : [])];
}

/** The context.py arguments that record one record's submission on its batch clock. */
export function submittedArguments(packetPath: string, recordSha256: string, elapsed: number): string[] {
  return ["--review-submitted", packetPath, "--record-sha256", recordSha256, "--submitted-elapsed", String(elapsed)];
}

/** Run one engine command line and read its JSON report (the TEST harness runs the same CLI in its private root). */
export function givenCheckReport(command: string, args: string[]): JsonRecord {
  const result = spawnSync(command, args, { encoding: "utf8", timeout: TIMEOUT_MS, maxBuffer: 4 * 1024 * 1024 });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Approved-content re-check refused this review: ${(result.stderr || result.stdout).trim().slice(0, 1500)
      || `exit ${result.status}`}`);
  }
  return objectValue(JSON.parse(result.stdout), "given check report");
}

/** The engine commands submissions and gate readers use; tests replace them with TEST doubles. */
export const givenCheck = {
  run: (packetPath: string, record?: RecordCheck): JsonRecord =>
    givenCheckReport(pythonInterpreter(), ["-B", CONTEXT, ...givenCheckArguments(packetPath, record)]),
  record: (packetPath: string, recordSha256: string, elapsed: number): JsonRecord =>
    givenCheckReport(pythonInterpreter(), ["-B", CONTEXT, ...submittedArguments(packetPath, recordSha256, elapsed)]),
};

function seconds(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) throw new Error(`${label} must be batch-clock seconds`);
  return value;
}

function batchClock(value: unknown): BatchClock | null {
  if (value === null) return null;
  const row = objectValue(value, "given check batch clock");
  exactKeys(row, CLOCK_KEYS, CLOCK_KEYS, "given check batch clock");
  const clock = { batchId: stringValue(row.batchId, "batch clock batch", 64), clipId: stringValue(row.clipId, "batch clock clip", 64),
    resolvedElapsed: seconds(row.resolvedElapsed, "resolvedElapsed"), nowElapsed: seconds(row.nowElapsed, "nowElapsed") };
  if (clock.nowElapsed < clock.resolvedElapsed) throw new Error("The batch clock reads earlier than the packet's recorded resolution");
  return clock;
}

/** A recorded `review-submitted` event as the engine reports it. */
export function submittedEvent(value: unknown): SubmittedEvent | null {
  if (value === null) return null;
  const row = objectValue(value, "recorded review submission");
  exactKeys(row, SUBMITTED_KEYS, SUBMITTED_KEYS, "recorded review submission");
  return { clipId: stringValue(row.clipId, "submission clip", 64), role: stringValue(row.role, "submission role", 64),
    recordSha256: sha256(row.recordSha256, "submitted record hash"), elapsed: seconds(row.elapsed, "submitted elapsed") };
}

function asSubmitted(value: unknown): AsSubmitted | null {
  if (value === null) return null;
  const row = objectValue(value, "as-submitted approval");
  exactKeys(row, AS_OF_KEYS, AS_OF_KEYS, "as-submitted approval");
  const later = row.supersededBy === null ? null : objectValue(row.supersededBy, "superseding approval");
  if (later) exactKeys(later, ["identity", "elapsed"], ["identity", "elapsed"], "superseding approval");
  return { submittedElapsed: seconds(row.submittedElapsed, "as-submitted elapsed"),
    authorityStatus: stringValue(row.authorityStatus, "as-submitted authority status", 32),
    approvalIdentity: sha256(row.approvalIdentity, "as-submitted approval identity"),
    approvalElapsed: seconds(row.approvalElapsed, "as-submitted approval time"),
    supersededBy: later && { identity: sha256(later.identity, "superseding identity"), elapsed: seconds(later.elapsed, "superseded at") } };
}

/** Re-derive this exact packet's given block; the report must name the same bytes the caller holds. With a record, the
 * bound packet's `review-submitted` event comes back too, and `asSubmitted` reads it as of that submission. */
export function currentGiven(packet: { path: string; sha256: string }, record?: RecordCheck): CurrentGiven {
  const report = givenCheck.run(packet.path, record);
  if (report.status !== "given-current") throw new Error("The approved-content re-check did not report the current given block");
  const named = objectValue(report.packet, "given check packet");
  if (named.path !== packet.path || sha256(named.sha256, "given check packet hash") !== packet.sha256) {
    throw new Error("The role packet changed after this review bound it; its given block cannot be re-checked");
  }
  const given = objectValue(report.given, "given check block"), clock = batchClock(report.batchClock);
  const submitted = submittedEvent(report.submitted), asOf = asSubmitted(report.asSubmitted), bound = given.status === "bound";
  if (bound !== (clock !== null) || (bound && Boolean(record)) !== (submitted !== null)) {
    throw new Error("A batch-bound given block needs the batch clock of its recorded resolution and, for a record, its "
      + "recorded submission (and only a bound one has them)");
  }
  if (clock && (clock.batchId !== given.batchId || clock.clipId !== given.clipId)) {
    throw new Error("The recorded packet resolution names another batch clip than the given block");
  }
  if ((bound && Boolean(record?.asSubmitted)) !== (asOf !== null)) throw new Error("An as-submitted reading was not reported as one");
  return { given, batchClock: clock, submitted, asSubmitted: asOf };
}

/** Record a batch-bound record's submission on its batch clock at the time the record states; unbound records have
 * no batch clock and record nothing. The engine refuses a time outside the packet resolution and the clock now, or
 * one earlier than a recorded approval change. */
export function recordSubmitted(packet: { path: string; sha256: string }, recordSha256: string,
  timing: { basis: string; submittedElapsed?: number }): SubmittedEvent | null {
  if (timing.basis !== "batch-authority") return null;
  const report = givenCheck.record(packet.path, recordSha256, seconds(timing.submittedElapsed, "submittedElapsed"));
  const named = objectValue(report.packet, "recorded submission packet");
  const event = objectValue(report.event, "recorded submission event");
  if (report.status !== "review-submitted-recorded" || named.path !== packet.path || named.sha256 !== packet.sha256
      || event.event !== "review-submitted") {
    throw new Error("The batch authority did not report recording this review's submission");
  }
  const recorded = submittedEvent({ clipId: event.clipId, role: event.role, recordSha256: event.recordSha256,
    elapsed: event.elapsed })!;
  if (recorded.recordSha256 !== recordSha256 || recorded.elapsed !== timing.submittedElapsed) {
    throw new Error("The batch authority recorded another submission than this record's");
  }
  return recorded;
}
