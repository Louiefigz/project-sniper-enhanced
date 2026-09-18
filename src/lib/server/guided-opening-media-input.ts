import { mkdirSync } from "node:fs";
import path from "node:path";
import { readCutPreviewObject, observeCutPreviewFile, assertCutPreviewDirectory } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { parseCompatibilityProjection } from "@/app/api/producer/auto-edit/compatibility-timeline-projection";
import { parsePrepareGuidedOpeningRequest } from "@/lib/producer/contracts/guided-source-color-v1";
import { parseCutApprovalRequest } from "@/lib/producer/contracts/cut-approval-request";
import { parseCurrentTreatmentProposal as parseTreatmentProposal } from "@/lib/producer/contracts/treatment-proposal-v8";
import { assertGuidedMusicIntent } from "./guided-proposal-music";
import { assertGuidedPresenterIntent } from "./guided-proposal-presenter";
import { assertOpeningFinishingMetadata } from "./guided-opening-finishing";
import { assertOpeningBindingContext, assertOpeningRequestLanes, type OpeningProposalContext } from "./guided-opening-request-lanes";
import { openingProfileForContext, hasPresenterMediaRequest, assertPresenterOpeningMetadata } from "./guided-opening-profile";
import { OPENING_DOCUMENT_NAMES, OPENING_MEDIA_SCOPE, parseCurrentOpeningMediaAuthority as parseGuidedOpeningMediaAuthority,
  parseCurrentOpeningMediaInput as parseGuidedOpeningMediaInput, type GuidedOpeningMediaInputV1, type OpeningDocumentName, type OpeningDocumentReference } from "@/lib/producer/contracts/guided-opening-media-v1";
import { openingMediaProfileForPlan, isManualMediaProfile } from "@/lib/producer/contracts/guided-media-profile";
import { isCaptionProfile, assertCaptionGraphWorkload } from "@/lib/producer/contracts/guided-caption-profile";
import { sha256, objectValue } from "@/lib/producer/contracts/validation";
import { atomicCreateFileSync } from "./atomic-file";
import { canonicalJson, canonicalJsonSha256 } from "./auto-edit-hash";
import { assertOpeningSubmission, buildOpeningAuthority, type OpeningReadiness } from "./guided-opening-authority";
import { proposalOccurrenceEvidence, assertGuidedFrameBindings, type GuidedFrameBindings } from "./guided-proposal-bindings";
import type { ProposalEvidence } from "./guided-proposal-evidence";
import { readGuidedExecution, type guidedOperation } from "./guided-cut-v2-store";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import type { ProjectMutationLease } from "./project-mutation-lease";
import type { TreatmentProposalV9 } from "@/lib/producer/contracts/treatment-proposal-v9";
import type { TreatmentProposalV10 } from "@/lib/producer/contracts/treatment-proposal-v10";

/** New media preparation metadata is separate from the immutable unavailable-only record. */
export function openingMediaAuthority(proposal: OpeningReadiness, heldProfile?: unknown) {
  if (proposal.result.proposal.schemaVersion === 9 || proposal.result.proposal.schemaVersion === 10) throw new Error("Native Shorts require their own project executor; legacy opening is unavailable");
  const profile = openingProfileForContext({ accepted: objectValue(proposal.plan?.value, "original accepted plan"), candidate: proposal.result.candidate!, manifest: objectValue(proposal.manifest?.value, "original manifest"),
    proposal: proposal.result.proposal, evidence: proposal.evidence, bindings: proposal.result.executionBindings }, heldProfile);
  if (proposal.result.proposal.schemaVersion >= 7) assertGuidedMusicIntent(proposal.plan.value, proposal.job.ctx.intent);
  if (proposal.result.proposal.schemaVersion === 8) assertGuidedPresenterIntent(proposal.plan.value, proposal.job.ctx.intent);
  const built = buildOpeningAuthority(proposal), { adapter: _adapter, ...identity } = built.input; void _adapter;
  const metadata = { plan: proposal.result.candidate!, bindings: built.bindings, reviewEndFrame: built.input.review.endFrameExclusive,
    proposal: proposal.result.proposal, evidence: proposal.evidence, accepted: proposal.plan.value, manifest: proposal.manifest.value };
  assertOpeningMediaMetadata(metadata);
  return { authority: parseGuidedOpeningMediaAuthority({ ...identity, schemaVersion: 2, kind: "guided-opening-media-authority",
    scope: OPENING_MEDIA_SCOPE, profile }), bindings: metadata.bindings };
}

