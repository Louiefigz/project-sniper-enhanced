/** Critic-authored observations: the critic supplies every judgment; this module checks and serializes it. */
import path from "node:path";
import { observeCutPreviewFile, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { validateProducerReview, type ProducerFinding, type ProducerMaterialIssue, type ProducerReview,
  type ProducerReviewStage } from "@/app/api/producer/auto-edit/review-contract";
import { exactKeys, objectValue, sha256, stringValue, type JsonRecord } from "@/lib/producer/contracts/validation";
import { reviewCoverage, reviewIdentity, type NativePrebuildReview, type NativePrebuildReviewBinding } from "./native-short-prebuild-review";
import { canonicalInput, type RolePacket } from "./native-review-packet";
import { approvals, assertRangeObserved, claimKinds, inspectionEntries, type Inspection,
  type ReviewTarget } from "./native-review-submission-shared";
import { assertPlausibleTiming, recordDigest, submissionBlock, submissionSeconds, type FrameClock,
  type Submission } from "./native-review-provenance";
import { approvedContentBlock } from "./native-review-approved-content";
import { recheckSharedEvidence } from "./native-review-shared-evidence";
import { currentGiven, recordSubmitted } from "./native-review-given-check";
import { canonicalJson } from "./auto-edit-hash";

export { frameClock, type FrameClock } from "./native-review-provenance";

export type ObservationKind = "native-plan-review-observations" | "native-motion-review-observations"
  | "native-final-review-observations";
/** Schema 2 replaces declared playback/listening flags with typed inspection entries and approved aspects. */
const OBSERVATION_SCHEMA = 2;
const COMMON = ["schemaVersion", "kind", "rolePacketSha256", "reviewer", "coverage", "verdict", "summary",
  "materialIssues", "findings", "limitations", "evidence", "inspection", "approves"];
const ROLE_KEYS: Record<ObservationKind, string[]> = {
  "native-plan-review-observations": ["scenes"],
  "native-motion-review-observations": ["windows", "assessment"],
  "native-final-review-observations": ["frameNotes", "events", "assessment"],
};
const EVIDENCE_LIMIT = 32;

export interface ObservationRequest {
  file: string; kind: ObservationKind; packet: RolePacket; stage: ProducerReviewStage;
  clock: FrameClock; framesRequired: boolean;
}
export interface Observations {
  file: NativePrebuildReviewBinding; value: JsonRecord; reviewer: NativePrebuildReview["reviewer"];
  coverage: NativePrebuildReview["coverage"]; review: ProducerReview; limitations: string[];
}

export function frameInteger(value: unknown, label: string, clock: FrameClock, end = false): number {
  const limit = end ? clock.totalFrames : clock.totalFrames - 1;
  if (!Number.isSafeInteger(value) || (value as number) < 0 || (value as number) > limit) {
    throw new Error(`${label} must be an integer frame within 0–${limit}`);
  }
  return value as number;
}

/** "frames a–b (x–y s)" for a start-inclusive, end-exclusive range. */
export function timecode(range: [number, number], clock: FrameClock): string {
  return `frames ${range[0]}–${range[1]} (${(range[0] / clock.fps).toFixed(3)}–${(range[1] / clock.fps).toFixed(3)} s)`;
}

function frameRange(value: unknown, label: string, clock: FrameClock): [number, number] {
  if (!Array.isArray(value) || value.length !== 2) throw new Error(`${label} must be [startFrame, endFrameExclusive]`);
  const start = frameInteger(value[0], `${label} start`, clock), end = frameInteger(value[1], `${label} end`, clock, true);
  if (end <= start) throw new Error(`${label} must end after it starts`);
  return [start, end];
}

function issue(value: unknown, at: string, material: boolean, request: ObservationRequest) {
  const row = objectValue(value, at);
  const keys = ["code", "severity", "lane", "message", "evidence", "frames", "scope", ...(material ? ["requiredAction"] : [])];
  exactKeys(row, keys, ["code", "severity", "lane", "message", ...(material ? ["requiredAction"] : [])], at);
  if (request.framesRequired && material && row.frames === undefined) {
    throw new Error(`${at} needs frames [start, endExclusive] locating the issue`);
  }
  const extra = row.evidence === undefined ? [] : row.evidence;
  if (!Array.isArray(extra) || extra.some(item => typeof item !== "string")) throw new Error(`${at}.evidence must be strings`);
  const evidence = [...(row.frames === undefined ? [] : [timecode(frameRange(row.frames, `${at}.frames`, request.clock), request.clock)]), ...extra as string[]];
  if (!evidence.length) throw new Error(`${at} needs frames or at least one evidence reference`);
  const common = { code: row.code, severity: row.severity, lane: row.lane, message: row.message, evidence };
  return material ? { ...common, requiredAction: row.requiredAction } : common;
}

function issueList(value: unknown, label: string, material: boolean, request: ObservationRequest) {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  return value.map((row, index) => issue(row, `${label}[${index}]`, material, request));
}

function limitations(value: unknown): string[] {
  if (!Array.isArray(value) || value.length > 20) throw new Error("limitations must be an array of at most 20 statements");
  return value.map((row, index) => stringValue(row, `limitations[${index}]`, 1000));
}

/** Reject a verdict that disagrees with the critic's own findings before the shared contract runs. */
export function assertVerdictConsistent(verdict: unknown, materialCount: number): void {
  if (verdict === "pass" && materialCount) {
    throw new Error(`Verdict pass is inconsistent with ${materialCount} material issue(s); use revise or block`);
  }
  if ((verdict === "revise" || verdict === "block") && !materialCount) {
    throw new Error(`Verdict ${verdict} needs at least one material issue with its smallest required repair`);
  }
  if (verdict !== "pass" && verdict !== "revise" && verdict !== "block") throw new Error("verdict must be pass, revise or block");
}

/** Declared independence plus refusal of any recorded author identity. */
export function assertIndependentOf(reviewer: NativePrebuildReview["reviewer"], authors: string[]): void {
  if (authors.includes(reviewer.sessionId)) throw new Error(`Reviewer session ${reviewer.sessionId} is a recorded author of this work`);
  if (authors.length && !authors.includes(reviewer.plannerSessionId)) {
    throw new Error(`plannerSessionId must name the recorded author (${authors.join(", ")})`);
  }
}

function review(value: JsonRecord, request: ObservationRequest, file: string): { review: ProducerReview; limits: string[] } {
  const material = issueList(value.materialIssues, "materialIssues", true, request);
  assertVerdictConsistent(value.verdict, material.length);
  const limits = limitations(value.limitations);
  const noted: ProducerFinding[] = limits.map((message, index) => ({ code: `REVIEW_LIMITATION_${index + 1}`,
    severity: "info", lane: "review", message: message.slice(0, 2000), evidence: [file] }));
  const findings = [...issueList(value.findings, "findings", false, request) as ProducerFinding[], ...noted];
  return { limits, review: validateProducerReview({ schemaVersion: 1, stage: request.stage, verdict: value.verdict,
    summary: stringValue(value.summary, "summary", 2000), materialIssues: material as ProducerMaterialIssue[], findings }, request.stage) };
}

/** Parse the critic's file strictly; nothing missing is defaulted and no judgment is added. */
export function readObservations(request: ObservationRequest): Observations {
  const file = canonicalInput(request.file, "Observations file"), observed = readCutPreviewObject(file);
  const value = objectValue(observed.value, "observations");
  exactKeys(value, [...COMMON, ...ROLE_KEYS[request.kind]], [...COMMON, ...ROLE_KEYS[request.kind]], "observations");
  if (value.schemaVersion !== OBSERVATION_SCHEMA || value.kind !== request.kind) {
    throw new Error(`Observations must be ${request.kind} schema ${OBSERVATION_SCHEMA}; re-resolve the role packet for a current draft`);
  }
  if (sha256(value.rolePacketSha256, "rolePacketSha256") !== request.packet.sha256) {
    throw new Error("Observations were written for a different role packet (rolePacketSha256 mismatch)");
  }
  const reviewer = reviewIdentity(value.reviewer);
  assertIndependentOf(reviewer, request.packet.authorSessionIds);
  const judged = review(value, request, file);
  return { file: { path: file, sha256: observed.sha256 }, value, reviewer, coverage: reviewCoverage(value.coverage),
    review: judged.review, limitations: judged.limits };
}

/** Observations file, role packet, then critic-listed files: canonical, single-link and hash-bound.
 * Files under `forbiddenRoots` are refused (motion evidence under the engine would change export unit hashes). */
export function bindEvidence(observations: Observations, packet: RolePacket,
  forbiddenRoots: string[] = []): NativePrebuildReviewBinding[] {
  const listed = observations.value.evidence;
  if (!Array.isArray(listed)) throw new Error("evidence must be an array of {path, sha256?}");
  const rows: NativePrebuildReviewBinding[] = [observations.file, { path: packet.path, sha256: packet.sha256 }];
  for (const [index, item] of listed.entries()) {
    const row = objectValue(item, `evidence[${index}]`);
    exactKeys(row, ["path", "sha256"], ["path"], `evidence[${index}]`);
    const file = canonicalInput(stringValue(row.path, `evidence[${index}].path`, 4096), `evidence[${index}]`);
    const root = forbiddenRoots.find(directory => file.startsWith(`${directory}${path.sep}`));
    if (root) {
      throw new Error(`evidence[${index}] ${file} is inside the engine (${root}); the exporter pins motion evidence, so it `
        + "would change the preview dependency hashes at export. Cite a copy outside the repository or omit it.");
    }
    const hash = evidenceHash(file, index);
    if (row.sha256 !== undefined && sha256(row.sha256, `evidence[${index}].sha256`) !== hash) {
      throw new Error(`evidence[${index}] changed after the critic recorded its hash: ${file}`);
    }
    if (!rows.some(existing => existing.path === file)) rows.push({ path: file, sha256: hash });
  }
  if (rows.length > EVIDENCE_LIMIT) throw new Error(`At most ${EVIDENCE_LIMIT - 2} evidence files can be listed`);
  return rows;
}

function evidenceHash(file: string, index: number): string {
  try { return observeCutPreviewFile(file, 256 * 1024 ** 2).sha256; } catch (error) {
    throw new Error(`evidence[${index}] ${file} cannot be bound by the review reader (a linked, empty or special file `
      + `is refused): ${error instanceof Error ? error.message : String(error)}`);
  }
}

function boundHash(packet: RolePacket, evidence: NativePrebuildReviewBinding[], file: string): string | undefined {
  return packet.artifacts.find(row => row.path === file)?.sha256 ?? packet.declaredMedia.find(row => row.path === file)?.sha256
    ?? evidence.find(row => row.path === file)?.sha256;
}

/** The critic's typed entries, each bound to bytes the packet froze or declared or to a listed evidence file.
 * A stated hash that differs from those bytes inspected an older or different artifact and is refused. */
export function bindInspection(observations: Observations, packet: RolePacket, evidence: NativePrebuildReviewBinding[]): Inspection {
  const value: Inspection = { schemaVersion: 1, entries: inspectionEntries(observations.value.inspection, "inspection"),
    approves: approvals(observations.value.approves, "approves") };
  value.entries.forEach((row, index) => {
    const bound = boundHash(packet, evidence, row.artifact.path);
    if (!bound) {
      throw new Error(`inspection[${index}] ${row.artifact.path} is neither frozen in the role packet nor listed in evidence; `
        + "bind the exact artifact you inspected");
    }
    if (bound !== row.artifact.sha256) {
      throw new Error(`Stale inspection: inspection[${index}] names sha256 ${row.artifact.sha256.slice(0, 12)} for `
        + `${row.artifact.path}, but this review binds ${bound.slice(0, 12)}; an older or different artifact cannot support it`);
    }
  });
  return value;
}

/** Every frame-located material issue or finding needs a frame inside its range observed with the claim's own
 * modality: looked at (stills or playback) for a visual or motion claim, heard for an audio-lane claim. */
export function assertClaimsObserved(observations: Observations, inspection: Inspection, targets: ReviewTarget[]): void {
  for (const key of ["materialIssues", "findings"] as const) {
    (observations.value[key] as JsonRecord[]).forEach((row, index) => {
      if (row.frames !== undefined) {
        assertRangeObserved(inspection, targets, { range: row.frames as [number, number], label: `${key}[${index}]`,
          kinds: claimKinds(row.lane) });
      }
    });
  }
}

/** Provenance and approved-content blocks every typed record carries. The bound shared evidence must still be
 * current; the packet's given block must still be what the batch authority's current approval yields (engine
 * re-check); and the claimed playback and listening must fit between packet resolution and this submission, on the
 * batch clock for a batch-bound packet. */
export function recordBlocks(observations: Observations, packet: RolePacket, inspection: Inspection,
  program: { targets: ReviewTarget[]; fps: number }) {
  recheckSharedEvidence(packet.sharedEvidence);
  const verdict = String(observations.review.verdict), answered = approvedContentBlock(packet.given, observations.value, verdict);
  const current = currentGiven(packet), approvedContent = approvedContentBlock(current.given, observations.value, verdict);
  if (canonicalJson(answered) !== canonicalJson(approvedContent)) {
    throw new Error("This role packet's given block is no longer what the batch authority's current approval yields for "
      + "its plan (the approval changed, a batch now holds the source, or the packet was edited); re-resolve the role packet");
  }
  const submission = submissionBlock(packet, new Date(), current.batchClock);
  assertPlausibleTiming(inspection, { ...program, elapsedSeconds: submissionSeconds(submission) });
  return { submission, approvedContent };
}

/** Record a batch-bound record's submission in its batch trail before publishing it: the record's canonical SHA-256
 * (a motion bundle's own row) at the submission time it states. Gate readers and check-final require that event;
 * an unbound record has no batch clock and records nothing. A publish that then fails leaves an event naming bytes
 * no file holds, which admits nothing. */
export function recordSubmission(packet: RolePacket, submission: Submission, record: JsonRecord): void {
  recordSubmitted(packet, recordDigest(record), submission.timing);
}
