import assert from "node:assert/strict";
import { test } from "node:test";
import { parseTreatmentProposalV4 } from "../contracts/treatment-proposal-v4";
import { assertProposalClauseCoverage } from "../contracts/treatment-proposal-v2";
import { parseTreatmentProposalV5, proposalV5GraphicValidationView } from "../contracts/treatment-proposal-v5";
import { applyGuidedCaptionOperations } from "@/lib/server/guided-proposal-captions";

const RAW = "Caption every spoken word using the Producer line preset.";
type Row = Record<string, unknown>;
function selection(patch: Row = {}): Row {
  return { schemaVersion: 1, preset: "producer-config-line-v1", coverage: "all-kept-transcript-words", suppression: "none", ...patch };
}
function operation(patch: Row = {}): Row {
  return { type: "captions-full-program", clauseIndex: 0, beatIndex: null, catalogKind: null, variables: null, grade: null,
    startAnchor: null, endAnchorExclusive: null, presentation: null, reason: "Keep every spoken word visible in the named line preset.",
    captions: selection(), ...patch };
}
function proposal(patch: Row = {}): Row {
  return { schemaVersion: 5, summary: "TEST ONLY caption request, not a render or approval.",
    graphicsStyle: "cutaway-only", graphicsStyleRationale: "TEST ONLY source picture remains visible throughout this fixture.",
    clauses: [{ start: 0, end: RAW.length, quote: RAW, disposition: "supported", rationale: "Use the explicitly named preset.", operationIndices: [0] }],
    beats: [{ startAnchor: 0, endAnchorExclusive: 1, purpose: "opening", summary: "TEST ONLY complete short program.", supportsBeatIndices: [] }],
    operations: [operation()], beatDecisions: [], hookSeamDecisions: [], openingEndAnchor: 1, continuityEndAnchor: 1,
    audioPolicy: "preserve-full-program", colorPolicy: "preserve", ...patch };
}
const plan = { target: { mode: "longform", width: 1920, height: 1080 }, cutTrack: [{ sourceId: "raw-1", start: 1.2, end: 9.8 }],
  captions: { burn: false }, audioGain: [], graphicsTrack: [], chapters: [], unrelated: { retained: true } };

test("V5 retains the actual caption operation and complete clause coverage; V4 remains closed", () => {
  const parsed = parseTreatmentProposalV5(proposal());
  assertProposalClauseCoverage(parsed, RAW);
  assert.equal(parsed.operations[0].type, "captions-full-program");
  assert.equal(parsed.operations[0].captions?.coverage, "all-kept-transcript-words");
  assert.equal(parsed.operations[0].reason, operation().reason);
  assert.throws(() => parseTreatmentProposalV4(proposal()));
  assert.throws(() => parseTreatmentProposalV4({ ...proposal(), schemaVersion: 4 }));
});

test("V5 does not inherit legacy String coercion of enum arrays or objects", () => {
  const row = proposal(), clauses = row.clauses as Row[], beats = row.beats as Row[];
  for (const patch of [{ operations: [operation({ type: ["preserve-cut"], captions: null, reason: null })] },
    { operations: [operation({ type: "grade", grade: ["warm"], captions: null, reason: null })] },
    { clauses: [{ ...clauses[0], disposition: ["supported"] }] }, { beats: [{ ...beats[0], purpose: ["opening"] }] },
    { colorPolicy: ["preserve"] }]) assert.throws(() => parseTreatmentProposalV5(proposal(patch)), /actual string/);
  assert.equal(proposalV5GraphicValidationView(parseTreatmentProposalV5(proposal())).operations[0].type, "preserve-cut");
});

test("caption nullability, unknown metadata and arbitrary replacement words never enter V5", () => {
  for (const patch of [{ captions: null }, { captions: selection({ text: "invented replacement" }) },
    { captions: selection({ suppression: "under-graphics" }) }, { captions: selection({ coverage: "selected-words" }) },
    { captions: selection({ preset: "custom-font" }) }, { beatIndex: 0 }, { startAnchor: 0 }, { grade: "warm" },
    { presentation: {} }, { variables: [] }, { reason: "brief" }, { additionalApproval: true }]) {
    assert.throws(() => parseTreatmentProposalV5(proposal({ operations: [operation(patch)] })), JSON.stringify(patch));
  }
  const { captions: _captions, ...missing } = operation(); void _captions;
  assert.throws(() => parseTreatmentProposalV5(proposal({ operations: [missing] })), /explicit captions/);
  assert.throws(() => parseTreatmentProposalV5(proposal({ inventedApproval: true })));
});