function pythonTruthy(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0;
  if (value !== null && typeof value === "object") return Object.keys(value).length > 0;
  return Boolean(value);
}

/** Mirror guided_opening_frames._profile's known metadata exclusions before launch.
 * Python still checks the full root registry, source class, media and execution independently. */
function assertOpeningPlanProfile(plan: Record<string, unknown>): void {
  if (Object.hasOwn(plan, "presenterLayouts")) throw new Error("Legacy opening profile has no presenterLayouts execution owner");
  const profile = openingMediaProfileForPlan(plan);
  assertOpeningFinishingMetadata(plan);
  const captioned = isCaptionProfile(profile);
  const target = objectValue(plan.target, "opening target"), mode = target.mode;
  if (mode !== "short" && mode !== "longform") throw new Error("Private opening target mode is unsupported");
  const unsupported = [...(captioned ? [] : ["captionsTrack"]), "titleCards", "brollTrack", "baselineLook", "punchIns",
    "transitions"];
  const active = unsupported.filter((key) => pythonTruthy(plan[key]));
  const reframe = pythonTruthy(plan.reframe) ? objectValue(plan.reframe, "opening reframe") : {};
  if (!isManualMediaProfile(profile) && (Object.keys(reframe).some((key) => key !== "strategy")
      || (Object.hasOwn(reframe, "strategy") ? reframe.strategy : mode === "short" ? "face" : "none") !== "none")) active.push("reframe");
  const captions = pythonTruthy(plan.captions) ? objectValue(plan.captions, "opening captions") : {};
  if (!captioned && pythonTruthy(Object.hasOwn(captions, "burn") ? captions.burn : mode === "short")) active.push("captions.burn");
  if (active.length) throw new Error(`Private opening profile has not qualified requested lanes: ${active.join(", ")}`);
  if (!Array.isArray(plan.cutTrack) || !plan.cutTrack.length) throw new Error("Private opening needs a nonempty unity cut");
  for (const value of plan.cutTrack) {
    const cut = objectValue(value, "opening cut"), speed = Object.hasOwn(cut, "speed") ? cut.speed : 1;
    if (typeof speed !== "number" || speed !== 1 || (cut.audioLeadMs !== undefined && cut.audioLeadMs !== 0)) {
      throw new Error("Private opening semantic execution has not qualified speed/J-cut leads");
    }
  }
}

/** Predicate parity with graphics/pip_hole.entry_has_hole; conditional holes retain their opt-out. */
function openingEntryHasHole(entry: Record<string, unknown>): boolean {
  if (entry.kind === "module-takeover") return true;
  if (!["module-scoreboard", "module-pipeline", "module-ledger-dark"].includes(String(entry.kind))) return false;
  const spec = pythonTruthy(entry.spec) ? objectValue(entry.spec, "opening graphic spec") : {};
  return pythonTruthy(spec.presenterFrame);
}

interface MediaMetadata extends Partial<Omit<OpeningProposalContext, "proposal">> {
  plan: Record<string, unknown>; bindings: GuidedFrameBindings | null; reviewEndFrame: number;
  proposal?: OpeningProposalContext["proposal"] | TreatmentProposalV9 | TreatmentProposalV10;
  accepted?: Record<string, unknown>; manifest?: Record<string, unknown>;
}

function assertLegacyMetadata(input: MediaMetadata): asserts input is MediaMetadata & Partial<OpeningProposalContext> {
  if (input.proposal?.schemaVersion === 9 || input.proposal?.schemaVersion === 10 || input.plan.executionRoute === "native-short-v1" || input.plan.nativeDirection) {
    throw new Error("Native Shorts cannot execute through the legacy opening/body renderer");
  }
}

