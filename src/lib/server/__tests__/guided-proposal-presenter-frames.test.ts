import assert from "node:assert/strict";
import { test } from "node:test";
import { parseTreatmentProposalV8 } from "@/lib/producer/contracts/treatment-proposal-v8";
import { guidedPresenterWindows } from "../guided-proposal-presenter";
import { presenterFixture, presenterProposal, layoutOperation, layoutSelection, layoutProposal, type Row } from "./_guided-proposal-presenter-fixture";

test("each supported layout is projected from the actual anchor frames without changing its payload", () => {
  const f = presenterFixture();
  for (const kind of ["inset", "bubble", "split"] as const) {
    const selection = layoutSelection(kind), proposal = presenterProposal([layoutOperation({ startAnchor: 2, endAnchorExclusive: 28, presenterLayout: selection })]);
    assert.deepEqual(guidedPresenterWindows(proposal, f.evidence), [{ operationIndex: 0, startFrame: 40, endFrameExclusive: 560, layout: selection }]);
  }
});

test("source occurrences are ordered unique and use exact half-open window intersections", () => {
  const f = presenterFixture();
  for (const sourceIds of [["raw-1", "raw-2"], ["raw-2"], ["raw-2", "raw-1", "other"]]) {
    const proposal = structuredClone(f.proposal); proposal.operations[0].presenterLayout!.sourceIds = sourceIds;
    assert.throws(() => guidedPresenterWindows(proposal, f.evidence), /sourceIds differ/);
  }
  const onlyMiddle = presenterProposal([layoutOperation({ startAnchor: 10, endAnchorExclusive: 20,
    presenterLayout: { ...layoutSelection(), sourceIds: ["raw-1"] } })]);
  assert.deepEqual(guidedPresenterWindows(onlyMiddle, f.evidence)[0].layout.sourceIds, ["raw-1"]);
});

test("frame evidence refuses missing, unsorted, duplicate or out-of-range anchors and invalid rates", () => {
  const f = presenterFixture();
  for (const frameRate of ["30", "60/2", "030/1", "0/1", "-30/1", "1/0", "1/1/1", "9007199254740993/1", ["30/1"]]) {
    assert.throws(() => guidedPresenterWindows(f.proposal, { ...f.evidence, frameRate } as typeof f.evidence));
  }
  for (const anchors of [[], [0, 600], [1, 600], [0, 599], [0, 20, 20, 600], [0, 40, 20, 600],
    [0, true, 600], [0, NaN, 600], [-0, 200, 400, 600], Array(60_003).fill(0)]) {
    assert.throws(() => guidedPresenterWindows(f.proposal, { ...f.evidence, anchors } as typeof f.evidence));
  }
  for (const totalFrames of [0, true, NaN, Infinity, 1.5, 1_000_000_001]) {
    assert.throws(() => guidedPresenterWindows(f.proposal, { ...f.evidence, totalFrames } as typeof f.evidence));
  }
});

test("retained source segments must be a complete contiguous indexed partition with anchor boundaries", () => {
  const f = presenterFixture();
  for (const patch of [{ index: true }, { index: 1 }, { sourceId: " " }, { startFrame: 1 }, { endFrameExclusive: 0 },
    { endFrameExclusive: 199 }, { endFrameExclusive: 220 }, { endFrameExclusive: "200" }]) {
    const evidence = structuredClone(f.evidence); Object.assign(evidence.segments[0], patch);
    assert.throws(() => guidedPresenterWindows(f.proposal, evidence));
  }
  const evidence = structuredClone(f.evidence); evidence.segments.pop();
  assert.throws(() => guidedPresenterWindows(f.proposal, evidence), /cover the full/);
  assert.throws(() => guidedPresenterWindows(f.proposal, { ...f.evidence, segments: [] }), /bounded retained/);
});

test("overlapping windows refuse last-writer-wins even when the submitted order is reversed", () => {
  const f = presenterFixture();
  const late = layoutOperation({ startAnchor: 15, endAnchorExclusive: 28,
    presenterLayout: { ...layoutSelection(), sourceIds: ["raw-1", "raw-2"] } });
  const early = layoutOperation({ startAnchor: 2, endAnchorExclusive: 18 });
  for (const operations of [[early, late], [late, early], [early, early]]) {
    assert.throws(() => guidedPresenterWindows(presenterProposal(operations), f.evidence), /overlap/);
  }
});

test("exact last-written-frame feasibility allows one full-layout frame and rejects an incomplete exit", () => {
  const f = presenterFixture(), evidence = { ...f.evidence, totalFrames: 50, anchors: [0, 1, 26, 50],
    segments: [{ index: 0, sourceId: "raw-2", startFrame: 0, endFrameExclusive: 50 }] };
  const raw = layoutProposal({ operations: [layoutOperation({ startAnchor: 1, endAnchorExclusive: 2,
    presenterLayout: { ...layoutSelection(), sourceIds: ["raw-2"] } })] });
  (raw.beats as Row[])[0].endAnchorExclusive = 3; raw.openingEndAnchor = 3; raw.continuityEndAnchor = 3;
  const proposal = parseTreatmentProposalV8(raw);
  assert.equal(guidedPresenterWindows(proposal, evidence)[0].endFrameExclusive, 26);
  assert.throws(() => guidedPresenterWindows(proposal, { ...evidence, anchors: [0, 1, 25, 50] }), /complete positive ramps/);
});

test("32 windows remain bounded while retaining every original index; the 33rd refuses before projection", () => {
  const f = presenterFixture();
  for (const count of [32, 33]) {
    const totalFrames = count * 40, anchors = Array.from({ length: count * 2 + 1 }, (_, index) => index * 20);
    const evidence = { ...f.evidence, totalFrames, anchors, segments: [{ index: 0, sourceId: "raw-2", startFrame: 0, endFrameExclusive: totalFrames }] };
    const operations = Array.from({ length: count }, (_, index) => layoutOperation({ startAnchor: index * 2, endAnchorExclusive: index * 2 + 2,
      presenterLayout: { ...layoutSelection(), sourceIds: ["raw-2"] } }));
    const raw = layoutProposal({ operations }); (raw.beats as Row[])[0].endAnchorExclusive = anchors.length - 1;
    raw.openingEndAnchor = anchors.length - 1; raw.continuityEndAnchor = anchors.length - 1;
    const proposal = parseTreatmentProposalV8(raw);
    if (count === 33) { assert.throws(() => guidedPresenterWindows(proposal, evidence), /at most 32/); continue; }
    assert.deepEqual(guidedPresenterWindows(proposal, evidence).map(row => row.operationIndex), Array.from({ length: 32 }, (_, index) => index));
  }
});

test("valid normalized metadata cannot authorize a stretched or incorrectly masked target", () => {
  const f = presenterFixture(); f.proposal.operations[0].presenterLayout!.presenterRect.height = 0.2;
  assert.throws(() => guidedPresenterWindows(f.proposal, f.evidence), /stretch/);
  const bubble = presenterProposal([layoutOperation({ startAnchor: 2, endAnchorExclusive: 28, presenterLayout: layoutSelection("bubble") })]);
  assert.throws(() => guidedPresenterWindows(bubble, { ...f.evidence, target: { ...f.evidence.target, width: 1080, height: 1920 } }), /stretch|square/);
});
