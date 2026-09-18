/** Actual input/compiler/store reconstruction; synthetic footage and provider, never creative approval. */
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { createGuidedProposalFixture } from "./_guided-proposal-fixture";
import { readGuidedTreatmentProposal } from "../guided-proposal-store";
import { readHistoricalGuidedProposal } from "../guided-proposal-history";
import { buildTreatmentCandidate } from "../guided-proposal-candidate";
import { buildProposalReadinessPacket } from "../guided-proposal-review-packet";
import { assertFullProgramMediaMetadata } from "../guided-opening-media-input";
import { parseTreatmentProposalV9, type TreatmentProposalV9 } from "@/lib/producer/contracts/treatment-proposal-v9";
import { buildCodexArgs, type CodexRunOptions } from "@/app/api/_lib/codex-cli";
import type { ProposalBrainInput } from "../guided-proposal-compiler";
import type { ProposalEvidence } from "../guided-proposal-evidence";
import { writeGuidedNativeProject } from "../guided-native-project-store";
import { buildNativeShortProjectFiles } from "../guided-native-project";
import type { NativeShortDirection } from "../guided-native-candidate";
import { buildNativeTreatmentCandidate } from "../guided-native-candidate";
import { buildProposalPrompt, runProposalBrain } from "../guided-proposal-compiler";
import { nativeReferenceImages, stageNativeReferences } from "../guided-native-references";
import { nativeDirectorTestBrain } from "./_native-director-fixture";

const RAW = "Preserve the cut and caption every word; illustrate the explanation with a persistent message reveal.";
function output(input: ProposalBrainInput): TreatmentProposalV9 {
  assert.match(input.prompt, /VISUAL EXPLANATION — shared directing standard v1/);
  assert.match(input.prompt, /SHORT FORMAT ADAPTATION/);
  const evidence: ProposalEvidence = JSON.parse(input.prompt.split("INPUT_DATA_JSON\n")[1]).evidence;
  assert.equal(evidence.nativeDirector?.review.verdict, "pass", "Director must finish before the scene worker");
  assert.equal(evidence.nativeDirector?.plan.fills.length, 2);
  assert.equal(input.imagePaths?.length, 3);
  for (const file of input.imagePaths!) assert.ok(readFileSync(file).length > 1000);
  const last = evidence.anchors.length - 1, word = evidence.occurrences[2];
  return parseTreatmentProposalV9({ schemaVersion: 9, summary: "TEST ONLY native directing mechanics.",
    clauses: [{ start: 0, end: RAW.length, quote: RAW, disposition: "supported", rationale: "TEST ONLY complete native request.", operationIndices: [0] }],
    beats: [{ startAnchor: 0, endAnchorExclusive: last, purpose: "opening", summary: "TEST complete source.", supportsBeatIndices: [] }],
    operations: [{ type: "native-scene", clauseIndex: 0, beatIndex: 0, scene: { id: "explain", startAnchor: 0, endAnchorExclusive: last,
      mechanism: "message-reveal", view: "presenter-illustration", question: "Can this be clearer?", object: "Original illustrative message exchange",
      quote: evidence.occurrences.map((row) => row[5]).join(" "), occurrenceIds: evidence.occurrences.map((row) => row[0]),
      referenceIds: ["N26-B05"], referenceReason: "TEST persistent container while the explanatory object develops; reference pixels are not reused.",
      requiredAssetIds: [], before: ["This"], steps: [{ anchor: evidence.anchors.indexOf(word[3]), occurrenceId: word[0], text: "Clearer", transitionFrames: 4 }],
      result: ["This", "Clearer"], readingHoldFrames: 30, rationale: "TEST develops in place, preserving context through the result hold." } }],
    openingEndAnchor: last, continuityEndAnchor: last, audioPolicy: "preserve-full-program", colorPolicy: "preserve" });
}

