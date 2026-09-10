/** Opt-in generated media + real durable routing. TEST admissions/critics/full-plan readiness gate only. */
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { test, type TestContext } from "node:test";
import { withCallerProcessDeadline } from "../caller-process-deadline";
import { createDurablePresenterFixture, reviewDurablePresenter, durablePresenterInput, DURABLE_PRESENTER_RAW } from "./_guided-presenter-durable-fixture";
import { observeGuidedOpeningMediaInput, openingMediaAuthority } from "../guided-opening-media-input";
import { openingImplementation } from "../guided-opening-authority";
import { PRESENTER_OPENING_PROFILE_FILES } from "../guided-opening-profile";
import { PRESENTER_CAPTION_PROFILE } from "@/lib/producer/contracts/guided-presenter-profile";
import { runCutPreviewProcess, CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { canonicalJsonSha256 } from "../auto-edit-hash";

const WORK_MS = 300000;
const COLD = `const {observeGuidedOpeningMediaInput:read}=require('./src/lib/server/guided-opening-media-input.ts');
const r=read(process.argv[1],process.argv[2]); for(const row of Object.values(r.documents)) delete row.bytes;
console.log(JSON.stringify(r));`;
type Evidence = Record<string, unknown>;

function originalRemaining(started: number) {
  let last = started;
  return () => {
    const now = performance.now(), remaining = Math.floor(WORK_MS - (now - started));
    assert.ok(now >= last && remaining > 0, "TEST original whole deadline expired or moved backwards");
    last = now; return remaining;
  };
}

function observeActualGroups(t: TestContext, evidence: Evidence) {
  const actual = process.kill.bind(process), rows: Evidence[] = [];
  evidence.ownedGroupObservations = rows;
  return t.mock.method(process, "kill", (pid: number, signal?: NodeJS.Signals | number) => {
    try {
      const result = actual(pid, signal);
      if (pid < 0 && signal === 0) rows.push({ group: -pid, state: "present" });
      return result;
    } catch (error) {
      if (pid < 0 && signal === 0) rows.push({ group: -pid, state: (error as NodeJS.ErrnoException).code ?? "unknown" });
      throw error;
    }
  });
}

async function checkInput(fixture: Awaited<ReturnType<typeof createDurablePresenterFixture>>, evidence: Evidence, remaining: () => number) {
  const acceptedBytes = readFileSync(fixture.ctx.planPath), started = performance.now();
  const ready = await reviewDurablePresenter(fixture.ctx.dir, remaining);
  evidence.readinessMs = performance.now() - started;
  assert.equal(ready.result.proposal.schemaVersion, 8); assert.equal(ready.evidence.schemaVersion, 8);
  assert.equal(ready.result.executionBindings!.schemaVersion, 2); assert.equal(ready.submission.rawIntent, DURABLE_PRESENTER_RAW);
  assert.equal(openingMediaAuthority(ready).authority.profile, PRESENTER_CAPTION_PROFILE);
  const held = openingImplementation(ready).files.map(row => row.name);
  for (const file of PRESENTER_OPENING_PROFILE_FILES) assert.ok(held.includes(file), file);
  assert.ok(ready.job.ctx.pipeline!.files.some(row => row.path === "src/lib/server/caller-process-deadline.ts"));
  const invocation = await durablePresenterInput(ready, remaining), warm = observeGuidedOpeningMediaInput(invocation.inputPath, invocation.inputSha256);
  assert.equal(Object.keys(warm.documents).length, 14); assert.equal(warm.authority.profile, PRESENTER_CAPTION_PROFILE);
  assert.equal(warm.documents.frameBindings.value.schemaVersion, 2);
  assert.deepEqual(warm.documents.candidatePlan.value.presenterLayouts, (ready.result.executionBindings as { presenterLayouts: unknown }).presenterLayouts);
  const coldResult = await runCutPreviewProcess({ command: process.execPath, args: ["--import", "tsx", "-e", COLD, invocation.inputPath, invocation.inputSha256],
    cwd: process.cwd(), env: { ...process.env, TSX_DISABLE_CACHE: "1" }, timeoutMs: Math.min(60000, remaining()) });
  const expected = { ...warm, documents: Object.fromEntries(Object.entries(warm.documents)
    .map(([name, row]) => [name, { sha256: row.sha256, sizeBytes: row.sizeBytes, value: row.value }])) };
  const cold = JSON.parse(coldResult.stdout); assert.deepEqual(cold, expected);
  assert.equal(cold.sourceBytesObserved, false); assert.equal(cold.currentJournalObserved, false); assert.equal(cold.pipelineFilesObserved, false);
  assert.deepEqual(readFileSync(fixture.ctx.planPath), acceptedBytes);
  for (const file of ["final.mp4", "base.mp4", ".sniper-qc-approved.json"]) assert.equal(existsSync(path.join(fixture.ctx.dir, file)), false);
  evidence.input = invocation.input; evidence.documents = expected.documents; evidence.profile = warm.authority.profile;
  evidence.coldReadHash = canonicalJsonSha256(cold); evidence.currentObservationClaims = { source: false, journal: false, pipelineFiles: false };
}

async function durableCase(input: { workspace: string; evidence: Evidence; remaining: () => number }) {
  const { workspace, evidence, remaining } = input, started = performance.now();
  const fixture = await createDurablePresenterFixture(workspace);
  evidence.fixtureRoot = fixture.root; evidence.setupMs = performance.now() - started;
  await checkInput(fixture, evidence, remaining);
  remaining(); fixture.cleanup(); evidence.fixtureCleaned = !existsSync(fixture.root);
  assert.equal(evidence.fixtureCleaned, true);
}

test("selected actual V8 caption/presenter survives durable readiness and 14-document warm+cold input without rendering", {
  skip: process.env.SNIPER_RUN_V8_PRESENTER_INPUT !== "1", timeout: WORK_MS + 30000,
}, async t => {
  const started = performance.now(), remaining = originalRemaining(started);
  const evidence: Evidence = { startedAt: new Date().toISOString(), workLimitMs: WORK_MS, directChildLimitMs: 60000,
    scope: "TEST-real-durable-routing-not-finishing-eligibility-or-human-approval", source: "real-generated-testsrc2-and-tone-not-ASR",
    stubs: ["admission decode/image facts", "writer", "two cut critics", "two readiness critics", "full-plan readiness gate bundle", "synthetic cut acceptance"],
    real: ["source bytes/hashes", "previsual cut gate", "private cut preview", "raw intake", "proposal advisors/store", "readiness storage", "warm+cold14docinput"],
    nativePreviewTiming: "inherited-owned-parent-group backstop; native leaf timers are NOT all <=60s",
    generatorTiming: "child-local handed remainder only; original parent deadline/group backstop stays authoritative across different clock epochs",
    genuineHumanAcceptance: false, presenterRendered: false, openingApproved: false, bodyGenerated: false, deliveryApproved: false };
  for (const key of ["SNIPER_RENDER_IMAGE_ID", "SNIPER_DOCKER_PATH", "SNIPER_DOCKER_SOCKET"]) assert.equal(process.env[key], undefined, `${key} must be absent`);
  const workspace = mkdtempSync(path.join(realpathSync(tmpdir()), "sniper-v8-presenter-durable-"));
  t.diagnostic(`Retained TEST evidence/workspace: ${workspace}`);
  const observation = observeActualGroups(t, evidence);
  try {
    await withCallerProcessDeadline({ remainingMs: remaining, maxChildMs: 60000, signal: t.signal }, () => durableCase({ workspace, evidence, remaining }));
    remaining(); evidence.state = "passed-test-routing-only";
  } catch (error) {
    evidence.state = "failed-retained-no-retry"; evidence.error = String(error);
    if (error instanceof CutPreviewProcessError) evidence.process = error.details;
    throw error;
  } finally {
    observation.mock.restore(); evidence.elapsedMs = performance.now() - started;
    writeFileSync(path.join(workspace, "TEST-EVIDENCE.json"), JSON.stringify(evidence, null, 2), { flag: "wx", mode: 0o600 });
  }
});
