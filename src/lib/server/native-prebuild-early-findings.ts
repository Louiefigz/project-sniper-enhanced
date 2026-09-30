/** Early findings of a bounded plan critic (P2-11), and what the final plan review must do with them.
 * A plan critic submits each material issue as soon as it has it (`native-review.ts submit-prebuild-early`), at most
 * three early records per role packet, so the coordinator can route a repair while one can still help. An early record
 * binds the current packet and plan digest, an independent reviewer and 1–16 execution-scoped material issues in the
 * shared issue shape; it is published beside the packet's final record as `<record>-EARLY-<k>.json` (exclusive create)
 * and then recorded on the batch trail (`review-early-findings`: packet, issues SHA-256, count, index). It never
 * carries a verdict and never admits anything. It is batch-bound only: outside a batch there is no budget to route
 * against, so the critic submits the final record. An early record the authority refused stays on disk unrecorded and
 * binds nothing. The final `submit-prebuild` of the same packet must keep every recorded early code as a material
 * issue or withdraw it in `withdrawnEarlyIssues` with a reason; a deleted or edited early record fails it closed.
 * Lateness: the final record is late when it is submitted after the `hardBy` the batch authority recorded at the
 * packet's resolution (reported by the engine's given check as `budget`); a packet without a recorded budget or a
 * batch clock is late with `lateBasis: "clock-unknown"` (never on time). The authority records the same rule on its
 * `review-submitted` event (`studio/production/packets.py`). */
import path from "node:path";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { validateProducerReview, type ProducerMaterialIssue } from "@/app/api/producer/auto-edit/review-contract";
import { pythonInterpreter, SCRIPTS_DIR } from "@/app/api/_lib/spawn-python";
import { exactKeys, objectValue, sha256, stringValue, type JsonRecord } from "@/lib/producer/contracts/validation";
import { canonicalJson, canonicalJsonSha256 } from "./auto-edit-hash";
import { nativeShortPrebuildPlanHash, reviewIdentity } from "./native-short-prebuild-review";
import type { NativeShortProjectInput } from "./native-short-project";
import { assertPacketCurrent, canonicalInput, canonicalOutput, publishValidatedJson, readRolePacket,
  type RolePacket } from "./native-review-packet";
import { assertIndependentOf, frameClock, frameInteger, timecode, type FrameClock } from "./native-review-observations";
import { currentGiven, givenCheck, givenCheckReport } from "./native-review-given-check";
import type { SubmissionTiming } from "./native-review-provenance";
import type { ReviewSubmissionPaths } from "./native-review-submission-shared";

/** The kind of a plan critic's early observations file (schema 1). */
export const EARLY_KIND = "native-plan-review-early-findings";
const EARLY_SCOPE = "native-short-plan-early-findings";
const MAX_EARLY_RECORDS = 3, MAX_EARLY_ISSUES = 16, WITHDRAW_REASON_MIN = 20;
const ISSUE_KEYS = ["code", "severity", "lane", "message", "evidence", "frames", "scope", "requiredAction"];
const EARLY_EVENT_KEYS = ["index", "issuesSha256", "issues", "elapsed"];
const CONTEXT = path.join(SCRIPTS_DIR, "producer", "context.py");

/** One `review-early-findings` event as the engine reports it for a packet. */
export interface EarlyEvent { index: number; issuesSha256: string; issues: number; elapsed: number }
/** Whether a final plan record came after its packet's budget, and on what basis. */
export interface ReviewLateness { late: boolean; lateBasis: "budget" | "clock-unknown"; hardBy: number | null }

/** The context.py arguments that record one early record on its packet's batch clock. */
export function earlyFindingsArguments(packetPath: string, issuesSha256: string, counts: { issues: number; index: number },
  elapsed: number): string[] {
  return ["--review-early-findings", packetPath, "--issues-sha256", issuesSha256, "--issues", String(counts.issues),
    "--early-index", String(counts.index), "--submitted-elapsed", String(elapsed)];
}

