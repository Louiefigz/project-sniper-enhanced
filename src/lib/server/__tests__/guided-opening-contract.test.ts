import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { test } from "node:test";
import { parsePrepareGuidedOpening, parseOpeningFrameRange } from "@/lib/producer/contracts/guided-opening-v1";
import { parseGraphicPresentation, parseTreatmentProposalV3, PROPOSAL_PRESENTATION_POLICY } from "@/lib/producer/contracts/treatment-proposal-v3";
import { parseTreatmentProposalV2 } from "@/lib/producer/contracts/treatment-proposal-v2";
import { buildTreatmentCandidate } from "../guided-proposal-candidate";
import { assertGuidedFrameBindings, proposalOccurrenceEvidence } from "../guided-proposal-bindings";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import type { ProposalEvidence } from "../guided-proposal-evidence";
import type { AcceptedGuidedCut } from "../guided-raw-treatment-store";

// Contract-only fixture: real catalog identity and defaults, no rendering or quality claim.
const catalogDefaults = { lineA: "A real point", lineB: "A clearer point", swapAt: 1.5, underlineWord: "", accent: "#054BC9", exit: "hold" };
const presentation = { schemaVersion: 1, anchor: "own-screen", placement: "full-canvas", compositeMode: "normal", baseTreatment: "preserve", rationale: "TEST explicit full-screen semantic card." };
function pureProposal() {
  return { schemaVersion: 3, summary: "TEST ONLY explicit presentation and independent frame windows",
    clauses: [{ start: 0, end: 9, quote: "Add title", disposition: "supported", rationale: "Exact cue", operationIndices: [0] }],
    beats: [{ startAnchor: 0, endAnchorExclusive: 5, purpose: "opening", summary: "TEST program", supportsBeatIndices: [] }],
    operations: [{ type: "catalog-graphic", clauseIndex: 0, beatIndex: 0, catalogKind: "line-swap", variables: Object.entries(catalogDefaults).map(([name, value]) => ({ name, value })),
      grade: null, startAnchor: 1, endAnchorExclusive: 2, presentation }],
    openingEndAnchor: 3, continuityEndAnchor: 4, audioPolicy: "preserve-full-program", colorPolicy: "preserve" };
}
function pureInput() {
  const target = { mode: "longform", width: 1080, height: 1920 };
  const evidence = { schemaVersion: 3, frameRate: "30000/1001", totalFrames: 17983, target,
    segments: [{ index: 0, sourceId: "s", startFrame: 0, endFrameExclusive: 17983, text: "TEST ten-minute program" }],
    catalog: [{ kind: "line-swap", canvas: [1080, 1920], fields: Object.keys(catalogDefaults), defaults: { ...catalogDefaults } }],
    anchors: [0, 30, 75, 1800, 2100, 17983], cleanEnds: [1800], occurrences: [[0, 0, 0, 30, 75, "Point.", 0]],
    presentationPolicy: PROPOSAL_PRESENTATION_POLICY, timelineMapHash: "a".repeat(64) } as unknown as ProposalEvidence;
  const cut = { plan: { value: { target, cutTrack: [{ sourceId: "s", start: 0, end: 600 }], cutDecisions: {} } } } as unknown as AcceptedGuidedCut;
  return { cut, evidence, rawIntent: "Add title", output: pureProposal() };
}

test("opening request is closed and cannot name paths, timing, approval, renderer or source selections", () => {
  const value = { schemaVersion: 1, operation: "prepare-guided-opening", idempotencyKey: randomUUID(), expectedToken: "token",
    expectedJournalHash: "a".repeat(64), proposalReadinessHash: "b".repeat(64), treatmentDraftRevisionHash: "c".repeat(64) };
  assert.deepEqual(parsePrepareGuidedOpening(value), value);
  for (const patch of [{ outputPath: "/tmp/final.mp4" }, { approved: true }, { renderer: "mock" }, { sourceSelection: {} }, { idempotencyKey: "../../escape" }, { frameRate: "30/1" }]) {
    assert.throws(() => parsePrepareGuidedOpening({ ...value, ...patch }));
  }
  for (const range of [{ startFrame: -1, endFrameExclusive: 20 }, { startFrame: 1, endFrameExclusive: 1 }, { startFrame: 0, endFrameExclusive: 101 }, { startFrame: 0, endFrameExclusive: 10.5 }]) {
    assert.throws(() => parseOpeningFrameRange(range, 100));
  }
});

