/** TEST-only explicit cut attestation and V6 output; real service authority and gates. */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { parseGuidedCutSubmissionV2 } from "@/lib/producer/contracts/guided-workflow-v2";
import { parseRawTreatmentSubmissionV1, parseTreatmentCompileSubmissionV1 } from "@/lib/producer/contracts/raw-treatment-v1";
import type { ProposalBrainInput } from "../guided-proposal-compiler";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { observeGuidedCutV2 } from "../guided-cut-v2-store";
import { acceptGuidedCutV2, readGuidedCutV2 } from "../guided-cut-v2";
import { admitRawTreatment } from "../guided-raw-treatment";
import { readRawTreatmentAdmission } from "../guided-raw-treatment-store";
import { compileGuidedTreatmentProposal } from "../guided-proposal";
import { readGuidedTreatmentProposal } from "../guided-proposal-store";
import { reviewGuidedTreatmentProposal } from "../guided-proposal-review";
import { readGuidedProposalReadiness } from "../guided-proposal-review-store";
import { passingReadinessResult, readinessRequest } from "./_guided-proposal-fixture";

export const CROP = [0.25, 0, 0.5, 1];
const CROP_REQUEST = "Crop raw-1 to the exact normalized rectangle [0.25,0,0.5,1], using fill with tracking off.";
const CAPTION_REQUEST = " Caption every kept word with the Producer line preset, with no suppression.";
export const RAW_V6_SHORT = CROP_REQUEST + CAPTION_REQUEST;

/** Author actual V6 positions, never store a crop as a preserve-cut operation. */
export function v6ShortProposal(input: ProposalBrainInput) {
  const evidence = JSON.parse(input.prompt.split("INPUT_DATA_JSON\n")[1]).evidence;
  assert.equal(evidence.schemaVersion, 6); assert.equal(evidence.target.mode, "short");
  assert.equal(evidence.target.width, 1080); assert.equal(evidence.target.height, 1920);
  assert.equal(evidence.totalFrames, 480); assert.equal(evidence.frameRate, "30/1");
  const last = evidence.anchors.length - 1;
  const empty = { beatIndex: null, catalogKind: null, variables: null, grade: null,
    startAnchor: null, endAnchorExclusive: null, presentation: null, captions: null, reframe: null };
  return { schemaVersion: 6, summary: "TEST ONLY explicit manual crop plus captured captions, not creator quality.",
    graphicsStyle: "cutaway-only", graphicsStyleRationale: "TEST ONLY no catalog graphics were requested; preserve the original graphics-off lane.",
    clauses: [{ start: 0, end: CROP_REQUEST.length, quote: CROP_REQUEST, disposition: "supported",
      rationale: "TEST ONLY exact submitted crop, no inferred subject tracking.", operationIndices: [0] },
    { start: CROP_REQUEST.length, end: RAW_V6_SHORT.length, quote: CAPTION_REQUEST, disposition: "supported",
      rationale: "TEST ONLY separate all-kept caption preset request.", operationIndices: [1] }],
    beats: [{ startAnchor: 0, endAnchorExclusive: last, purpose: "opening", summary: "TEST ONLY complete16-second source.", supportsBeatIndices: [] }],
    operations: [{ ...empty, type: "reframe-manual-short", clauseIndex: 0,
      reason: "TEST ONLY use the exact requested normalized crop without tracking.",
      reframe: { schemaVersion: 1, sourceId: "raw-1", layout: "fill", crop: [...CROP], track: false } },
    { ...empty, type: "captions-full-program", clauseIndex: 1, reason: "TEST ONLY caption every kept word with the explicitly requested preset.",
      captions: { schemaVersion: 1, preset: "producer-config-line-v1", coverage: "all-kept-transcript-words", suppression: "none" } }],
    beatDecisions: [], hookSeamDecisions: [], openingEndAnchor: last, continuityEndAnchor: last,
    audioPolicy: "preserve-full-program", colorPolicy: "preserve" };
}

async function acceptTestCut(dir: string): Promise<void> {
  const before = observeGuidedCutV2(dir);
  // Explicit TEST attestation only; no actual human speech/listening qualification.
  const submission = parseGuidedCutSubmissionV2({ schemaVersion: 2, operation: "accept-cut-await-treatment",
    idempotencyKey: randomUUID(), expectedToken: before.job.token, expectedJournalHash: before.sha256,
    requestHash: before.request.requestHash, executionKey: before.receipt.executionKey,
    receiptHash: before.receipt.receiptHash, mediaSha256: before.receipt.media.sha256,
    attestation: { watched: true, listened: true, acceptsExactCut: true, understandsTreatmentPending: true } });
  await acceptGuidedCutV2({ dir, submission });
}

/** No source/readiness/gate overrides; only compiler and independent critics are synthetic. */
export async function compileV6ShortReadiness(dir: string, remainingMs: () => number) {
  remainingMs();
  await acceptTestCut(dir);
  remainingMs();
  const cut = readGuidedCutV2(dir);
  await admitRawTreatment({ dir, submission: parseRawTreatmentSubmissionV1({ schemaVersion: 1,
    operation: "propose-post-cut-treatment", requestId: randomUUID(), idempotencyKey: randomUUID(),
    expectedToken: cut.job.token, expectedJournalHash: cut.sha256, cutDecisionHash: cut.pointer.cutDecisionHash,
    parentRevisionHash: cut.pointer.pictureLockedRevisionHash, rawIntent: RAW_V6_SHORT }) });
  const admitted = readRawTreatmentAdmission(dir);
  remainingMs();
  await compileGuidedTreatmentProposal({ dir, submission: parseTreatmentCompileSubmissionV1({ schemaVersion: 1,
    operation: "compile-post-cut-proposal", idempotencyKey: randomUUID(), expectedToken: admitted.job.token,
    expectedJournalHash: admitted.sha256, treatmentAdmissionHash: admitted.pointer.treatmentAdmissionHash }) },
  { proposalVersion: 6, brain: async (input) => ({ output: v6ShortProposal(input), provider: "codex", model: "TEST-ONLY-compiler",
    effort: "xhigh", elapsedMs: 1, promptHash: canonicalJsonSha256(input.prompt) }) });
  const compiled = readGuidedTreatmentProposal(dir);
  remainingMs();
  assert.deepEqual(compiled.result.blockers, []); assert.ok(compiled.result.candidate);
  assert.equal(compiled.result.proposal.schemaVersion, 6);
  const readiness = await reviewGuidedTreatmentProposal({ dir, submission: readinessRequest(dir) },
    { critic: async (input) => passingReadinessResult(input) });
  assert.ok(readiness.pointer.treatmentDraftRevisionHash, "Real readiness gates must produce a treatment draft");
  remainingMs();
  return readGuidedProposalReadiness(dir);
}
