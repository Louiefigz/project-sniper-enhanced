/** Actual TEMP protocol/lease capabilities. Initial readiness/authority and all native/media facts are TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHash, randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { canonicalJson, canonicalJsonSha256 as hash, autoEditRequestKey } from "../auto-edit-hash";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { readSelectedOpeningMedia } from "../guided-opening-selection";
import { guidedBodyAuthorityReads, holdGuidedBodyInputUnderLease } from "../guided-body-authority";
import { bodyOpeningVersionServices } from "../guided-body-opening-version";
import { sourceColorApprovalDependencies } from "../guided-source-color-approval";
import type { GuidedFrameBindingsV1 } from "../guided-proposal-bindings";
import { acquireProjectMutationLease, type ProjectMutationLease } from "../project-mutation-lease";
import { cleanupAttemptWriterFixture } from "./_guided-source-color-cleanup-attempt-fixture";
import { cleanupPendingPreRecordFixture } from "./_guided-source-color-cleanup-pending-read-fixture";
import { cleanupPendingCommitFixture } from "./_guided-source-color-cleanup-pending-commit-fixture";
import { sourceColorReadIntegrationFixture, type FinalReadSetup } from "./_guided-source-color-read-integration-fixture";
import { sourceColorSelectionFixture } from "./_guided-source-color-selection-fixture";
import { sourceColorApprovalFixture } from "./_guided-source-color-approval-fixture";

export type InitialBodySetup = (job: ReturnType<typeof observeHumanCutJob>["job"], root: string) => void;

/** Redirect only the new unpublished journal to the untouched original staged source/cut documents. */
function initialBody(t: TestContext, initialize?: InitialBodySetup) {
  const owned: { lease?: ProjectMutationLease } = {};
  t.after(() => owned.lease?.release());
  const writer = cleanupAttemptWriterFixture(t), dir = writer.staging.producerDir;
  const pending = cleanupPendingPreRecordFixture(t, writer, undefined, job => {
    initialize?.(job, writer.staging.root);
    job.ctx.planPath = path.join(dir, "edit_plan.json"); job.ctx.manifestPath = path.join(dir, "asset_manifest.json");
    job.requestKey = autoEditRequestKey(job.ctx);
    const { requestHash: _old, ...core } = job.cutApprovalRequest!; void _old;
    const original = { ...core, requestKey: job.requestKey };
    job.cutApprovalRequest = { ...original, requestHash: hash(original) };
  });
  const acquired = acquireProjectMutationLease(writer.staging.root, "TEST original source2 body hold");
  assert(acquired.lease); owned.lease = acquired.lease;
  return cleanupPendingCommitFixture(t, pending, acquired.lease);
}
type Initial = ReturnType<typeof initialBody>;

/** New-only inert media and canonical plan copies. No original stage, source, input or tool is rewritten. */
function publish(f: Initial, file: string, bytes: string) {
  const root = fs.realpathSync(f.staging.root); assert(file.startsWith(root + path.sep));
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  fs.writeFileSync(file, bytes, { flag: "wx", mode: 0o600 });
  return { path: file, sha256: createHash("sha256").update(bytes).digest("hex"), sizeBytes: Buffer.byteLength(bytes) };
}