/** Shared profile screening. All-row mode never silently drops a later presentation. */
function assertMediaMetadata(input: MediaMetadata, allPresentations: boolean): asserts input is MediaMetadata & { bindings: GuidedFrameBindings } {
  assertLegacyMetadata(input);
  if (hasPresenterMediaRequest(input.proposal, input.plan)) { assertPresenterOpeningMetadata(input, allPresentations); return; }
  assertOpeningPlanProfile(input.plan);
  const bindings = input.bindings, track = input.plan.graphicsTrack ?? [];
  if (!bindings || (bindings.schemaVersion !== 1 && bindings.schemaVersion !== 2) || bindings.unboundInheritedGraphicIds.length || !Array.isArray(track)
      || track.length > 128 || bindings.graphics.length !== track.length
      || !Number.isSafeInteger(input.reviewEndFrame) || input.reviewEndFrame <= 0 || input.reviewEndFrame > bindings.totalFrames) {
    throw new Error("Private opening needs exact whole-candidate bindings; inherited graphics are unsupported");
  }
  assertOpeningBindingContext({ ...input, bindings });
  const ids = new Set<string>();
  for (const [index, row] of bindings.graphics.entries()) {
    const entry = objectValue(track[index], "bound candidate graphic");
    if (row.order !== index || typeof row.graphicId !== "string" || !row.graphicId.trim()
        || row.graphicId.length > 200 || row.graphicId !== entry.id || ids.has(row.graphicId)) {
      throw new Error("Private graphic metadata lacks exact ordered unique whole-candidate coverage");
    }
    ids.add(row.graphicId);
  }
  const selected = allPresentations ? bindings.graphics : bindings.graphics.filter((row) => row.startFrame < input.reviewEndFrame);
  if (!allPresentations && selected.length > 8) throw new Error("Private opening exceeds its initial eight-graphic admission bound");
  for (const row of selected) {
    const presentation = row.presentation, entry = objectValue(track[row.order], "opening graphic");
    if (presentation.schemaVersion !== 1 || presentation.anchor !== "own-screen" || presentation.placement !== "full-canvas"
        || presentation.compositeMode !== "normal" || presentation.baseTreatment !== "preserve"
        || typeof presentation.rationale !== "string" || !presentation.rationale.trim() || entry.anchor !== "own-screen"
        || entry.takeoverBase != null || pythonTruthy(entry.exitOnCut) || pythonTruthy(entry.placement) || openingEntryHasHole(entry)) {
      throw new Error("Private opening has not qualified requested graphic presentation or additional placement/effect intent");
    }
  }
}

/** Cheap opening-only refusal, not admission/decoding/approval authority. */
export function assertOpeningMediaMetadata(input: MediaMetadata): asserts input is MediaMetadata & { bindings: GuidedFrameBindings } {
  assertMediaMetadata(input, false);
  if (!hasPresenterMediaRequest(input.proposal, input.plan) && isCaptionProfile(openingMediaProfileForPlan(input.plan))) {
    assertCaptionGraphWorkload(input.plan, input.bindings, input.bindings.graphics.length);
  }
}

/** Check ALL body metadata before admission; Python still owes actual all-template,
 * sealed media, resource, source/master, frame-binding and whole-output proof.
 * The structural 128 bound is not a qualified render workload or a new budget. */
export function assertFullProgramMediaMetadata(input: Omit<MediaMetadata, "reviewEndFrame">): void {
  const metadata = { ...input, reviewEndFrame: input.bindings?.totalFrames ?? 0 };
  assertMediaMetadata(metadata, true);
  if (!hasPresenterMediaRequest(input.proposal, input.plan) && isCaptionProfile(openingMediaProfileForPlan(input.plan))) {
    assertCaptionGraphWorkload(input.plan, metadata.bindings, metadata.bindings.graphics.length);
  }
}

function reference(file: string, expected?: string): OpeningDocumentReference {
  const observed = readCutPreviewObject(file);
  if (expected && observed.sha256 !== expected) throw new Error("Opening document differs from its held exact bytes");
  return { path: file, sha256: observed.sha256 };
}
function created(root: string, name: string, value: unknown): OpeningDocumentReference {
  const file = path.join(root, `${name}.json`); atomicCreateFileSync(file, canonicalJson(value));
  return reference(file, canonicalJsonSha256(value));
}

