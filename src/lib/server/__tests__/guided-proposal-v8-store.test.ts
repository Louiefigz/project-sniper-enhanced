/** Real synthetic bytes/store/preview; external-admission decode facts, creative and acceptance replies are TEST stubs. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { oldOperation, layoutOperation, layoutSelection } from "@/lib/producer/__tests__/_presenter-layout-fixture";
import { pythonInterpreter } from "@/app/api/_lib/spawn-python";
import { createGuidedProposalFixture, readinessRequest } from "./_guided-proposal-fixture";
import { presenterReaderContext, presenterReadinessStub } from "./_guided-opening-presenter-documents";
import { readGuidedTreatmentProposal } from "../guided-proposal-store";
import { readHistoricalGuidedProposal } from "../guided-proposal-history";
import { compileGuidedTreatmentProposal } from "../guided-proposal";
import { buildProposalReadinessPacket } from "../guided-proposal-review-packet";
import { reviewGuidedTreatmentProposal } from "../guided-proposal-review";
import type { ProposalBrainInput } from "../guided-proposal-compiler";

const RAW = "TEST ONLY preserve this synthetic cut; no presenter asset is supplied.";
const PRESENTER_RAW = "TEST ONLY show presentation-1 beside the manually declared inset presenter, preserving this synthetic cut.";
const CAPTION_REFUSAL = { name: "Error", message: "presenter explicit caption choice must be an object" };

/** Actual service boundary; TEST callbacks fail if intake incorrectly reaches source checks, gates or critics. */
async function assertCaptionRefusalBeforeWork(fixture: Awaited<ReturnType<typeof createGuidedProposalFixture>>) {
  const before = readFileSync(fixture.jobPath), plan = readFileSync(fixture.ctx.planPath);
  const submission = readinessRequest(fixture.ctx.dir), calls = { sources: 0, gates: 0, critics: 0 };
  await assert.rejects(reviewGuidedTreatmentProposal({ dir: fixture.ctx.dir, submission }, {
    verifySources: async () => { calls.sources++; throw new Error("TEST source verification must not run"); },
    gates: async () => { calls.gates++; throw new Error("TEST gates must not run"); },
    critic: async () => { calls.critics++; throw new Error("TEST critic must not run"); },
  }), CAPTION_REFUSAL);
  assert.deepEqual(calls, { sources: 0, gates: 0, critics: 0 });
  assert.deepEqual(readFileSync(fixture.jobPath), before); assert.deepEqual(readFileSync(fixture.ctx.planPath), plan);
  assert.equal(existsSync(path.join(fixture.ctx.dir, "guided-v2-operations", submission.idempotencyKey)), false);
}

test("pure V8 packet requires an explicit caption choice before readiness metadata can be returned", () => {
  const input = presenterReaderContext(false, false);
  delete input.accepted.captions; delete input.candidate.captions;
  const before = structuredClone(input);
  assert.throws(() => buildProposalReadinessPacket(presenterReadinessStub(input)), CAPTION_REFUSAL);
  assert.deepEqual(input, before);
});

/** Construct actual V8 no-op on real controller anchors, without borrowing an older persisted proposal. */
function syntheticV8(input: ProposalBrainInput) {
  const data = JSON.parse(input.prompt.split("INPUT_DATA_JSON\n")[1]);
  assert.equal(data.evidence.schemaVersion, 8);
  const last = data.evidence.anchors.length - 1, raw = data.rawIntent;
  return { schemaVersion: 8, summary: "TEST ONLY complete V8 storage and cold read, not rendered treatment.",
    graphicsStyle: "catalog-first", graphicsStyleRationale: "TEST ONLY retain the synthetic cut without authoring a catalog graphic.",
    clauses: [{ start: 0, end: raw.length, quote: raw, disposition: "supported",
      rationale: "TEST ONLY preserve the exact held synthetic program.", operationIndices: [0] }],
    beats: [{ startAnchor: 0, endAnchorExclusive: last, purpose: "opening",
      summary: "TEST ONLY complete short synthetic program.", supportsBeatIndices: [] }],
    operations: [oldOperation("preserve-cut")], beatDecisions: [], hookSeamDecisions: [],
    openingEndAnchor: last, continuityEndAnchor: last, audioPolicy: "preserve-full-program", colorPolicy: "preserve" };
}

/** Real hashed synthetic asset with TEST-stubbed admission facts; coordinates are declarations, not observed framing. */
function syntheticPresenterV8(input: ProposalBrainInput) {
  const data = JSON.parse(input.prompt.split("INPUT_DATA_JSON\n")[1]);
  const asset = data.evidence.presenterPolicy.assets[0];
  assert.equal(asset.assetId, "presentation-1"); assert.equal(asset.kind, "video"); assert.equal(asset.rights, "unverified");
  const base = syntheticV8(input);
  return { ...base, operations: [layoutOperation({ startAnchor: 0, endAnchorExclusive: data.evidence.anchors.length - 1,
    presenterLayout: { ...layoutSelection(), sourceIds: ["raw-1"], enterFrames: 1, exitFrames: 1 } })] };
}

