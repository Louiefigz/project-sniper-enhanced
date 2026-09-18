import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { parseContinueApprovedOpening, GUIDED_BODY_INPUT_SCOPE } from "@/lib/producer/contracts/guided-body-v1";
import { objectValue } from "@/lib/producer/contracts/validation";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import { readGuidedProposalReadiness } from "./guided-proposal-review-store";
import { readSelectedOpeningMedia } from "./guided-opening-selection";
import { readHeldOpeningResult } from "./guided-opening-result";
import { openingMediaAuthority, assertFullProgramMediaMetadata } from "./guided-opening-media-input";
import { verifyCleanedOpeningMediaUnderLease } from "./guided-opening-readback";
import { assertOpeningRecord } from "./guided-opening-process-activation";
import { bodyApprovalReads, readBodyOpeningApproval } from "./guided-body-approval";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { captureBodyVerifierRemainder, assertBodyVerifierRemainderCurrent } from "./guided-body-deadline";
import { assertBodyGraphWorkload, projectBodyProgramReferences } from "@/lib/producer/contracts/guided-body-media-v1";
import type { ProjectMutationLease } from "./project-mutation-lease";
import { readBodyOpeningResult, retainBodyOpeningMetadata, verifyBodyOpeningInput,
  retainBodyOpeningVerification, holdBodyOpeningReplay, type BodyOpeningVerification } from "./guided-body-opening-version";
import { assertBodySourceColorReplayMetadata, type HeldBodySourceColorReplayReferences } from "./guided-body-source-color-replay";

/** Internal test seams, never accepted from an HTTP request. Production reads retain their full guards. */
export const guidedBodyAuthorityReads = { canonicalDir: canonicalProducerDir, leaseGuard: cutPreviewLeaseGuard,
  job: observeHumanCutJob, readiness: readGuidedProposalReadiness, selection: readSelectedOpeningMedia,
  result: readHeldOpeningResult, mediaAuthority: openingMediaAuthority, verify: verifyCleanedOpeningMediaUnderLease,
  record: assertOpeningRecord, approval: bodyApprovalReads };
interface BodyInput { dir: unknown; submission: unknown; lease: ProjectMutationLease; remainingMs: () => number }
const sourceBodyInputs = new WeakMap<object, () => void>();

/** Only an actual body input minted here may carry source2 evidence into admission. */
export function assertBodyHeldSourceColorMetadata(input: object): void {
  const check = sourceBodyInputs.get(input);
  if (!check) throw new Error("Body source-color input requires its actual original held authority");
  check();
}

function retainSourceInput<T extends object>(input: T, replay: HeldBodySourceColorReplayReferences | null): T {
  if (replay) {
    const metadata = () => { assertBodySourceColorReplayMetadata(replay); };
    metadata(); sourceBodyInputs.set(input, metadata);
  }
  return input;
}

function equal(actual: unknown, expected: unknown, label: string): void {
  if (canonicalJsonSha256(actual) !== canonicalJsonSha256(expected)) throw new Error(`Body ${label} changed`);
}

function capture(input: BodyInput, reads: typeof guidedBodyAuthorityReads) {
  const submission = parseContinueApprovedOpening(structuredClone(input.submission)), dir = reads.canonicalDir(input.dir);
  const leaseGuard = reads.leaseGuard(dir, input.lease);
  const guard = () => {
    leaseGuard(); const remaining = input.remainingMs();
    if (!Number.isFinite(remaining) || remaining <= 0) throw new Error("Body input verification has no remaining caller budget");
    const current = reads.job(dir);
    if (current.sha256 !== submission.expectedJournalHash || current.job.token !== submission.expectedToken
        || current.job.status !== "treatment_admitted" || current.job.guidedHandoffV2?.openingExecutionClaimHash) throw new Error("Body names a stale or owned journal");
  };
  guard(); const current = reads.job(dir), proposal = reads.readiness(dir), selected = reads.selection(dir, guard);
  if (proposal.sha256 !== current.sha256 || selected.observed.sha256 !== current.sha256 || !proposal.draftRevision
      || proposal.readiness.verdict !== "clean" || proposal.readinessHash !== submission.proposalReadinessHash
      || proposal.pointer.treatmentDraftRevisionHash !== submission.treatmentDraftRevisionHash
      || selected.selectionHash !== submission.selectionHash || current.job.guidedHandoffV2?.openingApprovalHash !== submission.openingApprovalHash) {
    throw new Error("Body request does not bind the current approved opening and reviewed draft");
  }
  // The existing readiness reader requires the exact untouched PICTURE_LOCKED genesis, not arbitrary ancestry.
  const result = readBodyOpeningResult({ selected, guard }, reads.result), sourceColor = selected.fact.schemaVersion === 2;
  const media = reads.mediaAuthority(proposal, objectValue(result.record.value.authority, "held opening authority").profile);
  equal(result.record.value.authority, media.authority, "opening candidate/source/clock authority");
  const approval = readBodyOpeningApproval({ dir, current, selected, result, guard }, reads.approval);
  const metadata = retainBodyOpeningMetadata({ selected, result, approval }); guard(); metadata();
  const replay = holdBodyOpeningReplay({ selected, result, guard });
  return { dir, submission, guard, current, proposal, selected, result, media, approval, metadata, sourceColor, replay };
}

