import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { runAuthorStage } from "@/app/api/producer/auto-edit/authoring-stage";
import { acquireProjectMutationLease } from "../project-mutation-lease";
import { acceptGuidedCut, retryAcceptedCutContinuation, readAcceptedCutStatus,
  readPendingHumanCutDecision, HumanCutAcceptanceError } from "../human-cut-acceptance";
import { activeHumanCutAcceptance, verifyHumanAcceptedCut, observeHumanCutJob, readHumanCutAcceptance,
  readHumanCutActivation } from "../human-cut-acceptance-store";
import { verifyHumanAcceptedSourceBytes } from "../human-cut-source-verification";
import { markHumanCutWorker } from "../human-cut-continuation";
import { readAutoEditJob, startAutoEditJob } from "../auto-edit-job-store";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { writeContentAddressedJsonSync } from "../content-addressed-json";
import { diskCheckpointWriter, diskInvalidationWriter } from "@/app/api/producer/auto-edit/pipeline-writers";
import { parseHumanCutSubmission, parseHumanCutAcceptance, parseHumanCutActivation } from "@/lib/producer/contracts/human-cut-acceptance";
import { createHumanCutFixture as preparedFixture } from "./_human-cut-fixture";
import { prepareRequest } from "@/app/api/producer/auto-edit/request";
import { buildResumeAutoEditRequest } from "@/lib/producer/intent-flow";
import { producerRun } from "../producer-run-registry";
import { autoEditJobStream } from "@/app/api/producer/auto-edit/job-stream";

async function acceptPending(fixture: Awaited<ReturnType<typeof preparedFixture>>) {
  await assert.rejects(acceptGuidedCut({ dir: fixture.ctx.dir, submission: fixture.submission }, {
    launch: async () => { throw new Error("injected unavailable worker runtime"); },
  }), (error: unknown) => error instanceof HumanCutAcceptanceError && error.cutAccepted);
  return observeHumanCutJob(fixture.ctx.dir).job;
}

test("real admitted cut acceptance persists before launch, replays without spawning, and fences explicit retries", async () => {
  const fixture = await preparedFixture();
  let child: ReturnType<typeof spawn> | undefined;
  try {
    const pending = await acceptPending(fixture), fact = activeHumanCutAcceptance(pending);
    assert.equal(pending.status, "cut_accepted"); assert.equal(pending.attempts, 2);
    assert.equal(fact.preview.previewAttempt, 1); assert.equal(pending.artifactToken, fixture.run.job.token);
    assert.notEqual(pending.token, fixture.run.job.token);
    assert.equal(readAcceptedCutStatus(fixture.ctx.dir).canRetryContinuation, true);
    const stream = await new Response(autoEditJobStream(fixture.jobPath, pending.token)).text();
    assert.match(stream, /"event":"cut_accepted"/); assert.doesNotMatch(stream, /"event":"(?:outputs|complete)"/);
    for (const resume of [undefined, pending]) assert.throws(() => startAutoEditJob({
      ctx: pending.ctx, token: "no-bypass", snapshots: 0, resume }), /dedicated continuation/);
    const replay = await acceptGuidedCut({ dir: fixture.ctx.dir, submission: fixture.submission }, {
      launch: async () => { throw new Error("replay must never spawn"); },
    });
    assert.equal(replay.state, "cut_accepted"); assert.equal(observeHumanCutJob(fixture.ctx.dir).job.token, pending.token);
    await assert.rejects(acceptGuidedCut({ dir: fixture.ctx.dir, submission: { ...fixture.submission, idempotencyKey: randomUUID() } }), /different human decision/);
    const result = await retryAcceptedCutContinuation({ dir: fixture.ctx.dir, submission: {
      schemaVersion: 1, operation: "retry-continuation", acceptanceHash: pending.cutAcceptance!.acceptanceHash,
      requestHash: fact.request.requestHash,
    } }, { launch: async (jobPath) => {
      child = spawn(process.execPath, ["-e", "setInterval(()=>{},1000)"], { stdio: "ignore" });
      assert.ok(child.pid); const current = readAutoEditJob(jobPath)!;
      assert.notEqual(current.token, pending.token); assert.equal(current.attempts, 3);
      assert.throws(() => markHumanCutWorker(jobPath, pending.token, child!.pid!), /handoff/);
      markHumanCutWorker(jobPath, current.token, child.pid); return child.pid;
    } });
    assert.equal(result.state, "running");
    const running = observeHumanCutJob(fixture.ctx.dir).job;
    assert.equal(running.cutAcceptance!.acceptanceHash, pending.cutAcceptance!.acceptanceHash);
    assert.equal(activeHumanCutAcceptance(running).preview.previewAttempt, 1);
    assert.ok(!readdirSync(fixture.ctx.dir).includes("final.mp4"));
    assert.ok(!readdirSync(fixture.ctx.dir).includes(".sniper-qc-approved.json"));
  } finally { child?.kill(); fixture.cleanup(); }
});

