import { canonicalJsonSha256 } from "./auto-edit-hash";
import {
  invalidateRenderGraphV1,
  parseRenderGraphV1,
} from "@/lib/producer/contracts/render-graph";
import type { TypedCompatibilityEdit } from
  "@/app/api/producer/ai-edit/typed-compatibility-edit";
import {
  initializeProducerAuthoritySync,
  resolveProducerAuthorityHeadSync,
} from "./producer-revision-head";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
  writeAuthorityObjectSync,
} from "./producer-authority-files";
import { parseProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import {
  findCompatibilityShadowLock,
  type CompatibilityShadowLock,
} from "./producer-revision-shadow-lock";
import { planObjectContentHash } from "./auto-edit-authority";
import { compatibilityShadowBindings } from
  "./producer-revision-shadow-bindings";
import { commitCompatibilityShadowRevisionSync } from
  "./producer-revision-shadow-commit";

export interface ProducerRevisionShadowInput {
  producerDir: string;
  manifestPath: string;
  parentPlanText: string;
  parentPlanHash: string;
  childPlanBytes: Buffer;
  childPlanHash: string;
  rawIntent: string;
  requestId?: string;
  submittedAt?: string;
  typedEdit: TypedCompatibilityEdit;
}

export type ProducerRevisionShadowResult =
  | { status: "skipped-unqualified"; reason: string }
  | { status: "blocked"; reason: string }
  | {
      status: "committed" | "replayed";
      childRevisionHash: string;
      receiptHash: string;
    };

function initialGraph(input: ProducerRevisionShadowInput) {
  const operation = input.typedEdit.operation;
  const key = `graphic.${operation.target.id}.text`;
  const beforeText = operation.expectedCurrentText ?? "";
  const graph = parseRenderGraphV1({
    schemaVersion: 1,
    graphId: `graph-${input.parentPlanHash.slice(0, 16)}`,
    toolchainHash: canonicalJsonSha256({
      adapter: "typed-compatibility-render-graph",
      version: 1,
    }),
    rootNodeId: "node-final",
    nodes: [
      {
        nodeId: "node-plan-parent",
        kind: "source-snapshot",
        dependencies: [],
        inputDigests: { "plan.parent": input.parentPlanHash },
        outputArtifactHash: input.parentPlanHash,
        frameRange: null,
      },
      {
        nodeId: "node-graphic-text",
        kind: "scene-unit",
        dependencies: ["node-plan-parent"],
        inputDigests: { [key]: canonicalJsonSha256(beforeText) },
        outputArtifactHash: canonicalJsonSha256({
          plan: input.parentPlanHash, key, beforeText,
        }),
        frameRange: null,
      },
      {
        nodeId: "node-final",
        kind: "preview",
        dependencies: ["node-graphic-text"],
        inputDigests: {},
        outputArtifactHash: canonicalJsonSha256({
          plan: input.parentPlanHash, operation: null,
        }),
        frameRange: null,
      },
    ],
  });
  return {
    graph,
    changed: { [key]: canonicalJsonSha256(operation.text) },
  };
}

function existingParentRevision(
  input: ProducerRevisionShadowInput,
  parentContentHash: string,
  lock: CompatibilityShadowLock,
  paths: ReturnType<typeof producerAuthorityPaths>,
): string | null {
  try {
    const head = resolveProducerAuthorityHeadSync(input.producerDir);
    const revision = parseProjectRevision(
      assertObjectHashSync(paths.objects.revisions, head),
    );
    if (revision.pictureLockHash !== lock.hash) {
      throw new Error("typed shadow authority head does not match the live parent");
    }
    if (revision.planContentHash === parentContentHash) return head;
    const child = JSON.parse(
      input.childPlanBytes.toString("utf8")) as Record<string, unknown>;
    if (revision.planContentHash === planObjectContentHash(child)
        && revision.parentRevisionHash) return revision.parentRevisionHash;
    throw new Error("typed shadow authority head does not match the live parent");
  } catch (error) {
    if (!String(error).includes("uninitialized")) throw error;
    return null;
  }
}

function ensureGenesis(
  input: ProducerRevisionShadowInput,
  parent: Record<string, unknown>,
  lock: CompatibilityShadowLock,
  graph: ReturnType<typeof parseRenderGraphV1>,
): string {
  const paths = producerAuthorityPaths(input.producerDir);
  const parentContentHash = planObjectContentHash(parent);
  if (!parentContentHash) throw new Error("shadow parent plan is malformed");
  const existing = existingParentRevision(
    input, parentContentHash, lock, paths);
  if (existing) return existing;
  const bindings = compatibilityShadowBindings(parent, lock);
  const graphObject = writeAuthorityObjectSync(paths.objects.graphs, graph);
  const emptyLedger = writeAuthorityObjectSync(paths.objects.requests, {
    schemaVersion: 1, kind: "empty-request-ledger",
  });
  return initializeProducerAuthoritySync(input.producerDir, {
    schemaVersion: 1,
    parentRevisionHash: null,
    planContentHash: parentContentHash,
    manifestHash: bindings.manifestHash,
    sourceSnapshotSetHash: bindings.sourceSetHash,
    transcriptTimingHash: lock.transcriptDigest,
    timelineMapHash: lock.timelineMapHash,
    canvasProfileHash: bindings.canvasProfileHash,
    destinationProfileHashes: bindings.destinationProfileHashes,
    pictureLockHash: lock.hash,
    workflowState: "PICTURE_LOCKED",
    requestLedgerHash: emptyLedger.hash,
    renderGraphHash: graphObject.hash,
    projectionReceiptHash: null,
    authoritativeSidecars: {
      compatibilityLock: lock.hash,
      renderedPlanFile: input.parentPlanHash,
    },
  }, parent).revisionHash;
}

/** Commit the released one-operation path only when exact cut authority exists. */
export function commitTypedCompatibilityShadowSync(
  input: ProducerRevisionShadowInput,
): ProducerRevisionShadowResult {
  if (!input.requestId || !input.submittedAt) {
    return {
      status: "skipped-unqualified",
      reason: "request identity/timestamp was not captured at admission",
    };
  }
  const parent = JSON.parse(input.parentPlanText) as Record<string, unknown>;
  const lock = findCompatibilityShadowLock(
    input.producerDir,
    input.manifestPath,
    parent,
  );
  if (!lock) {
    return {
      status: "skipped-unqualified",
      reason: "no exact dual-review compatibility picture lock matches",
    };
  }
  const initial = initialGraph(input);
  const invalidated = invalidateRenderGraphV1(initial.graph, initial.changed);
  const parentRevisionHash = ensureGenesis(input, parent, lock, initial.graph);
  const outcome = commitCompatibilityShadowRevisionSync(input, {
    parent,
    parentRevisionHash,
    bindings: compatibilityShadowBindings(parent, lock),
    lock,
    invalidated,
  });
  if (!outcome.receiptHash
      || !["committed", "replayed"].includes(outcome.status)) {
    throw new Error(`typed shadow commit did not advance: ${outcome.status}`);
  }
  return {
    status: outcome.status as "committed" | "replayed",
    childRevisionHash: outcome.childRevisionHash,
    receiptHash: outcome.receiptHash,
  };
}

/** Keep shadow-authority faults observable without rolling back live authority. */
export function runTypedCompatibilityShadowSync(
  input: ProducerRevisionShadowInput,
): ProducerRevisionShadowResult {
  try {
    return commitTypedCompatibilityShadowSync(input);
  } catch (error) {
    return {
      status: "blocked",
      reason: error instanceof Error ? error.message : String(error),
    };
  }
}
