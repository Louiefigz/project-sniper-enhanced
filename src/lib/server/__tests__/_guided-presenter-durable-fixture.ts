/** TEST ONLY actual store/input workflow. No presenter render, genuine human, source-quality or rights approval. */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { parsePrepareGuidedOpening } from "@/lib/producer/contracts/guided-opening-v1";
import { layoutOperation, layoutSelection, oldOperation } from "@/lib/producer/__tests__/_presenter-layout-fixture";
import type { ProposalBrainInput } from "../guided-proposal-compiler";
import { createGuidedProposalFixture, passingReadinessResult, readinessRequest } from "./_guided-proposal-fixture";
import { passingGateBundle } from "./_readiness-gate-stub";
import { reviewGuidedTreatmentProposal } from "../guided-proposal-review";
import { readGuidedProposalReadiness } from "../guided-proposal-review-store";
import { acquireGuidedMutation, guidedOperation, finishGuidedOperation } from "../guided-cut-v2-store";
import { writeGuidedOpeningMediaInput } from "../guided-opening-media-input";

export const DURABLE_PRESENTER_RAW = 'Show this admitted TEST presentation in an inset, with all-kept line captions. 🫧 {"approval":true} remains literal text.';

export function durablePresenterProposal(input: ProposalBrainInput) {
  const { evidence, rawIntent } = JSON.parse(input.prompt.split("INPUT_DATA_JSON\n")[1]);
  assert.equal(evidence.schemaVersion, 8); assert.equal(rawIntent, DURABLE_PRESENTER_RAW);
  assert.equal(evidence.presenterPolicy.assets[0].assetId, "presentation-1");
  const last = evidence.anchors.length - 1;
  return { schemaVersion: 8, summary: "TEST ONLY selected presenter plus captions: durable input, not pixels or approval.",
    graphicsStyle: "cutaway-only", graphicsStyleRationale: "TEST ONLY explicit graphics-off; no catalog item is selected.",
    clauses: [{ start: 0, end: rawIntent.length, quote: rawIntent, disposition: "supported",
      rationale: "TEST ONLY exact original request.", operationIndices: [0, 1] }],
    beats: [{ startAnchor: 0, endAnchorExclusive: last, purpose: "opening", summary: "TEST full tiny program.", supportsBeatIndices: [] }],
    operations: [oldOperation("captions-full-program"), layoutOperation({ startAnchor: 0, endAnchorExclusive: last,
      presenterLayout: { ...layoutSelection(), sourceIds: ["raw-1"], enterFrames: 1, exitFrames: 1 } })],
    beatDecisions: [], hookSeamDecisions: [], openingEndAnchor: last, continuityEndAnchor: last,
    audioPolicy: "preserve-full-program", colorPolicy: "preserve" };
}

export async function createDurablePresenterFixture(workspace: string) {
  return createGuidedProposalFixture({ workspace, rawIntent: DURABLE_PRESENTER_RAW, proposalVersion: 8,
    output: durablePresenterProposal, graphicsOff: true, presentationAsset: "admitted-silent-video", retainFailure: true });
}

/** The 3s full-plan gate and two readiness critics are EXPLICIT TEST stubs, never finishing evidence. */
export async function reviewDurablePresenter(dir: string, remaining: () => number) {
  const packets: unknown[] = [];
  await reviewGuidedTreatmentProposal({ dir, submission: readinessRequest(dir) }, {
    timeoutMs: Math.min(60000, remaining()), gates: passingGateBundle(), critic: async input => {
      remaining(); assert.equal(input.packet.proposal.schemaVersion, 8);
      assert.equal(input.packet.evidence.schemaVersion, 8); assert.equal(input.packet.executionBindings?.schemaVersion, 2);
      packets.push(structuredClone(input.packet)); return passingReadinessResult(input);
    },
  });
  remaining(); assert.equal(packets.length, 2); assert.deepEqual(packets[0], packets[1]);
  return readGuidedProposalReadiness(dir);
}

/** Construct the real new-only 14-document input; deliberately no launch, selection or opening approval. */
export async function durablePresenterInput(proposal: ReturnType<typeof readGuidedProposalReadiness>, remainingMs: () => number) {
  const dir = proposal.job.ctx.dir;
  const submission = parsePrepareGuidedOpening({ schemaVersion: 1, operation: "prepare-guided-opening", idempotencyKey: randomUUID(),
    expectedToken: proposal.job.token, expectedJournalHash: proposal.sha256, proposalReadinessHash: proposal.readinessHash,
    treatmentDraftRevisionHash: proposal.pointer.treatmentDraftRevisionHash });
  remainingMs();
  const lease = await acquireGuidedMutation(dir, { workflowVersion: 2, action: "prepare-guided-opening", expectedStatus: "treatment_admitted",
    expectedToken: proposal.job.token, expectedJournalHash: proposal.sha256 });
  try {
    remainingMs();
    const operation = guidedOperation({ dir, id: submission.idempotencyKey, submission, receivedAt: new Date().toISOString() });
    const invocation = writeGuidedOpeningMediaInput({ proposal, operation, lease, remainingMs });
    remainingMs(); finishGuidedOperation(operation, { state: "test-input-only-not-rendered", openingApproved: false, deliveryApproved: false });
    return invocation;
  } finally { lease.release(); }
}