/** The engine command that records an early record on the batch trail; tests replace it with a TEST double. */
export const earlyFindingsCheck = {
  record: (packetPath: string, issuesSha256: string, counts: { issues: number; index: number }, elapsed: number): JsonRecord =>
    givenCheckReport(pythonInterpreter(), ["-B", CONTEXT, ...earlyFindingsArguments(packetPath, issuesSha256, counts, elapsed)]),
};

/** The packet's own JSON (budget, submission paths), read again and bound to the bytes the packet was verified as. */
function packetValue(packet: RolePacket): JsonRecord {
  const observed = readCutPreviewObject(packet.path);
  if (observed.sha256 !== packet.sha256) throw new Error("The role packet changed while this submission read it");
  return objectValue(observed.value, "role packet");
}

/** `<final record>-EARLY-<index>.json` beside the final record this packet names. */
export function earlyRecordPath(packet: RolePacket, index: number): string {
  const submission = objectValue(packetValue(packet).submission, "role packet submission");
  const record = stringValue(submission.record, "role packet submission record", 4096);
  return path.join(path.dirname(record), `${path.basename(record, ".json")}-EARLY-${index}.json`);
}

/** What the batch authority recorded for a batch-bound plan-critic packet: its budget and early records (none, and
 * no budget, for an unbound one). */
export function recordedReview(packet: RolePacket): { budget: JsonRecord | null; early: EarlyEvent[] } {
  if (packet.given?.status !== "bound") return { budget: null, early: [] };
  const report = givenCheck.run(packet.path);
  if (!Array.isArray(report.earlyFindings) || !("budget" in report)) {
    throw new Error("The engine's given check did not report this packet's budget and early findings");
  }
  const budget = report.budget === null ? null : objectValue(report.budget, "recorded packet budget");
  return { budget, early: report.earlyFindings.map((value, index) => {
    const row = objectValue(value, `early finding ${index}`);
    exactKeys(row, EARLY_EVENT_KEYS, EARLY_EVENT_KEYS, `early finding ${index}`);
    if (row.index !== index + 1 || !Number.isSafeInteger(row.issues) || typeof row.elapsed !== "number") {
      throw new Error("The engine reported early findings out of order or malformed");
    }
    return { index: index + 1, issuesSha256: sha256(row.issuesSha256, "early issues hash"), issues: row.issues as number,
      elapsed: row.elapsed };
  }) };
}

function issueRow(value: unknown, index: number, clock: FrameClock) {
  const at = `materialIssues[${index}]`, row = objectValue(value, at);
  exactKeys(row, ISSUE_KEYS, ["code", "severity", "lane", "message", "scope", "requiredAction"], at);
  if (row.scope !== "execution") throw new Error(`${at}.scope must be execution: an early finding reports an execution defect`);
  const listed = row.evidence === undefined ? [] : row.evidence;
  if (!Array.isArray(listed) || listed.some(item => typeof item !== "string")) throw new Error(`${at}.evidence must be strings`);
  const frames = row.frames === undefined ? [] : [row.frames as unknown[]];
  const located = frames.map(range => {
    if (!Array.isArray(range) || range.length !== 2) throw new Error(`${at}.frames must be [startFrame, endFrameExclusive]`);
    const start = frameInteger(range[0], `${at}.frames start`, clock), end = frameInteger(range[1], `${at}.frames end`, clock, true);
    if (end <= start) throw new Error(`${at}.frames must end after it starts`);
    return timecode([start, end], clock);
  });
  return { code: row.code, severity: row.severity, lane: row.lane, message: row.message,
    evidence: [...located, ...listed as string[]], requiredAction: row.requiredAction };
}

/** 1–16 execution-scoped material issues in the shared issue shape (validated by the shared review contract; the
 * `revise` there is only the contract's shape for material issues and is never recorded). */
