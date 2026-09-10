import assert from "node:assert/strict";
import path from "node:path";
import { test } from "node:test";
import { parseContinueApprovedOpening, GUIDED_BODY_INPUT_SCOPE } from "@/lib/producer/contracts/guided-body-v1";
import { holdGuidedBodyInputUnderLease } from "../guided-body-authority";
import { canonicalJsonSha256 as hash } from "../auto-edit-hash";
import { BODY_TEST_HASH, bodyAuthorityFixture, bodyTestDocument } from "./_guided-body-fixture";
import { runCutPreviewProcess } from "@/app/api/producer/auto-edit/cut-preview-process";
import { assertBodyGraphWorkload } from "@/lib/producer/contracts/guided-body-media-v1";
import { assertOpeningMediaMetadata } from "../guided-opening-media-input";

type Fixture = ReturnType<typeof bodyAuthorityFixture>;
test("a later body-only always-hole card rejects before the expensive verifier without narrowing opening-only acceptance", async () => {
  const f = bodyAuthorityFixture(), candidate = f.proposal.result.candidate, media = f.reads.mediaAuthority(f.proposal as never);
  candidate.graphicsTrack[7].kind = "nateherk-takeover";
  media.bindings!.graphics[7].entryHash = hash(candidate.graphicsTrack[7]);
  media.bindings!.candidatePlanHash = hash(candidate);
  const before = structuredClone({ candidate, bindings: media.bindings });
  assertOpeningMediaMetadata({ plan: candidate, bindings: media.bindings, reviewEndFrame: 1800 });
  await assert.rejects(holdGuidedBodyInputUnderLease(f.request, f.reads), /graphic presentation/);
  assert.equal(f.counts().verifications, 0);
  assert.deepEqual({ candidate, bindings: media.bindings }, before);
});

test("malformed full-body coverage also rejects before verification; supported later cards remain usable", async () => {
  const bad = bodyAuthorityFixture(), media = bad.reads.mediaAuthority(bad.proposal as never);
  media.bindings!.graphics.pop();
  await assert.rejects(holdGuidedBodyInputUnderLease(bad.request, bad.reads), /whole-candidate/);
  assert.equal(bad.counts().verifications, 0);
  const good = bodyAuthorityFixture(), result = await holdGuidedBodyInputUnderLease(good.request, good.reads);
  assert.equal(good.counts().verifications, 1); assert.equal(result.bindings!.graphics.length, 8);
  assert.equal(result.executable, false); assert.equal(result.bodyGenerated, false);
});
test("full body graph workload refuses unsupported native-pixel cost before an expensive verifier", async () => {
  assert.doesNotThrow(() => assertBodyGraphWorkload({ width: 1920, height: 1080 }, 31));
  assert.doesNotThrow(() => assertBodyGraphWorkload({ width: 3840, height: 2160 }, 7));
  assert.throws(() => assertBodyGraphWorkload({ width: 1920, height: 1080 }, 32));
  assert.throws(() => assertBodyGraphWorkload({ width: 3840, height: 2160 }, 8));
  const f = bodyAuthorityFixture(), read = f.reads.mediaAuthority;
  f.reads.mediaAuthority = ((...args: Parameters<typeof read>) => ({ ...read(...args), bindings: {
    graphics: Array.from({ length: 32 }, (_, order) => ({ order })),
  } })) as typeof read;
  await assert.rejects(holdGuidedBodyInputUnderLease(f.request, f.reads), /pixel|workload/i);
  assert.equal(f.counts().verifications, 0);
});
function resealApproval(f: Fixture): void {
  const approvalHash = hash(f.fact);
  f.current.job.guidedHandoffV2.openingApprovalHash = approvalHash;
  f.current.job.events[0].payload.approvalHash = approvalHash;
  f.current.sha256 = hash(f.current.job); f.proposal.sha256 = f.current.sha256;
  Object.assign(f.submission, { openingApprovalHash: approvalHash, expectedJournalHash: f.current.sha256 });
  (f.selected.observed as { sha256: string }).sha256 = f.current.sha256;
  f.reads.approval.approval = () => ({ approvalHash, approvedAt: String(f.fact.approvedAt), decisionHash: String(f.fact.decisionHash) });
  f.files.set(`${f.approvalRoot}/approval.json`, bodyTestDocument({ ...f.fact, approvalHash }));
}
function requalifyOutput(f: Fixture, patch: Record<string, unknown>): void {
  const output = bodyTestDocument({ ...f.records.output.value, ...patch });
  const receipt = bodyTestDocument({ ...f.records.receipt.value, outputSha256: output.sha256 });
  f.files.set(`${f.approvalRoot}/output.json`, output); f.files.set(`${f.approvalRoot}/verified.json`, receipt);
  Object.assign(f.fact.requalification as object, { readbackOutputSha256: output.sha256, readbackReceiptSha256: receipt.sha256 });
  resealApproval(f);
}