function assertRejected(held: ReturnType<typeof readGuidedTreatmentProposal>, change: (value: TreatmentProposalV9) => void, pattern: RegExp) {
  const proposal = parseTreatmentProposalV9(held.result.proposal); change(proposal);
  const compile = () => buildTreatmentCandidate({ cut: { ...held, receipt: held.cutReceipt }, rawIntent: RAW, evidence: held.evidence, output: proposal });
  try {
    const result = compile(); assert.equal(result.candidate, null); assert.match(JSON.stringify(result.blockers), pattern);
  } catch (error) { assert.match(String(error), pattern); }
}

test("native direction reaches the worker, immutable store, cold reader and explicit execution fence", { timeout: 180_000 }, async () => {
  const deadline = performance.now() + 180_000;
  const remainingMs = () => Math.max(1, Math.floor(deadline - performance.now()));
  const fixture = await createGuidedProposalFixture({ proposalVersion: 9, rawIntent: RAW, output,
    nativeReferences: [{ caseId: "N26", beatId: "N26-B05" }] });
  try {
    const held = readGuidedTreatmentProposal(fixture.ctx.dir);
    assert.deepEqual(held.result.blockers, []); assert.ok(held.result.candidate);
    assert.equal(held.result.candidate.executionRoute, "native-short-v1");
    assert.deepEqual(held.result.candidate.cutTrack, held.plan.value.cutTrack);
    assert.deepEqual(readGuidedTreatmentProposal(fixture.ctx.dir).result, held.result);
    assert.equal(readHistoricalGuidedProposal(fixture.ctx.dir).proposalVersion, 9);
    await assert.rejects(writeGuidedNativeProject(fixture.ctx.dir, remainingMs), /visual strategy.*geometry/);
    assertScopedRevision(held);
    for (const id of ["native-short", "source-cut-0", "dialogue-cut-0", "caption-0", "word-0"]) {
      assertRejected(held, (value) => { value.operations[0].scene.id = id; }, /reserved.*namespace/);
    }
    assert.throws(() => buildProposalReadinessPacket(held), /native audiovisual review/);
    assert.throws(() => assertFullProgramMediaMetadata({ plan: held.result.candidate!, bindings: null, proposal: held.result.proposal }), /legacy opening\/body/);
    assertRejected(held, (value) => { value.operations[0].scene.steps[0].anchor++; }, /exact retained word/);
    assertRejected(held, (value) => { value.operations[0].scene.steps = []; }, /action|result/);
    assertRejected(held, (value) => { value.operations[0].scene.requiredAssetIds = ["actual-customer-dm"]; }, /Required story assets/);
    assertRejected(held, (value) => { value.operations[0].scene.readingHoldFrames = 100; }, /reading hold/);
    assertRejected(held, (value) => { value.operations[0].scene.quote = "Invented source words"; }, /reproduce contiguous/);
    assertRejected(held, (value) => { value.operations = []; value.clauses[0].operationIndices = []; }, /Supported clauses/);
    const execution = path.join(fixture.ctx.dir, "guided-v2-operations", held.compileSubmission.idempotencyKey, "executions", String(held.receipt.executionId));
    const image = path.join(execution, "candidate-inputs", held.evidence.nativeReferences![0].images[0].file);
    const original = readFileSync(image); writeFileSync(image, Buffer.from("changed test snapshot"));
    assert.throws(() => readGuidedTreatmentProposal(fixture.ctx.dir), /reference image changed/);
    writeFileSync(image, original);
  } finally { fixture.cleanup(); }
});

function assertScopedRevision(held: ReturnType<typeof readGuidedTreatmentProposal>) {
  const original = held.result.candidate!, changed = structuredClone(original);
  const direction = changed.nativeDirection as NativeShortDirection;
  direction.scenes[0].direction.steps[0].text = "Much clearer";
  direction.scenes[0].direction.result[1] = "Much clearer";
  direction.scenes[0].steps[0].text = "Much clearer";
  const media = [{ sourceId: "raw-1", file: `assets/${"a".repeat(64)}.mp4`, sha256: "a".repeat(64) }];
  const groups = direction.occurrences.map((row) => [row[0]]);
  assert.throws(() => buildNativeShortProjectFiles(original, media, groups), /visual strategy.*geometry/);
  assert.throws(() => buildNativeShortProjectFiles(changed, media, groups), /visual strategy.*geometry/);
  const stale = structuredClone(original); (stale.cutTrack as Array<{ start: number }>)[0].start += 0.1;
  assert.throws(() => buildNativeShortProjectFiles(stale, media, groups), /accepted cut identity/);
}