function references(proposal: OpeningReadiness, root: string) {
  const dir = proposal.job.ctx.dir, built = openingMediaAuthority(proposal);
  const stored = (kind: string, hash: unknown) => reference(path.join(dir, ".sniper-authority-v1", "objects", kind, `${sha256(hash, kind)}.json`), String(hash));
  return { authority: created(root, "authority", built.authority),
    acceptedPlan: reference(proposal.job.ctx.planPath, proposal.plan.sha256), cutRequest: created(root, "cut-request", proposal.request),
    pictureLock: reference(path.join(dir, "picture_locks", `${proposal.request.pictureLockHash}.json`), proposal.request.pictureLockHash),
    cutProjection: reference(path.join(dir, "compatibility_projections", `${proposal.request.projectionReceiptHash}.json`), proposal.request.projectionReceiptHash),
    timelineMap: created(root, "timeline-map", proposal.projection.timelineMap),
    readinessReceipt: stored("receipts", proposal.readinessHash), readinessPacket: stored("receipts", proposal.readinessReceipt.packetHash),
    readinessBundle: stored("receipts", proposal.readinessReceipt.reviewBundleHash), treatmentDraft: stored("revisions", proposal.pointer.treatmentDraftRevisionHash),
    candidatePlan: stored("plans", built.authority.candidatePlanHash), manifest: reference(proposal.job.ctx.manifestPath, proposal.manifest.sha256),
    frameBindings: created(root, "frame-bindings", built.bindings), occurrences: created(root, "occurrences", proposalOccurrenceEvidence(proposal.evidence)) };
}

/** New-only, exact-input construction under the caller's real lease. This invokes no media or source job. */
export function writeGuidedOpeningMediaInput(input: { proposal: OpeningReadiness; operation: ReturnType<typeof guidedOperation>;
  lease: ProjectMutationLease; remainingMs: () => number }) {
  const { proposal, operation, lease } = input, dir = proposal.job.ctx.dir, guardLease = cutPreviewLeaseGuard(dir, lease);
  const guard = () => { guardLease(); input.remainingMs(); };
  const submission = parsePrepareGuidedOpeningRequest(operation.record.submission); assertOpeningSubmission(proposal, submission);
  const expectedRoot = path.join(dir, "guided-v2-operations", submission.idempotencyKey, "executions", operation.executionId);
  if (operation.execution !== expectedRoot) throw new Error("Opening input lost its server-derived execution directory");
  const started = readCutPreviewObject(path.join(expectedRoot, "start.json"));
  const start = readGuidedExecution({ dir, id: submission.idempotencyKey, executionId: operation.executionId, hash: started.sha256 });
  if (canonicalJsonSha256(submission) !== start.submissionHash) throw new Error("Opening input differs from its entire retained prepare request");
  guard(); assertCutPreviewDirectory(expectedRoot); openingMediaAuthority(proposal);
  const root = path.join(expectedRoot, "media-input"); mkdirSync(root, { mode: 0o700 }); // Never reuse even a failed construction.
  const documents = references(proposal, root), pipeline = proposal.job.ctx.pipeline;
  if (!pipeline) throw new Error("Opening worker requires its actual pinned pipeline");
  const lock = readCutPreviewObject(pipeline.lockPath);
  if (lock.value.digest !== pipeline.digest || canonicalJsonSha256(lock.value.files) !== pipeline.digest) throw new Error("Opening pinned pipeline lock changed");
  const core = { schemaVersion: 1 as const, kind: "guided-opening-media-input" as const, executionId: operation.executionId,
    profile: openingMediaAuthority(proposal).authority.profile, documents, pipeline: { snapshotRoot: pipeline.snapshotRoot, lockPath: pipeline.lockPath, lockSha256: lock.sha256, digest: pipeline.digest } };
  const value = parseGuidedOpeningMediaInput({ ...core, executionInputHash: canonicalJsonSha256(core) });
  const file = created(root, "input", value); observeGuidedOpeningMediaInput(file.path, file.sha256);
  guard(); if (observeHumanCutJob(dir).sha256 !== proposal.sha256) throw new Error("Opening job changed while preparing exact worker input");
  return { input: value, inputPath: file.path, inputSha256: file.sha256, documentsRoot: root };
}

