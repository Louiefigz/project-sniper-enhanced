/** TEST ONLY candidate/controller metadata and stubbed providers; never real editorial or media approval. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { buildCodexArgs } from "@/app/api/_lib/codex-cli";
import { PRESENTER_RAW, oldOperation } from "@/lib/producer/__tests__/_presenter-layout-fixture";
import { CURRENT_TREATMENT_PROPOSAL_VERSION } from "@/lib/producer/contracts/treatment-proposal-v5";
import { parseTreatmentProposalV8 } from "@/lib/producer/contracts/treatment-proposal-v8";
import { presenterFixture, presenterProposal, layoutOperation, type Row } from "./_guided-proposal-presenter-fixture";
import { buildTreatmentCandidate } from "../guided-proposal-candidate";
import { assertGuidedFrameBindings } from "../guided-proposal-bindings";
import { buildProposalPrompt, runProposalBrain } from "../guided-proposal-compiler";
import { GUIDED_CAPTION_CONFIG_FILES, guidedCaptionPolicy } from "../guided-proposal-captions";
import { guidedMusicPolicy } from "../guided-proposal-music";
import { guidedPresenterPolicy, assertGuidedPresenterCandidate } from "../guided-proposal-presenter";
import { buildProposalReadinessPacket, type ReviewedProposalInput } from "../guided-proposal-review-packet";
import { openingMediaAuthority, assertFullProgramMediaMetadata } from "../guided-opening-media-input";
import type { OpeningReadiness } from "../guided-opening-authority";
import type { ProposalEvidence } from "../guided-proposal-evidence";
import type { AcceptedGuidedCut } from "../guided-raw-treatment-store";
import { canonicalJsonSha256 } from "../auto-edit-hash";

/** Declared metadata fixture only; the real stored-evidence reader must independently observe source clocks. */
function candidateFixture() {
  const f = presenterFixture();
  const evidence = { ...f.evidence, schemaVersion: 8, cleanEnds: [600], occurrences: [], catalog: [],
    timelineMapHash: "c".repeat(64), introSeams: [], hookWindowS: 60,
    graphicsAdvice: { "graphics_planner.py": { introSemanticBeats: [] } },
    captionPolicy: guidedCaptionPolicy(GUIDED_CAPTION_CONFIG_FILES.map(name => ({ name, sha256: "d".repeat(64) }))),
    musicPolicy: guidedMusicPolicy(f.plan, f.manifest), presenterPolicy: f.policy } as unknown as ProposalEvidence;
  const target = f.plan.target as Row;
  const cut = { plan: { value: f.plan }, manifest: { value: f.manifest },
    job: { ctx: { intent: { scope: target.scope, lanes: target.lanes } } } } as unknown as AcceptedGuidedCut;
  return { ...f, cut, evidence, output: f.proposal, rawIntent: PRESENTER_RAW };
}

test("actual V8 candidate retains source-bound layouts separately from graphics without changing cuts/audio", () => {
  const f = candidateFixture(), before = structuredClone(f.plan), result = buildTreatmentCandidate(f);
  assert.deepEqual(result.blockers, []); assert.ok(result.candidate);
  assert.equal(result.proposal.schemaVersion, 8);
  assert.deepEqual(result.proposal, f.output); assert.deepEqual(f.plan, before);
  assertGuidedPresenterCandidate({ accepted: f.plan, candidate: result.candidate, manifest: f.manifest,
    proposal: f.proposal, evidence: f.evidence });
  for (const key of ["cutTrack", "cutDecisions", "audioGain", "captions", "captionsTrack", "unrelated"]) {
    assert.deepEqual(result.candidate[key], before[key], key);
  }
  const bindings = result.executionBindings; assert.ok(bindings); assert.equal(bindings.schemaVersion, 2);
  if (bindings.schemaVersion !== 2) throw new Error("Expected actual V2 bindings");
  assert.deepEqual(bindings.graphics, []); assert.deepEqual(bindings.presenterLayouts, result.candidate.presenterLayouts);
  assert.equal(bindings.presenterLayouts[0].operationIndex, 0);
  assert.deepEqual(bindings.presenterLayouts[0].layout.sourceIds, ["raw-2", "raw-1"]);
  assert.equal(bindings.candidatePlanHash, canonicalJsonSha256(result.candidate));
  assert.equal(Object.hasOwn(result, "executable"), false); assert.equal(result.range!.executable, false);
});