function unchanged(held: ReturnType<typeof capture>, reads: typeof guidedBodyAuthorityReads): void {
  if (held.replay) assertBodySourceColorReplayMetadata(held.replay);
  held.metadata(); held.guard();
  const current = reads.job(held.dir), proposal = reads.readiness(held.dir);
  equal(reads.mediaAuthority(proposal, held.media.authority.profile), held.media, "current exact media authority");
  equal([proposal.readinessHash, proposal.pointer.treatmentDraftRevisionHash, proposal.readinessReceipt],
    [held.proposal.readinessHash, held.proposal.pointer.treatmentDraftRevisionHash, held.proposal.readinessReceipt], "readiness");
  // Actual source2 private handles already retain every original record/inode and parsed value.
  // Recheck those handles; rebuilding cold history would repeat IO and lose original-inode continuity.
  if (held.sourceColor) { held.guard(); held.metadata(); return; }
  const selected = reads.selection(held.dir, held.guard), result = readBodyOpeningResult({ selected, guard: held.guard }, reads.result);
  const approval = readBodyOpeningApproval({ dir: held.dir, current, selected, result, guard: held.guard }, reads.approval);
  const metadata = retainBodyOpeningMetadata({ selected, result, approval });
  equal([selected.selectionHash, selected.fact, result.record.sha256, result.completion],
    [held.selected.selectionHash, held.selected.fact, held.result.record.sha256, held.result.completion], "selection/result");
  equal([approval.summary.approvalHash, approval.before.sha256, approval.files.start.sha256, approval.files.output.sha256,
    approval.files.receipt.sha256, approval.files.published.sha256], [held.approval.summary.approvalHash, held.approval.before.sha256,
    held.approval.files.start.sha256, held.approval.files.output.sha256, held.approval.files.receipt.sha256,
    held.approval.files.published.sha256], "approval evidence"); held.guard(); metadata(); held.metadata();
}

function fullProgram(held: ReturnType<typeof capture>) {
  const record = held.result.record.value, root = held.selected.held.claim.outputRoot;
  const full = objectValue(record.fullProgram, "held opening full program");
  const { base, masterSelection, candidatePlan, manifest } = projectBodyProgramReferences(record);
  const baseRoot = path.join(root, "full-program-base"), relative = path.relative(baseRoot, masterSelection.path);
  if (full.fullBasePrepared !== true || full.bodyGraphicsPrepared !== false || full.baseAudibleTrackNotSelected !== true
      || base.path !== path.join(baseRoot, "final.mp4") || relative.startsWith("..") || path.isAbsolute(relative)
      || path.basename(masterSelection.path) !== "selection-event.json"
      || candidatePlan.path !== path.join(held.dir, ".sniper-authority-v1/objects/plans", `${held.media.authority.candidatePlanHash}.json`)
      || candidatePlan.sha256 !== held.media.authority.candidatePlanHash || manifest.path !== held.proposal.job.ctx.manifestPath
      || manifest.sha256 !== held.proposal.manifest.sha256) throw new Error("Body reuse references differ from exact original full-program inputs");
  return { base, masterSelection, candidatePlan, manifest };
}

function verifiedMatches(held: ReturnType<typeof capture>, verified: BodyOpeningVerification) {
  if (verified.observed.sha256 !== held.current.sha256 || verified.observed.cleanupHash !== held.selected.fact.cleanupHash
      || verified.observed.held.claimHash !== held.selected.held.claimHash || verified.selected.record.sha256 !== held.result.record.sha256) {
    throw new Error("Body verification returned a different journal/cleanup/result");
  }
  equal(verified.selected.completion, held.result.completion, "fresh held completion");
  equal(verified.receipt.value.result, verified.result, "fresh readback result");
  equal(verified.receipt.value.clockHash, held.proposal.clock.hash, "fresh original clock");
}

