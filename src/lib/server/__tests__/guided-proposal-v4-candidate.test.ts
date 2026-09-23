import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { test } from "node:test";
import { pythonInterpreter } from "@/app/api/_lib/spawn-python";
import { buildTreatmentCandidate } from "../guided-proposal-candidate";
import { proposalIntroSeams, PROPOSAL_HOOK_WINDOW_S, type ProposalEvidence } from "../guided-proposal-evidence";
import { buildLongformPlan } from "../guided-proposal-longform";
import { parseTreatmentProposalV4 } from "@/lib/producer/contracts/treatment-proposal-v4";
import type { AcceptedGuidedCut } from "../guided-raw-treatment-store";

type Row = Record<string, unknown>;
const RAW = "Produce the long-form treatment.";
const TARGET = { mode: "longform", scope: "produced", width: 1920, height: 1080 };
const BEAT_A = { beatId: "intro-aaaaaaaaaaaa", shape: "data", outStart: 1, outEnd: 2, evidence: "first comparison: twelve versus twenty-eight",
  compatibleKinds: ["chart-story"], preferredKind: "chart-story", decisionRequired: true, minimumGraphicHoldS: 1.5 };
const BEAT_B = { beatId: "intro-bbbbbbbbbbbb", shape: "data", outStart: 5, outEnd: 6, evidence: "second comparison: twelve versus twenty-eight",
  compatibleKinds: ["chart-story"], preferredKind: "chart-story", decisionRequired: true, minimumGraphicHoldS: 1.5 };
const OPTIONAL = { ...BEAT_A, beatId: "intro-cccccccccccc", outStart: 40, decisionRequired: false };
const CHART_SPEC = { type: "bars", data: "12,28", labels: "First,Second", emphasize: 1, unit: "", accent: "#054BC9", exit: "fade" };
const CATALOG = [{ kind: "chart-story", canvas: [1920, 1080], defaults: CHART_SPEC, fields: Object.keys(CHART_SPEC) }];

/** TEST ONLY synthetic evidence: 2 partitions, 1 intro seam, actual landscape chart variables. Each numeric beat owns a distinct chart; no media or measured capability claim. */
function evidence(patch: Partial<ProposalEvidence> = {}): ProposalEvidence {
  const segments = [{ index: 0, sourceId: "s", startFrame: 0, endFrameExclusive: 900, text: BEAT_A.evidence },
    { index: 1, sourceId: "s", startFrame: 900, endFrameExclusive: 18000, text: BEAT_B.evidence }];
  return { schemaVersion: 4, frameRate: "30/1", totalFrames: 18000, target: TARGET, segments, catalog: CATALOG,
    anchors: [0, 30, 90, 150, 240, 900, 1800, 1950, 18000], cleanEnds: [1800], timelineMapHash: "e".repeat(64),
    introSeams: proposalIntroSeams(segments, "30/1"), hookWindowS: PROPOSAL_HOOK_WINDOW_S,
    graphicsAdvice: { "graphics_planner.py": { introSemanticBeats: [BEAT_A, BEAT_B, OPTIONAL],
      formAllocation: { maximumFeasibleDistinctKinds: 1, recommendedAssignment: [{ beatId: BEAT_A.beatId, kind: "chart-story" },
        { beatId: BEAT_B.beatId, kind: "chart-story" }] } } }, ...patch } as unknown as ProposalEvidence;
}
const cut = { plan: { value: { cutTrack: [{ sourceId: "s", start: 0, end: 30 }, { sourceId: "s", start: 40, end: 610 }],
  cutDecisions: {}, target: TARGET } } } as unknown as AcceptedGuidedCut;