test("frame bindings independently rederive actual V8 indices, source identity and timing after a candidate is rehashed", () => {
  const f = candidateFixture(), result = buildTreatmentCandidate(f); assert.ok(result.candidate);
  const input = { proposal: f.proposal, evidence: f.evidence, candidate: result.candidate, inheritedCount: 0 };
  assertGuidedFrameBindings(input, result.executionBindings);
  for (const patch of [{ operationIndex: 7 }, { startFrame: 41 }, { endFrameExclusive: 559 },
    { layout: { ...f.proposal.operations[0].presenterLayout, sourceIds: ["raw-1", "raw-2"] } }]) {
    const candidate = structuredClone(result.candidate);
    candidate.presenterLayouts = [(candidate.presenterLayouts as Row[]).map(row => ({ ...row, ...patch }))[0]];
    const binding = { ...result.executionBindings, candidatePlanHash: canonicalJsonSha256(candidate), presenterLayouts: candidate.presenterLayouts };
    assert.throws(() => assertGuidedFrameBindings({ ...input, candidate }, binding), /actual requested/);
  }
  for (const binding of [{ ...result.executionBindings, schemaVersion: 1 }, { ...result.executionBindings, presenterLayouts: [] },
    { ...result.executionBindings, sourceFramingObserved: true }]) {
    assert.throws(() => assertGuidedFrameBindings(input, binding), /bindings changed/);
  }
});

test("changed V8 policy, accepted intent, source occurrences and missing assets block before authoring a layout", () => {
  const f = candidateFixture();
  assert.throws(() => buildTreatmentCandidate({ ...f, evidence: { ...f.evidence, schemaVersion: 7 } }), /exact versioned/);
  assert.throws(() => buildTreatmentCandidate({ ...f, evidence: { ...f.evidence, presenterPolicy: undefined } }), /exact admitted-project/);
  const output = presenterProposal([layoutOperation({ startAnchor: 2, endAnchorExclusive: 28,
    presenterLayout: { ...f.proposal.operations[0].presenterLayout, sourceIds: ["raw-1"] } })]);
  const altered = [buildTreatmentCandidate({ ...f, output }),
    buildTreatmentCandidate({ ...f, evidence: { ...f.evidence, presenterPolicy: { ...f.policy, acceptedMotionEnabled: false } } }),
    buildTreatmentCandidate({ ...f, cut: { ...f.cut, manifest: { ...f.cut.manifest, value: { ...f.manifest, broll: [] } } } }),
    buildTreatmentCandidate({ ...f, cut: { ...f.cut, job: { ...f.cut.job,
      ctx: { ...f.cut.job.ctx, intent: { ...f.cut.job.ctx.intent, scope: "full" } as unknown as AcceptedGuidedCut["job"]["ctx"]["intent"] } } } })];
  for (const result of altered) { assert.equal(result.candidate, null); assert.ok(result.blockers.length); }
});

