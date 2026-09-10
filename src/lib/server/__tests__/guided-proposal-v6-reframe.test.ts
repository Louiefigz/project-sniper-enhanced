import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { pythonInterpreter } from "@/app/api/_lib/spawn-python";
import { assertProposalClauseCoverage } from "@/lib/producer/contracts/treatment-proposal-v2";
import { parseCurrentTreatmentProposal, parseTreatmentProposalV5, CURRENT_TREATMENT_PROPOSAL_VERSION } from "@/lib/producer/contracts/treatment-proposal-v5";
import { parseProposalManualReframe, parseTreatmentProposalV6, proposalV6ValidationView, MANUAL_REFRAME_MIN_FRACTION } from "@/lib/producer/contracts/treatment-proposal-v6";
import { parseCurrentTreatmentProposal as parseThroughV6 } from "@/lib/producer/contracts/treatment-proposal-v6";
import { applyGuidedReframeOperations, assertGuidedReframeCandidate } from "../guided-proposal-reframe";
import { buildTreatmentCandidate } from "../guided-proposal-candidate";
import { GUIDED_CAPTION_CONFIG_FILES, guidedCaptionPolicy } from "../guided-proposal-captions";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { buildProposalPrompt, runProposalBrain } from "../guided-proposal-compiler";
import type { ProposalEvidence } from "../guided-proposal-evidence";
import type { AcceptedGuidedCut } from "../guided-raw-treatment-store";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";

type Row = Record<string, unknown>;
const RAW = "Use the exact crop and caption every word with the Producer line preset.";
const PLAN = { planVersion: 3, target: { mode: "short", scope: "light", width: 1080, height: 1920, fps: 30,
  lanes: { motion: "off", captions: "auto" } }, cutTrack: [{ sourceId: "raw-1", start: 1.2, end: 9.8, speed: 1 }],
  cutDecisions: { removals: [] } };

function selection(patch: Row = {}): Row {
  return { schemaVersion: 1, sourceId: "raw-1", layout: "fill", crop: [0.5, 0, 0.5, 1], track: false, ...patch };
}
function cropOperation(patch: Row = {}): Row {
  return { type: "reframe-manual-short", clauseIndex: 0, beatIndex: null, catalogKind: null, variables: null, grade: null,
    startAnchor: null, endAnchorExclusive: null, presentation: null, reason: "Use the explicitly submitted right-half source crop.",
    captions: null, reframe: selection(), ...patch };
}
function captionOperation(patch: Row = {}): Row {
  return { ...cropOperation(), type: "captions-full-program", reason: "Caption every kept word using the named preset.", reframe: null,
    captions: { schemaVersion: 1, preset: "producer-config-line-v1", coverage: "all-kept-transcript-words", suppression: "none" }, ...patch };
}
function proposal(patch: Row = {}): Row {
  return { schemaVersion: 6, summary: "TEST ONLY manual geometry request; no source observation or approval.", graphicsStyle: "cutaway-only",
    graphicsStyleRationale: "TEST ONLY preserve the accepted short and its explicit caption lane.",
    clauses: [{ start: 0, end: RAW.length, quote: RAW, disposition: "supported", rationale: "Both exact visual requests preserve the accepted cut.", operationIndices: [0, 1] }],
    beats: [{ startAnchor: 0, endAnchorExclusive: 1, purpose: "opening", summary: "TEST ONLY whole short.", supportsBeatIndices: [] }],
    operations: [cropOperation(), captionOperation()], beatDecisions: [], hookSeamDecisions: [], openingEndAnchor: 1, continuityEndAnchor: 1,
    audioPolicy: "preserve-full-program", colorPolicy: "preserve", ...patch };
}
function apply(plan: Row = PLAN, raw: Row = proposal()): Row {
  return applyGuidedReframeOperations(plan, parseTreatmentProposalV6(raw));
}

