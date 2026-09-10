import { invalidateRenderGraphV1 } from
  "@/lib/producer/contracts/render-graph";
import { planObjectContentHash } from "./auto-edit-authority";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { commitProducerRevisionSync } from "./producer-revision-store";
import type { ProducerRevisionShadowInput } from
  "./producer-revision-shadow";
import type { CompatibilityShadowBindings } from
  "./producer-revision-shadow-bindings";
import type { CompatibilityShadowLock } from
  "./producer-revision-shadow-lock";

interface ShadowCommitAuthority {
  parent: Record<string, unknown>;
  parentRevisionHash: string;
  bindings: CompatibilityShadowBindings;
  lock: CompatibilityShadowLock;
  invalidated: ReturnType<typeof invalidateRenderGraphV1>;
}

function deterministicUuid(digest: string, offset: number): string {
  const rotated = digest.slice(offset) + digest.slice(0, offset);
  const hex = rotated.slice(0, 32);
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    `5${hex.slice(13, 16)}`,
    `a${hex.slice(17, 20)}`,
    hex.slice(20),
  ].join("-");
}

function plans(input: ProducerRevisionShadowInput, authority: ShadowCommitAuthority) {
  const child = JSON.parse(
    input.childPlanBytes.toString("utf8")) as Record<string, unknown>;
  const parentHash = planObjectContentHash(authority.parent);
  const childHash = planObjectContentHash(child);
  if (!parentHash || !childHash) throw new Error("typed shadow plan is malformed");
  return { child, parentHash, childHash };
}

function request(
  input: ProducerRevisionShadowInput,
  parentRevisionHash: string,
  seed: string,
) {
  const clauseId = deterministicUuid(seed, 0);
  return {
    schemaVersion: 1 as const,
    requestId: input.requestId!,
    idempotencyKey: deterministicUuid(seed, 8),
    parentRevisionHash,
    workflow: "cut-first" as const,
    rawIntent: input.rawIntent,
    submittedAt: input.submittedAt!,
    clauses: [{
      schemaVersion: 1 as const,
      clauseId,
      text: input.rawIntent,
      state: "candidate-executed" as const,
      disposition: "compiled to SetGraphicTextV1",
      blockingClauseIds: [],
    }],
  };
}

function batch(
  input: ProducerRevisionShadowInput,
  authority: ShadowCommitAuthority,
  parentPlanHash: string,
  seed: string,
) {
  const requestId = input.requestId!;
  const idempotencyKey = deterministicUuid(seed, 8);
  return {
    schemaVersion: 1 as const,
    batchId: deterministicUuid(seed, 16),
    requestId,
    idempotencyKey,
    stage: "treatment" as const,
    atomic: true as const,
    preserveUnrelated: true as const,
    base: {
      projectRevisionHash: authority.parentRevisionHash,
      planContentHash: parentPlanHash,
      manifestHash: authority.bindings.manifestHash,
      sourceSnapshotSetHash: authority.bindings.sourceSetHash,
      timelineMapHash: authority.lock.timelineMapHash,
      canvasProfileHash: authority.bindings.canvasProfileHash,
      destinationProfileHashes: authority.bindings.destinationProfileHashes,
      pictureLockHash: authority.lock.hash,
    },
    operations: [{
      schemaVersion: 1 as const,
      operationId: deterministicUuid(seed, 24),
      clauseId: deterministicUuid(seed, 0),
      action: input.typedEdit.operation,
    }],
  };
}

/** Materialize the exact semantic shadow transition under the parent CAS. */
export function commitCompatibilityShadowRevisionSync(
  input: ProducerRevisionShadowInput,
  authority: ShadowCommitAuthority,
) {
  const plan = plans(input, authority);
  const seed = canonicalJsonSha256({
    requestId: input.requestId,
    parentRevisionHash: authority.parentRevisionHash,
    operationHash: input.typedEdit.operationHash,
  });
  return commitProducerRevisionSync({
    producerDir: input.producerDir,
    planObject: plan.child,
    request: request(input, authority.parentRevisionHash, seed),
    batch: batch(input, authority, plan.parentHash, seed),
    revision: {
      planContentHash: plan.childHash,
      manifestHash: authority.bindings.manifestHash,
      sourceSnapshotSetHash: authority.bindings.sourceSetHash,
      transcriptTimingHash: authority.lock.transcriptDigest,
      timelineMapHash: authority.lock.timelineMapHash,
      canvasProfileHash: authority.bindings.canvasProfileHash,
      destinationProfileHashes: authority.bindings.destinationProfileHashes,
      pictureLockHash: authority.lock.hash,
      workflowState: "TREATMENT_DRAFT",
      authoritativeSidecars: {
        compatibilityLock: authority.lock.hash,
        canonicalPlan: plan.childHash,
        renderedPlanFile: input.childPlanHash,
      },
    },
    renderGraph: authority.invalidated.graph,
    projectionReceipt: null,
    invalidationReceipt: authority.invalidated.receipt,
    invariantProofHash: canonicalJsonSha256({
      parentPlanHash: input.parentPlanHash,
      childPlanHash: input.childPlanHash,
      operationHash: input.typedEdit.operationHash,
    }),
  });
}
