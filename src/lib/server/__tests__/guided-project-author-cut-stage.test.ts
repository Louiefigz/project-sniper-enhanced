/** Actual stage/writer with TEST-only provider and source/gate/preview boundaries. */
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { test } from "node:test";
import { runAuthorStage } from "@/app/api/producer/auto-edit/authoring-stage";
import { runWriter, authoringWriterGuards } from "@/app/api/producer/auto-edit/authoring-writer";
import type { AuthoringResult } from "@/app/api/producer/auto-edit/authoring";
import { authoredCutStageGuards } from "../guided-project-author-cut-stage";
import { authoredStageFixture, SUCCESS } from "./_guided-project-author-cut-stage-fixture";

test("new authored seed invokes exactly cut/start, guards output before binding, then reviews and pauses", async (t) => {
  const f = authoredStageFixture(t);
  const result = await runAuthorStage(f.run, f.deps);
  assert.equal(result.status, "awaiting_cut_approval");
  assert.deepEqual(f.calls, ["current", "drain", "current", "seed", "writer:cut:start", "draft", "bind-session",
    "current", "drain", "current", "previsual", "current", "drain", "current", "two-critics",
    "current", "drain", "current", "approve-previsual", "current", "drain", "current", "compatibility",
    "current", "drain", "current", "preview", "current", "drain", "current"]);
  assert.equal(f.run.job.cutAcceptance, undefined); assert.equal(f.run.job.guidedHandoffV2, undefined);
  await assert.rejects(runAuthorStage(f.run, f.deps), /new-only/);
  assert.equal(f.calls.filter((call) => call.startsWith("writer:")).length, 1);
});

test("two in-process entries cannot both pass the asynchronous initial ownership check and start writers", async (t) => {
  const f = authoredStageFixture(t);
  const outcomes = await Promise.allSettled([runAuthorStage(f.run, f.deps), runAuthorStage(f.run, f.deps)]);
  assert.equal(outcomes.filter((result) => result.status === "fulfilled").length, 1);
  const rejected = outcomes.find((result) => result.status === "rejected");
  assert.match(String(rejected?.reason), /new-only/);
  assert.equal(f.calls.filter((call) => call.startsWith("writer:")).length, 1);
});

test("wrong policy, replay, accepted/saved/handoff and already-started attempts cannot invoke writer", async (t) => {
  const f = authoredStageFixture(t), original = structuredClone(f.run.job);
  const changes = [{ attempts: 2 }, { status: "failed" }, { reviewSavedPlan: true }, { checkpoint: "authoring" },
    { cutAcceptance: {} }, { cutAcceptanceAttempt: {} }, { cutApprovalRequest: {} }, { cutPreview: {} },
    { guidedHandoffV2: {} }, { cutApprovalWaitStartedAt: new Date().toISOString() }];
  for (const change of changes) {
    f.run.job = { ...structuredClone(original), ...change } as typeof original;
    await assert.rejects(runAuthorStage(f.run, f.deps), /new-only/);
  }
  for (const policy of [null, {}, { ...original.ctx.authoredCut, policy: "supplied-cut" }]) {
    f.run.job = structuredClone(original); f.run.job.ctx.authoredCut = policy as never;
    await assert.rejects(runAuthorStage(f.run, f.deps));
  }
  f.run.job = structuredClone(original); f.run.job.ctx.existingCutCandidate = {} as never;
  await assert.rejects(runAuthorStage(f.run, f.deps));
  assert.deepEqual(f.calls, []);
});

test("seed drift or unresolved existing child ownership fails before first provider invocation", async (t) => {
  const f = authoredStageFixture(t);
  writeFileSync(f.run.job.ctx.planPath, JSON.stringify(f.draft));
  await assert.rejects(runAuthorStage(f.run, f.deps));
  assert.equal(f.calls.some((call) => call.startsWith("writer:")), false);
  writeFileSync(f.run.job.ctx.planPath, JSON.stringify(f.seed));
  t.mock.method(authoredCutStageGuards, "quiescent", async () => { throw new Error("TEST ownership unresolved"); });
  await assert.rejects(runAuthorStage(f.run, f.deps), /ownership unresolved/);
  assert.equal(f.calls.some((call) => call.startsWith("writer:")), false);
});

test("blocked, protocol, provider and ordinary exit failure precede draft checks/binding/normalization", async (t) => {
  const f = authoredStageFixture(t), initial = structuredClone(f.run.job);
  const outcomes: AuthoringResult[] = [
    { ...SUCCESS, blocked: { marker: "CUT_AUTHORING_BLOCKED", reason: "source_timing_review_required" } },
    { ...SUCCESS, timedOut: true, protocolFailure: "TEST malformed root" },
    { ...SUCCESS, providerFailure: "TEST provider error" }, { ...SUCCESS, code: 1, errTail: "TEST exit" }];
  for (const outcome of outcomes) {
    f.run.job = structuredClone(initial); f.calls.length = 0;
    const raw = JSON.stringify({ ...f.draft, graphicsTrack: [{ id: "TEST unauthorized" }] });
    writeFileSync(f.run.job.ctx.planPath, JSON.stringify(f.seed));
    f.deps.author = async () => { writeFileSync(f.run.job.ctx.planPath, raw); return outcome; };
    await assert.rejects(runAuthorStage(f.run, f.deps));
    assert.equal(readFileSync(f.run.job.ctx.planPath, "utf8"), raw);
    assert.equal(f.calls.some((call) => ["draft", "bind-session", "two-critics", "preview"].includes(call)), false);
    assert.equal(f.events.some((event) => ["authoring_done", "authoring_deadline_recovered"].includes(String(event.event))), false);
  }
});