const operation = (startAnchor: number, endAnchorExclusive: number, catalogKind: string, anchor: string): Row => ({
  type: "catalog-graphic", clauseIndex: 0, beatIndex: 0, catalogKind, variables: Object.entries(CHART_SPEC).map(([name, value]) => ({ name, value })),
  grade: null, startAnchor, endAnchorExclusive, reason: "Anchors the spoken contrast.",
  presentation: { schemaVersion: 1, anchor, placement: anchor === "own-screen" ? "full-canvas" : "measured-free-region",
    compositeMode: "normal", baseTreatment: "preserve", rationale: "Declared creative intent only." },
});
function proposal(patch: Row = {}): Row {
  return { schemaVersion: 4, summary: "TEST ONLY v4 proposal", graphicsStyle: "catalog-first",
    graphicsStyleRationale: "Catalog chart compares the two numbers spoken at each separate beat.",
    clauses: [{ start: 0, end: RAW.length, quote: RAW, disposition: "supported", rationale: "Executable", operationIndices: [0, 1] }],
    beats: [{ startAnchor: 0, endAnchorExclusive: 4, purpose: "opening", summary: "Opening promise", supportsBeatIndices: [] },
      { startAnchor: 4, endAnchorExclusive: 8, purpose: "body", summary: "Body payoff", supportsBeatIndices: [] }],
    operations: [operation(1, 2, "chart-story", "own-screen"), operation(3, 4, "chart-story", "free-band")],
    beatDecisions: [{ beatId: BEAT_A.beatId, decision: "graphic", reason: "The first pair of numbers needs a side-by-side comparison.",
      kind: "chart-story", alternativesConsidered: [], selectionReason: "A bar chart compares the two numbers in the first claim.", operationIndex: 0 },
    { beatId: BEAT_B.beatId, decision: "graphic", reason: "The second pair of numbers needs its own visible comparison.",
      kind: "chart-story", alternativesConsidered: [], selectionReason: "A second chart binds to the second spoken numeric comparison.", operationIndex: 1 }],
    hookSeamDecisions: [{ seamIndex: 0, decision: "clean-hook", reason: "Continuous delivery reads cleaner as a hard cut.",
      evidence: "Sentence continues across the seam" }],
    openingEndAnchor: 6, continuityEndAnchor: 7, audioPolicy: "preserve-full-program", colorPolicy: "preserve", ...patch };
}
function decisions(patch: Row, index = 0): Row[] {
  const rows = proposal().beatDecisions as Row[];
  return rows.map((row, id) => id === index ? { ...row, ...patch } : row);
}
function build(output: Row = proposal(), input: Partial<{ evidence: ProposalEvidence; cut: AcceptedGuidedCut }> = {}) {
  return buildTreatmentCandidate({ cut: input.cut ?? cut, rawIntent: RAW, evidence: input.evidence ?? evidence(), output });
}
function blocked(output: Row, expected: RegExp, input?: Parameters<typeof build>[1]) {
  const result = build(output, input);
  assert.equal(result.candidate, null, `expected a blocker matching ${expected}`);
  assert.ok(result.blockers.some((row) => expected.test(row.reason)), JSON.stringify(result.blockers));
}

test("V4 candidate carries catalog-first numeric beat and clean-hook metadata without claiming rendered qualification", () => {
  const result = build();
  assert.deepEqual(result.blockers, []);
  const plan = result.candidate!;
  assert.deepEqual(plan.target, { ...TARGET, graphicsStyle: "catalog-first",
    graphicsStyleRationale: "Catalog chart compares the two numbers spoken at each separate beat." });
  const track = plan.graphicsTrack as Array<Record<string, unknown>>;
  assert.deepEqual(track.map((row) => [row.kind, row.outStart, row.outEnd, row.semanticBeatId, row.reason]),
    [["chart-story", 1, 3, BEAT_A.beatId, "Anchors the spoken contrast."], ["chart-story", 5, 8, BEAT_B.beatId, "Anchors the spoken contrast."]]);
  assert.deepEqual(plan.graphicsDecisions, (proposal().beatDecisions as Row[]).map(({ operationIndex: _index, ...row }, index) => {
    void _index; return { ...row, graphicId: track[index].id };
  }));
  assert.equal(plan.transitions instanceof Array && plan.transitions.length, 0);
  assert.deepEqual(plan.transitionRationale, { decision: "clean-hook", reason: "Continuous delivery reads cleaner as a hard cut.",
    seams: [{ outTime: 30, evidence: "Sentence continues across the seam", seamIndex: 0, reason: "Continuous delivery reads cleaner as a hard cut." }] });
  assert.deepEqual(plan.cutTrack, cut.plan.value.cutTrack);
  assert.equal(result.executionBindings?.graphics.length, 2);
  assert.deepEqual(result.range!.approval, { startFrame: 0, endFrameExclusive: 1800 });
});

