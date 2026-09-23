import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { test } from "node:test";
import { pythonInterpreter } from "@/app/api/_lib/spawn-python";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { parseTreatmentProposalV5 } from "@/lib/producer/contracts/treatment-proposal-v5";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { buildTreatmentCandidate } from "../guided-proposal-candidate";
import { GUIDED_CAPTION_CONFIG_FILES, guidedCaptionPolicy } from "../guided-proposal-captions";
import { buildProposalPrompt, runProposalBrain } from "../guided-proposal-compiler";
import { assertStoredProposalEvidence, type ProposalEvidence } from "../guided-proposal-evidence";
import type { AcceptedGuidedCut } from "../guided-raw-treatment-store";
import { appendTestCaptionProposal, TEST_CAPTION_INTENT } from "./_guided-longform-proposal";
import { assertProposalClauseCoverage } from "@/lib/producer/contracts/treatment-proposal-v2";

/** TEST ONLY scalar catalog configuration; no rendered or source observation claim. */
const GRAPHIC_SPEC = { type: "bars", data: "1,2", labels: "TEST A,TEST B", emphasize: 1, unit: "", accent: "#054BC9", exit: "hold" };

type Row = Record<string, unknown>;
const RAW = "Add the Producer line captions and compare the two spoken values.";
const TARGET = { mode: "longform", scope: "produced", width: 1920, height: 1080 };
const PLAN = { target: TARGET, cutTrack: [{ sourceId: "raw-1", start: 0, end: 2 }], captions: { burn: false } };
const cut = { plan: { value: PLAN } } as unknown as AcceptedGuidedCut;

/** TEST ONLY minimal full-program clause/beat fixture, not admitted-source or rendered evidence. */
function proposal(patch: Row = {}): Row {
  return { schemaVersion: 5, summary: "TEST ONLY caption and graphic operation indices.", graphicsStyle: "catalog-first",
    graphicsStyleRationale: "TEST ONLY one declared numeric comparison earns the brief graphic.",
    clauses: [{ start: 0, end: RAW.length, quote: RAW, disposition: "supported", rationale: "Both named operations preserve the accepted words.", operationIndices: [0, 1] }],
    beats: [{ startAnchor: 0, endAnchorExclusive: 3, purpose: "opening", summary: "TEST ONLY complete short program.", supportsBeatIndices: [] }],
    operations: [{ type: "captions-full-program", clauseIndex: 0, beatIndex: null, catalogKind: null, variables: null, grade: null,
      startAnchor: null, endAnchorExclusive: null, presentation: null, reason: "Use the named preset for every kept spoken word.",
      captions: { schemaVersion: 1, preset: "producer-config-line-v1", coverage: "all-kept-transcript-words", suppression: "none" } },
    { type: "catalog-graphic", clauseIndex: 0, beatIndex: 0, catalogKind: "chart-story", variables: Object.entries(GRAPHIC_SPEC).map(([name, value]) => ({ name, value })),
      grade: null, startAnchor: 1, endAnchorExclusive: 2, captions: null, reason: "Compare the two declared TEST values.",
      presentation: { schemaVersion: 1, anchor: "own-screen", placement: "full-canvas", compositeMode: "normal", baseTreatment: "preserve",
        rationale: "TEST ONLY exact native canvas graphic." } }],
    beatDecisions: [{ beatId: "intro-aaaaaaaaaaaa", decision: "graphic", kind: "chart-story", reason: "The two declared values need a comparison.",
      alternativesConsidered: [], selectionReason: "The TEST chart carries the declared comparison values.", operationIndex: 1 }],
    hookSeamDecisions: [], openingEndAnchor: 3, continuityEndAnchor: 3, audioPolicy: "preserve-full-program", colorPolicy: "preserve", ...patch };
}
function evidence(patch: Partial<ProposalEvidence> = {}): ProposalEvidence {
  return { schemaVersion: 5, frameRate: "30/1", totalFrames: 60, target: TARGET, anchors: [0, 15, 30, 60], cleanEnds: [60],
    segments: [{ index: 0, sourceId: "raw-1", startFrame: 0, endFrameExclusive: 60, text: "One two" }], occurrences: [],
    catalog: [{ kind: "chart-story", canvas: [1920, 1080], defaults: GRAPHIC_SPEC, fields: Object.keys(GRAPHIC_SPEC) }],
    introSeams: [], hookWindowS: 60, timelineMapHash: "a".repeat(64),
    graphicsAdvice: { "graphics_planner.py": { introSemanticBeats: [{ beatId: "intro-aaaaaaaaaaaa", shape: "number", outStart: 0.5,
      evidence: "One two", compatibleKinds: ["chart-story"], minimumGraphicHoldS: 0.2, decisionRequired: true }] } },
    captionPolicy: guidedCaptionPolicy(GUIDED_CAPTION_CONFIG_FILES.map((name) => ({ name, sha256: "b".repeat(64) }))),
    ...patch } as unknown as ProposalEvidence;
}
function build(output: Row = proposal(), supplied: ProposalEvidence = evidence(), plan: Row = PLAN) {
  return buildTreatmentCandidate({ cut: { ...cut, plan: { value: plan } } as unknown as AcceptedGuidedCut, rawIntent: RAW, evidence: supplied, output });
}