test("eligible successful and timed-out drafts must pass strict source/target/budget guard before binding", async (t) => {
  const f = authoredStageFixture(t), initial = structuredClone(f.run.job);
  t.mock.method(authoringWriterGuards, "authoredDraft", () => { throw new Error("TEST source/target/budget drift"); });
  for (const timedOut of [false, true]) {
    f.run.job = structuredClone(initial); f.calls.length = 0;
    writeFileSync(f.run.job.ctx.planPath, JSON.stringify(f.seed));
    f.deps.author = async () => { f.writeDraft(); return { ...SUCCESS, timedOut, code: timedOut ? 1 : 0 }; };
    await assert.rejects(runAuthorStage(f.run, f.deps), /source\/target\/budget drift/);
    assert.equal(f.calls.includes("bind-session"), false); assert.equal(f.calls.includes("two-critics"), false);
  }
});

test("changed nonblocked timeout retains ordinary preapproval recovery and still runs all gates", async (t) => {
  const f = authoredStageFixture(t);
  f.deps.author = async (_ctx, _send, stage, mode) => {
    f.calls.push(`writer:${stage}:${mode}`); f.writeDraft(); return { ...SUCCESS, timedOut: true, code: 1 };
  };
  assert.equal((await runAuthorStage(f.run, f.deps)).status, "awaiting_cut_approval");
  assert.equal(f.events.filter((event) => event.event === "authoring_deadline_recovered").length, 1);
  assert.ok(f.calls.indexOf("draft") < f.calls.indexOf("bind-session"));
  assert.deepEqual(f.calls.filter((call) => ["previsual", "two-critics", "approve-previsual", "compatibility", "preview"].includes(call)),
    ["previsual", "two-critics", "approve-previsual", "compatibility", "preview"]);
});

test("even a passing draft guard cannot recover a timeout whose plan content did not change", async (t) => {
  const f = authoredStageFixture(t); f.writeDraft();
  f.deps.author = async () => ({ ...SUCCESS, timedOut: true, code: 1 });
  await assert.rejects(runWriter(f.run, f.deps, "cut", "start"), /timed out/);
  assert.equal(f.events.some((event) => event.event === "authoring_deadline_recovered"), false);
});

test("provider returning the original empty seed cannot become an authored draft", async (t) => {
  const f = authoredStageFixture(t);
  f.deps.author = async () => SUCCESS;
  await assert.rejects(runAuthorStage(f.run, f.deps));
  assert.equal(f.calls.includes("bind-session"), false); assert.equal(f.calls.includes("two-critics"), false);
});

test("source/ownership failure between phases or after preview forbids successful handoff", async (t) => {
  const f = authoredStageFixture(t), initial = structuredClone(f.run.job);
  for (const stop of ["previsual", "two-critics", "approve-previsual", "compatibility", "preview"]) {
    f.run.job = structuredClone(initial); f.calls.length = 0;
    writeFileSync(f.run.job.ctx.planPath, JSON.stringify(f.seed));
    t.mock.method(authoredCutStageGuards, "current", () => {
      if (f.calls.includes(stop)) throw new Error(`TEST drift after ${stop}`);
    });
    await assert.rejects(runAuthorStage(f.run, f.deps), /TEST drift/);
    if (stop !== "preview") assert.equal(f.calls.includes("preview"), false);
    assert.equal(f.run.job.cutAcceptance, undefined);
  }
});

test("unresolved ownership after a passing previsual gate cannot reach critics or preview", async (t) => {
  const f = authoredStageFixture(t);
  t.mock.method(authoredCutStageGuards, "quiescent", async () => {
    if (f.calls.includes("previsual")) throw new Error("TEST late ownership unresolved");
  });
  await assert.rejects(runAuthorStage(f.run, f.deps), /late ownership unresolved/);
  assert.equal(f.calls.includes("two-critics"), false); assert.equal(f.calls.includes("preview"), false);
});

test("gate, critic, approval, compatibility and preview failures cannot enter later phases", async (t) => {
  const f = authoredStageFixture(t), initial = structuredClone(f.run.job);
  for (const phase of ["validateCut", "reviewCut", "approveCut"] as const) {
    f.run.job = structuredClone(initial); f.calls.length = 0;
    writeFileSync(f.run.job.ctx.planPath, JSON.stringify(f.seed));
    const failure = t.mock.method(f.deps, phase, async () => { throw new Error(`TEST ${phase} failure`); });
    await assert.rejects(runAuthorStage(f.run, f.deps), /TEST .* failure/); failure.mock.restore();
    assert.equal(f.calls.includes("preview"), false);
  }
  f.run.job = structuredClone(initial); writeFileSync(f.run.job.ctx.planPath, JSON.stringify(f.seed));
  t.mock.method(authoredCutStageGuards, "boundary", async () => null);
  await assert.rejects(runAuthorStage(f.run, f.deps), /qualified preview PAUSE/);
});