test("body request is closed, exact and contains no client authority or runtime controls", () => {
  const f = bodyAuthorityFixture(); assert.deepEqual(parseContinueApprovedOpening(f.submission), f.submission);
  for (const patch of [{ schemaVersion: 2 }, { operation: "approve-guided-opening" }, { idempotencyKey: "bad" }, { expectedToken: "" },
    { openingApprovalHash: "bad" }, { plan: {} }, { dir: "/tmp/elsewhere" }, { deadline: 123 }, { bodyGenerated: true }, { renderer: "host" }]) {
    assert.throws(() => parseContinueApprovedOpening({ ...f.submission, ...patch }));
  }
  for (const key of Object.keys(f.submission)) {
    const row = { ...f.submission } as Record<string, unknown>; delete row[key]; assert.throws(() => parseContinueApprovedOpening(row));
  }
});

test("held body input uses current verification and immutable exact references without launching or releasing caller lease", async () => {
  const f = bodyAuthorityFixture(), before = hash({ job: f.current.job, fact: f.fact });
  const value = await holdGuidedBodyInputUnderLease(f.request, f.reads);
  assert.equal(value.scope, GUIDED_BODY_INPUT_SCOPE); assert.equal(value.executable, false);
  assert.equal(value.bodyGenerated, false); assert.equal(value.bodyReadiness, "not-qualified"); assert.equal(value.deliveryApproved, false);
  assert.equal(value.references.masterSelection.path, `${f.root}/full-program-base/audio/master/selection-event.json`);
  assert.deepEqual(value.origin, { clockHash: BODY_TEST_HASH, startedAt: "2026-09-06T12:00:00.000Z" });
  assert.equal(f.counts().verifications, 1); assert.ok(f.counts().checks > 2); value.assertUnchanged();
  assert.equal(hash({ job: f.current.job, fact: f.fact }), before);
  assert.ok(Object.isFrozen(value)); assert.ok(Object.isFrozen(value.references)); assert.ok(Object.isFrozen(value.authority));
});

test("55minute body hold reaches the actual opening runner with one bounded integer verifier deadline", async () => {
  const f = bodyAuthorityFixture(), verify = f.reads.verify;
  const command = { command: process.execPath, args: ["-e", "process.stdout.write('TEST verifier child')"],
    cwd: process.cwd(), env: { PATH: process.env.PATH, NODE_ENV: "test" as const }, purpose: "guided-opening" as const };
  const original = 55 * 60_000 + 0.75;
  assert.throws(() => runCutPreviewProcess({ ...command, timeoutMs: Math.floor(original) }), /bounded POSIX/);
  assert.throws(() => runCutPreviewProcess({ ...command, timeoutMs: 1000.5 }), /bounded POSIX/);
  f.request.remainingMs = () => original;
  f.reads.verify = async (input) => {
    const timeoutMs = input.remainingMs();
    assert.ok(Number.isInteger(timeoutMs) && timeoutMs > 0 && timeoutMs <= 25 * 60_000);
    const output = await runCutPreviewProcess({ ...command, timeoutMs });
    assert.equal(output.stdout, "TEST verifier child"); assert.equal(output.stderr, "");
    assert.ok(input.remainingMs() <= timeoutMs);
    return verify(input);
  };
  const held = await holdGuidedBodyInputUnderLease(f.request, f.reads);
  assert.equal(held.executable, false); assert.equal(f.counts().verifications, 1);
  // Only subprocess admission/stop is real; fixture metadata and verification remain explicitly TEST stubs.
});