test("same-size silent source drift fails acceptance, records engine failure and starts a separate new human wait", async () => {
  const fixture = await preparedFixture();
  try {
    const before = observeHumanCutJob(fixture.ctx.dir).job;
    const manifest = JSON.parse(readFileSync(fixture.ctx.manifestPath, "utf8"));
    const silent = manifest.sources.find((source: { id: string }) => source.id === "silent").path;
    const bytes = readFileSync(silent); bytes[Math.floor(bytes.length / 2)] ^= 1; writeFileSync(silent, bytes);
    await assert.rejects(acceptGuidedCut({ dir: fixture.ctx.dir, submission: fixture.submission }), /exited/);
    const failed = observeHumanCutJob(fixture.ctx.dir).job;
    assert.equal(failed.status, "awaiting_cut_approval"); assert.equal(failed.cutAcceptance, undefined);
    assert.equal(failed.cutAcceptanceAttempt!.state, "failed");
    assert.equal(failed.cutAcceptanceAttempt!.completedAt, failed.cutApprovalWaitStartedAt);
    assert.ok(failed.cutApprovalWaitStartedAt! >= before.cutApprovalWaitStartedAt!);
    assert.ok(failed.events.some((event) => event.payload.event === "cut_acceptance_verification_failed"));
    const timing = readFileSync(path.join(fixture.ctx.dir, "stage_timings.jsonl"), "utf8");
    assert.match(timing, /"stage":"human_cut_acceptance".*"status":"failed"/);
  } finally { fixture.cleanup(); }
});

test("orphan immutable acceptance is inert and same-key recovery revalidates sources before journal activation", async () => {
  const fixture = await preparedFixture();
  try {
    await assert.rejects(acceptGuidedCut({ dir: fixture.ctx.dir, submission: fixture.submission }, {
      fault: (point) => { if (point === "after-fact") throw new Error("simulated crash before journal CAS"); },
    }), /simulated crash/);
    const failed = observeHumanCutJob(fixture.ctx.dir).job;
    assert.equal(failed.status, "awaiting_cut_approval");
    const facts = readdirSync(path.join(fixture.ctx.dir, "human-cut-acceptances")); assert.equal(facts.length, 1);
    const originalBytes = readFileSync(path.join(fixture.ctx.dir, "human-cut-acceptances", facts[0]));
    const accepted = await acceptPending(fixture);
    assert.equal(accepted.cutAcceptance!.acceptanceHash, facts[0].replace(".json", ""));
    assert.equal(readdirSync(path.join(fixture.ctx.dir, "human-cut-acceptances")).length, 1);
    assert.equal(readHumanCutAcceptance(fixture.ctx.dir, accepted.cutAcceptance!.acceptanceHash).decisionHash,
      canonicalJsonSha256(fixture.submission));
    assert.deepEqual(readFileSync(path.join(fixture.ctx.dir, "human-cut-acceptances", facts[0])), originalBytes);
    const fact = activeHumanCutAcceptance(accepted), activation = readHumanCutActivation(accepted, fact)!;
    const status = readAcceptedCutStatus(fixture.ctx.dir);
    assert.equal(activation.waitStartedAt, failed.cutApprovalWaitStartedAt);
    assert.ok(activation.waitStoppedAt >= failed.cutApprovalWaitStartedAt!);
    assert.ok(activation.waitStoppedAt > fact.submittedAt, "later human retry stops its own waiting interval");
    assert.notEqual(activation.executionId, fact.verificationExecutionId);
    assert.equal(status.waitStoppedAt, activation.waitStoppedAt); assert.equal(status.decisionSubmittedAt, fact.submittedAt);
    assert.equal(status.timingState, "verified-activation");
    const acceptedEvent = accepted.events.find((event) => event.payload.event === "human_cut_accepted")!.payload;
    assert.equal(acceptedEvent.userWaitEndedAt, activation.waitStoppedAt);
    assert.equal(acceptedEvent.verificationExecutionId, activation.executionId);
    assertLegacyActivationTiming(fixture, accepted);
  } finally { fixture.cleanup(); }
});

