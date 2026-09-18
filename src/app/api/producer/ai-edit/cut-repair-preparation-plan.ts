import {
  invalidateRenderGraphV1,
  parseRenderGraphV1,
  type RenderGraphV1,
} from "@/lib/producer/contracts/render-graph";
import {
  parseCutRestoreSpeechV1,
  type CutRestoreSpeechV1,
} from "@/lib/producer/contracts/cut-restore-speech-v1";
import {
  parseCutRepairSelectionPolicyV1,
  type CutRepairSelectionPolicyV1,
} from "@/lib/producer/contracts/cut-repair-review-transition";
import {
  bindCutRepairPicturePlanAuthority,
  type CutRepairPicturePlanAuthorityV1,
} from "@/lib/producer/contracts/cut-repair-picture-plan-authority";
import { exactKeys, objectValue, sha256 } from
  "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import {
  parseCompatibilityProjection,
  type CompatibilityTimelineProjectionV1,
} from "../auto-edit/compatibility-timeline-projection";

export interface PreparedMediaResult {
  preparedMedia: Record<string, unknown>;
  parentRevisionHash: string;
  contextAuthorityHash: string;
  operation: CutRestoreSpeechV1;
  operationHash: string;
  selectionPolicy: CutRepairSelectionPolicyV1;
  selectionPolicyHash: string;
  projectSampleRate: number;
  reviewPlan: Record<string, unknown>;
  reviewPlanHash: string;
  reviewProjection: CompatibilityTimelineProjectionV1;
  reviewTimelineMapHash: string;
  picturePlanAuthority: CutRepairPicturePlanAuthorityV1 | null;
  fragmentReceipt: Record<string, unknown>;
  compositeReceipt: Record<string, unknown>;
}

const PREPARED_MEDIA_KEYS = [
  "schemaVersion", "kind", "parentRevisionHash", "contextAuthorityHash",
  "operation", "operationHash", "selectionPolicy", "selectionPolicyHash",
  "projectSampleRate", "reviewPlan", "reviewPlanHash", "reviewProjection",
  "reviewTimelineMapHash", "fragmentReceipt", "compositeReceipt",
] as const;

export interface PreparedReviewGraph {
  graph: RenderGraphV1;
  strategy: "dialogue-stem" | "base-segment-fallback";
}

function strategyNodes(
  graph: RenderGraphV1,
): {
  ids: Set<string>;
  strategy: PreparedReviewGraph["strategy"];
} {
  const dialogue = graph.nodes.filter(
    (node) => node.kind === "dialogue-stem");
  if (dialogue.length) {
    return {
      ids: new Set(dialogue.map((node) => node.nodeId)),
      strategy: "dialogue-stem",
    };
  }
  const base = graph.nodes.filter((node) => node.kind === "base-segment");
  if (!base.length) throw new Error("RENDER_GRAPH_AUDIO_NODE_REQUIRED");
  return {
    ids: new Set(base.map((node) => node.nodeId)),
    strategy: "base-segment-fallback",
  };
}

/** Mark the smallest graph audio substrate available in current authority. */
export function buildPreparedReviewGraph(
  graph: RenderGraphV1,
  operationHash: string,
): PreparedReviewGraph {
  const target = strategyNodes(parseRenderGraphV1(graph));
  const key = `cut.restoreSpeech.${operationHash.slice(0, 32)}`;
  const bound = parseRenderGraphV1({
    ...graph,
    nodes: graph.nodes.map((node) => target.ids.has(node.nodeId)
      ? {
          ...node,
          inputDigests: { ...node.inputDigests, [key]: graph.toolchainHash },
        } : node),
  });
  const result = invalidateRenderGraphV1(bound, { [key]: operationHash });
  const root = result.graph.nodes.find(
    (node) => node.nodeId === graph.rootNodeId);
  if (root?.outputArtifactHash !== null) {
    throw new Error("cut repair render invalidation did not reach the root");
  }
  return { graph: result.graph, strategy: target.strategy };
}

function receipt(
  value: unknown,
  kind: string,
  operationHash: string,
  label: string,
): Record<string, unknown> {
  const row = objectValue(value, label);
  const output = objectValue(row.output, `${label}.output`);
  if (row.schemaVersion !== 1 || row.kind !== kind
      || row.operationHash !== operationHash
      || row.exactOutputDurationPreserved !== true
      || typeof output.path !== "string") {
    throw new Error(`${label} is not duration-preserving prepared media`);
  }
  sha256(output.sha256, `${label}.output.sha256`);
  return row;
}

function preparedMediaFields(
  row: Record<string, unknown>,
  operationHash: string,
) {
  if (!Number.isSafeInteger(row.projectSampleRate)
      || Number(row.projectSampleRate) <= 0) {
    throw new Error("cut repair prepared project sample rate is invalid");
  }
  return {
    projectSampleRate: Number(row.projectSampleRate),
    fragmentReceipt: receipt(
      row.fragmentReceipt, "cut-repair-fragment",
      operationHash, "prepared fragment receipt"),
    compositeReceipt: receipt(
      row.compositeReceipt, "cut-repair-composite",
      operationHash, "prepared composite receipt"),
  };
}

/** Reparse every Python-owned plan/media output before durable storage. */
export function parsePreparedMediaResult(
  value: unknown,
): PreparedMediaResult {
  const row = objectValue(value, "cut repair prepared media");
  exactKeys(
    row, PREPARED_MEDIA_KEYS, PREPARED_MEDIA_KEYS,
    "cut repair prepared media");
  if (row.schemaVersion !== 1 || row.kind !== "cut-repair-prepared-media") {
    throw new Error("cut repair prepared media version is unsupported");
  }
  const operation = parseCutRestoreSpeechV1(row.operation);
  const operationHash = sha256(row.operationHash, "prepared operation hash");
  const policy = parseCutRepairSelectionPolicyV1(row.selectionPolicy);
  const policyHash = sha256(
    row.selectionPolicyHash, "prepared selection policy hash");
  const plan = objectValue(row.reviewPlan, "prepared review plan");
  const planHash = sha256(row.reviewPlanHash, "prepared review plan hash");
  const projection = parseCompatibilityProjection(
    row.reviewProjection, planHash);
  if (canonicalJsonSha256(operation) !== operationHash
      || canonicalJsonSha256(policy) !== policyHash
      || canonicalJsonSha256(plan) !== planHash
      || projection.timelineMapHash !== row.reviewTimelineMapHash) {
    throw new Error("cut repair prepared plan or selection is stale");
  }
  const picturePlanAuthority = bindCutRepairPicturePlanAuthority(
    plan, operation, projection.timelineMapHash);
  return {
    preparedMedia: row,
    parentRevisionHash: sha256(
      row.parentRevisionHash, "prepared parent revision"),
    contextAuthorityHash: sha256(
      row.contextAuthorityHash, "prepared context authority"),
    operation,
    operationHash,
    selectionPolicy: policy,
    selectionPolicyHash: policyHash,
    reviewPlan: plan,
    reviewPlanHash: planHash,
    reviewProjection: projection,
    reviewTimelineMapHash: projection.timelineMapHash,
    picturePlanAuthority,
    ...preparedMediaFields(row, operationHash),
  };
}