test("a resealed approval cannot replace selected bytes, claim, cleanup, result or original clock", async () => {
  for (const key of ["selectionHash", "claimHash", "executionId", "cleanupHash", "mediaResultSha256", "receiptHash", "coreMediaSha256",
    "reviewMediaSha256", "clockHash", "generationStartedAt"]) {
    const f = bodyAuthorityFixture(); f.fact[key] = "b".repeat(64); resealApproval(f);
    await assert.rejects(holdGuidedBodyInputUnderLease(f.request, f.reads), /differs|changed/);
    assert.equal(f.counts().verifications, 0, key);
  }
});

test("a resealed decision cannot authorize different exact media or before journal", async () => {
  for (const key of ["coreMediaSha256", "reviewMediaSha256", "expectedJournalHash", "expectedToken"]) {
    const f = bodyAuthorityFixture(), decision = f.fact.decision as Record<string, unknown>;
    decision[key] = "b".repeat(64); f.fact.decisionHash = hash(decision); resealApproval(f);
    await assert.rejects(holdGuidedBodyInputUnderLease(f.request, f.reads), /decision differs/);
  }
});

test("the exact current post-approval journal must reconstruct from the retained before snapshot", async () => {
  for (const mutate of [(f: Fixture) => { f.current.job.message = "unrelated external change"; },
    (f: Fixture) => { f.current.job.nextEventId += 1; }, (f: Fixture) => { f.current.job.events[0].payload.event = "other"; },
    (f: Fixture) => { (f.current.job as Record<string, unknown>).hiddenPlan = {}; }]) {
    const f = bodyAuthorityFixture(); mutate(f); resealApproval(f);
    await assert.rejects(holdGuidedBodyInputUnderLease(f.request, f.reads), /journal transition/);
  }
});

test("unknown, reordered, failed or rehashed approval verification cannot become body authority", async () => {
  for (const patch of [{ processGroupStopped: false }, { observedAt: "2026-09-06T12:03:00.000Z" }, { stdout: "{}" },
    { stderr: "x".repeat(2 * 1024 * 1024 + 1) }, { unknown: true }]) {
    const f = bodyAuthorityFixture(); requalifyOutput(f, patch);
    await assert.rejects(holdGuidedBodyInputUnderLease(f.request, f.reads)); assert.equal(f.counts().verifications, 0);
  }
  const f = bodyAuthorityFixture(); (f.fact.requalification as Record<string, unknown>).readbackDirectory = "../escape"; resealApproval(f);
  await assert.rejects(holdGuidedBodyInputUnderLease(f.request, f.reads));
});

test("missing private approval/readback or failure markers block before invoking current media verification", async () => {
  for (const name of ["start", "output", "verified", "approval"]) {
    const f = bodyAuthorityFixture(); f.files.delete(`${f.approvalRoot}/${name}.json`);
    await assert.rejects(holdGuidedBodyInputUnderLease(f.request, f.reads), /missing/); assert.equal(f.counts().verifications, 0);
  }
  const f = bodyAuthorityFixture(); f.faults.failure = true;
  await assert.rejects(holdGuidedBodyInputUnderLease(f.request, f.reads), /retained failure/);
});

test("stale requests, replaced leases, exhausted budgets and unavailable readiness fail before media", async () => {
  for (const key of ["expectedJournalHash", "openingApprovalHash", "selectionHash", "proposalReadinessHash", "treatmentDraftRevisionHash"] as const) {
    const f = bodyAuthorityFixture(); f.submission[key] = "b".repeat(64);
    await assert.rejects(holdGuidedBodyInputUnderLease(f.request, f.reads)); assert.equal(f.counts().verifications, 0);
  }
  for (const key of ["lease", "budget"] as const) {
    const f = bodyAuthorityFixture(); f.faults[key] = true;
    await assert.rejects(holdGuidedBodyInputUnderLease(f.request, f.reads)); assert.equal(f.counts().verifications, 0);
  }
  const f = bodyAuthorityFixture(); f.reads.readiness = () => { throw new Error("TEST successor is not exact picture-lock head"); };
  await assert.rejects(holdGuidedBodyInputUnderLease(f.request, f.reads), /successor/);
});

