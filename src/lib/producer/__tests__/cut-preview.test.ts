import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, realpathSync, renameSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { runAuthorStage } from "@/app/api/producer/auto-edit/authoring-stage";
import { renderPrivateCutPreview } from "@/app/api/producer/auto-edit/cut-preview";
import { readCurrentCutPreview, readCutPreviewEvidence, parseCutPreviewReceipt } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { createHash } from "node:crypto";
import { verifyCutPreviewSources } from "@/app/api/producer/auto-edit/cut-preview-verification";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { CutPreviewProcessError, runCutPreviewProcess, type CutPreviewProcessInput } from "@/app/api/producer/auto-edit/cut-preview-process";
import { pythonInterpreter, SCRIPTS_DIR } from "@/app/api/_lib/spawn-python";
import { acquireProjectMutationLease } from "@/lib/server/project-mutation-lease";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import type { CutApprovalRequestV1 } from "@/lib/producer/contracts/cut-approval-request";
import { guidedFixture } from "./_guided-cut-fixture";

const producer = path.join(SCRIPTS_DIR, "producer");
const env = { ...process.env, PYTHONPATH: `${producer}${path.delimiter}${path.join(producer, "tests")}` };

function rejectForgedToolchains(directory: string, request: CutApprovalRequestV1): void {
  const runtimeFile = path.join(directory, "toolchain.json"), receiptFile = path.join(directory, "receipt.json");
  const runtimeBytes = readFileSync(runtimeFile), receiptBytes = readFileSync(receiptFile);
  const { toolchainHash: _oldHash, ...runtime } = JSON.parse(runtimeBytes.toString());
  const { receiptHash: _oldReceiptHash, ...receipt } = JSON.parse(receiptBytes.toString());
  const variants = [[], [...runtime.files, runtime.files[0]],
    runtime.files.filter((row: { path: string }) => row.path !== runtime.binaries.ffmpeg),
    [...runtime.files, { path: path.join(directory, "cut-preview.mp4"), sha256: receipt.media.sha256 }]];
  try {
    for (const files of variants) {
      const forgedRuntime = { ...runtime, files };
      const toolchainHash = canonicalJsonSha256(forgedRuntime);
      const forgedReceipt = { ...receipt, toolchainHash };
      writeFileSync(runtimeFile, JSON.stringify({ ...forgedRuntime, toolchainHash }));
      writeFileSync(receiptFile, JSON.stringify({ ...forgedReceipt, receiptHash: canonicalJsonSha256(forgedReceipt) }));
      assert.throws(() => readCurrentCutPreview(directory, request), /toolchain/);
      assert.throws(() => readCutPreviewEvidence(directory, request), /toolchain/);
    }
  } finally { writeFileSync(runtimeFile, runtimeBytes); writeFileSync(receiptFile, receiptBytes); }
}

function evidenceDoesNotObserveMedia(directory: string, request: CutApprovalRequestV1): void {
  const movie = path.join(directory, "cut-preview.mp4"), hidden = path.join(directory, "test-hidden.mp4");
  const original = readFileSync(movie), corrupted = Buffer.from(original);
  corrupted[Math.floor(corrupted.length / 2)] ^= 1;
  try {
    writeFileSync(movie, corrupted); // Same size: a stat-only shortcut would miss this.
    const evidence = readCutPreviewEvidence(directory, request);
    assert.equal(evidence.observationScope, "receipt-proofs-and-toolchain-only");
    assert.equal(evidence.mediaBytesObserved, false);
    assert.throws(() => readCurrentCutPreview(directory, request), /media bytes changed/);
    renameSync(movie, hidden);
    try {
      assert.deepEqual(readCutPreviewEvidence(directory, request), evidence);
      assert.throws(() => readCurrentCutPreview(directory, request), /ENOENT/);
    } finally { renameSync(hidden, movie); }
  } finally { writeFileSync(movie, original); }
  assert.equal(readCurrentCutPreview(directory, request).media.sizeBytes, original.length);
}

