import path from "node:path";
import { existsSync } from "node:fs";
import { objectValue, sha256 } from "@/lib/producer/contracts/validation";
import { parseRenderGraphV1 } from "@/lib/producer/contracts/render-graph";
import { parseProjectRevision, type ProjectRevisionV2 } from "@/lib/producer/contracts/project-revision";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { planObjectContentHash } from "./auto-edit-authority";
import { autoEditProjectionReceipt } from "./producer-auto-edit-projection-authority";
import { producerAuthorityPaths, writeAuthorityObjectSync } from "./producer-authority-files";
import { initializeProducerAuthoritySync, resolveProducerAuthorityHeadSync } from "./producer-revision-head";
import type { GuidedCutObservation } from "./guided-cut-v2-store";

function sourceSetSnapshot(cut: GuidedCutObservation) {
  const admission = objectValue(cut.manifest.value.sourceSetAdmission, "sourceSetAdmission");
  const relative = admission.receiptPath;
  if (typeof relative !== "string" || path.isAbsolute(relative)) throw new Error("Admitted source-set receipt path is invalid");
  const base = path.dirname(cut.job.ctx.manifestPath), file = path.resolve(base, relative);
  const within = path.relative(base, file);
  if (!within || within.startsWith("..") || path.isAbsolute(within)) throw new Error("Admitted source-set receipt escaped source root");
  const observed = readCutPreviewObject(file);
  if (observed.sha256 !== cut.receipt.sourceSetReceiptHash) throw new Error("Actual source-set receipt changed");
  return observed;
}

function profiles(cut: GuidedCutObservation) {
  const target = objectValue(cut.plan.value.target, "declared cut target");
  if (!["width", "height"].every((key) => Number.isSafeInteger(target[key]) && Number(target[key]) > 0)
      || !["short", "longform"].includes(String(target.mode))) throw new Error("Cut target has no explicit destination/canvas authority");
  return target; // Declared target only, not a claim that the private preview rendered this destination.
}

function cutGraph(cut: GuidedCutObservation, objects: { decision: string; lock: string; projection: string; source: string }) {
  return parseRenderGraphV1({ schemaVersion: 1, graphId: `guided-cut-${objects.decision.slice(0, 16)}`,
    toolchainHash: cut.receipt.toolchainHash, rootNodeId: "node-treatment-pending", nodes: [
      { nodeId: "node-source", kind: "source-snapshot", dependencies: [], frameRange: null,
        inputDigests: { manifest: cut.manifest.sha256, sourceSet: cut.receipt.sourceSetDigest }, outputArtifactHash: objects.source },
      { nodeId: "node-timeline", kind: "timeline-map", dependencies: ["node-source"], frameRange: null,
        inputDigests: { pictureLock: objects.lock, timeline: cut.request.timelineMapHash }, outputArtifactHash: objects.projection },
      { nodeId: "node-treatment-pending", kind: "preview", dependencies: ["node-timeline"], frameRange: null,
        inputDigests: { cutDecision: objects.decision }, outputArtifactHash: null },
    ] });
}

/** Materialize actual cut/source/plan objects; unrendered graph outputs remain null. */
export function prepareGuidedPictureLock(cut: GuidedCutObservation, cutDecisionHash: string) {
  const paths = producerAuthorityPaths(cut.job.ctx.dir);
  const sourceSet = sourceSetSnapshot(cut), target = profiles(cut);
  const put = (value: unknown) => writeAuthorityObjectSync(paths.objects.receipts, value).hash;
  const sourceSnapshot = put(sourceSet.value), manifestSnapshot = put(cut.manifest.value);
  const targetHash = put(target), lockHash = put(cut.lock.value);
  if (lockHash !== cut.request.pictureLockHash) throw new Error("Cut lock is not canonical immutable authority");
  const projection = writeAuthorityObjectSync(paths.objects.projections, cut.projection);
  const contentHash = planObjectContentHash(cut.plan.value);
  if (!contentHash) throw new Error("Cut plan content is malformed");
  const receipt = writeAuthorityObjectSync(paths.objects.projections, autoEditProjectionReceipt({
    planContentHash: contentHash, manifestHash: cut.manifest.sha256,
    sourceSnapshotSetHash: cut.receipt.sourceSetDigest, projection: cut.projection }));
  const graph = cutGraph(cut, { decision: cutDecisionHash, lock: lockHash, projection: projection.hash, source: sourceSnapshot });
  const graphHash = writeAuthorityObjectSync(paths.objects.graphs, graph).hash;
  const ledger = writeAuthorityObjectSync(paths.objects.requests,
    { schemaVersion: 2, kind: "guided-accepted-cut-ledger", cutDecisionHash, treatmentExecuted: false }).hash;
  const value = { schemaVersion: 1, parentRevisionHash: null, planContentHash: contentHash,
    manifestHash: cut.manifest.sha256, sourceSnapshotSetHash: cut.receipt.sourceSetDigest,
    transcriptTimingHash: String(cut.lock.value.transcriptDigest), timelineMapHash: cut.request.timelineMapHash,
    canvasProfileHash: targetHash, destinationProfileHashes: [targetHash], pictureLockHash: lockHash,
    workflowState: "PICTURE_LOCKED", requestLedgerHash: ledger, renderGraphHash: graphHash,
    projectionReceiptHash: receipt.hash, authoritativeSidecars: { guidedCutDecisionV2: cutDecisionHash,
      manifestSnapshot, sourceSetSnapshot: sourceSnapshot, sourceSetReceiptFile: sourceSet.sha256,
      compatibilityLock: lockHash, compatibilityTimelineProjectionV1: projection.hash,
      originalCutPlanFile: cut.plan.sha256, declaredTargetProfile: targetHash } };
  return { paths, value, plan: cut.plan.value, cutDecisionHash };
}