test("an actual verifier failure, different result or changed pinned tools returns no held input", async () => {
  const failed = bodyAuthorityFixture(); failed.faults.verification = true;
  await assert.rejects(holdGuidedBodyInputUnderLease(failed.request, failed.reads), /failed actual verifier/);
  const wrong = bodyAuthorityFixture(); wrong.verified.observed.cleanupHash = "b".repeat(64);
  await assert.rejects(holdGuidedBodyInputUnderLease(wrong.request, wrong.reads), /different journal/);
  const tools = bodyAuthorityFixture(), file = path.join(path.dirname(tools.verified.receipt.path), "start.json");
  const changed = bodyTestDocument({ ...tools.files.get(file)!.value, tools: { script: "/TEST/other.py" } }); tools.files.set(file, changed);
  tools.verified.receipt.value.startSha256 = changed.sha256;
  await assert.rejects(holdGuidedBodyInputUnderLease(tools.request, tools.reads), /pinned verifier tools/);
});

test("post-verification lease/journal/receipt failure and later assertion never grant usable continuation", async () => {
  for (const key of ["lease", "budget", "record"] as const) {
    const f = bodyAuthorityFixture(), verify = f.reads.verify;
    f.reads.verify = async (input) => { const result = await verify(input); f.faults[key] = true; return result; };
    await assert.rejects(holdGuidedBodyInputUnderLease(f.request, f.reads));
  }
  const f = bodyAuthorityFixture(), value = await holdGuidedBodyInputUnderLease(f.request, f.reads);
  f.current.sha256 = "b".repeat(64); assert.throws(value.assertUnchanged, /stale/);
});

test("held full-program reuse cannot select another plan, base, AAC transport or out-of-root master", async () => {
  for (const mutate of [(record: Record<string, unknown>) => { (record.fullProgram as Record<string, unknown>).baseAudibleTrackNotSelected = false; },
    (record: Record<string, unknown>) => { (record.fullProgram as Record<string, unknown>).fullMasterSelectionEventPath = "/TEST/foreign/selection-event.json"; },
    (record: Record<string, unknown>) => { ((record.documents as Record<string, unknown>).candidatePlan as Record<string, unknown>).path = "/TEST/other-plan.json"; }]) {
    const f = bodyAuthorityFixture(); mutate((f.result.record as ReturnType<typeof bodyTestDocument>).value);
    await assert.rejects(holdGuidedBodyInputUnderLease(f.request, f.reads), /reuse references/);
  }
});

test("the initial budget callback cannot replace the body caller's original lease or remainder", async () => {
  const lease = bodyAuthorityFixture();
  lease.request.remainingMs = () => { lease.request.lease = { release() { throw new Error("TEST replacement lease must not release"); } }; return 1_000; };
  await assert.rejects(holdGuidedBodyInputUnderLease(lease.request, lease.reads), /original caller identity/);
  assert.equal(lease.counts().verifications, 0);
  const budget = bodyAuthorityFixture(), original = budget.request.remainingMs;
  budget.request.remainingMs = () => { budget.request.remainingMs = original; return 1_000; };
  await assert.rejects(holdGuidedBodyInputUnderLease(budget.request, budget.reads), /original caller identity/);
  assert.equal(budget.counts().verifications, 0);
});

test("a replacement caller remainder after verification cannot authorize a body hold", async () => {
  const f = bodyAuthorityFixture(), verify = f.reads.verify;
  f.reads.verify = async request => { const result = await verify(request); f.request.remainingMs = () => 1_500_000; return result; };
  await assert.rejects(holdGuidedBodyInputUnderLease(f.request, f.reads), /original caller identity/);
  assert.equal(f.counts().verifications, 1);
});