function immutable<T>(value: T): T {
  if (value && typeof value === "object") {
    Object.values(value).forEach(immutable); Object.freeze(value);
  }
  return value;
}

/** Retain the original caller before its first budget callback; aliases cannot replace the lease or buy time. */
function bodyCaller(input: BodyInput) {
  const original = { ...input, release: input.lease.release };
  const submission = parseContinueApprovedOpening(structuredClone(input.submission));
  const check = () => {
    if (input.dir !== original.dir || input.submission !== original.submission || input.lease !== original.lease
        || input.remainingMs !== original.remainingMs || original.lease.release !== original.release
        || !isDeepStrictEqual(input.submission, submission)) {
      throw new Error("Body input original caller identity changed");
    }
  };
  const remainingMs = captureBodyVerifierRemainder(() => {
    check(); const remaining = original.remainingMs(); check(); return remaining;
  });
  check(); return { ...original, remainingMs, assertCaller: check };
}

/** Requalify held inputs under a caller-owned lease/remainder. No body launch, head advance, plan save or approval.
 * The returned guard rechecks metadata/receipts; actual media freshness belongs only to the just-returned verifier.
 * Future body execution must separately admit ALL body presentations, its resources/deadline and final QC. */
export async function holdGuidedBodyInputUnderLease(input: BodyInput, reads = guidedBodyAuthorityReads) {
  const caller = bodyCaller(input), { remainingMs } = caller, held = capture(caller, reads);
  assertBodyGraphWorkload(held.media.authority.target, held.media.bindings?.graphics.length ?? Number.NaN);
  assertFullProgramMediaMetadata({ plan: held.proposal.result.candidate!, bindings: held.media.bindings,
    proposal: held.proposal.result.proposal, evidence: held.proposal.evidence,
    accepted: held.proposal.plan?.value, manifest: held.proposal.manifest?.value });
  held.guard(); remainingMs();
  const verified = await verifyBodyOpeningInput({ selected: held.selected, request: { dir: held.dir, lease: caller.lease,
    expectedCleanupHash: String(held.selected.fact.cleanupHash), remainingMs } }, reads.verify);
  const verificationMetadata = retainBodyOpeningVerification(held.sourceColor, verified);
  remainingMs(); held.metadata(); verificationMetadata();
  verifiedMatches(held, verified); reads.record(verified.receipt); reads.record(verified.output); unchanged(held, reads);
  const start = reads.approval.file(path.join(path.dirname(verified.receipt.path), "start.json"));
  equal(start.sha256, verified.receipt.value.startSha256, "fresh verifier start");
  equal(start.value.tools, held.approval.files.start.value.tools, "approval/current pinned verifier tools");
  const references = fullProgram(held);
  held.guard(); remainingMs(); held.metadata(); verificationMetadata();
  const source = held.replay ? { schemaVersion: 2 as const, sourceColorReplay: held.replay.references } : { schemaVersion: 1 as const };
  const result = retainSourceInput(immutable({ ...source, scope: GUIDED_BODY_INPUT_SCOPE, submission: structuredClone(held.submission),
    journalHash: held.current.sha256, approvalHash: held.approval.summary.approvalHash,
    selectionHash: held.selected.selectionHash, readinessHash: held.proposal.readinessHash,
    draftRevisionHash: held.submission.treatmentDraftRevisionHash, authority: structuredClone(held.media.authority), bindings: structuredClone(held.media.bindings),
    origin: { clockHash: held.proposal.clock.hash, startedAt: held.proposal.generationStartedAt }, references,
    verification: { receiptPath: verified.receipt.path, receiptSha256: verified.receipt.sha256, outputSha256: verified.output.sha256 },
    executable: false as const, bodyReadiness: "not-qualified" as const, bodyGenerated: false as const, deliveryApproved: false as const,
    assertUnchanged: () => {
      reads.record(verified.receipt); reads.record(verified.output); unchanged(held, reads); verificationMetadata();
      caller.assertCaller(); assertBodyVerifierRemainderCurrent(remainingMs);
    } }), held.replay);
  caller.assertCaller(); assertBodyVerifierRemainderCurrent(remainingMs); return result;
}
