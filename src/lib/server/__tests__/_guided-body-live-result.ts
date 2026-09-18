/** TEST-only final observations. Not production source authority, listening or delivery approval. */
import assert from "node:assert/strict";
import { lstatSync, readdirSync } from "node:fs";
import path from "node:path";
import { observeCutPreviewFile, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { exactKeys, objectValue } from "@/lib/producer/contracts/validation";
import type { GuidedBodyCandidateV1, GuidedBodyStatusV1 } from "@/lib/producer/contracts/guided-body-command-v1";
import { bodyLiveObserverTimeout, retainBodyLive, type BodyLiveLog } from "./_guided-body-live-support";

const REQUIRED_PASSES = ["duration", "audio_decode_complete", "loudness_integrated", "loudness_true_peak",
  "format_resolution", "format_vcodec", "format_profile", "format_pix_fmt", "format_cfr", "format_faststart",
  "format_acodec", "format_arate", "format_achannels", "audio_av_timing", "final_identity"];

/** A failed/import-broken/timed-out command is not a proved intentional conflict rejection. */
export function assertBodyLiveConflict(failure: unknown): void {
  assert.ok(failure instanceof CutPreviewProcessError, "Expected actual bounded CLI failure provenance");
  assert.ok(Number.isInteger(failure.exitCode) && Number(failure.exitCode) > 0 && Number(failure.exitCode) <= 255);
  assert.equal(failure.details.groupStopped, true); assert.equal(failure.details.forcedStop, false);
  assert.equal(failure.details.timedOut, false); assert.equal(failure.details.stdout, "");
  assert.ok(Buffer.byteLength(failure.details.stderr, "utf8") <= 16 * 1024);
  const row = objectValue(JSON.parse(failure.details.stderr.trim()), "TEST actual conflict denial");
  exactKeys(row, ["ok", "code", "error"], ["ok", "code", "error"], "TEST conflict denial");
  assert.equal(row.ok, false); assert.equal(row.code, "BODY_REQUEST_CONFLICT");
  assert.ok(typeof row.error === "string" && row.error.length > 0 && row.error.length <= 4000);
}

/** All lineage fields must remain the fresh candidate's, not just a matching media filename. */
export function assertBodyLiveStatus(status: GuidedBodyStatusV1, result: GuidedBodyCandidateV1): void {
  for (const key of ["state", "requestId", "executionId", "admissionClaimHash", "activationHash",
    "cleanupHash", "candidateHash", "journalHash", "bodyApproved", "deliveryApproved"] as const) {
    assert.equal(status[key], result[key], key);
  }
  assert.deepEqual(status.candidate, result.candidate);
  assert.equal(status.sourceFreshness, "not-observed-by-status");
}

/** Small stat inventory for replay non-mutation, explicitly NOT a whole-artifact byte proof. */
export function bodyLiveMetadataInventory(root: string) {
  const result: Record<string, Record<string, string>> = {}, pending = [root];
  while (pending.length) {
    const file = pending.pop()!, info = lstatSync(file, { bigint: true });
    if (info.isSymbolicLink() || (!info.isFile() && !info.isDirectory())) throw new Error("TEST replay inventory refuses links/special files");
    if (Object.keys(result).length >= 8192) throw new Error("TEST replay metadata inventory exceeded8192entries");
    result[path.relative(root, file) || "."] = { kind: info.isDirectory() ? "directory" : "file",
      device: String(info.dev), inode: String(info.ino), size: String(info.size),
      mtimeNs: String(info.mtimeNs), ctimeNs: String(info.ctimeNs), links: String(info.nlink) };
    if (info.isDirectory()) pending.push(...readdirSync(file).map((name) => path.join(file, name)));
  }
  return result;
}

/** Keep material warnings visible; zero deterministic failures is not subjective quality equivalence. */
export function bodyLiveAuditSummary(audit: Record<string, unknown>, expected: { path: string; sha256: string; requireCaptions?: boolean }) {
  assert.equal(audit.final, expected.path); assert.equal(audit.finalSha256, expected.sha256);
  assert.equal(audit.exitCode, 0); assert.ok(audit.overall === "pass" || audit.overall === "warn");
  assert.ok(Array.isArray(audit.checks) && audit.checks.length > 0);
  const checks = audit.checks.map((row) => objectValue(row, "TEST actual body audit check"));
  assert.equal(new Set(checks.map((row) => row.name)).size, checks.length, "Actual checks cannot duplicate names");
  for (const name of REQUIRED_PASSES) assert.equal(checks.find((row) => row.name === name)?.status, "pass", name);
  if (expected.requireCaptions) assert.equal(checks.find((row) => row.name === "caption_authority")?.status, "pass", "requested full-program caption authority");
  const counts = Object.fromEntries(["pass", "warn", "fail"].map((status) => [status, checks.filter((row) => row.status === status).length]));
  assert.deepEqual(audit.counts, counts); assert.equal(counts.fail, 0);
  assert.equal(counts.pass + counts.warn, checks.length);
  assert.equal(audit.overall, counts.warn ? "warn" : "pass");
  const audio = objectValue(audit.audioDelivery, "TEST body final audio observation");
  assert.equal(audio.audioDecodeSucceeded, true);
  return { counts, warnings: checks.filter((row) => row.status === "warn"), audioDelivery: audio,
    fullVideoSubjectivelyReviewed: false, listeningPerformed: false, creativeQualityQualified: false };
}

/** Reobserve streamed final bytes and the actual report at the exact newly returned private path. */
export function observeBodyLiveCandidate(input: {
  log: BodyLiveLog; dir: string; requestId: string; executionId: string;
  candidate: { path: string; sha256: string }; generationStartedAt: string; requireCaptions?: boolean;
}) {
  const { log, dir, candidate, requestId, executionId } = input;
  assert.equal(path.dirname(path.dirname(dir)), log.workspace);
  const execution = path.join(dir, "guided-v2-operations", requestId, "executions", executionId);
  assert.equal(candidate.path, path.join(execution, "body-media-output", "body-candidate", "final.mp4"));
  const guard = () => { bodyLiveObserverTimeout(input.generationStartedAt); };
  const file = observeCutPreviewFile(candidate.path, 2 * 1024 ** 3, false, guard);
  assert.equal(file.sha256, candidate.sha256);
  const report = readCutPreviewObject(path.join(path.dirname(candidate.path), "audit_report.json"));
  const summary = bodyLiveAuditSummary(report.value, { ...candidate, requireCaptions: input.requireCaptions });
  const retained = { scope: "TEST-only-streamed-private-final-and-retained-audit-not-human-or-delivery-approval",
    candidate: { ...candidate, sizeBytes: file.sizeBytes }, auditReportSha256: report.sha256, ...summary };
  retainBodyLive(log, "body-actual-final-observation.json", retained);
  return { execution, observation: retained };
}