test("image attachments are explicit CLI arguments without granting tools", () => {
  const args = buildCodexArgs({ sandbox: "read-only", timeoutMs: 1000, tools: "none", imagePaths: ["/tmp/selected reference.jpg"] });
  assert.equal(args[args.indexOf("--image") + 1], "/tmp/selected reference.jpg");
  assert.ok(args.includes("shell_tool")); assert.equal(args.at(-1), "-");
  assert.throws(() => buildCodexArgs({ sandbox: "read-only", timeoutMs: 1000, imagePaths: ["relative.jpg"] }), /absolute/);
});

test("Director rejection prevents the native scene worker from being called", { timeout: 180_000 }, async () => {
  let sceneCalls = 0;
  await assert.rejects(createGuidedProposalFixture({ proposalVersion: 9, rawIntent: RAW,
    nativeReferences: [{ caseId: "N26", beatId: "N26-B05" }],
    output: (input) => { sceneCalls++; return output(input); },
    directorBrain: async (input) => {
      const result = await nativeDirectorTestBrain(input);
      if (input.phase === "critic") Object.assign(result.output, { verdict: "revise", findings: ["TEST unsupported hook promise."] });
      return result;
    } }), /Director critique blocked/);
  assert.equal(sceneCalls, 0, "No native scene work may start after a rejected Director plan");
});

/** Synthetic source-clock fixture for policy boundaries; no media or creative-quality claim. */
function policyFixture() {
  const target = { mode: "short", width: 1080, height: 1920, music: false,
    lanes: { captions: "auto", graphics: "auto", motion: "auto" } };
  const plan = { target, cutTrack: [{ sourceId: "test", start: 0, end: 10, speed: 1 }] };
  const evidence = { schemaVersion: 9, target, frameRate: "30/1", totalFrames: 300,
    timelineMapHash: "a".repeat(64), anchors: [0, 30, 60, 90, 300], cleanEnds: [90],
    segments: [{ index: 0, sourceId: "test", startFrame: 0, endFrameExclusive: 300, text: "One change holds." }],
    occurrences: [[0, 0, 0, 0, 30, "One", 0], [1, 0, 1, 30, 60, "change", 0], [2, 0, 2, 60, 90, "holds.", 0]],
    nativeReferences: [{ id: "TEST", images: [{ file: "TEST-not-media.jpg" }] }],
  } as unknown as ProposalEvidence;
  const scene = { id: "test-hold", startAnchor: 0, endAnchorExclusive: 4, mechanism: "message-reveal", view: "presenter-illustration",
    question: "What changes?", object: "TEST illustration", quote: "One change holds.", occurrenceIds: [0, 1, 2], referenceIds: ["TEST"],
    referenceReason: "TEST policy boundary only.", requiredAssetIds: [], before: ["One"],
    steps: [{ anchor: 1, occurrenceId: 1, text: "Change", transitionFrames: 4 }], result: ["One", "Change"], readingHoldFrames: 210,
    rationale: "TEST seven-second result hold has no template-swap quota." };
  const proposal = parseTreatmentProposalV9({ schemaVersion: 9, summary: "TEST long hold.",
    clauses: [{ start: 0, end: 4, quote: "Hold", disposition: "supported", rationale: "TEST exact request", operationIndices: [0] }],
    beats: [{ startAnchor: 0, endAnchorExclusive: 4, purpose: "opening", summary: "TEST complete beat", supportsBeatIndices: [] }],
    operations: [{ type: "native-scene", clauseIndex: 0, beatIndex: 0, scene }], openingEndAnchor: 4, continuityEndAnchor: 4,
    colorPolicy: "preserve", audioPolicy: "preserve-full-program" });
  return { plan, evidence, output: proposal, rawIntent: "Hold" };
}