function assertLegacyActivationTiming(fixture: Awaited<ReturnType<typeof preparedFixture>>, accepted: ReturnType<typeof readAutoEditJob> & {}): void {
  const original = readFileSync(fixture.jobPath);
  writeFileSync(fixture.jobPath, JSON.stringify({ ...accepted, cutAcceptance: { acceptanceHash: accepted.cutAcceptance!.acceptanceHash } }));
  const status = readAcceptedCutStatus(fixture.ctx.dir);
  assert.equal(status.cutAccepted, true); assert.equal(status.waitStoppedAt, null);
  assert.equal(status.timingState, "unavailable-legacy-activation");
  writeFileSync(fixture.jobPath, original);
}

test("accepted visual continuation bypasses no independent cut wall, survives visual-plan resume, and forbids recut fallback", async () => {
  const fixture = await preparedFixture();
  try {
    const pending = await acceptPending(fixture);
    const running = { ...pending, status: "running" as const };
    writeFileSync(fixture.jobPath, JSON.stringify(running));
    const run = { job: running, io: { send: () => {}, sendRaw: () => {},
      advance: diskCheckpointWriter(fixture.jobPath, running.token), invalidate: diskInvalidationWriter(fixture.jobPath, running.token) } };
    const deps = { ...fixture.deps, cutApprovalAccepted: verifyHumanAcceptedCut,
      author: async (...args: Parameters<typeof fixture.deps.author>) => {
        assert.equal(args[2], "visual");
        const plan = JSON.parse(readFileSync(fixture.ctx.planPath, "utf8")); plan.visualTestMarker = "visual-only-expansion";
        writeFileSync(fixture.ctx.planPath, JSON.stringify(plan)); return fixture.deps.author(...args);
      } };
    const first = await runAuthorStage(run, deps); assert.equal(first.status, "authored");
    const second = await runAuthorStage(run, deps); assert.equal(second.status, "authored");
    assert.equal(fixture.calls.cutWriters, 1); assert.equal(fixture.calls.critics, 2); assert.equal(fixture.calls.visualWriters, 1);
    const { lease } = acquireProjectMutationLease(fixture.root, "accepted current source oracle"); assert.ok(lease);
    try { await verifyHumanAcceptedSourceBytes({ job: run.job, lease }); } finally { lease.release(); }
    const plan = JSON.parse(readFileSync(fixture.ctx.planPath, "utf8")); plan.cutTrack[0].end -= 0.5;
    writeFileSync(fixture.ctx.planPath, JSON.stringify(plan));
    await assert.rejects(runAuthorStage(run, deps));
    assert.equal(fixture.calls.cutWriters, 1); assert.equal(fixture.calls.critics, 2); assert.equal(fixture.calls.visualWriters, 1);
  } finally { fixture.cleanup(); }
});