test("current compiler rejects retired styles and kinds even with declared catalog metadata", () => {
  assert.throws(() => build(proposal({ graphicsStyle: "cutaway-only" })), /styles are retired/);
  const output = proposal(), supplied = evidence();
  (output.operations as Row[])[1].catalogKind = "title-card";
  (output.beatDecisions as Row[])[0].kind = "title-card";
  supplied.catalog[0].kind = "title-card";
  const result = build(output, supplied);
  assert.equal(result.candidate, null);
  assert.equal(result.executionBindings, undefined);
  assert.ok(result.blockers.some(row => /title-card.*retired or unregistered/.test(row.reason)));
});

test("V5 candidate keeps actual caption operation, graphic indices and all accepted cut fields", () => {
  const before = structuredClone(PLAN), result = build();
  assert.deepEqual(result.blockers, []);
  assert.deepEqual(PLAN, before);
  assert.equal(result.proposal.schemaVersion, 5);
  assert.equal(result.proposal.operations[0].type, "captions-full-program");
  assert.equal(result.executionBindings?.graphics[0].operationIndex, 1);
  assert.equal(result.executionBindings?.candidatePlanHash, canonicalJsonSha256(result.candidate));
  assert.deepEqual(result.candidate?.cutTrack, PLAN.cutTrack);
  assert.deepEqual(result.candidate?.captionsTrack, { schemaVersion: 1, source: "kept-transcript", defaultPolicy: "line", groups: [] });
  assert.deepEqual(result.candidate?.captions, { burn: true });
  assert.equal((result.candidate?.graphicsDecisions as Row[])[0].graphicId, (result.candidate?.graphicsTrack as Row[])[0].id);
});

test("live TEST caption request keeps existing semantic/graphic indices and has its own exact clause", () => {
  const before = parseTreatmentProposalV5(proposal()), saved = structuredClone(before);
  const current = appendTestCaptionProposal(before, RAW, "producer-config-line-v1");
  assert.deepEqual(before, saved);
  assert.deepEqual(current.operations.slice(0, before.operations.length), before.operations);
  assert.deepEqual(current.beatDecisions, before.beatDecisions);
  assert.deepEqual(current.clauses[1].operationIndices, [before.operations.length]);
  assert.equal(current.operations.at(-1)?.clauseIndex, 1);
  assertProposalClauseCoverage(current, RAW + TEST_CAPTION_INTENT);
  assert.throws(() => appendTestCaptionProposal({ ...before, schemaVersion: 4 }, RAW, "producer-config-line-v1"), /explicit V5/);
  assert.throws(() => appendTestCaptionProposal(before, RAW, "producer-config-karaoke-v1"), /only the line preset/);
  assert.throws(() => appendTestCaptionProposal(before, "changed TEST quote", "producer-config-line-v1"), /exact original/);
});

test("V5 cannot bypass full-program story/graphic obligations or clause coverage", () => {
  assert.equal(build(proposal({ beatDecisions: [] })).candidate, null);
  const rows = proposal().beatDecisions as Row[];
  assert.ok(build(proposal({ beatDecisions: [{ ...rows[0], operationIndex: 0 }] })).blockers.some((row) => /not a compiled catalog graphic/.test(row.reason)));
  const clauses = proposal().clauses as Row[];
  assert.throws(() => build(proposal({ clauses: [{ ...clauses[0], operationIndices: [1] }] })), /unrequested operation/);
  assert.throws(() => build(proposal({ clauses: [{ ...clauses[0], quote: "A changed request" }] })), /rewrote original/);
});

test("V5 requires its exact evidence version and closed captured caption preset policy", () => {
  assert.throws(() => build(proposal(), evidence({ schemaVersion: 4 })), /exact versioned evidence/);
  assert.throws(() => build(proposal(), evidence({ captionPolicy: undefined })), /exact captured caption policy/);
  const changed = evidence(); (changed.captionPolicy as unknown as Row).suppression = "under-graphics";
  assert.throws(() => build(proposal(), changed), /exact captured caption policy/);
  const truncated = evidence(); truncated.captionPolicy!.configuration.pop();
  assert.throws(() => build(proposal(), truncated), /closure is incomplete/);
  assert.equal(build(proposal(), evidence(), { ...PLAN, target: { ...TARGET, width: 3840 } }).candidate, null);
  assert.equal(build(proposal(), evidence(), { ...PLAN, captionStyles: {} }).candidate, null);
});

