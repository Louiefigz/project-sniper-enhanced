/** Actual service/final-history/result readers over TEMP metadata; readiness, native and claim admission remain TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import childProcess from "node:child_process";
import { randomUUID, createHash } from "node:crypto";
import type { TestContext } from "node:test";
import { SOURCE_COLOR_READBACK_STAGES } from "@/lib/producer/contracts/guided-opening-result-v2";
import { canonicalJson } from "../auto-edit-hash";
import { saveHumanCutJobSnapshot } from "../human-cut-acceptance-store";
import { readHistoricalOpeningCleanup } from "../guided-opening-cleanup-store";
import { readHeldSourceColorOpeningResult } from "../guided-source-color-opening-result";
import { sourceColorReadbackDependencies, verifyCleanedSourceColorOpeningMediaUnderLease } from "../guided-source-color-readback";
import { readSourceColorReadbackHistory, type SourceColorReadbackHistoryInput,
  type SourceColorReadbackHistoryReference } from "../guided-source-color-readback-history";
import { sourceColorReadIntegrationFixture, type SourceColorReadIntegrationFixture } from "./_guided-source-color-read-integration-fixture";

/** This is only a synthetic native reply; the actual service must authenticate and publish it. */
function nativeReply(f: SourceColorReadIntegrationFixture) {
  const { executionClaimSha256, ...completion } = f.media.completion;
  return { ...completion, kind: "guided-opening-media-readback", status: "verified", claimSha256: executionClaimSha256,
    scope: "exact-source-color-held-private-media-not-opening-or-delivery-approval", elapsedMs: 0,
    stages: SOURCE_COLOR_READBACK_STAGES.map(stage => ({ stage, status: "complete", elapsedMs: 0 })),
    sourceColorRecordsReplayed: true, basePictureConsumptionVerified: true, gamutMeasured: false, gradeApplied: false, colorQualified: false,
    processGroupAndDockerCleanup: "requires-separate-owned-server-observation", currentJournalAndLease: "requires-separate-owned-server-observation" };
}

/** Borrow one explicit TEST verification allowance; never start a native child. */
async function verify(f: SourceColorReadIntegrationFixture) {
  const end = performance.now() + 30_000, reply = nativeReply(f), counts = { native: 0 };
  const verified = await verifyCleanedSourceColorOpeningMediaUnderLease({ dir: f.cleanup.job.ctx.dir, lease: f.projectLease,
    expectedCleanupHash: f.cleanup.cleanupHash, remainingMs: () => Math.max(0, Math.floor(end - performance.now())) }, {
    readiness: () => undefined as unknown as ReturnType<typeof sourceColorReadbackDependencies.readiness>, tools: () => f.media.tools.read,
    invoke: async input => {
      input.remainingMs(); input.beforeSpawn?.(); counts.native++;
      const result = { stdout: JSON.stringify(reply), stderr: "TEST no native source/media replay" };
      input.afterSettled?.({ ...result, timedOut: false, groupStopped: true, forcedStop: false }); return result;
    },
  });
  return { verified, counts };
}

/** No full selection fact is minted here; these exact references merely name the actual emitted records. */
function references(verified: Awaited<ReturnType<typeof verify>>["verified"]): SourceColorReadbackHistoryReference {
  const { observed: c, selected: s, receipt, output } = verified, held = c.held;
  return { schemaVersion: 2, beforeJournalHash: c.sha256, cleanupHash: c.cleanupHash, claimHash: held.claimHash,
    executionId: held.claim.executionId, inputSha256: held.claim.inputSha256, executionInputHash: held.claim.executionInputHash,
    outputRoot: held.claim.outputRoot, readbackDirectory: path.basename(path.dirname(receipt.path)),
    readbackStartSha256: String(receipt.value.startSha256), readbackOutputSha256: output.sha256, readbackReceiptSha256: receipt.sha256,
    mediaResultSha256: s.record.sha256, receiptHash: s.completion.receiptHash, clockHash: held.claim.clockHash,
    generationStartedAt: held.claim.generationStartedAt, selectionQualifiedAt: new Date().toISOString() };
}

/** The actual saved final snapshot is read independently; no sealed live capability is cloned or rebaselined. */
export async function sourceColorReadbackHistoryFixture(t: TestContext) {
  t.mock.method(childProcess, "spawn", () => { throw new Error("TEST forbids native children"); });
  const f = await sourceColorReadIntegrationFixture(t), { verified, counts } = await verify(f), ref = references(verified);
  saveHumanCutJobSnapshot(verified.observed.job.ctx.dir, verified.observed);
  const cleanup = readHistoricalOpeningCleanup(verified.observed.job.ctx.dir, ref.beforeJournalHash);
  const selected = readHeldSourceColorOpeningResult({ held: cleanup.held, guard: () => {} });
  const callbacks = { guard: () => {} }, calls = { guard: 0 };
  const input: SourceColorReadbackHistoryInput = { cleanup, selected, reference: ref, guard: () => { calls.guard++; callbacks.guard(); } };
  const directory = path.dirname(verified.receipt.path), files = { start: path.join(directory, "start.json"),
    output: path.join(directory, "output.json"), verified: path.join(directory, "verified.json") };
  return { original: f, verified, counts, input, callbacks, calls, files, root: f.staging.root,
    read: () => readSourceColorReadbackHistory(input) };
}
export type HistoryFixture = Awaited<ReturnType<typeof sourceColorReadbackHistoryFixture>>;
export type HistoryFileRole = keyof HistoryFixture["files"];

/** Mutation permission is exactly one of the three already-published regular single-link TEST readback files. */
export function historyFixtureFile(f: HistoryFixture, role: HistoryFileRole): string {
  const file = f.files[role], root = fs.realpathSync(f.root);
  assert(file.startsWith(root + path.sep)); assert.equal(fs.realpathSync(file), file);
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  return file;
}

/** Same bytes still replace the original inode; this never touches code, tools, sources or other dependencies. */
export function replaceHistoryFile(f: HistoryFixture, role: HistoryFileRole): void {
  const file = historyFixtureFile(f, role), temporary = path.join(path.dirname(file), `TEST-history-${randomUUID()}.json`);
  fs.writeFileSync(temporary, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}

/** Deliberately forged raw reference tests semantic refusal, not merely an easy stale-hash failure. */
export function rewriteHistoryRecord(f: HistoryFixture, role: HistoryFileRole, change: (value: Record<string, unknown>) => void): void {
  const file = historyFixtureFile(f, role), value = JSON.parse(fs.readFileSync(file, "utf8")); change(value);
  const bytes = canonicalJson(value); fs.writeFileSync(file, bytes);
  const key = { start: "readbackStartSha256", output: "readbackOutputSha256", verified: "readbackReceiptSha256" } as const;
  f.input.reference[key[role]] = createHash("sha256").update(bytes).digest("hex");
}