test("V6 retains real crop/caption operation types, payloads and original indices", () => {
  const raw = proposal(), before = structuredClone(raw), parsed = parseTreatmentProposalV6(raw);
  assertProposalClauseCoverage(parsed, RAW);
  assert.deepEqual(raw, before);
  assert.deepEqual(parsed.operations.map((item) => item.type), ["reframe-manual-short", "captions-full-program"]);
  assert.deepEqual(parsed.operations[0].reframe, selection());
  assert.equal(parsed.operations[1].captions?.preset, "producer-config-line-v1");
  const view = proposalV6ValidationView(parsed);
  assert.deepEqual(view.operations.map((item) => item.type), ["preserve-cut", "captions-full-program"]);
  assert.deepEqual(view.clauses, parsed.clauses);
  assert.deepEqual(parsed.operations[0].reframe, selection());
});

test("historical V5 dispatch remains closed while explicit V6 dispatch accepts its own contract", () => {
  assert.equal(CURRENT_TREATMENT_PROPOSAL_VERSION, 5);
  assert.throws(() => parseCurrentTreatmentProposal(proposal()));
  assert.deepEqual(parseThroughV6(proposal()), parseTreatmentProposalV6(proposal()));
  assert.throws(() => parseThroughV6(proposal({ schemaVersion: 7 })));
  assert.throws(() => parseTreatmentProposalV5(proposal()));
  assert.throws(() => parseTreatmentProposalV5({ ...proposal(), schemaVersion: 5 }));
  const view = proposalV6ValidationView(parseTreatmentProposalV6(proposal()));
  assert.deepEqual(parseCurrentTreatmentProposal(view), view);
});

test("V6 requires exact reframe/null on every operation and rejects coercion or extra payloads", () => {
  const { reframe: _crop, ...missing } = cropOperation(); void _crop;
  const { reframe: _caption, ...missingCaption } = captionOperation(); void _caption;
  const invalid = [missing, cropOperation({ reframe: null }), cropOperation({ type: ["reframe-manual-short"] }),
    cropOperation({ reason: "brief" }), cropOperation({ captions: captionOperation().captions }), cropOperation({ beatIndex: 0 }),
    cropOperation({ catalogKind: "title-card" }), cropOperation({ variables: [] }), cropOperation({ grade: "warm" }),
    cropOperation({ startAnchor: 0 }), cropOperation({ endAnchorExclusive: 1 }), cropOperation({ presentation: {} }),
    cropOperation({ approval: true })];
  for (const row of invalid) assert.throws(() => parseTreatmentProposalV6(proposal({ operations: [row, captionOperation()] })));
  assert.throws(() => parseTreatmentProposalV6(proposal({ operations: [cropOperation(), missingCaption] })));
  assert.throws(() => parseTreatmentProposalV6(proposal({ extra: true })));
  assert.throws(() => parseTreatmentProposalV6(proposal({ colorPolicy: ["preserve"] })));
});

test("exact crop coordinates reject malformed, nonfinite, out-of-frame and unsupported geometry", () => {
  for (const crop of [[0, 0, 0.049, 1], [0, 0, 1, 0.049], [0.6, 0, 0.5, 1], [0, 0.6, 1, 0.5],
    [-0.1, 0, 1, 1], [0, 0, 1], [0, 0, 1, 1, 0], [false, 0, 1, 1], ["0", 0, 1, 1], [NaN, 0, 1, 1], [0, Infinity, 1, 1]]) {
    assert.throws(() => parseProposalManualReframe(selection({ crop })));
  }
  for (const patch of [{ track: true }, { track: 0 }, { layout: "split" }, { sourceId: [] }, { sourceId: " " },
    { sourceId: "a".repeat(129) }, { schemaVersion: "1" }, { approval: true }]) assert.throws(() => parseProposalManualReframe(selection(patch)));
  assert.deepEqual(parseProposalManualReframe(selection({ crop: [0, 0, 0.05, 0.05] })).crop, [0, 0, 0.05, 0.05]);
});

