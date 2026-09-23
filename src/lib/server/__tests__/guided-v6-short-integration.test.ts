/** Opt-in actual source/bootstrap/preview/gates fixture; no creator ASR or approval. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";
import { pythonInterpreter, SCRIPTS_DIR } from "@/app/api/_lib/spawn-python";
import { parseBootstrapRequest, assertBootstrapIntent } from "../guided-project-bootstrap-contract";
import { parseTreatmentProposalV6 } from "@/lib/producer/contracts/treatment-proposal-v6";
import { assertProposalClauseCoverage } from "@/lib/producer/contracts/treatment-proposal-v2";
import { CURRENT_TREATMENT_PROPOSAL_VERSION } from "@/lib/producer/contracts/treatment-proposal-v5";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { createV6ShortBootstrapFixture } from "./_guided-v6-short-fixture";
import { compileV6ShortReadiness, v6ShortProposal, RAW_V6_SHORT, CROP } from "./_guided-v6-short-proposal";
import { prepareV6ShortInput } from "./_guided-v6-short-input";
import type { ProposalBrainInput } from "../guided-proposal-compiler";

function description() {
  const producer = path.join(SCRIPTS_DIR, "producer");
  return JSON.parse(execFileSync(pythonInterpreter(), [path.join(producer, "tests/_guided_v6_short_source.py"), "--describe"],
    { encoding: "utf8", timeout: 10_000, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1",
      PYTHONPATH: `${producer}${path.delimiter}${path.join(producer, "tests")}` } }));
}

test("V6 TEST begins with exact short/light intent and four previsual fields, never inherited geometry", () => {
  const docs = description(), { plan, intent } = docs;
  assert.deepEqual(Object.keys(plan).sort(), ["cutDecisions", "cutTrack", "planVersion", "target"]);
  assert.deepEqual(intent, { mode: "short", scope: "light", lanes: { captions: "auto", motion: "off", graphics: "off" } });
  const request = parseBootstrapRequest({ schemaVersion: 1, operation: "bootstrap-existing-cut",
    idempotencyKey: "00000000-0000-4000-8000-000000000001", intent,
    manifest: { path: "/TEST-not-observed/manifest.json", sha256: "a".repeat(64) },
    candidate: { path: "/TEST-not-observed/plan.json", sha256: "b".repeat(64) } });
  assert.deepEqual(request.intent, intent);
  assertBootstrapIntent(plan, request.intent);
  assert.equal(plan.cutTrack[0].end, 16); assert.equal(plan.target.fps, 30);
  assert.equal(docs.transcript.transcript[0].words.at(-1).end, 16);
  assert.match(docs.transcript.testOnly, /no ASR/);
  assert.equal(CURRENT_TREATMENT_PROPOSAL_VERSION, 5, "V6 remains internal qualification-only");
});

test("V6 TEST proposal retains separate original crop and caption clauses without graphics or a surrogate", () => {
  const evidence = { schemaVersion: 6, target: { mode: "short", width: 1080, height: 1920 },
    totalFrames: 480, frameRate: "30/1", anchors: [0, 240, 480] };
  const input = { prompt: `TEST ONLY\nINPUT_DATA_JSON\n${JSON.stringify({ evidence })}` } as ProposalBrainInput;
  const proposal = parseTreatmentProposalV6(v6ShortProposal(input));
  assertProposalClauseCoverage(proposal, RAW_V6_SHORT);
  assert.deepEqual(proposal.operations.map((row) => [row.type, row.clauseIndex]),
    [["reframe-manual-short", 0], ["captions-full-program", 1]]);
  assert.deepEqual(proposal.operations[0].reframe?.crop, CROP);
  assert.equal(proposal.operations[1].captions?.suppression, "none");
});

test("actual graphics advisors honor initial off lanes with no media or measured capability assertion", () => {
  const docs = description(), root = realpathSync(mkdtempSync(path.join(tmpdir(), "sniper-v6-advice-metadata-")));
  const planPath = path.join(root, "TEST-plan.json"), manifestPath = path.join(root, "TEST-manifest.json");
  writeFileSync(planPath, JSON.stringify(docs.plan), { flag: "wx" });
  writeFileSync(path.join(root, "TEST-transcript.json"), JSON.stringify(docs.transcript), { flag: "wx" });
  writeFileSync(manifestPath, JSON.stringify({ sources: [{ id: "raw-1", transcriptPath: "TEST-transcript.json" }] }), { flag: "wx" });
  const producer = path.join(SCRIPTS_DIR, "producer"), options = { encoding: "utf8" as const, timeout: 10_000,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONPATH: producer } };
  const style = JSON.parse(execFileSync(pythonInterpreter(), [path.join(producer, "graphics_style_advisor.py"), planPath, root, manifestPath], options));
  assert.equal(style.recommendedTargetFields.graphicsStyle, "catalog-first");
  const advicePath = path.join(root, "TEST-advice-plan.json");
  writeFileSync(advicePath, JSON.stringify({ ...docs.plan, target: { ...docs.plan.target, ...style.recommendedTargetFields } }), { flag: "wx" });
  const advice = JSON.parse(execFileSync(pythonInterpreter(), [path.join(producer, "graphics_planner.py"), advicePath, root, manifestPath,
    "--json", "--style", style.recommendedTargetFields.graphicsStyle], options));
  assert.deepEqual(advice.candidates, []); assert.deepEqual(advice.introSemanticBeats, []);
  assert.equal(advice.meta.candidateCount, 0); assert.equal(docs.plan.target.lanes.graphics, "off");
  assert.deepEqual(advice.zoom.punchIns, []); assert.deepEqual(advice.treatmentMap, []);
  writeFileSync(path.join(root, "TEST-advice-evidence.json"), JSON.stringify({ scope: "metadata-only-not-media-admission-or-capability", style, advice }), { flag: "wx" });
});

test("actual fresh V6 bootstrap to cut preview, TEST acceptance, real readiness and both14-document readers", {
  skip: process.env.SNIPER_RUN_V6_SHORT_INTEGRATION !== "1", timeout: 600_000,
}, async (t) => {
  const began = performance.now();
  const remainingMs = () => {
    const remaining = Math.floor(600_000 - (performance.now() - began));
    if (t.signal.aborted || remaining < 1000) throw new Error("Original10-minute TEST window expired; no retry or fresh clock");
    return remaining;
  };
  const fixture = await createV6ShortBootstrapFixture(t, remainingMs);
  const savedBefore = readFileSync(path.join(fixture.dir, "edit_plan.json"));
  try {
    const readiness = await compileV6ShortReadiness(fixture.dir, remainingMs);
    const input = await prepareV6ShortInput(fixture.dir, remainingMs), docs = input.observed.documents;
    assert.equal(Object.keys(docs).length, 14); assert.equal(readiness.result.proposal.schemaVersion, 6);
    assert.equal(Object.hasOwn(docs.acceptedPlan.value, "reframe"), false);
    assert.equal(Object.hasOwn(docs.acceptedPlan.value, "captions"), false);
    assert.deepEqual(docs.candidatePlan.value.reframe, { layout: "fill", crop: CROP, track: false });
    assert.deepEqual(docs.candidatePlan.value.captions, { burn: true });
    assert.deepEqual(docs.candidatePlan.value.cutTrack, docs.acceptedPlan.value.cutTrack);
    assert.equal(canonicalJsonSha256(docs.candidatePlan.value.cutDecisions), canonicalJsonSha256(docs.acceptedPlan.value.cutDecisions));
    assert.deepEqual(readFileSync(path.join(fixture.dir, "edit_plan.json")), savedBefore);
    assert.equal(observeHumanCutJob(fixture.dir).job.status, "treatment_admitted");
    assert.equal(existsSync(path.join(input.operation.execution, "media-output")), false);
    assert.equal(existsSync(path.join(fixture.dir, "final.mp4")), false);
    writeFileSync(path.join(fixture.workspace, "TEST-V6-INTEGRATION.json"), JSON.stringify({
      scope: "TEST-real-bootstrap-and-readiness-input-not-opening-render-or-delivery", elapsedMs: performance.now() - began,
      dir: fixture.dir, inputPath: input.invocation.inputPath, inputSha256: input.invocation.inputSha256,
      critics: "Two TEST cut critics and two TEST readiness critics", realSourceAdmission: true, gatesWaived: false,
      actualAsr: false, genuineHumanAcceptance: false, detachedWorkerQualified: false, openingRendered: false,
    }), { flag: "wx", mode: 0o600 });
  } catch (error) {
    writeFileSync(path.join(fixture.workspace, "TEST-V6-FAILURE.json"), JSON.stringify({ elapsedMs: performance.now() - began,
      error: String(error), stack: error instanceof Error ? error.stack : null, genuineHumanAcceptance: false }), { flag: "wx", mode: 0o600 });
    throw error;
  }
});
