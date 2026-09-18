/** TEST ONLY authority-shaped JSON. Exercises byte/cold readers, never source admission, journals, media or human approval. */
import path from "node:path";
import { randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import { atomicCreateFileSync } from "../atomic-file";
import { canonicalJson, canonicalJsonSha256 as hash } from "../auto-edit-hash";
import { presenterProfileFixture, materializeProfile } from "@/lib/producer/__tests__/_guided-presenter-profile-fixture";
import { parseTreatmentProposalV8 } from "@/lib/producer/contracts/treatment-proposal-v8";
import { openingProfileForContext } from "../guided-opening-profile";
import { proposalOccurrenceEvidence } from "../guided-proposal-bindings";
import { PROPOSAL_PRESENTATION_POLICY } from "@/lib/producer/contracts/treatment-proposal-v3";
import { OPENING_DOCUMENT_NAMES, OPENING_MEDIA_SCOPE } from "@/lib/producer/contracts/guided-opening-media-v1";
import type { GuidedPresenterProfileInput } from "@/lib/producer/contracts/guided-presenter-profile";
import type { ReviewedProposalInput } from "../guided-proposal-review-packet";

export const TEST_PRESENTER_HASH = "a".repeat(64), TEST_STARTED = "2026-09-07T00:00:00.000Z";
const SPAN = { startFrame: 0, endFrameExclusive: 600 };

export function presenterReaderContext(short: boolean, captioned: boolean) {
  const input = presenterProfileFixture({ short, captioned });
  const accepted = { ...input.accepted, cutTrack: [{ sourceId: "raw-1", start: 0, end: 20 }] };
  const proposal = parseTreatmentProposalV8(input.proposal);
  proposal.operations = proposal.operations.map(row => row.presenterLayout
    ? { ...row, presenterLayout: { ...row.presenterLayout, sourceIds: ["raw-1"] } } : row);
  const evidence = { ...input.evidence, presentationPolicy: PROPOSAL_PRESENTATION_POLICY,
    segments: [{ index: 0, sourceId: "raw-1", startFrame: 0, endFrameExclusive: 600 }] } as typeof input.evidence;
  return materializeProfile({ accepted, proposal, evidence, manifest: { ...input.manifest,
    sourceSetAdmission: { sourceSetDigest: TEST_PRESENTER_HASH } } });
}

/** Pure readiness packet input stub, not a real readable readiness or human acceptance record. */
export function presenterReadinessStub(input: GuidedPresenterProfileInput): ReviewedProposalInput {
  return { plan: { value: input.accepted }, manifest: { value: input.manifest }, evidence: input.evidence,
    result: { proposal: input.proposal, candidate: input.candidate, executionBindings: input.bindings, blockers: [],
      range: { approval: SPAN, review: SPAN } }, proposalHash: TEST_PRESENTER_HASH, clock: { hash: TEST_PRESENTER_HASH },
    generationStartedAt: TEST_STARTED, submission: { rawIntent: "TEST ONLY" },
    pointer: { treatmentAdmissionHash: TEST_PRESENTER_HASH, cutDecisionHash: TEST_PRESENTER_HASH,
      pictureLockedRevisionHash: TEST_PRESENTER_HASH } } as unknown as ReviewedProposalInput;
}

function timelineProjection(accepted: Record<string, unknown>) {
  const segment = { index: 0, source_id: "raw-1", src_start: 0, src_end: 20, speed: 1, out_start: 0, out_end: 20, audio_lead_s: 0 };
  const timelineMap = { outputDuration: 20, segments: [segment] };
  const timelineMapHash = hash({ quantization: "millionths-half-up-v1", outputDuration: 20_000_000,
    segments: [{ ...segment, src_end: 20_000_000, speed: 1_000_000, out_end: 20_000_000 }] });
  return { schemaVersion: 1, kind: "compatibility-timeline-projection", approvedCutPlanHash: hash(accepted),
    cutTrackDigest: hash(accepted.cutTrack), cutDecisionsDigest: hash(accepted.cutDecisions), compilerHash: TEST_PRESENTER_HASH,
    timelineMap, timelineMapHash };
}

function initialDocuments(input: GuidedPresenterProfileInput) {
  const cutProjection = timelineProjection(input.accepted), manifestHash = hash(input.manifest);
  const shared = { cutAuthorityDigest: TEST_PRESENTER_HASH, cutApprovalReceiptHash: TEST_PRESENTER_HASH,
    cutReviewApprovalReceiptHash: TEST_PRESENTER_HASH, timelineMapHash: cutProjection.timelineMapHash,
    projectionReceiptHash: hash(cutProjection) };
  const pictureLock = { ...shared, manifestHash, approvedCutPlanHash: hash(input.accepted) };
  const request = { schemaVersion: 1, createdAt: TEST_STARTED, requestKey: TEST_PRESENTER_HASH, planHash: hash(input.accepted),
    authorityDigest: TEST_PRESENTER_HASH, pictureLockHash: hash(pictureLock), ...shared };
  const cutRequest = { ...request, requestHash: hash(request) };
  return { acceptedPlan: input.accepted, candidatePlan: input.candidate, manifest: input.manifest, cutProjection,
    timelineMap: cutProjection.timelineMap, pictureLock, cutRequest, frameBindings: input.bindings,
    occurrences: proposalOccurrenceEvidence(input.evidence), treatmentDraft: { TEST_ONLY: "not a real treatment revision" },
    readinessBundle: { TEST_ONLY: "not actual critic or gate results" } };
}

function completeDocuments(input: GuidedPresenterProfileInput) {
  const docs = initialDocuments(input), draftHash = hash(docs.treatmentDraft);
  const readinessPacket = { ...presenterReadinessStub(input).result, range: { approval: SPAN, review: SPAN },
    evidence: input.evidence, proposalHash: TEST_PRESENTER_HASH, cutDecisionHash: TEST_PRESENTER_HASH,
    parentRevisionHash: TEST_PRESENTER_HASH, treatmentAdmissionHash: TEST_PRESENTER_HASH,
    clockHash: TEST_PRESENTER_HASH, generationStartedAt: TEST_STARTED };
  const readinessReceipt = { packetHash: hash(readinessPacket), reviewBundleHash: hash(docs.readinessBundle),
    treatmentDraftRevisionHash: draftHash, proposalHash: TEST_PRESENTER_HASH };
  const authority = { schemaVersion: 2, kind: "guided-opening-media-authority", scope: OPENING_MEDIA_SCOPE,
    profile: openingProfileForContext(input), runId: "TEST-ONLY-presenter-documents", previewAttempt: 1,
    contextHash: TEST_PRESENTER_HASH, cutDecisionHash: TEST_PRESENTER_HASH, acceptedRevisionHash: TEST_PRESENTER_HASH,
    requestHash: docs.cutRequest.requestHash, pictureLockHash: hash(docs.pictureLock), projectionHash: hash(docs.cutProjection),
    sourceSetDigest: TEST_PRESENTER_HASH, manifestHash: hash(docs.manifest), timelineMapHash: docs.cutProjection.timelineMapHash,
    rawAdmissionHash: TEST_PRESENTER_HASH, proposalHash: TEST_PRESENTER_HASH, readinessHash: hash(readinessReceipt), draftRevisionHash: draftHash,
    candidatePlanHash: hash(docs.candidatePlan), frameBindingsHash: hash(docs.frameBindings), occurrenceEvidenceHash: hash(docs.occurrences),
    clockHash: TEST_PRESENTER_HASH, generationStartedAt: TEST_STARTED, frameRate: "30/1", totalFrames: 600,
    target: input.accepted.target, core: SPAN, review: SPAN };
  return { ...docs, authority, readinessPacket, readinessReceipt };
}

/** New-only inert files, not a captured runtime, actual admission, worker invocation or media qualification. */
export function writePresenterDocuments(root: string, input: GuidedPresenterProfileInput) {
  const docs = completeDocuments(input);
  const write = (name: string, value: unknown) => {
    const file = path.join(root, `${name}.json`); atomicCreateFileSync(file, canonicalJson(value));
    return { path: file, sha256: hash(value) };
  };
  const documents = Object.fromEntries(OPENING_DOCUMENT_NAMES.map(name => [name, write(name, docs[name])])) as
    Record<typeof OPENING_DOCUMENT_NAMES[number], ReturnType<typeof write>>;
  const files: unknown[] = [], digest = hash(files), lock = write("TEST-empty-pipeline-lock", { files, digest });
  const snapshotRoot = path.join(root, "TEST-not-a-real-pipeline"); mkdirSync(snapshotRoot);
  const core = { schemaVersion: 1, kind: "guided-opening-media-input", executionId: randomUUID(), profile: docs.authority.profile,
    documents, pipeline: { snapshotRoot, lockPath: lock.path, lockSha256: lock.sha256, digest } };
  const value = { ...core, executionInputHash: hash(core) }, ref = write("input", value);
  return { docs, value, ref };
}