function rejectResignedProofs(directory: string, request: CutApprovalRequestV1): void {
  const receiptFile = path.join(directory, "receipt.json"), proofFile = path.join(directory, "cut_manifestation.v1.json");
  const receiptBytes = readFileSync(receiptFile), proofBytes = readFileSync(proofFile);
  const { receiptHash: _receiptHash, ...receipt } = JSON.parse(receiptBytes.toString());
  const { receiptHash: _proofHash, ...proof } = JSON.parse(proofBytes.toString());
  try {
    const forged = { ...proof, concat: { ...proof.concat, sha256: "0".repeat(64) } };
    const proofHash = canonicalJsonSha256(forged);
    const forgedBytes = Buffer.from(JSON.stringify({ ...forged, receiptHash: proofHash }));
    const forgedReceipt = { ...receipt, manifestationHash: proofHash,
      manifestationFileHash: createHash("sha256").update(forgedBytes).digest("hex") };
    writeFileSync(proofFile, forgedBytes);
    writeFileSync(receiptFile, JSON.stringify({ ...forgedReceipt, receiptHash: canonicalJsonSha256(forgedReceipt) }));
    assert.throws(() => readCutPreviewEvidence(directory, request), /manifestation proof/);
    writeFileSync(proofFile, proofBytes);
    const wrongRequest = { ...receipt, planHash: "0".repeat(64) };
    writeFileSync(receiptFile, JSON.stringify({ ...wrongRequest, receiptHash: canonicalJsonSha256(wrongRequest) }));
    assert.throws(() => readCutPreviewEvidence(directory, request), /another reviewed cut/);
    const overBound = { ...receipt, media: { ...receipt.media, videoFrames: 72001 } };
    writeFileSync(receiptFile, JSON.stringify({ ...overBound, receiptHash: canonicalJsonSha256(overBound) }));
    assert.throws(() => readCutPreviewEvidence(directory, request), /qualified browser/);
  } finally { writeFileSync(receiptFile, receiptBytes); writeFileSync(proofFile, proofBytes); }
}

