/** Submission-time re-check of the shared source evidence a role packet bound (unit B1).
 * One implementation of the rule: the engine's own `context.py --evidence-check`, which re-observes the sealed record,
 * its manifest, transcripts and bound files, its recorded location and whether a later version supersedes it. The
 * review is refused unless that check reports the same record the packet bound. */
import { spawnSync } from "node:child_process";
import path from "node:path";
import { pythonInterpreter, SCRIPTS_DIR } from "@/app/api/_lib/spawn-python";
import { objectValue, sha256, stringValue, type JsonRecord } from "@/lib/producer/contracts/validation";

const CONTEXT = path.join(SCRIPTS_DIR, "producer", "context.py");
const TIMEOUT_MS = 120_000;

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

/** Refuse when the evidence the packet bound is no longer the current, located, unsuperseded record. */
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