test("ordinary V5 operations require null caption selection and preserve V4 constraints", () => {
  const preserve = { ...operation(), type: "preserve-cut", captions: null, reason: null };
  const parsed = parseTreatmentProposalV5(proposal({ operations: [preserve] }));
  assert.equal(parsed.operations[0].type, "preserve-cut");
  assert.deepEqual(applyGuidedCaptionOperations(plan, parsed), plan);
  assert.throws(() => parseTreatmentProposalV5(proposal({ operations: [{ ...preserve, captions: selection() }] })), /Only captions-full-program/);
  assert.throws(() => parseTreatmentProposalV5(proposal({ operations: [{ ...preserve, beatIndex: 0 }] })));
});

test("caption projection preserves original plan and all non-caption fields exactly", () => {
  const before = structuredClone(plan), parsed = parseTreatmentProposalV5(proposal());
  const candidate = applyGuidedCaptionOperations(plan, parsed);
  assert.deepEqual(plan, before);
  assert.deepEqual(candidate, { ...before, captions: { burn: true },
    captionsTrack: { schemaVersion: 1, source: "kept-transcript", defaultPolicy: "line", groups: [] } });
  assert.notEqual(candidate.cutTrack, plan.cutTrack);
  const karaoke = parseTreatmentProposalV5(proposal({ operations: [operation({ captions: selection({ preset: "producer-config-karaoke-v1" }) })] }));
  assert.equal((applyGuidedCaptionOperations(plan, karaoke).captionsTrack as Row).defaultPolicy, "karaoke");
});

test("contradictory caption clauses are blocked; duplicate identical requests produce only one track", () => {
  const both = [operation(), operation({ captions: selection({ preset: "producer-config-karaoke-v1" }) })];
  assert.throws(() => applyGuidedCaptionOperations(plan, parseTreatmentProposalV5(proposal({ operations: both }))), /conflicting presets/);
  const repeated = parseTreatmentProposalV5(proposal({ operations: [operation(), operation()] }));
  assert.deepEqual(applyGuidedCaptionOperations(plan, repeated), applyGuidedCaptionOperations(plan, parseTreatmentProposalV5(proposal())));
});

test("caption requests cannot silently override accepted off/operator/trim intent", () => {
  const parsed = parseTreatmentProposalV5(proposal());
  for (const target of [{ ...plan.target, lanes: { captions: "off" } }, { ...plan.target, lanes: { captions: "operator" } },
    { ...plan.target, scope: "trim", lanes: { captions: "auto" } }, { ...plan.target, treatment: "clean-cut" }]) {
    assert.throws(() => applyGuidedCaptionOperations({ ...plan, target }, parsed), /treatment-intent revision/);
  }
  for (const scope of ["light", "produced", "full"]) {
    assert.doesNotThrow(() => applyGuidedCaptionOperations({ ...plan, target: { ...plan.target, scope } }, parsed));
  }
  for (const patch of [{ scope: null }, { lanes: { captions: null } }, { lanes: { captions: ["auto"] } }]) {
    assert.throws(() => applyGuidedCaptionOperations({ ...plan, target: { ...plan.target, ...patch } }, parsed));
  }
});

test("existing authority, unknown burn controls and legacy chapters cannot be silently overwritten", () => {
  const parsed = parseTreatmentProposalV5(proposal());
  for (const patch of [{ captionsTrack: null }, { captionsTrack: [] }, { captionStyles: {} }, { captionCorrectionLedger: {} },
    { dialogueCaptionAuthority: {} }, { captionChapters: [] }, { captionChapters: null }, { captionChapters: {} },
    { captions: { burn: true } }, { captions: { burn: false, size: 99 } }, { captions: {} },
    { chapters: [{ outTime: 3, title: "Old unbound chapter" }] }]) {
    assert.throws(() => applyGuidedCaptionOperations({ ...plan, ...patch }, parsed), JSON.stringify(patch));
  }
});