test("real video bytes with TEST admission facts survive V8 store/history and the Python selected-source join", async () => {
  const fixture = await createGuidedProposalFixture({ rawIntent: PRESENTER_RAW, proposalVersion: 8, output: syntheticPresenterV8,
    graphicsOff: true, presentationAsset: "admitted-silent-video" });
  try {
    const stored = readGuidedTreatmentProposal(fixture.ctx.dir), bindings = stored.result.executionBindings;
    assert.equal(stored.submission.rawIntent, PRESENTER_RAW);
    assert.equal(stored.result.proposal.clauses[0].quote, PRESENTER_RAW);
    assert.deepEqual(stored.result.blockers, []); assert.equal(bindings!.schemaVersion, 2);
    if (bindings!.schemaVersion !== 2) throw new Error("Expected actual V8 frame bindings");
    assert.equal(bindings!.presenterLayouts[0].operationIndex, 0);
    assert.equal(bindings!.presenterLayouts[0].endFrameExclusive, fixture.receipt.media.videoFrames);
    assert.deepEqual(bindings!.presenterLayouts[0].layout.sourceIds, ["raw-1"]);
    assert.deepEqual(stored.result.candidate!.presenterLayouts, bindings!.presenterLayouts);
    const code = "import json,sys; from pathlib import Path; from cut_preview_io import bound_json; from ingest_execution_authority import execution_media_authority_entries; "
      + "from guided_presenter_assets import select_presenter_assets; from graphics.presenter_layout_contract import PresenterCanvas; "
      + "plan=json.load(sys.stdin); manifest=bound_json(Path(sys.argv[1])); entries=execution_media_authority_entries(plan,manifest,sys.argv[1]); "
      + "assert entries is not None; selected=select_presenter_assets(plan,manifest,entries,PresenterCanvas(1920,1080,int(sys.argv[2]),'yuv420p')); "
      + "print(json.dumps([{'operationIndex':s.operation_index,'assetId':s.admission.asset_id,'lane':s.admission.lane,'executable':s.executable} for s in selected]))";
    const observed = execFileSync(pythonInterpreter(), ["-c", code, fixture.ctx.manifestPath, String(fixture.receipt.media.videoFrames)], {
      input: JSON.stringify(stored.result.candidate), encoding: "utf8", timeout: 10000,
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONPATH: ["scripts", "scripts/producer"].join(path.delimiter) },
    });
    assert.deepEqual(JSON.parse(observed), [{ operationIndex: 0, assetId: "presentation-1", lane: "source", executable: false }]);
    assert.equal(readHistoricalGuidedProposal(fixture.ctx.dir).proposalVersion, 8);
    assert.equal(existsSync(path.join(fixture.ctx.dir, "final.mp4")), false);
    assert.throws(() => buildProposalReadinessPacket(stored), CAPTION_REFUSAL);
    await assertCaptionRefusalBeforeWork(fixture);
  } finally { fixture.cleanup(); }
});

test("actual V8 compile, immutable storage, cold read/history and exact replay never invoke readiness or rendering", async () => {
  const fixture = await createGuidedProposalFixture({ rawIntent: RAW, proposalVersion: 8, output: syntheticV8, graphicsOff: true });
  try {
    const originalPlan = readFileSync(fixture.ctx.planPath), originalJob = readFileSync(fixture.jobPath);
    const stored = readGuidedTreatmentProposal(fixture.ctx.dir);
    assert.equal(stored.evidence.schemaVersion, 8); assert.equal(stored.result.proposal.schemaVersion, 8);
    assert.deepEqual(stored.evidence.catalog, []); // Explicit initial graphics-off: no measured-catalog claim.
    assert.deepEqual(stored.evidence.presenterPolicy!.assets, []);
    assert.equal(stored.result.executionBindings!.schemaVersion, 2); assert.deepEqual(stored.result.blockers, []);
    assert.equal(stored.receipt.executable, false); assert.equal(stored.available, false);
    assert.equal(stored.submission.rawIntent, RAW); assert.equal(stored.result.candidate!.presenterLayouts, undefined);
    const packet = buildProposalReadinessPacket(stored);
    assert.equal(packet.proposal.schemaVersion, 8); assert.equal(packet.evidence.schemaVersion, 8);
    assert.equal(packet.executionBindings?.schemaVersion, 2);
    assert.deepEqual(packet.executionBindings, stored.result.executionBindings);
    const history = readHistoricalGuidedProposal(fixture.ctx.dir);
    assert.equal(history.proposalVersion, 8); assert.equal(history.currentExecutionAuthority, false);
    assert.equal(history.rawIntent, RAW); assert.equal(history.readinessCurrentness, "not-revalidated");
    const replay = await compileGuidedTreatmentProposal({ dir: fixture.ctx.dir, submission: stored.compileSubmission }, {
      proposalVersion: 8, brain: async () => { throw new Error("Exact replay must not invoke a provider"); },
    });
    assert.equal(replay.replayed, true); assert.equal(replay.proposalHash, stored.proposalHash);
    assert.equal(replay.generationStartedAt, stored.generationStartedAt);
    assert.deepEqual(readFileSync(fixture.ctx.planPath), originalPlan);
    assert.deepEqual(readFileSync(fixture.jobPath), originalJob);
    for (const name of ["base.mp4", "final.mp4", ".sniper-qc-approved.json", ".render-graph-v1/ACTIVE.json"]) {
      assert.equal(existsSync(path.join(fixture.ctx.dir, name)), false);
    }
  } finally { fixture.cleanup(); }
});