test("human attestations and immutable acceptance use closed schemas and reject forged bindings", async () => {
  const fixture = await preparedFixture();
  try {
    for (const patch of [{ extra: true }, { attestation: { ...fixture.submission.attestation, listened: false } },
      { idempotencyKey: "not-a-uuid" }]) assert.throws(() => parseHumanCutSubmission({ ...fixture.submission, ...patch }));
    const pending = await acceptPending(fixture), fact = activeHumanCutAcceptance(pending);
    for (const patch of [{ sourceVerification: "skipped" }, { continuationAttempt: 9 }, { extra: true },
      { decisionHash: "0".repeat(64) }, { preview: { ...fact.preview, mediaSha256: "0".repeat(64) } }]) {
      assert.throws(() => parseHumanCutAcceptance({ ...fact, ...patch }));
    }
    const activation = readHumanCutActivation(pending, fact)!;
    for (const patch of [{ extra: true }, { executionId: "not-a-uuid" }, { waitStoppedAt: "2000-01-01T00:00:00.000Z" }]) {
      assert.throws(() => parseHumanCutActivation({ ...activation, ...patch }));
    }
    const activationPath = path.join(fixture.ctx.dir, "human-cut-activations", `${pending.cutAcceptance!.activationHash}.json`);
    const bytes = readFileSync(activationPath);
    writeFileSync(activationPath, JSON.stringify({ ...activation, executionId: randomUUID() }));
    assert.throws(() => readAcceptedCutStatus(fixture.ctx.dir), /identity or clock changed/);
    writeFileSync(activationPath, bytes);
    const forged = writeContentAddressedJsonSync(path.dirname(activationPath), { ...activation, executionId: randomUUID() });
    const jobBytes = readFileSync(fixture.jobPath);
    writeFileSync(fixture.jobPath, JSON.stringify({ ...pending,
      cutAcceptance: { ...pending.cutAcceptance, activationHash: forged.hash } }));
    assert.throws(() => readAcceptedCutStatus(fixture.ctx.dir), /exact verifying journal/);
    writeFileSync(fixture.jobPath, jobBytes);
  } finally { fixture.cleanup(); }
});

test("accepted interrupted Resume preserves the exact durable context and cannot reconcile or fresh-replace it", async () => {
  const fixture = await preparedFixture();
  try {
    const pending = await acceptPending(fixture), interrupted = { ...pending, status: "interrupted" as const };
    writeFileSync(fixture.jobPath, JSON.stringify(interrupted));
    const projectFile = path.join(fixture.root, "project.json"), projectBytes = readFileSync(projectFile);
    const body = buildResumeAutoEditRequest(fixture.ctx.dir, JSON.parse(projectBytes.toString()).intent, "mp4-only", "cut-first");
    const request = prepareRequest(body);
    assert.deepEqual(request.ctx, interrupted.ctx); assert.equal(request.resume, true);
    assert.deepEqual(readFileSync(projectFile), projectBytes);
    assert.equal(producerRun(fixture.ctx.dir, { recover: false })!.workflowPolicy, "cut-first");
    for (const patch of [{ resume: false }, { reviewSavedPlan: true }, { music: true }, { brief: "new treatment" },
      { workflowPolicy: undefined }, { deliveryPolicy: "palmier-hybrid" }]) {
      assert.throws(() => prepareRequest({ ...body, ...patch }));
      assert.deepEqual(readFileSync(projectFile), projectBytes);
    }
    assert.throws(() => startAutoEditJob({ ctx: interrupted.ctx, token: "fresh-bypass", snapshots: 0 }), /cannot be replaced/);
  } finally { fixture.cleanup(); }
});

function assertRecoveryReadback(fixture: Awaited<ReturnType<typeof preparedFixture>>, orphan: ReturnType<typeof observeHumanCutJob>): void {
  const prior = orphan.job.cutAcceptanceAttempt!, recovered = readPendingHumanCutDecision(fixture.ctx.dir);
  assert.equal(recovered.scope, "previously-submitted-human-cut-decision-not-new-approval");
  assert.deepEqual(recovered.submission, fixture.submission);
  assert.equal(observeHumanCutJob(fixture.ctx.dir).sha256, orphan.sha256, "cross-session readback cannot mutate the pending decision");
  const decisionFile = path.join(fixture.ctx.dir, "human-cut-attempts", prior.idempotencyKey, "submission.json");
  const decisionBytes = readFileSync(decisionFile), changed = JSON.parse(decisionBytes.toString());
  changed.submission.idempotencyKey = randomUUID(); writeFileSync(decisionFile, JSON.stringify(changed));
  assert.throws(() => readPendingHumanCutDecision(fixture.ctx.dir), /identity changed/);
  writeFileSync(decisionFile, decisionBytes);
}