test("the deterministic Python intro gates accept the exact compiled candidate receipts", () => {
  const built = build(); assert.deepEqual(built.blockers, []); assert.ok(built.candidate);
  const plan = built.candidate;
  const code = `import json,sys
from intro_transition_contract import intro_seams, valid_clean_hook_receipt
from graphics.intro_semantic_binding import decision_map, decision_error, reuse_errors, duplicate_beat_errors
data = json.load(sys.stdin); plan = data["plan"]
seams = intro_seams(plan["cutTrack"], 60.0); decisions = decision_map(plan)
print(json.dumps({"seams": seams, "receipt": valid_clean_hook_receipt(plan, seams),
  "errors": [decision_error(beat, decisions.get(beat["beatId"]) or {}, plan) for beat in data["beats"]],
  "reuse": reuse_errors(plan), "duplicates": duplicate_beat_errors(plan)}))`;
  const output = execFileSync(pythonInterpreter(), ["-c", code], { cwd: path.join(process.cwd(), "scripts", "producer"),
    input: JSON.stringify({ plan, beats: [BEAT_A, BEAT_B] }), encoding: "utf8", env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } });
  assert.deepEqual(JSON.parse(output), { seams: [30], receipt: true, errors: [null, null], reuse: [], duplicates: [] });
});

