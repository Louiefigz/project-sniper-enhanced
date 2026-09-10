/** Actual service/selection/CAS/history over inert TEMP bytes; initial admission/readiness/native remain TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import childProcess from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { SOURCE_COLOR_READBACK_STAGES } from "@/lib/producer/contracts/guided-opening-result-v2";
import { verifyCleanedSourceColorOpeningMediaUnderLease, sourceColorReadbackDependencies } from "../guided-source-color-readback";
import { sourceColorSelectionDependencies } from "../guided-source-color-selection";
import { selectVerifiedOpeningMediaUnderLease } from "../guided-opening-selection";
import { autoEditJobPath } from "../auto-edit-job-persistence";
import { cleanupPendingCommitFixture } from "./_guided-source-color-cleanup-pending-commit-fixture";
import { sourceColorReadIntegrationFixture, type SourceColorReadIntegrationFixture } from "./_guided-source-color-read-integration-fixture";

/** Physical files only support metadata stat checks; their contents are not playable media. */
function picture(f: ReturnType<typeof cleanupPendingCommitFixture>) {
  const output = f.input.held.claim.outputRoot; assert(output.startsWith(fs.realpathSync(f.staging.root) + path.sep));
  fs.mkdirSync(output, { recursive: true, mode: 0o700 }); assert.equal(fs.realpathSync(output), output);
  const rows = [30, 60].map((frames, index) => {
    const file = path.join(output, `${index ? "review" : "core"}.mp4`), bytes = Buffer.from(`TEST inert ${frames}-frame metadata only`);
    fs.writeFileSync(file, bytes, { flag: "wx", mode: 0o644 }); fs.chmodSync(file, 0o644);
    return { path: file, sha256: createHash("sha256").update(bytes).digest("hex"), sizeBytes: bytes.length,
      startFrame: 0, endFrameExclusive: frames, startSample: 0, endSampleExclusive: frames / 30 * 48048 };
  });
  return { authority: { frameRate: "30000/1001", target: { width: 160, height: 90 },
    core: { startFrame: 0, endFrameExclusive: 30 }, review: { startFrame: 0, endFrameExclusive: 60 } },
  media: { core: rows[0], review: rows[1] } };
}

function nativeReply(f: SourceColorReadIntegrationFixture) {
  const { executionClaimSha256, ...completion } = f.media.completion;
  return { ...completion, kind: "guided-opening-media-readback", status: "verified", claimSha256: executionClaimSha256,
    scope: "exact-source-color-held-private-media-not-opening-or-delivery-approval", elapsedMs: 0,
    stages: SOURCE_COLOR_READBACK_STAGES.map(stage => ({ stage, status: "complete", elapsedMs: 0 })),
    sourceColorRecordsReplayed: true, basePictureConsumptionVerified: true, gamutMeasured: false, gradeApplied: false, colorQualified: false,
    processGroupAndDockerCleanup: "requires-separate-owned-server-observation", currentJournalAndLease: "requires-separate-owned-server-observation" };
}

/** The actual verifier and selector receive the exact same original lease and callback object. */
export async function sourceColorSelectionFixture(t: TestContext, original?: SourceColorReadIntegrationFixture) {
  t.mock.method(childProcess, "spawn", () => { throw new Error("TEST no native children"); });
  const f = original ?? await initialSelection(t);
  const callbacks = { remaining: () => {}, readiness: () => {} }, calls = { remaining: 0, native: 0 }, end = performance.now() + 30_000;
  const readback = { dir: f.cleanup.job.ctx.dir, lease: f.projectLease, expectedCleanupHash: f.cleanup.cleanupHash,
    remainingMs: () => { calls.remaining++; callbacks.remaining(); return Math.max(0, Math.floor(end - performance.now())); } };
  const verified = await verifyCleanedSourceColorOpeningMediaUnderLease(readback, {
    readiness: () => undefined as unknown as ReturnType<typeof sourceColorReadbackDependencies.readiness>, tools: () => f.media.tools.read,
    invoke: async input => {
      input.remainingMs(); input.beforeSpawn?.(); calls.native++;
      const result = { stdout: JSON.stringify(nativeReply(f)), stderr: "TEST native replay stub" };
      input.afterSettled?.({ ...result, timedOut: false, groupStopped: true, forcedStop: false }); return result;
    },
  });
  t.mock.method(sourceColorSelectionDependencies, "readiness", () => { callbacks.readiness(); });
  const input = { dir: readback.dir, lease: readback.lease, remainingMs: readback.remainingMs, verified };
  calls.remaining = 0;
  const files = { archive: f.recorded.fact.archive.path, result: f.media.file, output: verified.output.path,
    journal: autoEditJobPath(readback.dir), core: String((f.media.record.media as Record<string, Record<string, unknown>>).core.path) };
  return { ...f, verified, input, readback, callbacks, calls, files, select: () => selectVerifiedOpeningMediaUnderLease(input) };
}
export type SourceColorSelectionFixture = Awaited<ReturnType<typeof sourceColorSelectionFixture>>;

/** Preserve the historical default; callers may instead supply an already-original prepublication fixture. */
async function initialSelection(t: TestContext) {
  const initial = cleanupPendingCommitFixture(t);
  return sourceColorReadIntegrationFixture(t, initial, picture(initial));
}

/** Only explicitly named TEMP files, never code, installed tools or arbitrary held dependencies. */
export function replaceSelectionFixtureFile(f: SourceColorSelectionFixture, role: keyof SourceColorSelectionFixture["files"]): void {
  const file = f.files[role], root = fs.realpathSync(f.staging.root); assert(file.startsWith(root + path.sep));
  assert.equal(fs.realpathSync(file), file); assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const temporary = path.join(path.dirname(file), `TEST-selection-${randomUUID()}.json`);
  fs.writeFileSync(temporary, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}
