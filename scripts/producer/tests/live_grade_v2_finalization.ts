/** TEST-only live-return cleanup and finalization. Stored records are not replay authority. */
import fs from "node:fs";
import path from "node:path";
import { canonicalJsonSha256 } from "../../../src/lib/server/auto-edit-hash";
import { readBytes, sha } from "../../../src/app/api/producer/studio/import/files";
import { checkTime, object, SHA, writeRecord } from "../../../src/lib/server/grade-observation-store";
import type { GradeProcessResult } from "../../../src/lib/server/grade-observation-process";
import { assertLiveReturn, PROFILE, PROJECT_POLICY, type v2Input } from "./live_grade_v2_contract";

export interface V2LiveReturn {
  held: GradeProcessResult;
  closed: { code: number | null; signal: string | null; absent: boolean };
  pid: number | null;
  stdout: string;
  stderr: string;
}
interface HeldFile { path: string; sha256: string }
export interface V2Finalization {
  live: V2LiveReturn;
  input: HeldFile;
  result: HeldFile;
  claim: HeldFile;
  candidate?: HeldFile;
  deadline: bigint;
}
export interface V2FinalChecks {
  ownership: () => void;
  parents: () => void;
  proof: () => void;
  readHash?: (file: string) => string;
  time?: (deadline: bigint) => void;
}
const hash = (file: string): string => sha(readBytes(file, 8 * 1024 * 1024));

/** Bind intended serialized bytes before publication, not a post-write new SHA. */
export function writeHeldRecord(file: string, value: unknown): string {
  const expected = sha(`${JSON.stringify(value, null, 1)}\n`);
  if (writeRecord(file, value) !== expected || hash(file) !== expected)
    throw new Error("New TEST record differs from intended publication bytes");
  return expected;
}

/** Cleanup may accept a normal failed return, never a partial/interrupted pipe. */
export function assertCleanupReturn(live: V2LiveReturn): void {
  const { held, closed } = live;
  if (!["complete", "failed"].includes(held.status) || !held.cleanupVerified || held.failure
      || !held.handshake || !held.resultSha256 || !SHA.test(held.resultSha256)
      || !Number.isSafeInteger(live.pid) || Number(live.pid) < 1
      || closed.code !== 0 || closed.signal !== null || closed.absent !== true)
    throw new Error("Live normal return, exact result and proven group/Docker cleanup are required");
}

/** Read the exact live-returned raw bytes once; do not reopen for JSON parsing. */
export function readCleanupProof(directory: string, input: ReturnType<typeof v2Input>,
  inputSha: string, live: V2LiveReturn): Record<string, unknown> {
  assertCleanupReturn(live);
  const raw = readBytes(path.join(directory, "observation.json"), 8 * 1024 * 1024);
  if (sha(raw) !== live.held.resultSha256) throw new Error("Actual live cleanup result bytes changed");
  const value = object(JSON.parse(raw.toString("utf8"))), { artifactHash, ...body } = value;
  const required = ["schemaVersion", "policy", "profile", "limits", "jobId", "inputSha256", "status",
    "cleanupVerified", "cleanupMs", "workerPhaseMs", "replayMs", "gradeApplicable", "deliveryApproved",
    "elapsedMs", "artifactHash"];
  const optional = ["errors", "parentsSha256", "implementation", "observation"];
  if (required.some(key => !(key in value)) || Object.keys(value).some(key => ![...required, ...optional].includes(key))
      || artifactHash !== canonicalJsonSha256(body) || value.schemaVersion !== 2 || value.policy !== PROJECT_POLICY
      || value.profile !== PROFILE || value.jobId !== input.jobId || value.inputSha256 !== inputSha
      || value.status !== live.held.status || value.cleanupVerified !== true
      || value.gradeApplicable !== false || value.deliveryApproved !== false)
    throw new Error("Live cleanup result is not bound to the original V2 job/input");
  if (value.status === "failed" && (!Array.isArray(value.errors) || "observation" in value))
    throw new Error("Failed cleanup result has unsupported shape");
  if (hash(path.join(directory, "input.json")) !== inputSha) throw new Error("Original cleanup input changed");
  return value;
}

function exact(file: HeldFile, checks: V2FinalChecks): void {
  if (!SHA.test(file.sha256) || (checks.readHash ?? hash)(file.path) !== file.sha256)
    throw new Error(`Held finalization bytes changed: ${path.basename(file.path)}`);
}

/** All final byte reads precede the last parent/lease/time observations. */
function terminal(input: V2Finalization, checks: V2FinalChecks, success: boolean): void {
  assertCleanupReturn(input.live);
  if (input.result.sha256 !== input.live.held.resultSha256) throw new Error("Finalization result differs from live return");
  checks.ownership(); (checks.time ?? checkTime)(input.deadline);
  checks.proof();
  if (input.candidate) exact(input.candidate, checks);
  exact(input.input, checks); exact(input.result, checks);
  exact(input.claim, checks); // The last read may consume time or reveal a parent mutation.
  if (success) checks.parents();
  checks.ownership(); (checks.time ?? checkTime)(input.deadline);
  // Cooperating writers are excluded by both still-held leases. No callback or
  // byte-reading work follows the final guards before removing this exact claim.
  fs.unlinkSync(input.claim.path);
}

export function finalizeV2Success(input: V2Finalization, checks: V2FinalChecks): void {
  assertLiveReturn(input.live.held, input.live.closed);
  if (!input.candidate) throw new Error("Exact TEST candidate bytes must be held before success");
  terminal(input, checks, true);
}

/** Separate, bounded metadata cleanup credit can never grant generation success. */
export function releaseV2Failed(input: V2Finalization, checks: V2FinalChecks,
  reason: string): void {
  checks.ownership(); (checks.time ?? checkTime)(input.deadline); checks.proof();
  writeHeldRecord(path.join(path.dirname(input.input.path), "TEST-cleanup-release-candidate.json"), {
    schemaVersion: 1, status: "cleanup-only-candidate", reason: reason.slice(0, 2000),
    inputSha256: input.input.sha256, actualResultSha256: input.result.sha256,
    claimSha256: input.claim.sha256, selection: "not-success-or-approval", noApproval: true,
  });
  // This marker alone is not authority. Replay cannot call this function from
  // disk-only facts; the caller must retain the actual live return and leases.
  terminal({ ...input, candidate: undefined }, checks, false);
}