test("actual cut gates -> private decoded preview -> read-only admitted-byte verification", async () => {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-cut-preview-")));
  try {
    const fixture = guidedFixture(root);
    execFileSync(pythonInterpreter(), [path.join(producer, "tests/_cut_preview_fixture.py"), root], { env, timeout: 20_000 });
    const outcome = await runAuthorStage(fixture.run, fixture.deps);
    if (outcome.status !== "awaiting_cut_approval") throw new Error("missing cut request");
    const acquired = acquireProjectMutationLease(root, "private preview test");
    assert.ok(acquired.lease);
    try {
      const preview = await renderPrivateCutPreview({ job: fixture.run.job, request: outcome.request, lease: acquired.lease, timeoutMs: 30_000 });
      assert.equal(preview.receipt.media.fullDecode, "passed");
      assert.equal(preview.receipt.media.audio.presentedAudioSamples, 144144);
      assert.equal(preview.receipt.runId, fixture.run.job.artifactToken ?? fixture.run.job.token);
      assert.equal(readCurrentCutPreview(preview.directory, outcome.request).receiptHash, preview.receipt.receiptHash);
      rejectForgedToolchains(preview.directory, outcome.request);
      evidenceDoesNotObserveMedia(preview.directory, outcome.request);
      rejectResignedProofs(preview.directory, outcome.request);
      const receiptBytes = readFileSync(path.join(preview.directory, "receipt.json"));
      const before = readdirSync(preview.directory).sort();
      await verifyCutPreviewSources({ job: fixture.run.job, request: outcome.request, executionKey: preview.receipt.executionKey, lease: acquired.lease });
      assert.deepEqual(readdirSync(preview.directory).sort(), before);
      assert.deepEqual(readFileSync(path.join(preview.directory, "receipt.json")), receiptBytes);
      const journal = readFileSync(path.join(preview.directory, "stage_timings.jsonl"), "utf8").trim().split("\n").map((line) => JSON.parse(line));
      assert.ok(journal.every((row) => row.runId === preview.receipt.runId && row.attemptId === fixture.run.job.token && row.attemptNo === 1));
      assert.ok(journal.every((row) => typeof row.parentSpanId === "string"));
      assert.throws(() => parseCutPreviewReceipt({ ...preview.receipt, extra: true }));
      const manifest = JSON.parse(readFileSync(fixture.ctx.manifestPath, "utf8"));
      const silent = manifest.sources.find((row: { id: string }) => row.id === "silent").path;
      writeFileSync(silent, Buffer.concat([readFileSync(silent), Buffer.from("drift")]));
      await assert.rejects(verifyCutPreviewSources({ job: fixture.run.job, request: outcome.request,
        executionKey: preview.receipt.executionKey, lease: acquired.lease }), /exited/);
      assert.deepEqual(readFileSync(path.join(preview.directory, "receipt.json")), receiptBytes);
      assert.ok(!readdirSync(fixture.ctx.dir).some((name) => ["final.mp4", "base_final.mp4", ".sniper-qc-approved.json", ".render-graph-v1"].includes(name)));
    } finally { acquired.lease.release(); }
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("lease guard rejects absent, released or replaced actual ownership", () => {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-preview-lease-")));
  try {
    const fake = { release() {} };
    assert.throws(() => cutPreviewLeaseGuard(root, fake));
    const acquired = acquireProjectMutationLease(root, "preview lease check");
    assert.ok(acquired.lease);
    const guard = cutPreviewLeaseGuard(root, acquired.lease);
    guard(); acquired.lease.release();
    assert.throws(guard);
    const replacement = acquireProjectMutationLease(root, "replacement");
    assert.ok(replacement.lease);
    assert.throws(guard, /replaced/);
    replacement.lease.release();
  } finally { rmSync(root, { recursive: true, force: true }); }
});

for (const purpose of [undefined, "guided-opening"] as const) test(`${purpose ?? "legacy cut"} deadline terminates and verifies the entire owned child/grandchild process group`, async () => {
  const code = `const {spawn}=require('child_process');process.on('SIGTERM',()=>{});const c=spawn(process.execPath,['-e',"process.on('SIGTERM',()=>{});setInterval(()=>{},1000)"],{stdio:'ignore'});console.log(c.pid);setInterval(()=>{},1000)`;
  await assert.rejects(runCutPreviewProcess({ command: process.execPath, args: ["-e", code], cwd: producer,
    env: process.env, timeoutMs: 400, purpose }), (error: unknown) => {
    assert.ok(error instanceof CutPreviewProcessError);
    assert.equal(error.details.timedOut, true);
    assert.equal(error.details.groupStopped, true);
    assert.equal(error.details.forcedStop, true);
    assert.throws(() => process.kill(Number(error.details.stdout.trim()), 0));
    return true;
  });
});

test("only explicit guided-opening admits the bounded25-minute ceiling; invalid inputs never launch", async () => {
  const input: CutPreviewProcessInput = { command: process.execPath, args: ["-e", "process.stdout.write('owned child complete')"],
    cwd: producer, env: process.env, timeoutMs: 900_000 };
  for (const purpose of [undefined, "cut-preview"] as const) {
    assert.throws(() => runCutPreviewProcess({ ...input, purpose, timeoutMs: 900_001 }), /bounded POSIX/);
    assert.equal((await runCutPreviewProcess({ ...input, purpose })).stdout, "owned child complete");
  }
  assert.equal((await runCutPreviewProcess({ ...input, purpose: "guided-opening", timeoutMs: 1_500_000 })).stdout, "owned child complete");
  for (const timeoutMs of [0, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY, 1_500_001]) {
    assert.throws(() => runCutPreviewProcess({ ...input, purpose: "guided-opening", timeoutMs }), /bounded POSIX/);
  }
  for (const purpose of ["unknown", "", false, 1, null] as unknown as CutPreviewProcessInput["purpose"][]) {
    assert.throws(() => runCutPreviewProcess({ ...input, purpose }), /bounded POSIX/);
  }
});

test("a zero-exit leader cannot leave a live descendant or exceed output budget", async () => {
  const code = `const {spawn}=require('child_process');const c=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore'});c.unref()`;
  await assert.rejects(runCutPreviewProcess({ command: process.execPath, args: ["-e", code], cwd: producer,
    env: process.env, timeoutMs: 2000 }), /left a live process group/);
  await assert.rejects(runCutPreviewProcess({ command: process.execPath,
    args: ["-e", "process.stdout.write(Buffer.alloc(3*1024*1024));setInterval(()=>{},1000)"], cwd: producer,
    env: process.env, timeoutMs: 2000 }), (error: unknown) => {
    assert.ok(error instanceof CutPreviewProcessError);
    assert.equal(error.details.groupStopped, true);
    assert.ok(error.details.stdout.length <= 2 * 1024 * 1024);
    return true;
  });
});
