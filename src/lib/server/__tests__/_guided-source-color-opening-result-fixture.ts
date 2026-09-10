/** Actual stopped-ledger/result readers over TEMP metadata; initial claim/media provenance remains TEST-only.
 * No tool, source, source-color evidence file, worker, daemon, runtime admission or lease is used.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import type { TestContext } from "node:test";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { SOURCE_COLOR_READBACK_STAGES } from "@/lib/producer/contracts/guided-opening-result-v2";
import { canonicalJson, canonicalJsonSha256 } from "../auto-edit-hash";
import { writeGuidedObject } from "../guided-cut-v2-store";
import { openingProcessFixture } from "./_guided-opening-process-fixture";

/** Own exact role paths before any read; this fixture never targets code, sources or live resource markers. */
function fixtureStorage(f: ReturnType<typeof openingProcessFixture>) {
  const output = f.held.claim.outputRoot, inputPath = path.join(f.root, "media-input/input.json");
  fs.mkdirSync(path.dirname(inputPath), { mode: 0o700 }); fs.mkdirSync(output, { mode: 0o700 });
  fs.mkdirSync(path.join(output, "audio"), { mode: 0o700 });
  const resultPath = path.join(output, "media-result.json"), intentPath = path.join(f.root, "media-process-intent.json");
  const outcomePath = path.join(f.root, "media-process-result.json"), ledgerPath = path.join(f.root, "owned-process-ledger.media.jsonl");
  const journalPath = path.join(f.root, "TEST-held-journal.json");
  const allowed = new Set([inputPath, f.held.claimPath, resultPath, intentPath, outcomePath, ledgerPath, journalPath]);
  const target = (file: string) => {
    assert(allowed.has(file)); assert(file.startsWith(f.root + path.sep));
    assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
    if (!fs.existsSync(file)) return;
    const info = fs.lstatSync(file); assert(info.isFile()); assert.equal(info.nlink, 1); assert.equal(info.uid, process.getuid!());
    assert.equal(fs.realpathSync(file), file);
  };
  const write = (file: string, value: unknown) => { target(file); fs.writeFileSync(file, canonicalJson(value), { mode: 0o600 }); fs.chmodSync(file, 0o600); };
  return { output, inputPath, resultPath, intentPath, outcomePath, ledgerPath, journalPath, allowed, target, write };
}

