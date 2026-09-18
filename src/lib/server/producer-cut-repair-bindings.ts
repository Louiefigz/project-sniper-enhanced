import type { FrameRangeV1 } from "@/lib/producer/contracts/cut-restore-speech-v1";
import type { EditBatchV1 } from "@/lib/producer/contracts/edit-batch";
import type { ProjectRevision } from "@/lib/producer/contracts/project-revision";
import type {
  InvalidationReceiptV1,
  RenderGraphV1,
  RenderNodeKindV1,
} from "@/lib/producer/contracts/render-graph";
import { canonicalJsonSha256 } from "./auto-edit-hash";

function containsRange(outer: FrameRangeV1, inner: FrameRangeV1): boolean {
  return outer.startFrame <= inner.startFrame
    && outer.endFrameExclusive >= inner.endFrameExclusive;
}

/** Require graph invalidation to cover every repair-authorized dirty window. */
export function assertCutInvalidation(
  batch: EditBatchV1,
  invalidation: InvalidationReceiptV1,
  graph: RenderGraphV1,
): void {
  if (batch.stage !== "cut") return;
  const authorized = batch.operations.flatMap((row) => {
    const action = row.action;
    return action.operation === "cut.restoreSpeech"
      ? [...action.pictureDirtyWindows, ...action.audioDirtyWindows] : [];
  });
  const uncovered = authorized.filter(
    (window) => !invalidation.dirtyWindows.some(
      (dirty) => containsRange(dirty, window),
    ),
  );
  if (uncovered.length) {
    throw new Error("cut repair dirty windows are absent from graph invalidation");
  }
  for (const operation of batch.operations) {
    const action = operation.action;
    if (action.operation !== "cut.restoreSpeech") continue;
    const key = `cut.restoreSpeech.${operation.operationId}`;
    const digest = canonicalJsonSha256(action);
    const requiredKinds: RenderNodeKindV1[] = action.method === "audio-lj-overlap"
      ? ["dialogue-stem"] : ["base-segment", "dialogue-stem"];
    const bound = graph.nodes.filter(
      (node) => node.inputDigests[key] === digest
        && invalidation.dirtyNodeIds.includes(node.nodeId),
    );
    if (!invalidation.changedInputKeys.includes(key)
        || requiredKinds.some((kind) => !bound.some((node) => node.kind === kind))) {
      throw new Error("cut repair is not bound to its segmented dirty render nodes");
    }
  }
}

function assertTreatmentRevision(
  revision: ProjectRevision,
  batch: EditBatchV1,
): void {
  if (revision.timelineMapHash !== batch.base.timelineMapHash
      || revision.pictureLockHash !== batch.base.pictureLockHash) {
    throw new Error("treatment revision changed cut or picture-lock authority");
  }
}

function assertCutRevision(
  revision: ProjectRevision,
  batch: EditBatchV1,
  invariantProofHash: string,
): void {
  const hashes = new Set(batch.operations.map((row) => (
    row.action.operation === "cut.restoreSpeech"
      ? row.action.target.transcriptTimingHash : ""
  )));
  const sidecars = revision.authoritativeSidecars;
  if (revision.workflowState !== "PICTURE_LOCKED"
      || revision.timelineMapHash === batch.base.timelineMapHash
      || revision.pictureLockHash === batch.base.pictureLockHash
      || revision.pictureLockHash === null
      || hashes.size !== 1
      || !hashes.has(revision.transcriptTimingHash)
      || sidecars.pictureLock !== revision.pictureLockHash
      || !sidecars.pictureLockSupersession
      || !sidecars.cutRepairFragmentReceipt
      || !sidecars.palmierCutRepairDisposition
      || sidecars.cutRepairInvariantProof !== invariantProofHash) {
    throw new Error("cut repair revision lacks child-lock supersession authority");
  }
}

/** Enforce the stage-specific revision boundary before materialization. */
export function assertStageRevisionBindings(
  revision: ProjectRevision,
  batch: EditBatchV1,
  invariantProofHash: string,
): void {
  if (batch.stage === "treatment") assertTreatmentRevision(revision, batch);
  else assertCutRevision(revision, batch, invariantProofHash);
}