test("V3 graphics require explicit reviewed presentation; V2 stays unchanged without an executable sidecar", () => {
  assert.deepEqual(parseGraphicPresentation(presentation), presentation);
  for (const patch of [{ anchor: "free-band" }, { placement: "guess" }, { baseTreatment: "blur-desat" }, { zoom: 1.28 }, { rationale: "" }]) {
    assert.throws(() => parseGraphicPresentation({ ...presentation, ...patch }));
  }
  const missing = pureProposal() as unknown as Record<string, unknown>;
  missing.operations = pureProposal().operations.map(({ presentation: _value, ...operation }) => { void _value; return operation; });
  assert.throws(() => parseTreatmentProposalV3(missing), /requires explicit/);
  const legacy = { ...missing, schemaVersion: 2 }; assert.equal(parseTreatmentProposalV2(legacy).schemaVersion, 2);
  const input = pureInput(), legacyResult = buildTreatmentCandidate({ ...input, evidence: { ...input.evidence, schemaVersion: 2 }, output: legacy });
  assert.equal(legacyResult.executionBindings, undefined); assert.equal((legacyResult.candidate!.graphicsTrack as Record<string, unknown>[])[0].anchor, undefined);
  assert.throws(() => buildTreatmentCandidate({ ...input, output: legacy }), /no presentation upgrade/);
});

test("exact fractional frame bindings survive seconds projection and reject entry omission or presentation drift", () => {
  const input = pureInput(), before = canonicalJsonSha256(input.cut.plan.value), result = buildTreatmentCandidate(input);
  assert.equal(result.blockers.length, 0); assert.equal(canonicalJsonSha256(input.cut.plan.value), before);
  assert.equal(result.proposal.schemaVersion, 3); assert.ok(result.executionBindings);
  const binding = result.executionBindings.graphics[0], row = (result.candidate!.graphicsTrack as Record<string, unknown>[])[0];
  assert.deepEqual([binding.startFrame, binding.endFrameExclusive], [30, 75]); assert.equal(row.anchor, "own-screen");
  assert.equal(row.outStart, 1.001); assert.equal(row.outEnd, 2.5025); assert.equal(row.proposalFrameRange, undefined);
  assert.equal(binding.entryHash, canonicalJsonSha256(row)); assert.equal(result.executionBindings.candidatePlanHash, canonicalJsonSha256(result.candidate));
  assert.equal(result.executionBindings.occurrenceEvidenceHash, canonicalJsonSha256(proposalOccurrenceEvidence(input.evidence)));
  const boundInput = { proposal: parseTreatmentProposalV3(input.output), evidence: input.evidence, candidate: result.candidate!, inheritedCount: 0 };
  for (const patch of [{ graphics: [] }, { totalFrames: 1 }, { candidatePlanHash: "f".repeat(64) },
    { graphics: [{ ...binding, startFrame: 31 }] }, { graphics: [{ ...binding, presentation: { ...presentation, anchor: "free-band" } }] }]) {
    assert.throws(() => assertGuidedFrameBindings(boundInput, { ...result.executionBindings, ...patch }), /bindings changed/);
  }
  const resized = buildTreatmentCandidate({ ...input, evidence: { ...input.evidence, target: { width: 1280, height: 720 } } });
  assert.equal(resized.candidate, null); assert.match(resized.blockers[0].reason, /no implicit resize/);
});

test("only schema3 exact empty asset defaults mean no asset; nonempty and legacy proposals remain blocked", () => {
  const input = pureInput(), row = input.evidence.catalog[0];
  row.defaults = { ...row.defaults, iconFile: "" }; row.fields.push("iconFile");
  input.output.operations[0].variables.push({ name: "iconFile", value: "" });
  assert.equal(buildTreatmentCandidate(input).blockers.length, 0);
  for (const value of ["notion.svg", "https://example.invalid/icon.png", " ", "../icon.svg"]) {
    const output = structuredClone(input.output); output.operations[0].variables.at(-1)!.value = value;
    const blocked = buildTreatmentCandidate({ ...input, output });
    assert.equal(blocked.candidate, null); assert.match(blocked.blockers[0].reason, /separately resolved asset/);
  }
  const nonemptyDefault = structuredClone(input.evidence); nonemptyDefault.catalog[0].defaults.iconFile = "notion.svg";
  assert.match(buildTreatmentCandidate({ ...input, evidence: nonemptyDefault }).blockers[0].reason, /separately resolved asset/);
  const legacy = { ...input.output, schemaVersion: 2, operations: input.output.operations.map(({ presentation: _drop, ...row }) => { void _drop; return row; }) };
  assert.match(buildTreatmentCandidate({ ...input, output: legacy, evidence: { ...input.evidence, schemaVersion: 2 } }).blockers[0].reason, /separately resolved asset/);
});

test("retired catalog identities cannot become candidates through caller evidence", () => {
  const input = pureInput();
  input.output.operations[0].catalogKind = "title-card";
  input.evidence.catalog[0].kind = "title-card";
  const result = buildTreatmentCandidate(input);
  assert.equal(result.candidate, null);
  assert.match(result.blockers[0].reason, /retired|catalog/i);
});