test("verification runs without expiring launch/job locks and reobserves actual lease and exact draft before CAS", async () => {
  const fixture = await preparedFixture();
  try {
    const planBytes = readFileSync(fixture.ctx.planPath);
    assert.throws(() => readPendingHumanCutDecision(fixture.ctx.dir), /previously submitted/);
    await assert.rejects(acceptGuidedCut({ dir: fixture.ctx.dir, submission: fixture.submission }, {
      verifySources: async () => {
        assert.ok(!readdirSync(fixture.ctx.dir).includes(".sniper-auto-edit-launch.lock"));
        assert.ok(!readdirSync(fixture.ctx.dir).includes(".sniper-auto-edit-job.json.lock"));
        writeFileSync(fixture.ctx.planPath, Buffer.concat([planBytes, Buffer.from("\n")]));
        await Promise.resolve();
      },
    }), /authority changed/);
    assert.equal(observeHumanCutJob(fixture.ctx.dir).job.cutAcceptance, undefined);
    writeFileSync(fixture.ctx.planPath, planBytes);
    let replacement: { release: () => void } | undefined;
    try {
      await assert.rejects(acceptGuidedCut({ dir: fixture.ctx.dir, submission: fixture.submission }, {
        verifySources: async ({ lease }) => {
          lease.release(); replacement = acquireProjectMutationLease(fixture.root, "test competing lease").lease;
          assert.ok(replacement);
        },
      }), /replaced/);
      assert.equal(observeHumanCutJob(fixture.ctx.dir).job.cutAcceptance, undefined);
      assert.equal(observeHumanCutJob(fixture.ctx.dir).job.cutAcceptanceAttempt!.state, "verifying",
        "lost lease leaves an explicitly incomplete attempt; it cannot write a fabricated terminal result");
    } finally { replacement?.release(); }
    const orphan = observeHumanCutJob(fixture.ctx.dir), prior = orphan.job.cutAcceptanceAttempt!;
    assertRecoveryReadback(fixture, orphan);
    await assert.rejects(acceptGuidedCut({ dir: fixture.ctx.dir,
      submission: { ...fixture.submission, idempotencyKey: randomUUID() } }), /exact retained decision/);
    assert.equal(observeHumanCutJob(fixture.ctx.dir).sha256, orphan.sha256);
    const pending = await acceptPending(fixture), fact = activeHumanCutAcceptance(pending);
    assert.equal(fact.submittedAt, prior.receivedAt, "retry cannot turn the crashed verification gap into human waiting");
    assert.equal(fact.waitStartedAt, orphan.job.cutApprovalWaitStartedAt);
    assert.notEqual(fact.verificationExecutionId, prior.executionId);
    const attempts = path.join(fixture.ctx.dir, "human-cut-attempts", prior.idempotencyKey, "executions");
    assert.equal(existsSync(path.join(attempts, prior.executionId, "result.json")), false,
      "the earlier abandoned execution remains incomplete, not fabricated complete");
    const started = JSON.parse(readFileSync(path.join(attempts, fact.verificationExecutionId, "start.json"), "utf8"));
    assert.equal(started.priorIncompleteExecutionId, prior.executionId);
    assert.equal(started.gapClassification, "unobserved-not-human-wait");
    const activation = readHumanCutActivation(pending, fact)!;
    assert.equal(activation.waitStoppedAt, prior.receivedAt, "orphan verification gap is still not human wait");
    assert.equal(activation.executionId, fact.verificationExecutionId);
    assert.equal(readAcceptedCutStatus(fixture.ctx.dir).waitStoppedAt, prior.receivedAt);
  } finally { fixture.cleanup(); }
});