function earlyIssues(value: unknown, clock: FrameClock): ProducerMaterialIssue[] {
  if (!Array.isArray(value) || !value.length || value.length > MAX_EARLY_ISSUES) {
    throw new Error(`Early findings need 1–${MAX_EARLY_ISSUES} material issues; with none, keep reviewing`);
  }
  const rows = value.map((row, index) => issueRow(row, index, clock));
  if (rows.some(row => !row.evidence.length)) throw new Error("Each early material issue needs frames or an evidence reference");
  return validateProducerReview({ schemaVersion: 1, stage: "plan", verdict: "revise", summary: "early findings",
    materialIssues: rows, findings: [] }, "plan").materialIssues;
}

/** The packet's plan, unchanged since the packet froze it, and its frame clock. */
function currentPlan(packet: RolePacket): { planHash: string; clock: FrameClock } {
  const subject = objectValue(packet.subject.plan, "role packet plan");
  const value = readCutPreviewObject(stringValue(subject.path, "plan path", 4096)).value as unknown as NativeShortProjectInput;
  const planHash = nativeShortPrebuildPlanHash(value);
  if (planHash !== subject.planHash) throw new Error("Stale plan: the plan's authored digest differs from the role packet's");
  const canvas = objectValue(value.canvas, "plan canvas");
  return { planHash, clock: frameClock(canvas.frameRate, canvas.totalFrames) };
}

function readEarlyObservations(file: string, packet: RolePacket, clock: FrameClock) {
  const observed = readCutPreviewObject(canonicalInput(file, "Early observations file"));
  const value = objectValue(observed.value, "early observations"), keys = ["schemaVersion", "kind", "rolePacketSha256",
    "reviewer", "materialIssues"];
  exactKeys(value, keys, keys, "early observations");
  if (value.schemaVersion !== 1 || value.kind !== EARLY_KIND) throw new Error(`Early observations must be ${EARLY_KIND} schema 1`);
  if (sha256(value.rolePacketSha256, "rolePacketSha256") !== packet.sha256) {
    throw new Error("Early observations were written for a different role packet (rolePacketSha256 mismatch)");
  }
  const reviewer = reviewIdentity(value.reviewer);
  assertIndependentOf(reviewer, packet.authorSessionIds);
  return { file: { path: canonicalInput(file, "Early observations file"), sha256: observed.sha256 }, reviewer,
    issues: earlyIssues(value.materialIssues, clock) };
}

/** The next early record of a batch-bound packet: its index and exact path, refused past the third. */
function nextRecord(packet: RolePacket, output: string): number {
  const index = recordedReview(packet).early.length + 1;
  if (index > MAX_EARLY_RECORDS) {
    throw new Error(`A plan critic records at most ${MAX_EARLY_RECORDS} early findings per role packet; put later issues in the final record`);
  }
  const expected = earlyRecordPath(packet, index);
  if (output !== expected) throw new Error(`The next early findings record of this packet is ${expected}`);
  return index;
}

/** Record early material issues of a batch-bound plan-critic packet; never a verdict and never an admission. */
export function submitNativePrebuildEarlyFindings(paths: ReviewSubmissionPaths) {
  const packet = readRolePacket(paths.packet, "plan-critic");
  assertPacketCurrent(packet);
  const plan = currentPlan(packet), current = currentGiven(packet);
  if (!current.batchClock) throw new Error("Early findings are recorded only for a batch-bound packet; outside a batch submit the final record");
  if (canonicalJson(current.given) !== canonicalJson(packet.given)) {
    throw new Error("The batch authority's approval no longer yields this packet's given block; re-resolve the role packet");
  }
  const output = canonicalOutput(paths.output, "Early findings record", packet.subject), index = nextRecord(packet, output);
  const observations = readEarlyObservations(paths.observations, packet, plan.clock);
  const issuesSha256 = canonicalJsonSha256(observations.issues), clock = current.batchClock;
  const record = { schemaVersion: 1, scope: EARLY_SCOPE, index, planHash: plan.planHash,
    rolePacket: { path: packet.path, sha256: packet.sha256 }, observations: observations.file, reviewer: observations.reviewer,
    materialIssues: observations.issues, issuesSha256, timing: { basis: "batch-authority", batchId: clock.batchId,
      clipId: clock.clipId, resolvedElapsed: clock.resolvedElapsed, submittedElapsed: clock.nowElapsed } };
  const published = publishValidatedJson(output, record, candidate => {
    if (canonicalJson(readCutPreviewObject(candidate).value) !== canonicalJson(record)) throw new Error("Early record re-read differs");
  });
  const report = earlyFindingsCheck.record(packet.path, issuesSha256, { issues: observations.issues.length, index }, clock.nowElapsed);
  const event = objectValue(report.event, "recorded early findings event");
  if (report.status !== "early-findings-recorded" || event.index !== index || event.issuesSha256 !== issuesSha256) {
    throw new Error(`Early record ${published.path} was published but the batch authority did not record it; it binds nothing`);
  }
  return { status: "early-findings-recorded" as const, record: published.path, issues: observations.issues.length, index };
}

