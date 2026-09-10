/** TEST-only exact original-claim recovery. This path cannot run an observation. */
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { pythonInterpreter } from "../../../src/app/api/_lib/spawn-python";
import { runCutPreviewProcess, CutPreviewProcessError } from "../../../src/app/api/producer/auto-edit/cut-preview-process";
import { readBytes, sha } from "../../../src/app/api/producer/studio/import/files";
import { checkTime, object, privateDirectory, readRecord, SHA } from "../../../src/lib/server/grade-observation-store";
import { acquireV2Scope } from "./live_grade_v2_lifecycle";
import { checkPinsV2, hashV2, readLifecycle, requireStoppedV2, runtimeV2 } from "./live_grade_v2_lifecycle";
import { writeHeldRecord } from "./live_grade_v2_finalization";

const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/u;
function exactDirectory(raw: string, jobId: string): string {
  if (!path.isAbsolute(raw) || fs.realpathSync(raw) !== raw || !raw.startsWith("/private/tmp/sniper-grade-v2-live-")
      || path.basename(raw) !== "producer" || path.basename(path.dirname(raw)) !== "synthetic" || !UUID.test(jobId))
    throw new Error("Exact original TEST producer/job required for cleanup");
  privateDirectory(raw);
  return privateDirectory(path.join(raw, ".sniper-grade-observations", jobId));
}
function heldClaim(file: string, dir: string, jobId: string) {
  const raw = readBytes(file, 64 * 1024), row = object(JSON.parse(raw.toString("utf8")));
  if (Object.keys(row).sort().join() !== "dir,jobId,lifecycleSha256,requestDigest" || row.dir !== dir || row.jobId !== jobId
      || typeof row.requestDigest !== "string" || !SHA.test(row.requestDigest)
      || typeof row.lifecycleSha256 !== "string" || !SHA.test(row.lifecycleSha256)) throw new Error("Different or malformed original TEST claim");
  return { row, raw, sha256: sha(raw) };
}
export function cleanupResult(stdout: string, name: string): Record<string, unknown> {
  if (Buffer.byteLength(stdout) > 16 * 1024) throw new Error("Cleanup result exceeds bound");
  const value = object(JSON.parse(stdout)), state = value.state;
  const keys = ["state", "containerName", "cleanupVerified", "intentSha256", "removal"];
  if (Object.keys(value).sort().join() !== keys.sort().join() || state !== "reconciled"
      || value.containerName !== name || value.cleanupVerified !== true) throw new Error("Unverified cleanup-only result");
  if ((value.intentSha256 !== null && (typeof value.intentSha256 !== "string" || !SHA.test(value.intentSha256)))
      || object(value.removal).containerRef !== name || object(value.removal).canonicalAbsenceProved !== true)
    throw new Error("Exact Docker name absence is unproved");
  return value;
}

/** Only an actual fresh cleanup return can call this final guarded removal. */
export function finishV2Recovery(claim: { path: string; sha256: string },
  retained: { path: string; sha256: string }[], guard: () => void): void {
  guard();
  for (const file of retained) if (hashV2(file.path) !== file.sha256) throw new Error("Actual cleanup publication changed");
  if (hashV2(claim.path) !== claim.sha256) throw new Error("Original recovery claim changed");
  guard();
  fs.unlinkSync(claim.path);
}
function retainFailure(attempt: string, error: unknown, started: bigint): void {
  const processFailure = error instanceof CutPreviewProcessError ? { exitCode: error.exitCode,
    details: { ...error.details, stdout: error.details.stdout.slice(0, 16000), stderr: error.details.stderr.slice(0, 16000) } } : null;
  try {
    writeHeldRecord(path.join(attempt, "failed.json"), { error: String(error), processFailure, ownershipRetained: true,
      elapsedMs: Number(process.hrtime.bigint() - started) / 1e6, noApproval: true });
  } catch (retentionError) { throw new AggregateError([error, retentionError], "Cleanup failed; failure retention also failed"); }
}

/** Current pins/controls and actual group absence are rechecked, never source media. */
export async function recoverV2Owner(raw: string, jobId: string): Promise<Record<string, unknown>> {
  const started = process.hrtime.bigint(), deadline = started + BigInt(95_000_000_000);
  const directory = exactDirectory(raw, jobId), scope = acquireV2Scope(raw, true);
  const attempt = path.join(directory, "TEST-recovery-" + randomUUID());
  try {
    fs.mkdirSync(attempt, { mode: 0o700 });
    const claimPath = path.join(scope.resource, "active.json"), claim = heldClaim(claimPath, raw, jobId);
    const life = readLifecycle(directory, String(claim.row.lifecycleSha256));
    const input = readRecord(path.join(directory, "input.json"));
    if (life.resource !== scope.resource || life.root !== fs.realpathSync(process.cwd()) || life.inputSha256 !== claim.row.requestDigest
        || input.ownerPid !== life.supervisor.pid || input.jobId !== jobId || input.producerDir !== raw)
      throw new Error("Recovery differs from original supervisor input/claim");
    const guard = () => {
      scope.guard(); checkTime(deadline); requireStoppedV2(life); checkPinsV2(life.pins);
      if (JSON.stringify(runtimeV2(life.root)) !== JSON.stringify(life.runtime)
          || hashV2(path.join(directory, "input.json")) !== life.inputSha256
          || !readBytes(claimPath, 64 * 1024).equals(claim.raw)) throw new Error("Recovery controls or exact active claim changed");
      readLifecycle(directory, String(claim.row.lifecycleSha256));
      requireStoppedV2(life); scope.guard(); checkTime(deadline);
    };
    guard();
    const timeoutMs = Math.min(90000, Math.floor(Number(deadline - process.hrtime.bigint()) / 1e6) - 1000);
    if (timeoutMs < 1) throw new Error("Cleanup-only budget exhausted before worker");
    const python = pythonInterpreter(), script = path.join(life.root, "scripts/producer/tests/live_grade_v2_launch.py");
    if (python !== life.python) throw new Error("Original logical venv invocation path changed");
    const command = { command: python, args: ["-I", "-S", "-B", script, directory, String(claim.row.lifecycleSha256), "--cleanup", String(timeoutMs)],
      cwd: life.root, env: { ...process.env }, timeoutMs };
    writeHeldRecord(path.join(attempt, "intent.json"), { kind: "TEST-cleanup-only", originalDeadlineNs: life.deadlineNs,
      claimSha256: claim.sha256, lifecycleSha256: claim.row.lifecycleSha256, timeoutMs, command: [python, ...command.args] });
    const output = await runCutPreviewProcess(command);
    const outcomePath = path.join(attempt, "actual-return.json"), outcomeSha = writeHeldRecord(outcomePath, output);
    const result = cleanupResult(output.stdout, life.containerName);
    const record = { status: "cleanup-only", result, originalDeadlineNs: life.deadlineNs, inputSha256: life.inputSha256,
      lifecycleSha256: claim.row.lifecycleSha256, claimSha256: claim.sha256, elapsedMs: Number(process.hrtime.bigint() - started) / 1e6,
      gradeApplicable: false, deliveryApproved: false, selection: "not-observation-or-retry" };
    const recordPath = path.join(attempt, "candidate.json"), recordSha = writeHeldRecord(recordPath, record);
    finishV2Recovery({ path: claimPath, sha256: claim.sha256 },
      [{ path: outcomePath, sha256: outcomeSha }, { path: recordPath, sha256: recordSha }], guard);
    return record;
  } catch (error) {
    retainFailure(attempt, error, started);
    throw error;
  } finally { scope.release(); }
}