test("every deterministic decisionRequired beat needs exactly one grounded, covering graphic decision", () => {
  blocked(proposal({ beatDecisions: [(proposal().beatDecisions as Row[])[0]] }), /Deterministic beat intro-bbbbbbbbbbbb \(data at 5s.*no graphic decision/);
  blocked(proposal({ beatDecisions: decisions({ beatId: "intro-dddddddddddd" }) }), /names no deterministic decisionRequired beat/);
  blocked(proposal({ beatDecisions: decisions({ kind: "ui-focus-zoom", alternativesConsidered: [] }) }), /differs from the bound operation catalogKind/);
  blocked(proposal({ beatDecisions: decisions({ kind: "chart-story" }, 1),
    operations: [operation(1, 2, "chart-story", "own-screen"), operation(3, 4, "ui-focus-zoom", "free-band")] }), /Requested catalog kind .* unavailable/);
  blocked(proposal({ beatDecisions: decisions({ alternativesConsidered: ["invented-card"] }) }), /outside compatible forms/);
  const swapped = evidence({ graphicsAdvice: { "graphics_planner.py": { introSemanticBeats: [{ ...BEAT_A, compatibleKinds: ["ui-focus-zoom"] }, BEAT_B],
    formAllocation: { maximumFeasibleDistinctKinds: 1, recommendedAssignment: [] } } } });
  blocked(proposal({ beatDecisions: decisions({ alternativesConsidered: [] }) }), /is outside compatible forms \[ui-focus-zoom\]/, { evidence: swapped });
});

test("a bound graphic must be on screen at the exact beat and hold the deterministic minimum", () => {
  blocked(proposal({ operations: [operation(3, 4, "chart-story", "own-screen"), operation(3, 4, "chart-story", "free-band")] }),
    /are not on screen at the exact semantic beat 1s/);
  const strict = evidence({ graphicsAdvice: { "graphics_planner.py": { introSemanticBeats: [{ ...BEAT_A, minimumGraphicHoldS: 4 }, BEAT_B],
    formAllocation: { maximumFeasibleDistinctKinds: 1, recommendedAssignment: [] } } } });
  blocked(proposal(), /hold 2.00s is shorter than minimumGraphicHoldS 4s/, { evidence: strict });
});

test("beat coverage is half-open on the frame clock: [startFrame, endFrameExclusive)", () => {
  // operation(1, 2) binds anchors[1]..anchors[2] → frames [30, 90) at 30/1; every beat time below is an exact frame.
  const beatAt = (outStart: number, anchors?: number[]) => evidence({ ...(anchors ? { anchors } : {}),
    graphicsAdvice: { "graphics_planner.py": { introSemanticBeats: [{ ...BEAT_A, outStart }, BEAT_B],
      formAllocation: { maximumFeasibleDistinctKinds: 1, recommendedAssignment: [{ beatId: BEAT_A.beatId, kind: "chart-story" },
        { beatId: BEAT_B.beatId, kind: "chart-story" }] } } } });
  assert.deepEqual(build(proposal(), { evidence: beatAt(1) }).blockers, []);                    // frame 30 === startFrame: covered
  blocked(proposal(), /not on screen at the exact semantic beat 3s/, { evidence: beatAt(3) }); // frame 90 === endFrameExclusive: NOT covered
  const shifted = beatAt(3, [0, 30, 91, 150, 240, 900, 1800, 1950, 18000]);                     // graphic [30, 91): frame 90 === endFrameExclusive - 1
  assert.deepEqual(build(proposal(), { evidence: shifted }).blockers, []);
});

test("beat decisions must bind a compiled catalog graphic, never a preserve-cut or unrelated operation", () => {
  const preserve = { type: "preserve-cut", clauseIndex: 0, beatIndex: null, catalogKind: null, variables: null, grade: null,
    startAnchor: null, endAnchorExclusive: null, presentation: null, reason: null };
  blocked(proposal({ operations: [operation(1, 2, "chart-story", "own-screen"), preserve],
    clauses: [{ start: 0, end: RAW.length, quote: RAW, disposition: "supported", rationale: "Executable", operationIndices: [0, 1] }] }),
  /operationIndex 1 is not a compiled catalog graphic/);
});

test("intro seam coverage, face-bridge and pre-authored lanes fail closed instead of being silently fixed", () => {
  blocked(proposal({ hookSeamDecisions: [] }), /Intro seam 0 at 30s has no clean-hook decision/);
  blocked(proposal({ hookSeamDecisions: [{ seamIndex: 1, decision: "clean-hook", reason: "Continuous delivery reads cleaner as a hard cut.",
    evidence: "Sentence continues across the seam" }] }), /Hook seam decision 1 names no seam in this evidence/);
  blocked(proposal({ graphicsStyle: "face-bridge" }), /face-bridge\/visualProfile is not supported by guided V4/);
  const authored = { plan: { value: { ...cut.plan.value, transitions: [{ outTime: 30 }], graphicsDecisions: [{ beatId: "prior" }] } } } as unknown as AcceptedGuidedCut;
  const result = build(proposal(), { cut: authored });
  assert.equal(result.candidate, null);
  assert.deepEqual(result.blockers.map((row) => row.reason).filter((row) => row.includes("already carries")),
    ["Accepted cut already carries transitions; guided V4 cannot replace an existing decision receipt",
      "Accepted cut already carries graphicsDecisions; guided V4 cannot replace an existing decision receipt"]);
});

test("V4 evidence and V4 proposals cannot be mixed with an older schema in either direction", () => {
  const { graphicsStyle: _style, graphicsStyleRationale: _rationale, beatDecisions: _beats, hookSeamDecisions: _seams, ...v3 } = proposal();
  void _style; void _rationale; void _beats; void _seams;
  const v3Operations = (v3.operations as Row[]).map(({ reason: _reason, ...rest }) => { void _reason; return rest; });
  assert.throws(() => build({ ...v3, schemaVersion: 3, operations: v3Operations }), /must match its exact versioned evidence/);
  const older = evidence({ schemaVersion: 3, introSeams: undefined, hookWindowS: undefined });
  assert.throws(() => build(proposal(), { evidence: older }), /must match its exact versioned evidence/);
});

// Inert decision-grammar evidence intentionally names hypothetical alternatives; never a compiled/renderable catalog.
test("decision grammar still requires two other alternatives when an inert beat exposes three", () => {
  const output = parseTreatmentProposalV4(proposal({ beatDecisions: decisions({ alternativesConsidered: ["TEST-alternative-a"] }) }));
  const inert = evidence({ graphicsAdvice: { "graphics_planner.py": { introSemanticBeats: [
    { ...BEAT_A, compatibleKinds: ["chart-story", "TEST-alternative-a", "TEST-alternative-b"] }, BEAT_B] } } });
  const inspect = (value: typeof output) => buildLongformPlan({ proposal: value, evidence: inert, plan: cut.plan.value,
    graphics: [{ kind: "chart-story", proposalFrameRange: { startFrame: 30, endFrameExclusive: 90 } },
      { kind: "chart-story", proposalFrameRange: { startFrame: 150, endFrameExclusive: 240 } }] });
  assert.match(inspect(output).blockers[0].reason, /considered 1 alternative\(s\); needs 2/);
  output.beatDecisions[0].alternativesConsidered.push("TEST-alternative-b");
  assert.deepEqual(inspect(output).blockers, []);
});

test("legacy style enums and retired graphic metadata cannot authorize a current candidate", () => {
  const before = structuredClone(cut.plan.value);
  for (const graphicsStyle of ["overlay-rich", "cutaway-only"]) {
    assert.throws(() => build(proposal({ graphicsStyle })), /Legacy or unknown visual styles are retired/);
  }
  const historical = evidence({ catalog: [...CATALOG, { kind: "statement-card", canvas: [1080, 1920],
    defaults: CHART_SPEC, fields: Object.keys(CHART_SPEC) }] });
  blocked(proposal({ operations: [operation(1, 2, "statement-card", "free-band"), operation(3, 4, "chart-story", "free-band")] }),
    /Visual source "statement-card" is retired or unregistered/, { evidence: historical });
  assert.deepEqual(cut.plan.value, before);
});