test("crop cannot fabricate a caption preset or resolve duplicate/conflicting crops", () => {
  const alteredCaption = captionOperation({ captions: { ...(captionOperation().captions as Row), preset: "producer-config-karaoke-v1" } });
  for (const operations of [[cropOperation()], [cropOperation(), cropOperation(), captionOperation()],
    [cropOperation(), cropOperation({ reframe: selection({ crop: [0, 0, 1, 1] }) }), captionOperation()],
    [cropOperation(), captionOperation(), alteredCaption]]) assert.throws(() => parseTreatmentProposalV6(proposal({ operations })));
  assert.doesNotThrow(() => parseTreatmentProposalV6(proposal({ operations: [cropOperation(), alteredCaption] })));
});

test("pure projection adds only exact reframe without applying captions or changing accepted inputs", () => {
  const before = structuredClone(PLAN), result = apply();
  assert.deepEqual(PLAN, before);
  assert.deepEqual(result, { ...before, reframe: { layout: "fill", crop: [0.5, 0, 0.5, 1], track: false } });
  assert.equal(Object.hasOwn(result, "captions"), false);
  assert.equal(Object.hasOwn(result, "captionsTrack"), false);
  (result.cutTrack as Row[])[0].start = 7;
  assert.equal(PLAN.cutTrack[0].start, 1.2);
  const extra = { ...PLAN, music: { enabled: false }, audioGain: [], sourceEvidence: { testOnly: true } };
  assert.deepEqual(apply(extra), { ...extra, reframe: { layout: "fill", crop: [0.5, 0, 0.5, 1], track: false } });
});

test("accepted scope-default auto works but explicit off/operator and trim-auto never become captions", () => {
  assert.doesNotThrow(() => apply({ ...PLAN, target: { ...PLAN.target, lanes: {} } }));
  for (const target of [{ ...PLAN.target, scope: "trim" }, { ...PLAN.target, lanes: { captions: "off" } },
    { ...PLAN.target, lanes: { captions: "operator" } }, { ...PLAN.target, scope: "made-up" },
    { ...PLAN.target, scope: undefined }, { ...PLAN.target, lanes: { captions: ["auto"] } }]) assert.throws(() => apply({ ...PLAN, target }));
});

test("target, selected source, existing reframe and existing caption authority are never overwritten", () => {
  for (const patch of [{ target: { ...PLAN.target, width: 1920 } }, { target: { ...PLAN.target, mode: "longform" } },
    { target: { ...PLAN.target, height: "1920" } }, { cutTrack: [] }, { cutTrack: [{ sourceId: "raw-2" }] },
    { cutTrack: [...PLAN.cutTrack, { sourceId: "raw-2" }] }, { reframe: null }, { reframe: {} }, { reframe: { strategy: "face" } },
    { captions: { burn: true } }, { captionsTrack: null }, { captionChapters: [] }, { captionStyles: {} },
    { captionCorrectionLedger: {} }, { dialogueCaptionAuthority: {} }, { chapters: [{ title: "TEST" }] }]) {
    const plan = { ...PLAN, ...patch }, before = structuredClone(plan);
    assert.throws(() => apply(plan)); assert.deepEqual(plan, before);
  }
  assert.throws(() => apply(PLAN, proposal({ operations: [cropOperation({ reframe: selection({ sourceId: "raw-2" }) }), captionOperation()] })));
});

test("V6 without crop remains unchanged; it is not an implicit crop or caption executor", () => {
  const preserve = cropOperation({ type: "preserve-cut", reframe: null, reason: null });
  assert.deepEqual(apply(PLAN, proposal({ operations: [preserve] })), PLAN);
});