function readDocuments(input: GuidedOpeningMediaInputV1) {
  const values = {} as Record<OpeningDocumentName, ReturnType<typeof readCutPreviewObject>>; let total = 0;
  for (const name of OPENING_DOCUMENT_NAMES) {
    const ref = input.documents[name], observed = observeCutPreviewFile(ref.path, Math.min(16 * 1024 * 1024, 64 * 1024 * 1024 - total), true);
    total += observed.sizeBytes;
    if (observed.sha256 !== ref.sha256) throw new Error(`Opening exact document changed: ${name}`);
    const value = objectValue(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes)), name);
    values[name] = { ...observed, value };
  }
  return values;
}

function packetBindings(docs: ReturnType<typeof readDocuments>, authority: ReturnType<typeof parseGuidedOpeningMediaAuthority>) {
  const packet = docs.readinessPacket.value, candidate = docs.candidatePlan.value, evidence = objectValue(packet.evidence, "opening full-program evidence") as unknown as ProposalEvidence;
  if (packet.proposalHash !== authority.proposalHash || packet.cutDecisionHash !== authority.cutDecisionHash
      || packet.parentRevisionHash !== authority.acceptedRevisionHash || packet.treatmentAdmissionHash !== authority.rawAdmissionHash
      || packet.clockHash !== authority.clockHash || packet.generationStartedAt !== authority.generationStartedAt
      || canonicalJsonSha256(packet.candidate) !== docs.candidatePlan.sha256
      || canonicalJsonSha256(packet.executionBindings) !== docs.frameBindings.sha256
      || canonicalJsonSha256(proposalOccurrenceEvidence(evidence)) !== docs.occurrences.sha256
      || evidence.frameRate !== authority.frameRate || evidence.totalFrames !== authority.totalFrames) throw new Error("Opening packet/occurrence/frame identity changed");
  const inherited = docs.acceptedPlan.value.graphicsTrack;
  const proposal = parseTreatmentProposal(packet.proposal);
  if (proposal.schemaVersion === 2) throw new Error("Opening execution requires an explicit-presentation proposal (v3 or v4)");
  const binding = assertGuidedFrameBindings({ proposal, evidence, candidate,
    inheritedCount: Array.isArray(inherited) ? inherited.length : 0 }, docs.frameBindings.value);
  if (binding.unboundInheritedGraphicIds.length || binding.graphics.some((row) => row.presentation.anchor !== "own-screen")) throw new Error("Opening declared presentation is unsupported");
  const range = objectValue(packet.range, "opening proposal range");
  if (canonicalJsonSha256(range.approval) !== canonicalJsonSha256(authority.core)
      || canonicalJsonSha256(range.review) !== canonicalJsonSha256(authority.review)) throw new Error("Opening requested range differs from its reviewed whole program");
}

function cutDocumentBindings(docs: ReturnType<typeof readDocuments>, authority: ReturnType<typeof parseGuidedOpeningMediaAuthority>) {
  const request = parseCutApprovalRequest(docs.cutRequest.value), lock = docs.pictureLock.value;
  const admission = objectValue(docs.manifest.value.sourceSetAdmission, "opening source-set metadata");
  const fields = ["cutAuthorityDigest", "cutApprovalReceiptHash", "cutReviewApprovalReceiptHash", "timelineMapHash", "projectionReceiptHash"] as const;
  if (fields.some((key) => lock[key] !== request[key]) || lock.manifestHash !== authority.manifestHash
      || request.pictureLockHash !== authority.pictureLockHash || request.projectionReceiptHash !== authority.projectionHash
      || admission.sourceSetDigest !== authority.sourceSetDigest) throw new Error("Opening cut request/lock/manifest metadata relationships changed");
  return request;
}

const GRAPHICS_STYLES = ["cutaway-only", "overlay-rich", "face-bridge"];

/** A v4 candidate may add ONLY the declared graphics style to the accepted target; canvas, rate, mode, scope and excerpt stay exact. */
function styleFreeTarget(target: unknown): Record<string, unknown> {
  const row = objectValue(target, "candidate target"), { graphicsStyle, graphicsStyleRationale, ...rest } = row;
  if (graphicsStyle === undefined && graphicsStyleRationale === undefined) return rest;
  if (!GRAPHICS_STYLES.includes(String(graphicsStyle)) || typeof graphicsStyleRationale !== "string" || !graphicsStyleRationale.trim()) {
    throw new Error("Candidate target declares an unsupported or unexplained graphics style");
  }
  return rest;
}