/** All three original cut occurrences and both source identities remain unchanged; no camera/history is inferred. */
function bodyPicture(f: Initial) {
  const opening = f.staging.context.opening, candidate = structuredClone(opening.documents.candidatePlan.value);
  const accepted = readCutPreviewObject(f.before.job.ctx.planPath), manifest = readCutPreviewObject(f.before.job.ctx.manifestPath);
  assert.deepEqual(candidate, accepted.value); assert.deepEqual(manifest.value, opening.documents.manifest.value);
  const dir = f.before.job.ctx.dir, output = f.input.held.claim.outputRoot, candidatePlanHash = hash(candidate);
  const documents = { candidatePlan: publish(f, path.join(dir, ".sniper-authority-v1/objects/plans", `${candidatePlanHash}.json`), canonicalJson(candidate)),
    manifest: { path: f.before.job.ctx.manifestPath, sha256: manifest.sha256 } };
  const totalFrames = 72, target = { width: 1920, height: 1080 }, frameRate = "24/1";
  const bindings: GuidedFrameBindingsV1 = { schemaVersion: 1, kind: "guided-frame-presentation-bindings",
    scope: "controller-frames-and-declared-presentation-not-rendered-proof", frameRate, totalFrames,
    targetHash: hash(candidate.target), candidatePlanHash, occurrenceEvidenceHash: hash(candidate.cutTrack), graphics: [], unboundInheritedGraphicIds: [] };
  const authority = { profile: opening.input.profile, candidatePlanHash, sourceSetDigest: opening.authority.sourceSetDigest,
    clockHash: f.input.held.claim.clockHash, generationStartedAt: f.input.held.claim.generationStartedAt,
    frameRate, totalFrames, target, core: { startFrame: 0, endFrameExclusive: 24 }, review: { startFrame: 0, endFrameExclusive: totalFrames } };
  const rows = [24, totalFrames].map((frames, index) => ({ ...publish(f, path.join(output, `${index ? "review" : "core"}.mp4`),
    `TEST inert body range ${frames}; no media qualification\n`), startFrame: 0, endFrameExclusive: frames,
  startSample: 0, endSampleExclusive: frames * 2000 }));
  const base = publish(f, path.join(output, "full-program-base/final.mp4"), "TEST inert complete base; never decoded\n");
  const master = publish(f, path.join(output, "full-program-base/audio/master/selection-event.json"), canonicalJson({ TEST: "not a native audio selection" }));
  const fullProgram = { fullBasePrepared: true, bodyGraphicsPrepared: false, baseAudibleTrackNotSelected: true, base,
    fullMasterSelectionEventPath: master.path, fullMasterSelectionEventSha256: master.sha256 };
  return { picture: { authority, media: { core: rows[0], review: rows[1] }, documents, fullProgram }, candidate, accepted, manifest, bindings };
}

/** Readiness/source authority is explicitly TEST metadata; actual current job, private selection and approval are not replaced. */
function bodyReads(f: Awaited<ReturnType<typeof sourceColorApprovalFixture>>, metadata: ReturnType<typeof bodyPicture>) {
  const current = observeHumanCutJob(f.input.dir), pointer = current.job.guidedHandoffV2!;
  const proposal = { ...current, pointer, readinessHash: pointer.proposalReadinessHash, readiness: { verdict: "clean" },
    result: { candidate: metadata.candidate }, draftRevision: {}, readinessReceipt: {}, plan: metadata.accepted,
    manifest: metadata.manifest, clock: { hash: f.input.selected.held.claim.clockHash },
    generationStartedAt: f.input.selected.held.claim.generationStartedAt } as unknown as ReturnType<typeof guidedBodyAuthorityReads.readiness>;
  const media = { authority: metadata.picture.authority, bindings: metadata.bindings } as unknown as ReturnType<typeof guidedBodyAuthorityReads.mediaAuthority>;
  const reads = { ...guidedBodyAuthorityReads, canonicalDir: (dir: unknown) => {
    assert.equal(dir, f.input.dir); assert.equal(fs.realpathSync(String(dir)), dir); return String(dir);
  }, readiness: () => proposal, mediaAuthority: () => media };
  const request = { dir: f.input.dir, lease: f.projectLease, remainingMs: f.input.remainingMs, submission: {
    schemaVersion: 1, operation: "continue-approved-opening", idempotencyKey: randomUUID(), expectedToken: current.job.token,
    expectedJournalHash: current.sha256, openingApprovalHash: pointer.openingApprovalHash,
    selectionHash: pointer.openingMediaSelectionHash, proposalReadinessHash: pointer.proposalReadinessHash,
    treatmentDraftRevisionHash: pointer.treatmentDraftRevisionHash } };
  return { current, proposal, reads, request };
}

/** Actual final cleanup → selection → explicit TEST approval → body authority; no body admission or worker runs. */
export async function sourceColorBodyAuthorityFixture(t: TestContext, initialize?: InitialBodySetup, finalize?: FinalReadSetup) {
  const initial = initialBody(t, initialize), metadata = bodyPicture(initial);
  const integrated = await sourceColorReadIntegrationFixture(t, initial, metadata.picture, finalize);
  const selection = await sourceColorSelectionFixture(t, integrated), f = await sourceColorApprovalFixture(t, selection);
  const approval = await f.approve(), context = bodyReads(f, metadata), selected = readSelectedOpeningMedia(f.input.dir);
  t.mock.method(bodyOpeningVersionServices, "sourceVerify", sourceColorApprovalDependencies.verify);
  const hold = () => holdGuidedBodyInputUnderLease(context.request, context.reads);
  const record = integrated.media.record as Record<string, unknown>;
  assert.deepEqual(record.documents, metadata.picture.documents);
  assert.deepEqual(record.fullProgram, metadata.picture.fullProgram);
  return { f, approval, metadata, selected, ...context, hold };
}
