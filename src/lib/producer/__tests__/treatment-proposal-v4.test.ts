import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { parseTreatmentProposalV2 } from "@/lib/producer/contracts/treatment-proposal-v2";
import { parseTreatmentProposalV3 } from "@/lib/producer/contracts/treatment-proposal-v3";
import { parseTreatmentProposal, parseTreatmentProposalV4 } from "@/lib/producer/contracts/treatment-proposal-v4";

type Row = Record<string, unknown>;
const RAW = "Produce the long-form treatment.";
const REASON = "The spoken contrast needs a visible anchor.";
const SELECTION = "A statement card matches this single claim.";
const graphic = (clauseIndex: number, startAnchor: number, endAnchorExclusive: number, catalogKind: string): Row => ({
  type: "catalog-graphic", clauseIndex, beatIndex: 0, catalogKind, variables: [{ name: "title", value: "Two paths" }],
  grade: null, startAnchor, endAnchorExclusive, reason: "Anchors the spoken contrast.",
  presentation: { schemaVersion: 1, anchor: "free-band", placement: "measured-free-region", compositeMode: "normal",
    baseTreatment: "preserve", rationale: "Keeps the presenter visible under the claim." },
});

function proposal(patch: Row = {}): Row {
  return { schemaVersion: 4, summary: "TEST ONLY v4 proposal", graphicsStyle: "overlay-rich",
    graphicsStyleRationale: "Overlay-rich keeps the presenter on screen under every claim.",
    clauses: [{ start: 0, end: RAW.length, quote: RAW, disposition: "supported", rationale: "Executable", operationIndices: [0, 1] }],
    beats: [{ startAnchor: 0, endAnchorExclusive: 4, purpose: "opening", summary: "Opening promise", supportsBeatIndices: [] },
      { startAnchor: 4, endAnchorExclusive: 8, purpose: "body", summary: "Body payoff", supportsBeatIndices: [] }],
    operations: [graphic(0, 1, 2, "title-card"), graphic(0, 3, 4, "list-card")],
    beatDecisions: [{ beatId: "intro-aaaaaaaaaaaa", decision: "graphic", reason: REASON, kind: "title-card",
      alternativesConsidered: ["list-card", "rail-card"], selectionReason: SELECTION, operationIndex: 0 },
    { beatId: "intro-bbbbbbbbbbbb", decision: "graphic", reason: REASON, kind: "list-card",
      alternativesConsidered: ["title-card"], selectionReason: SELECTION, operationIndex: 1 }],
    hookSeamDecisions: [{ seamIndex: 0, decision: "clean-hook", reason: "Continuous delivery reads cleaner as a hard cut.",
      evidence: "Sentence continues across the seam" }],
    openingEndAnchor: 6, continuityEndAnchor: 7, audioPolicy: "preserve-full-program", colorPolicy: "preserve", ...patch };
}
function decisions(patch: Row): Row {
  const rows = proposal().beatDecisions as Row[];
  return proposal({ beatDecisions: [{ ...rows[0], ...patch }, rows[1]] });
}

test("V4 keeps the closed V3/V2 contract and adds only decided style, graphic and seam fields", () => {
  const parsed = parseTreatmentProposalV4(proposal());
  assert.equal(parsed.schemaVersion, 4);
  assert.equal(parsed.graphicsStyle, "overlay-rich");
  assert.deepEqual(parsed.operations.map((row) => row.reason), ["Anchors the spoken contrast.", "Anchors the spoken contrast."]);
  assert.deepEqual(parsed, parseTreatmentProposal(proposal()));
  assert.equal(parsed.beatDecisions[0].decision, "graphic");
  assert.equal(parsed.hookSeamDecisions[0].seamIndex, 0);
  for (const patch of [{ schemaVersion: 3 }, { finalApproved: true }, { graphicsStyle: "invented" }, { graphicsStyle: null },
    { graphicsStyleRationale: "too short" }, { graphicsStyleRationale: "" }, { audioPolicy: "renormalize" }]) {
    assert.throws(() => parseTreatmentProposalV4(proposal(patch)), /V4 proposal|unsupported fields|graphicsStyle|audio\/color/);
  }
  for (const key of ["graphicsStyle", "graphicsStyleRationale", "beatDecisions", "hookSeamDecisions"]) {
    const row = proposal(); delete row[key];
    assert.throws(() => parseTreatmentProposalV4(row), /missing fields/);
  }
});

test("the provider's structured-output schema and the parser cannot drift apart", () => {
  const schema = JSON.parse(readFileSync(path.join(process.cwd(), "schemas", "producer", "treatment-proposal-v4.schema.json"), "utf8"));
  assert.equal(schema.properties.schemaVersion.const, 4);
  assert.equal(schema.additionalProperties, false);
  assert.deepEqual([...schema.required].sort(), Object.keys(proposal()).sort());
  assert.deepEqual([...schema.$defs.operation.required].sort(), Object.keys((proposal().operations as Row[])[0]).sort());
  assert.deepEqual([...schema.$defs.beatDecision.required].sort(), Object.keys((proposal().beatDecisions as Row[])[0]).sort());
  assert.deepEqual([...schema.$defs.hookSeamDecision.required].sort(), Object.keys((proposal().hookSeamDecisions as Row[])[0]).sort());
  for (const name of ["operation", "beatDecision", "hookSeamDecision"]) {
    assert.deepEqual([...schema.$defs[name].required].sort(), Object.keys(schema.$defs[name].properties).sort());
    assert.equal(schema.$defs[name].additionalProperties, false);
  }
});