test("V5 schema retains every field, and the actual Python caption compiler preserves full word coverage", () => {
  const schema = JSON.parse(readFileSync("schemas/producer/treatment-proposal-v5.schema.json", "utf8"));
  const parsed = parseTreatmentProposalV5(proposal());
  assert.equal(schema.properties.schemaVersion.const, 5);
  assert.deepEqual([...schema.required].sort(), Object.keys(parsed).sort());
  assert.deepEqual([...schema.$defs.operation.required].sort(), Object.keys(parsed.operations[0]).sort());
  assert.deepEqual([...schema.$defs.captionSelection.required].sort(), Object.keys(parsed.operations[0].captions!).sort());
  const candidate = build().candidate!;
  const code = `import json,sys
from captions.caption_plan_pipeline import caption_styles,validate_plan_caption_authority
from captions.caption_compile import compile_caption_track,CaptionCompileContext
from captions.caption_words import CaptionFrameRate
from _caption_fixtures import resolved_words,DESTINATION
plan=json.load(sys.stdin); track,ledger=validate_plan_caption_authority(plan)
words=resolved_words(['One','two']); styles=caption_styles(plan,track)
compiled=compile_caption_track(CaptionCompileContext(track,ledger,words,CaptionFrameRate(30,1),'a'*64,style_inputs=styles,destination=DESTINATION))
print(json.dumps({'coverage':compiled['coverage'],'tokens':[row['text'] for cue in compiled['cues'] for row in cue['tokens']],'modes':[cue['mode'] for cue in compiled['cues']]}))`;
  const result = JSON.parse(execFileSync(pythonInterpreter(), ["-c", code], { cwd: path.join(process.cwd(), "scripts/producer"),
    input: JSON.stringify(candidate), encoding: "utf8", timeout: 10000,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONPATH: ".:tests" } }));
  assert.deepEqual(result.tokens, ["One", "two"]);
  assert.ok(result.modes.every((mode: string) => mode === "line"));
  assert.deepEqual(result.coverage.suppressedWordIds, []);
  assert.deepEqual(result.coverage.omittedWordIds, []);
  assert.deepEqual(result.coverage.expectedWordIds, result.coverage.renderedWordIds);
});

test("V5-only prompt authorizes named caption presets, and schema routing never falls back", async () => {
  const prompt = buildProposalPrompt(RAW, evidence());
  assert.match(prompt, /captions-full-program/);
  assert.match(prompt, /Custom fonts, colors, placement, selective captions, translation/);
  assert.match(prompt, /Accepted scope\/lane ownership must already assign captions to the system/);
  assert.match(prompt, /hookSeamDecisions/);
  assert.ok(!buildProposalPrompt(RAW, evidence({ schemaVersion: 4 })).includes("Candidate operations are measured"));
  const prior = process.env.SNIPER_BRAIN_PROVIDER; process.env.SNIPER_BRAIN_PROVIDER = "codex";
  try {
    const options = { prompt: "TEST ONLY no model call", ctx: {} as AutoEditCtx, cwd: "/private/tmp", timeoutMs: 500 };
    await runProposalBrain({ ...options, schema: { properties: { schemaVersion: { const: 5 } } } }, { codex: async (input) => {
      assert.equal(input.schema, "producer-treatment-proposal-v5"); return { message: "{}", stderr: "", ms: 1 };
    } });
    await assert.rejects(runProposalBrain({ ...options, schema: { properties: { schemaVersion: { const: 99 } } } }), /no fallback/);
  } finally { if (prior === undefined) delete process.env.SNIPER_BRAIN_PROVIDER; else process.env.SNIPER_BRAIN_PROVIDER = prior; }
});

test("stored V5 evidence cannot omit its caption policy or smuggle it into V4", () => {
  const row = { ...evidence(), cutDecisionHash: "a", parentRevisionHash: "b", catalogHash: "c", doctrine: [], pipelineHash: "d",
    wordTupleFields: [], wordTimingScope: "transcript-derived-floor-start-ceil-end-not-audibility-or-semantic-approval",
    scope: "full-program-proposal-evidence-not-render-or-quality-approval", presentationPolicy: {} } as unknown as ProposalEvidence;
  const { captionPolicy: _policy, ...missing } = row; void _policy;
  const staged = {} as Parameters<typeof assertStoredProposalEvidence>[2];
  assert.throws(() => assertStoredProposalEvidence(cut, missing as ProposalEvidence, staged), /missing fields: captionPolicy/);
  assert.throws(() => assertStoredProposalEvidence(cut, { ...row, schemaVersion: 4 }, staged), /unsupported fields: captionPolicy/);
});

test("structured JSON schema rejects malformed caption data without depending on TS coercion", () => {
  const valid = proposal(), operations = valid.operations as Row[];
  const first = operations[0], { captions: _caps, ...missing } = first; void _caps;
  const rows = [valid, proposal({ schemaVersion: 4 }), proposal({ operations: [missing, operations[1]] }),
    proposal({ operations: [{ ...first, type: ["captions-full-program"] }, operations[1]] }),
    proposal({ operations: [{ ...first, captions: { ...(first.captions as Row), text: "Invented words" } }, operations[1]] })];
  const output = execFileSync(pythonInterpreter(), ["scripts/producer/contracts/schema_validator.py", "--batch"], {
    cwd: process.cwd(), input: JSON.stringify(rows.map((document) => ({ schema: "treatment-proposal-v5.schema.json", document }))),
    encoding: "utf8", timeout: 10000, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
  });
  assert.deepEqual(JSON.parse(output).map((row: { valid: boolean }) => row.valid), [true, false, false, false, false]);
});