/** The recorded early codes of this packet, each read from its own record (bytes and issues hash re-checked). */
function earlyCodes(packet: RolePacket, recorded: EarlyEvent[]): string[] {
  return recorded.flatMap(event => {
    const file = earlyRecordPath(packet, event.index);
    let value: JsonRecord;
    try { value = objectValue(readCutPreviewObject(file).value, "early findings record"); } catch {
      throw new Error(`Early findings record ${event.index} of this packet is missing or unreadable (${file}); it was recorded on the batch trail`);
    }
    const bound = objectValue(value.rolePacket, "early record packet");
    if (bound.sha256 !== packet.sha256 || value.issuesSha256 !== event.issuesSha256
        || canonicalJsonSha256(value.materialIssues) !== event.issuesSha256) {
      throw new Error(`Early findings record ${file} differs from what the batch authority recorded`);
    }
    return (value.materialIssues as JsonRecord[]).map(row => String(row.code));
  });
}

/** Every recorded early code is kept as a material issue or withdrawn with a reason of at least 20 characters. */
export function assertEarlyFindingsAccounted(packet: RolePacket, observations: JsonRecord,
  recorded: EarlyEvent[]): { early: string[]; withdrawn: string[] } {
  const early = earlyCodes(packet, recorded), listed = observations.withdrawnEarlyIssues ?? [];
  if (!Array.isArray(listed)) throw new Error("withdrawnEarlyIssues must be an array of {code, reason}");
  const withdrawn = listed.map((value, index) => {
    const row = objectValue(value, `withdrawnEarlyIssues[${index}]`);
    exactKeys(row, ["code", "reason"], ["code", "reason"], `withdrawnEarlyIssues[${index}]`);
    const code = stringValue(row.code, `withdrawnEarlyIssues[${index}].code`, 128);
    if (stringValue(row.reason, `withdrawnEarlyIssues[${index}].reason`, 2000).trim().length < WITHDRAW_REASON_MIN) {
      throw new Error(`withdrawnEarlyIssues[${index}].reason must explain the withdrawal in at least ${WITHDRAW_REASON_MIN} characters`);
    }
    if (!early.includes(code)) throw new Error(`withdrawnEarlyIssues[${index}] names ${code}, which no early finding of this packet raised`);
    return code;
  });
  const kept = new Set(((observations.materialIssues ?? []) as JsonRecord[]).map(row => String(row.code)));
  const missing = early.find(code => !kept.has(code) && !withdrawn.includes(code));
  if (missing) throw new Error(`Final plan review omits early finding ${missing}; keep it as a material issue or withdraw it with a reason`);
  return { early, withdrawn };
}

/** Late when submitted after the recorded `hardBy`; an unknown budget or batch clock is late (fail closed). */
export function reviewLateness(budget: JsonRecord | null, timing: SubmissionTiming): ReviewLateness {
  const hardBy = budget?.hardBy;
  if (timing.basis !== "batch-authority" || typeof hardBy !== "number") return { late: true, lateBasis: "clock-unknown", hardBy: null };
  return { late: timing.submittedElapsed > hardBy, lateBasis: "budget", hardBy };
}