/** Exact one-winner genesis; never replaces an unrelated working/approved head. */
export function commitGuidedPictureLock(prepared: ReturnType<typeof prepareGuidedPictureLock>): string {
  const { paths } = prepared, dir = path.dirname(paths.root);
  if (existsSync(path.join(paths.advances, "GENESIS.json"))) {
    const head = resolveProducerAuthorityHeadSync(dir);
    const stored = readCutPreviewObject(path.join(paths.objects.revisions, `${head}.json`));
    const revision = parseProjectRevision(stored.value);
    if (stored.sha256 !== head || revision.workflowState !== "PICTURE_LOCKED" || revision.parentRevisionHash !== null
        || revision.authoritativeSidecars.guidedCutDecisionV2 !== prepared.cutDecisionHash
        || revision.planContentHash !== prepared.value.planContentHash || revision.renderGraphHash !== prepared.value.renderGraphHash
        || revision.requestLedgerHash !== prepared.value.requestLedgerHash || existsSync(paths.approvedHead)) {
      throw new Error("Guided cut conflicts with existing revision authority; no replacement or migration is authorized");
    }
  }
  return initializeProducerAuthoritySync(dir, prepared.value, prepared.plan).revisionHash;
}

/** Read-only current-parent check, including actual V2 plan and referenced cut. */
export function readGuidedPictureLock(dir: string, hash: string, cutDecisionHash: string, cut: GuidedCutObservation) {
  const root = path.join(dir, ".sniper-authority-v1");
  const observed = readCutPreviewObject(path.join(root, "objects", "revisions", `${hash}.json`));
  const revision = parseProjectRevision(observed.value);
  if (observed.sha256 !== hash || canonicalJsonSha256(revision) !== hash || revision.schemaVersion !== 2
      || revision.workflowState !== "PICTURE_LOCKED" || revision.parentRevisionHash !== null
      || revision.authoritativeSidecars.guidedCutDecisionV2 !== cutDecisionHash || existsSync(path.join(root, "APPROVED_HEAD"))) {
    throw new Error("Guided treatment parent is not the exact unapproved picture-locked revision");
  }
  const plan = readCutPreviewObject(path.join(root, "objects", "plans", `${revision.planObjectHash}.json`));
  if (plan.sha256 !== revision.planObjectHash || planObjectContentHash(plan.value) !== revision.planContentHash) {
    throw new Error("Guided picture-lock plan object changed");
  }
  const genesis = readCutPreviewObject(path.join(root, "advances", "GENESIS.json")).value;
  if (genesis.revisionHash !== hash || existsSync(path.join(root, "advances", `${hash}.json`))) {
    throw new Error("Guided picture-lock parent is no longer the current revision");
  }
  assertPictureLockClosure(root, revision, cut);
  return revision;
}

/** Required closure is content-addressed and compared with the current exact cut, not mere filenames. */
function assertPictureLockClosure(root: string, revision: ProjectRevisionV2, cut: GuidedCutObservation): void {
  const sidecars = revision.authoritativeSidecars, source = sourceSetSnapshot(cut), target = profiles(cut);
  const verify = (kind: string, hash: unknown, expected: unknown) => {
    const id = sha256(hash, `${kind} object`), object = readCutPreviewObject(path.join(root, "objects", kind, `${id}.json`));
    if (object.sha256 !== id || canonicalJsonSha256(object.value) !== id || canonicalJsonSha256(expected) !== id) {
      throw new Error(`Guided picture-lock ${kind} object closure changed`);
    }
  };
  verify("receipts", sidecars.manifestSnapshot, cut.manifest.value);
  verify("receipts", sidecars.sourceSetSnapshot, source.value);
  verify("receipts", sidecars.compatibilityLock, cut.lock.value);
  verify("receipts", sidecars.declaredTargetProfile, target);
  verify("projections", sidecars.compatibilityTimelineProjectionV1, cut.projection);
  verify("projections", revision.projectionReceiptHash, autoEditProjectionReceipt({ planContentHash: revision.planContentHash,
    manifestHash: cut.manifest.sha256, sourceSnapshotSetHash: cut.receipt.sourceSetDigest, projection: cut.projection }));
  verify("requests", revision.requestLedgerHash, { schemaVersion: 2, kind: "guided-accepted-cut-ledger",
    cutDecisionHash: sidecars.guidedCutDecisionV2, treatmentExecuted: false });
  verify("graphs", revision.renderGraphHash, cutGraph(cut, { decision: sidecars.guidedCutDecisionV2,
    lock: sidecars.compatibilityLock, projection: sidecars.compatibilityTimelineProjectionV1, source: sidecars.sourceSetSnapshot }));
  if (sidecars.sourceSetReceiptFile !== source.sha256 || sidecars.originalCutPlanFile !== cut.plan.sha256
      || revision.canvasProfileHash !== sidecars.declaredTargetProfile || revision.pictureLockHash !== sidecars.compatibilityLock
      || canonicalJsonSha256(revision.destinationProfileHashes) !== canonicalJsonSha256([sidecars.declaredTargetProfile])
      || revision.transcriptTimingHash !== cut.lock.value.transcriptDigest) throw new Error("Guided picture-lock closure relationships changed");
}