/** Validate byte bindings and existing semantic hashes separately; never grants current journal or source authority. */
export function observeGuidedOpeningMediaInput(file: string, expectedSha256: string) {
  const observed = observeCutPreviewFile(file, 128 * 1024, true);
  const input = parseGuidedOpeningMediaInput(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes)));
  const { executionInputHash, ...core } = input;
  if (observed.sha256 !== sha256(expectedSha256, "held input bytes") || canonicalJsonSha256(core) !== executionInputHash) throw new Error("Opening invocation differs from its separately held input bytes");
  const docs = readDocuments(input), authority = parseGuidedOpeningMediaAuthority(docs.authority.value);
  const packet = docs.readinessPacket.value;
  const profile = openingProfileForContext({ accepted: docs.acceptedPlan.value, candidate: docs.candidatePlan.value,
    manifest: docs.manifest.value, proposal: packet.proposal,
    evidence: objectValue(packet.evidence, "opening evidence") as unknown as ProposalEvidence, bindings: docs.frameBindings.value }, input.profile);
  if (input.profile !== authority.profile || input.profile !== profile) {
    throw new Error("Opening input/authority differs from its exact candidate geometry class");
  }
  const request = cutDocumentBindings(docs, authority), plan = docs.acceptedPlan.value, candidate = docs.candidatePlan.value;
  assertOpeningRequestLanes({ accepted: plan, candidate, manifest: docs.manifest.value,
    packet: docs.readinessPacket.value, profile: input.profile });
  const projection = parseCompatibilityProjection(docs.cutProjection.value, String(docs.pictureLock.value.approvedCutPlanHash));
  const direct: Array<[OpeningDocumentName, string]> = [["acceptedPlan", String(request.planHash)], ["pictureLock", authority.pictureLockHash],
    ["cutProjection", authority.projectionHash], ["readinessReceipt", authority.readinessHash], ["treatmentDraft", authority.draftRevisionHash],
    ["candidatePlan", authority.candidatePlanHash], ["manifest", authority.manifestHash], ["frameBindings", authority.frameBindingsHash], ["occurrences", authority.occurrenceEvidenceHash]];
  if (direct.some(([name, hash]) => docs[name].sha256 !== hash) || request.requestHash !== authority.requestHash
      || request.timelineMapHash !== authority.timelineMapHash || projection.timelineMapHash !== authority.timelineMapHash
      || canonicalJsonSha256(projection.timelineMap) !== docs.timelineMap.sha256
      || canonicalJsonSha256(plan.cutTrack) !== canonicalJsonSha256(candidate.cutTrack)
      || canonicalJsonSha256(plan.cutDecisions ?? {}) !== canonicalJsonSha256(candidate.cutDecisions ?? {})
      || canonicalJsonSha256(plan.target) !== canonicalJsonSha256(styleFreeTarget(candidate.target))
      || canonicalJsonSha256(styleFreeTarget(candidate.target)) !== canonicalJsonSha256(authority.target)) throw new Error("Opening input lost its exact accepted cut/target/document relationships");
  const ready = docs.readinessReceipt.value;
  if (ready.packetHash !== docs.readinessPacket.sha256 || ready.reviewBundleHash !== docs.readinessBundle.sha256
      || ready.treatmentDraftRevisionHash !== authority.draftRevisionHash || ready.proposalHash !== authority.proposalHash) throw new Error("Opening input lost its held readiness objects");
  packetBindings(docs, authority);
  const lock = readCutPreviewObject(input.pipeline.lockPath);
  if (lock.sha256 !== input.pipeline.lockSha256 || lock.value.digest !== input.pipeline.digest
      || canonicalJsonSha256(lock.value.files) !== input.pipeline.digest) throw new Error("Opening input pipeline lock changed");
  return { input, authority, documents: docs, inputSha256: observed.sha256,
    observationScope: "bound-input-documents-only" as const, sourceBytesObserved: false as const,
    currentJournalObserved: false as const, pipelineFilesObserved: false as const };
}