test("new schema is closed, preserves old definitions and rejects malformed transport shapes", () => {
  const schema = JSON.parse(readFileSync("schemas/producer/treatment-proposal-v6.schema.json", "utf8"));
  const old = JSON.parse(readFileSync("schemas/producer/treatment-proposal-v5.schema.json", "utf8"));
  const parsed = parseTreatmentProposalV6(proposal());
  assert.equal(schema.properties.schemaVersion.const, 6);
  assert.deepEqual([...schema.required].sort(), Object.keys(parsed).sort());
  assert.deepEqual([...schema.$defs.operation.required].sort(), Object.keys(parsed.operations[0]).sort());
  assert.deepEqual([...schema.$defs.manualReframe.required].sort(), Object.keys(parsed.operations[0].reframe!).sort());
  for (const key of Object.keys(old.$defs).filter((key) => key !== "operation")) assert.deepEqual(schema.$defs[key], old.$defs[key]);
  const rows = [proposal(), proposal({ schemaVersion: 5 }), proposal({ inventedApproval: true }),
    proposal({ operations: [cropOperation({ reframe: selection({ track: 0 }) }), captionOperation()] }),
    proposal({ operations: [cropOperation({ reframe: selection({ crop: [0, 0, 1] }) }), captionOperation()] }),
    proposal({ operations: [cropOperation({ reframe: selection({ sourceId: [] }) }), captionOperation()] })];
  const output = execFileSync(pythonInterpreter(), ["scripts/producer/contracts/schema_validator.py", "--batch"], {
    input: JSON.stringify(rows.map((document) => ({ schema: "treatment-proposal-v6.schema.json", document }))), encoding: "utf8",
    timeout: 10000, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
  });
  assert.deepEqual(JSON.parse(output).map((row: { valid: boolean }) => row.valid), [true, false, false, false, false, false]);
});

test("crop minimum mirrors the existing renderer and TS manual profile bounds", () => {
  const value = execFileSync(pythonInterpreter(), ["-c", "from producer_config import REFRAME_SPLIT; print(REFRAME_SPLIT['crop_min_frac'])"], {
    cwd: "scripts/producer", encoding: "utf8", timeout: 10000, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
  });
  assert.equal(Number(value), MANUAL_REFRAME_MIN_FRACTION);
  assert.doesNotThrow(() => apply(PLAN, proposal({ operations: [cropOperation({ reframe: selection({ crop: [0, 0, 0.05, 0.05] }) }), captionOperation()] })));
});

function candidateFixture() {
  const output = proposal(), operations = output.operations as Row[];
  operations.push({ type: "catalog-graphic", clauseIndex: 0, beatIndex: 0, catalogKind: "TEST-portrait-card",
    variables: [{ name: "title", value: "TEST crop" }], grade: null, startAnchor: 1, endAnchorExclusive: 2,
    captions: null, reframe: null, reason: "TEST ONLY explain the expressly requested crop.",
    presentation: { schemaVersion: 1, anchor: "own-screen", placement: "full-canvas", compositeMode: "normal",
      baseTreatment: "preserve", rationale: "TEST ONLY exact native portrait canvas." } });
  (output.clauses as Row[])[0].operationIndices = [0, 1, 2];
  (output.beats as Row[])[0].endAnchorExclusive = 3;
  output.openingEndAnchor = 3; output.continuityEndAnchor = 3;
  const evidence = { schemaVersion: 6, frameRate: "30/1", totalFrames: 258, target: PLAN.target,
    anchors: [0, 60, 90, 258], cleanEnds: [258], occurrences: [], introSeams: [], hookWindowS: 60,
    timelineMapHash: "a".repeat(64), segments: [{ index: 0, sourceId: "raw-1", startFrame: 0,
      endFrameExclusive: 258, text: "TEST ONLY exact crop and all kept captions." }],
    graphicsAdvice: { "graphics_planner.py": { introSemanticBeats: [] } },
    catalog: [{ kind: "TEST-portrait-card", canvas: [1080, 1920], defaults: { title: "TEST" }, fields: ["title"] }],
    captionPolicy: guidedCaptionPolicy(GUIDED_CAPTION_CONFIG_FILES.map(name => ({ name, sha256: "b".repeat(64) })))
  } as unknown as ProposalEvidence;
  return { output, evidence, cut: { plan: { value: PLAN } } as unknown as AcceptedGuidedCut };
}

