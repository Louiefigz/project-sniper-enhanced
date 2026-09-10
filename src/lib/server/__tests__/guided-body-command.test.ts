import assert from "node:assert/strict";
import { test } from "node:test";
import { randomUUID } from "node:crypto";
import { mkdtempSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import path from "node:path";
import { executeBodyCommand, bodyCommandFailure, type bodyCommandServices } from "../../../../scripts/producer/guided-body";
import { BodyRequestConflictError } from "../guided-body-service";
import { parseGuidedBodyRunResult, parseGuidedBodyStatus } from "@/lib/producer/contracts/guided-body-command-v1";
import { parseBodyMediaCompletion, parseBodyMediaReadback, parseBodyCleanupResult } from "@/lib/producer/contracts/guided-body-result-v1";
import { bodyAuthorityFixture } from "./_guided-body-fixture";

const H = "a".repeat(64), id = randomUUID(), root = "/private/tmp/TEST-body-command";
function status() {
  return { ok: true, state: "failed-or-unresolved", detail: "TEST metadata only", journalHash: H, requestId: id, executionId: id,
    admissionClaimHash: H, activationHash: H, cleanupHash: null, candidateHash: null, candidate: null,
    observedAt: "2026-09-07T12:00:00.000Z", sourceFreshness: "not-observed-by-status", bodyApproved: false, deliveryApproved: false };
}
function completion() {
  return { schemaVersion: 1, kind: "guided-body-media-completion", status: "complete", executionId: id,
    inputSha256: H, executionActivationSha256: H, receiptPath: `${root}/body-result.json`, receiptSha256: H,
    receiptHash: H, bodyApproved: false, deliveryApproved: false };
}

test("body status/replay/candidate replies are closed and never conflate metadata with approval", () => {
  const row = status(); assert.doesNotThrow(() => parseGuidedBodyStatus(row));
  assert.doesNotThrow(() => parseGuidedBodyRunResult({ ok: true, replayed: true, status: row }));
  for (const patch of [{ state: "ready" }, { bodyApproved: true }, { deliveryApproved: true }, { sourceFreshness: "current" },
    { candidate: { path: `${root}/final.mp4`, sha256: H } }, { hidden: "authority" }]) {
    assert.throws(() => parseGuidedBodyStatus({ ...row, ...patch }));
  }
  const candidate = { ok: true, replayed: false, state: "private-candidate-qualified", requestId: id, executionId: id,
    admissionClaimHash: H, activationHash: H, cleanupHash: H, candidateHash: H, journalHash: H,
    candidate: { path: `${root}/final.mp4`, sha256: H }, bodyApproved: false, deliveryApproved: false };
  assert.doesNotThrow(() => parseGuidedBodyRunResult(candidate));
  for (const patch of [{ candidateHash: null }, { candidate: { ...candidate.candidate, sha256: "bad" } }, { bodyApproved: true }]) {
    assert.throws(() => parseGuidedBodyRunResult({ ...candidate, ...patch }));
  }
});

test("actual stdout envelopes reject extra rows, false cleanup, missing coverage and approval flags", () => {
  const row = completion(); assert.doesNotThrow(() => parseBodyMediaCompletion(JSON.stringify(row)));
  for (const patch of [{ status: "failed" }, { bodyApproved: true }, { receiptHash: "bad" }, { extra: true }]) {
    assert.throws(() => parseBodyMediaCompletion(JSON.stringify({ ...row, ...patch })));
  }
  assert.throws(() => parseBodyMediaCompletion(JSON.stringify(row) + "\n{}"));
  const names = ["body-read-control", "body-read-current-inputs", "body-read-held-result", "body-read-current-pipeline",
    "body-read-whole-base-master", "body-read-all-graphics", "body-read-final-media-and-qc", "body-read-final-revalidation"];
  const read = { ...row, kind: "guided-body-media-readback", status: "verified", scope: "exact-held-private-body-media-not-body-or-delivery-approval",
    elapsedMs: 10, stages: names.map((stage) => ({ stage, status: "complete", elapsedMs: 1 })),
    processGroupAndDockerCleanup: "requires-separate-owned-controller-observation", currentJournalAndLease: "requires-separate-owned-controller-observation" };
  assert.doesNotThrow(() => parseBodyMediaReadback(JSON.stringify(read)));
  assert.throws(() => parseBodyMediaReadback(JSON.stringify({ ...read, stages: read.stages.slice(1) })));
  assert.throws(() => parseBodyMediaReadback(JSON.stringify({ ...read, processGroupAndDockerCleanup: "verified" })));
  const cleanup = { schemaVersion: 1, kind: "guided-body-cleanup-result", activationPath: `${root}/activation.json`, activationSha256: H,
    inputSha256: H, outputRoot: root, executionId: id, cleanupVerified: true, graphics: [], elapsedMs: 2,
    stages: ["body-cleanup-control", "body-cleanup-control-after"].map((stage) => ({ stage, status: "complete", elapsedMs: 1 })),
    budgetScope: "separate-protected-cleanup-not-render-allowance", processGroupStopped: "requires-owned-controller-observation", bodyApproved: false, deliveryApproved: false };
  assert.doesNotThrow(() => parseBodyCleanupResult(JSON.stringify(cleanup)));
  assert.throws(() => parseBodyCleanupResult(JSON.stringify({ ...cleanup, cleanupVerified: false })));
});

test("CLI status never runs, requests are bounded/no-follow, and paid/runtime/approval extras cannot reach services", async () => {
  const dir = realpathSync(mkdtempSync("/private/tmp/sniper-body-command-")), request = path.join(dir, "request.json"), f = bodyAuthorityFixture();
  const calls = { run: 0, status: 0, cleanup: 0 }, services = { run: async () => { calls.run += 1; return { ok: true, replayed: true, status: status() }; },
    status: () => { calls.status += 1; return status(); }, cleanup: async () => { calls.cleanup += 1; return {}; } } as unknown as typeof bodyCommandServices;
  try {
    await executeBodyCommand(["status", dir], services); assert.deepEqual(calls, { run: 0, status: 1, cleanup: 0 });
    writeFileSync(request, JSON.stringify(f.submission)); await executeBodyCommand(["run", dir, request], services);
    assert.equal(calls.run, 1);
    for (const bytes of ["{" , " ".repeat(16_385), JSON.stringify({ ...f.submission, runtime: {} }), JSON.stringify({ ...f.submission, bodyApproved: true })]) {
      writeFileSync(request, bytes); await assert.rejects(executeBodyCommand(["run", dir, request], services));
    }
    writeFileSync(request, JSON.stringify(f.submission)); symlinkSync(request, path.join(dir, "link.json"));
    await assert.rejects(executeBodyCommand(["run", dir, path.join(dir, "link.json")], services));
    await assert.rejects(executeBodyCommand(["run", dir], services)); assert.equal(calls.run, 1);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("CLI conflict is an exact typed error, never a generic failure/import/timeout lookalike", () => {
  assert.equal(bodyCommandFailure(new BodyRequestConflictError("different request")).code, "BODY_REQUEST_CONFLICT");
  for (const error of [new Error("BODY_REQUEST_CONFLICT"), { code: "BODY_REQUEST_CONFLICT" }, new Error("timeout")]) {
    assert.equal(bodyCommandFailure(error).code, "BODY_COMMAND_FAILED");
  }
  assert.equal(bodyCommandFailure(new Error("x".repeat(5000))).error.length, 4000);
});