/** Retain exact mutable TEST data before a real reader starts; fault writes use only its fixed leaf allowlist. */
export function sourceColorOpeningResultFixture(t: TestContext, version = 3) {
  const f = openingProcessFixture({ status: "complete", error: "" }, version); t.after(f.cleanup);
  const { output, inputPath, resultPath, intentPath, outcomePath, ledgerPath, journalPath, allowed, target, write } = fixtureStorage(f);
  const claim = f.held.claim;
  const input = { executionId: claim.executionId, executionInputHash: "b".repeat(64), TEST: "original input admission is stubbed" };
  write(inputPath, input); claim.inputPath = inputPath; claim.inputSha256 = canonicalJsonSha256(input);
  claim.executionInputHash = input.executionInputHash; write(f.held.claimPath, claim);
  f.held.claimSha256 = canonicalJsonSha256(claim); f.held.claimHash = f.held.claimSha256;
  const prior = readCutPreviewObject(path.join(f.held.job.ctx.dir, "human-cut-job-snapshots", `${f.intent.journalHash}.json`)).value;
  (prior.guidedHandoffV2 as Record<string, unknown>).openingExecutionClaimHash = f.held.claimHash;
  f.held.job.guidedHandoffV2!.openingExecutionClaimHash = f.held.claimHash;
  const priorHash = canonicalJsonSha256(prior), priorPath = path.join(f.held.job.ctx.dir, "human-cut-job-snapshots", `${priorHash}.json`);
  allowed.add(priorPath); write(priorPath, prior);
  Object.assign(f.intent, { claimHash: f.held.claimHash, inputSha256: claim.inputSha256, journalHash: priorHash });
  Object.assign(f.outcome, { claimHash: f.held.claimHash, inputSha256: claim.inputSha256, intentHash: canonicalJsonSha256(f.intent) });
  Object.assign(f.activation, { claimHash: f.held.claimHash, inputSha256: claim.inputSha256, beforeJournalHash: priorHash,
    intentSha256: canonicalJsonSha256(f.intent) });
  target(ledgerPath); fs.chmodSync(ledgerPath, 0o600);
  const evidence = { path: path.join(output, "source-color-evidence.json"), sha256: "c".repeat(64), sizeBytes: 128, receiptHash: "d".repeat(64) };
  const body: Record<string, unknown> = { schemaVersion: 2, kind: "guided-opening-media-result", status: "complete",
    scope: "private-opening-media-not-opening-body-or-delivery-approval", executionId: claim.executionId,
    inputPath, inputSha256: claim.inputSha256, executionInputHash: claim.executionInputHash,
    executionClaim: { path: f.held.claimPath, sha256: f.held.claimSha256 }, sourceColorEvidence: evidence,
    openingApproved: false, deliveryApproved: false, TEST: "opaque AV content, no source/media qualification" };
  const completion = { schemaVersion: 2, kind: "guided-opening-media-completion", status: "complete", executionId: claim.executionId,
    inputSha256: claim.inputSha256, executionInputHash: claim.executionInputHash, executionClaimSha256: f.held.claimSha256,
    receiptPath: resultPath, receiptSha256: "", receiptHash: "", sourceColorEvidence: { ...evidence }, openingApproved: false, deliveryApproved: false };
  const publish = () => {
    const record = { ...body, receiptHash: canonicalJsonSha256(body) }; write(resultPath, record);
    completion.receiptSha256 = canonicalJsonSha256(record); completion.receiptHash = record.receiptHash;
    f.outcome.stdout = JSON.stringify(completion); f.activation.outcomeSha256 = canonicalJsonSha256(f.outcome);
    const hash = writeGuidedObject(f.held.job.ctx.dir, f.activation);
    const activationPath = path.join(f.held.job.ctx.dir, ".sniper-authority-v1/objects/receipts", `${hash}.json`);
    allowed.add(activationPath); target(activationPath); fs.chmodSync(activationPath, 0o600);
    f.held.job.guidedHandoffV2!.openingProcessOutcomeHash = hash;
    write(intentPath, f.intent); write(outcomePath, f.outcome); write(journalPath, f.held.job);
    Object.assign(f.held, readCutPreviewObject(journalPath));
  };
  publish();
  let calls = 0, onGuard = () => {};
  const context = { held: f.held, guard: () => { calls++; onGuard(); } };
  const rewrite = (file: string, bytes: Buffer | string) => { target(file); assert(fs.existsSync(file)); fs.writeFileSync(file, bytes); };
  return { ...f, context, completion, body, evidence, resultPath, inputPath, intentPath, outcomePath, ledgerPath, priorPath,
    publish, rewrite, calls: () => calls, onGuard: (callback: () => void) => { onGuard = callback; } };
}

/** Schema2 returned text only, never proof that a child or native media inspection ran. */
export function sourceColorResultReadback(f: ReturnType<typeof sourceColorOpeningResultFixture>): Record<string, unknown> {
  const { executionClaimSha256, ...identity } = f.completion;
  return { ...identity, kind: "guided-opening-media-readback", status: "verified", claimSha256: executionClaimSha256,
    scope: "exact-source-color-held-private-media-not-opening-or-delivery-approval", elapsedMs: 100,
    stages: SOURCE_COLOR_READBACK_STAGES.map(stage => ({ stage, status: "complete", elapsedMs: 1 })),
    sourceColorRecordsReplayed: true, basePictureConsumptionVerified: true, gamutMeasured: false, gradeApplied: false, colorQualified: false,
    processGroupAndDockerCleanup: "requires-separate-owned-server-observation", currentJournalAndLease: "requires-separate-owned-server-observation" };
}