test("native holds follow authored reading time, and a presenter hold needs no compulsory graphic", () => {
  const input = policyFixture();
  assert.deepEqual(buildNativeTreatmentCandidate(input).blockers, []);
  const scene = input.output.operations[0].scene;
  scene.mechanism = "presenter-hold"; scene.view = "presenter"; scene.before = []; scene.steps = []; scene.result = []; scene.readingHoldFrames = 0;
  assert.deepEqual(buildNativeTreatmentCandidate(input).blockers, []);
});

test("scene-generated mount identities cannot collide with another scene", () => {
  const input = policyFixture(), scene = input.output.operations[0].scene;
  scene.mechanism = "presenter-hold"; scene.view = "presenter"; scene.before = []; scene.steps = []; scene.result = []; scene.readingHoldFrames = 0;
  scene.id = "another-slot"; scene.endAnchorExclusive = 2; scene.occurrenceIds = [0, 1]; scene.quote = "One change";
  const other = { ...structuredClone(scene), id: "another", startAnchor: 2, endAnchorExclusive: 4, occurrenceIds: [2], quote: "holds." };
  input.output.operations.push({ type: "native-scene", clauseIndex: 0, beatIndex: 0, scene: other });
  input.output.clauses[0].operationIndices.push(1);
  const result = buildNativeTreatmentCandidate(input);
  assert.equal(result.candidate, null); assert.match(result.blockers[0].reason, /element identities collide/);
});

test("native executor cannot override off/operator lanes or a music request", () => {
  for (const lane of ["captions", "graphics", "motion"] as const) {
    for (const owner of ["off", "operator"]) {
      const input = policyFixture(); input.evidence.target.lanes = { ...input.plan.target.lanes, [lane]: owner };
      assert.throws(() => buildNativeTreatmentCandidate(input), /ownership/);
    }
  }
  const input = policyFixture(); input.evidence.target.music = true;
  assert.throws(() => buildNativeTreatmentCandidate(input), /music-enabled/);
});

test("native worker validates the exact attachment set before a provider call", async () => {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-native-images-")));
  const prior = process.env.SNIPER_BRAIN_PROVIDER;
  try {
    process.env.SNIPER_BRAIN_PROVIDER = "codex";
    const inputs = path.join(directory, "candidate-inputs"); mkdirSync(inputs);
    const references = stageNativeReferences(inputs, [{ caseId: "N26", beatId: "N26-B05" }]);
    const fixture = policyFixture(), evidence = { ...fixture.evidence, nativeReferences: references };
    const input: ProposalBrainInput = { cwd: directory, ctx: {} as ProposalBrainInput["ctx"], timeoutMs: 1000,
      prompt: buildProposalPrompt("Hold", evidence), imagePaths: nativeReferenceImages(directory, references),
      schema: JSON.parse(readFileSync("schemas/producer/treatment-proposal-v9.schema.json", "utf8")) };
    let calls = 0;
    const deps = { codex: async (options: CodexRunOptions) => {
      calls++; assert.deepEqual(options.imagePaths, input.imagePaths); assert.equal(options.tools, "none");
      return { message: JSON.stringify(fixture.output), stderr: "", ms: 1 };
    } };
    await runProposalBrain(input, deps); assert.equal(calls, 1);
    await assert.rejects(runProposalBrain({ ...input, imagePaths: input.imagePaths!.slice(1) }, deps), /frozen prompt evidence/);
    await assert.rejects(runProposalBrain({ ...input, prompt: input.prompt.replace('"N26-B05"', '"N26-B09"') }, deps), /frozen prompt evidence/);
    process.env.SNIPER_BRAIN_PROVIDER = "legacy";
    await assert.rejects(runProposalBrain(input, deps), /no text-only fallback/);
    assert.equal(calls, 1, "Substitution and unsupported providers must fail before dispatch");
  } finally {
    if (prior === undefined) delete process.env.SNIPER_BRAIN_PROVIDER; else process.env.SNIPER_BRAIN_PROVIDER = prior;
    rmSync(directory, { recursive: true, force: true });
  }
});