test("mixed layout, music, captions and catalog operations retain the actual array indices", () => {
  const f = candidateFixture(), target = { ...(f.plan.target as Row), music: true };
  const plan: Row = { ...f.plan, target }; delete plan.captions; delete plan.captionsTrack;
  const manifest = { ...f.manifest, music: [{ id: "music-1", path: "/TEST/snapshot.wav", originalPath: "/TEST/original.wav",
    sourceSha256: "e".repeat(64), sourceSizeBytes: 8000, admissionReceiptPath: "/TEST/receipt.json",
    admissionReceiptSha256: "f".repeat(64), duration: 5 }] };
  const graphic = layoutOperation({ type: "catalog-graphic", presenterLayout: null, catalogKind: "TEST-card",
    variables: [{ name: "title", value: "TEST ONLY slide" }], startAnchor: 0, endAnchorExclusive: 2,
    presentation: { schemaVersion: 1, anchor: "own-screen", placement: "full-canvas", compositeMode: "normal",
      baseTreatment: "preserve", rationale: "TEST ONLY native full-canvas picture declaration." } });
  const output = presenterProposal([oldOperation("music-bed-full-program"), oldOperation("captions-full-program"),
    layoutOperation({ startAnchor: 2, endAnchorExclusive: 28 }), graphic]);
  const evidence = { ...f.evidence, target, musicPolicy: guidedMusicPolicy(plan, manifest),
    presenterPolicy: guidedPresenterPolicy(plan, manifest),
    catalog: [{ kind: "TEST-card", canvas: [1920, 1080], defaults: { title: "TEST" }, fields: ["title"] }] };
  const cut = { ...f.cut, plan: { ...f.cut.plan, value: plan }, manifest: { ...f.cut.manifest, value: manifest },
    job: { ...f.cut.job, ctx: { ...f.cut.job.ctx, intent: { ...f.cut.job.ctx.intent, music: true } } } };
  const result = buildTreatmentCandidate({ ...f, cut, evidence, output });
  assert.deepEqual(result.blockers, []); assert.ok(result.candidate);
  assert.deepEqual(result.proposal.operations.map(row => row.type), output.operations.map(row => row.type));
  assert.equal(result.executionBindings!.graphics[0].operationIndex, 3);
  assert.equal(result.executionBindings!.schemaVersion, 2);
  if (result.executionBindings!.schemaVersion !== 2) throw new Error("Expected V2 bindings");
  assert.equal(result.executionBindings!.presenterLayouts[0].operationIndex, 2);
  assert.deepEqual(result.candidate.music, { enabled: true, assetId: "music-1", gapDb: 11, duck: true });
  assert.deepEqual(result.candidate.captions, { burn: true });
  assert.deepEqual(result.candidate.cutTrack, plan.cutTrack); assert.deepEqual(result.candidate.audioGain, plan.audioGain);
});

test("V8 prompt and schema registration stay read-only, subscription-routed and explicitly not renderer availability", async () => {
  const f = candidateFixture(), prompt = buildProposalPrompt(PRESENTER_RAW, f.evidence);
  assert.match(prompt, /presenter-layout-window/); assert.match(prompt, /accepted motion AND broll/);
  assert.match(prompt, /NOT detected face bounds/); assert.match(prompt, /not connected to the owned opening\/body renderer/);
  assert.match(prompt, /assetAudio:\"discard\"/); assert.equal(CURRENT_TREATMENT_PROPOSAL_VERSION, 5);
  const schema = JSON.parse(readFileSync("schemas/producer/treatment-proposal-v8.schema.json", "utf8"));
  const prior = process.env.SNIPER_BRAIN_PROVIDER; process.env.SNIPER_BRAIN_PROVIDER = "codex";
  let calls = 0;
  try {
    await runProposalBrain({ prompt, ctx: f.cut.job.ctx, cwd: "/private/tmp", timeoutMs: 500, schema }, { codex: async options => {
      calls++; assert.equal(options.schema, "producer-treatment-proposal-v8");
      assert.equal(options.sandbox, "read-only"); assert.equal(options.tools, "none");
      const args = buildCodexArgs(options);
      assert.ok(args.some(value => value.endsWith("schemas/producer/treatment-proposal-v8.schema.json")));
      return { message: JSON.stringify(f.proposal), stderr: "", ms: 1 };
    }, legacy: async () => { throw new Error("No provider fallback"); } });
  } finally { if (prior === undefined) delete process.env.SNIPER_BRAIN_PROVIDER; else process.env.SNIPER_BRAIN_PROVIDER = prior; }
  assert.equal(calls, 1);
});

test("nonempty V8 cannot enter readiness or media without full original accepted/source context", () => {
  const f = candidateFixture(), result = buildTreatmentCandidate(f);
  const input = { result } as ReviewedProposalInput;
  assert.throws(() => buildProposalReadinessPacket(input), /presenter original accepted plan/);
  assert.throws(() => openingMediaAuthority(input as OpeningReadiness), /original accepted plan/);
  assert.throws(() => assertFullProgramMediaMetadata({ plan: result.candidate!, bindings: result.executionBindings! }), /original proposal\/evidence context/);
  const noop = buildTreatmentCandidate({ ...f, output: presenterProposal([oldOperation("preserve-cut")]) });
  assert.equal(noop.executionBindings!.schemaVersion, 2);
  assert.throws(() => buildProposalReadinessPacket({ result: noop } as ReviewedProposalInput), /V8 opening evidence/);
  assert.throws(() => parseTreatmentProposalV8({ ...f.output, schemaVersion: 7 }));
});