test("stored V2 and V3 objects still parse unchanged through the V4 dispatcher", () => {
  const v3: Row = { ...proposal(), schemaVersion: 3, operations: (proposal().operations as Row[]).map(({ reason: _reason, ...rest }) => { void _reason; return rest; }) };
  delete v3.graphicsStyle; delete v3.graphicsStyleRationale; delete v3.beatDecisions; delete v3.hookSeamDecisions;
  assert.deepEqual(parseTreatmentProposal(v3), parseTreatmentProposalV3(v3));
  const v2 = { ...v3, schemaVersion: 2, operations: (v3.operations as Row[]).map(({ presentation: _p, ...rest }) => { void _p; return rest; }) };
  assert.deepEqual(parseTreatmentProposal(v2), parseTreatmentProposalV2(v2));
  assert.equal(parseTreatmentProposal(v2).schemaVersion, 2);
});

test("every operation must declare a purposeful reason exactly when it is a catalog graphic", () => {
  const operations = () => (proposal().operations as Row[]).map((row) => ({ ...row }));
  const missing = operations(); delete missing[0].reason;
  assert.throws(() => parseTreatmentProposalV4(proposal({ operations: missing })), /explicit purposeful reason or null/);
  const blank = operations(); blank[0].reason = null;
  assert.throws(() => parseTreatmentProposalV4(proposal({ operations: blank })), /non-null operation reason/);
  const short = operations(); short[0].reason = "short";
  assert.throws(() => parseTreatmentProposalV4(proposal({ operations: short })), /substantive characters/);
  const preserve = [{ type: "preserve-cut", clauseIndex: 0, beatIndex: null, catalogKind: null, variables: null, grade: null,
    startAnchor: null, endAnchorExclusive: null, presentation: null, reason: "Retains the accepted cut." }];
  assert.throws(() => parseTreatmentProposalV4(proposal({ operations: preserve, beatDecisions: [], clauses:
    [{ start: 0, end: RAW.length, quote: RAW, disposition: "supported", rationale: "Executable", operationIndices: [0] }] })), /non-null operation reason/);
});

test("beat decisions are closed, single-use and cannot omit, delegate or under-consider a required beat", () => {
  for (const patch of [{ decision: "omit" }, { decision: "broll" }, { decision: "graphic-maybe" }]) {
    assert.throws(() => parseTreatmentProposalV4(decisions(patch)), /only decision "graphic"/);
  }
  assert.throws(() => parseTreatmentProposalV4(decisions({ reason: "too short" })), /substantive characters/);
  assert.throws(() => parseTreatmentProposalV4(decisions({ selectionReason: "too short" })), /substantive characters/);
  assert.throws(() => parseTreatmentProposalV4(decisions({ alternativesConsidered: ["list-card", "list-card"] })), /must be unique/);
  assert.throws(() => parseTreatmentProposalV4(decisions({ alternativesConsidered: ["title-card"] })), /never the selected kind/);
  assert.throws(() => parseTreatmentProposalV4(decisions({ alternativesConsidered: [7] })), /alternative kind/);
  assert.throws(() => parseTreatmentProposalV4(decisions({ informationForm: "statement" })), /unsupported fields/);
  assert.throws(() => parseTreatmentProposalV4(decisions({ beatId: "intro-bbbbbbbbbbbb" })), /beatId must be unique/);
  assert.throws(() => parseTreatmentProposalV4(decisions({ operationIndex: 1 })), /operationIndex must be unique/);
  assert.throws(() => parseTreatmentProposalV4(proposal({ beatDecisions: Array.from({ length: 129 }, () => (proposal().beatDecisions as Row[])[0]) })), /bounded array/);
});

test("hook seam decisions are clean-hook only and carry the renderer's minimum reason and evidence", () => {
  const seam = (patch: Row) => proposal({ hookSeamDecisions: [{ ...(proposal().hookSeamDecisions as Row[])[0], ...patch }] });
  assert.throws(() => parseTreatmentProposalV4(seam({ decision: "cross-dissolve" })), /must be "clean-hook"/);
  assert.throws(() => parseTreatmentProposalV4(seam({ reason: "hard cut" })), /substantive characters/);
  assert.throws(() => parseTreatmentProposalV4(seam({ evidence: "too short" })), /substantive characters/);
  assert.throws(() => parseTreatmentProposalV4(seam({ outTime: 30 })), /unsupported fields/);
  assert.throws(() => parseTreatmentProposalV4(seam({ seamIndex: -1 })), /bounded nonnegative integer/);
  const rows = proposal().hookSeamDecisions as Row[];
  assert.throws(() => parseTreatmentProposalV4(proposal({ hookSeamDecisions: [rows[0], { ...rows[0] }] })), /seamIndex must be unique/);
});