test("V6 candidate builds crop then captions then graphics, preserving original operation indices", () => {
  const supplied = candidateFixture(), before = structuredClone(PLAN), originalProposal = structuredClone(supplied.output);
  const result = buildTreatmentCandidate({ ...supplied, rawIntent: RAW });
  assert.deepEqual(result.blockers, []); assert.ok(result.candidate);
  assert.deepEqual(PLAN, before); assert.deepEqual(supplied.output, originalProposal);
  assert.deepEqual(result.proposal.operations.map(item => item.type), ["reframe-manual-short", "captions-full-program", "catalog-graphic"]);
  assert.deepEqual(result.candidate.reframe, { layout: "fill", crop: [0.5, 0, 0.5, 1], track: false });
  assert.deepEqual(result.candidate.captions, { burn: true });
  assert.deepEqual(result.candidate.captionsTrack, { schemaVersion: 1, source: "kept-transcript", defaultPolicy: "line", groups: [] });
  assert.deepEqual(result.candidate.cutTrack, PLAN.cutTrack); assert.deepEqual(result.candidate.cutDecisions, PLAN.cutDecisions);
  const { graphicsStyle, graphicsStyleRationale, ...lockedTarget } = result.candidate.target as Row;
  assert.deepEqual(lockedTarget, PLAN.target);
  assert.equal(graphicsStyle, "cutaway-only"); assert.equal(graphicsStyleRationale, supplied.output.graphicsStyleRationale);
  assert.equal(result.executionBindings?.graphics[0].operationIndex, 2);
  assert.equal(result.executionBindings?.candidatePlanHash, canonicalJsonSha256(result.candidate));
  assertGuidedReframeCandidate(PLAN, result.candidate, parseTreatmentProposalV6(supplied.output));
});

test("request-derived validation rejects rehashed crop, caption preset and added authority", () => {
  const supplied = candidateFixture(), result = buildTreatmentCandidate({ ...supplied, rawIntent: RAW });
  const current = parseTreatmentProposalV6(supplied.output), candidate = result.candidate!;
  const changes = [{ reframe: { layout: "fill", crop: [0, 0, 1, 1], track: false } },
    { captions: { burn: false } }, { captionsTrack: { ...(candidate.captionsTrack as Row), defaultPolicy: "karaoke" } },
    { captionStyles: {} }, { captionChapters: [] }, { dialogueCaptionAuthority: null }, { chapters: {} }];
  for (const change of changes) {
    const altered = { ...candidate, ...change };
    assert.notEqual(canonicalJsonSha256(altered), canonicalJsonSha256(candidate));
    assert.throws(() => assertGuidedReframeCandidate(PLAN, altered, current), /actual V6 request/);
  }
  const changedRequest = parseTreatmentProposalV6(proposal({ operations: [cropOperation({ reframe: selection({ crop: [0, 0, 1, 1] }) }), captionOperation()] }));
  assert.throws(() => assertGuidedReframeCandidate(PLAN, candidate, changedRequest), /actual V6 request/);
});

test("V6 cannot use V5 evidence or omit exact caption policy", () => {
  const supplied = candidateFixture();
  assert.throws(() => buildTreatmentCandidate({ ...supplied, rawIntent: RAW,
    evidence: { ...supplied.evidence, schemaVersion: 5 } }), /exact versioned evidence/);
  assert.throws(() => buildTreatmentCandidate({ ...supplied, rawIntent: RAW,
    evidence: { ...supplied.evidence, captionPolicy: undefined } }), /exact captured caption policy/);
});

test("explicit V6 prompt and schema route never infer tracking, approval or historical fallback", async () => {
  const supplied = candidateFixture(), prompt = buildProposalPrompt(RAW, supplied.evidence);
  assert.match(prompt, /reframe-manual-short/); assert.match(prompt, /separate explicit captions-full-program/);
  assert.match(prompt, /no inferred automatic crop/); assert.match(prompt, /actual V6 array/);
  const prior = process.env.SNIPER_BRAIN_PROVIDER; process.env.SNIPER_BRAIN_PROVIDER = "codex";
  try {
    await runProposalBrain({ prompt: "TEST ONLY no provider call", ctx: {} as AutoEditCtx, cwd: "/private/tmp", timeoutMs: 500,
      schema: { properties: { schemaVersion: { const: 6 } } } }, { codex: async input => {
        assert.equal(input.schema, "producer-treatment-proposal-v6"); return { message: "{}", stderr: "", ms: 1 };
      } });
  } finally { if (prior === undefined) delete process.env.SNIPER_BRAIN_PROVIDER; else process.env.SNIPER_BRAIN_PROVIDER = prior; }
});
