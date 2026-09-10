import { createHash } from "node:crypto";
import {
  lstatSync,
  readFileSync,
  realpathSync,
} from "node:fs";
import path from "node:path";
import {
  parseCompatibilityProjection,
  type CompatibilityTimelineProjectionV1,
} from "@/app/api/producer/auto-edit/compatibility-timeline-projection";
import type { ProjectionReceiptV1 } from
  "@/lib/producer/contracts/projection-receipt";
import {
  parseRenderGraphV1,
  type RenderGraphV1,
} from "@/lib/producer/contracts/render-graph";
import {
  requireSourceSetAdmission,
  type AssetManifest,
} from "@/lib/producer/types";
import { planObjectContentHash } from "./auto-edit-authority";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { assertObjectHashSync } from "./producer-authority-files";
import { findCompatibilityShadowLock } from
  "./producer-revision-shadow-lock";
import {
  observeStagedRenderGraphAuthoritySync,
  type StagedRenderGraphAuthority,
} from "./staged-render-graph-authority";
import { autoEditProjectionReceipt } from
  "./producer-auto-edit-projection-authority";
import { autoEditGenesisValue } from
  "./producer-auto-edit-genesis-value";

export interface AutoEditGenesisExpectation {
  producerDir: string;
  planPath: string;
  manifestPath: string;
  candidatePath: string;
  expectedPlanHash: string;
  expectedManifestHash: string;
  expectedCandidateHash: string;
}

export interface AutoEditGenesisFacts {
  planObject: Record<string, unknown>;
  planContentHash: string;
  planFileHash: string;
  manifestHash: string;
  sourceSnapshotSetHash: string;
  transcriptTimingHash: string;
  timelineMapHash: string;
  canvasProfileHash: string;
  destinationProfileHashes: string[];
  pictureLockHash: string;
  renderGraph: RenderGraphV1;
  renderGraphReceipt: Record<string, unknown>;
  renderGraphCandidatePointer: Record<string, unknown>;
  projection: CompatibilityTimelineProjectionV1;
  projectionReceipt: ProjectionReceiptV1;
  authoritativeSidecars: Record<string, string>;
}

interface StableJson {
  hash: string;
  value: Record<string, unknown>;
}

export class ProducerAuthorityReadinessError extends Error {
  constructor(readonly missingFacts: string[]) {
    super(`producer authority is not ready: ${missingFacts.join(", ")}`);
    this.name = "ProducerAuthorityReadinessError";
  }
}

function stableJson(filePath: string, label: string): StableJson {
  const resolved = path.resolve(filePath);
  const before = lstatSync(resolved);
  if (!before.isFile() || before.isSymbolicLink()
      || realpathSync(resolved) !== resolved) {
    throw new Error(`${label} is not a canonical regular file`);
  }
  const bytes = readFileSync(resolved);
  const after = lstatSync(resolved);
  if (before.dev !== after.dev || before.ino !== after.ino
      || before.size !== after.size || before.mtimeMs !== after.mtimeMs
      || before.ctimeMs !== after.ctimeMs) {
    throw new Error(`${label} changed while read`);
  }
  const value = JSON.parse(bytes.toString("utf8")) as unknown;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} is not a JSON object`);
  }
  return {
    hash: createHash("sha256").update(bytes).digest("hex"),
    value: value as Record<string, unknown>,
  };
}

function targetProfile(plan: Record<string, unknown>): {
  canvas: string;
  destinations: string[];
} {
  const target = plan.target;
  if (!target || typeof target !== "object" || Array.isArray(target)) {
    throw new ProducerAuthorityReadinessError([
      "canvasProfileHash", "destinationProfileHashes",
    ]);
  }
  const canvas = canonicalJsonSha256(target);
  return { canvas, destinations: [canvas] };
}

function compatibilityFacts(
  input: AutoEditGenesisExpectation,
  plan: Record<string, unknown>,
): {
  lock: NonNullable<ReturnType<typeof findCompatibilityShadowLock>>;
  projection: CompatibilityTimelineProjectionV1;
} {
  const lock = findCompatibilityShadowLock(
    input.producerDir, input.manifestPath, plan);
  if (!lock) {
    throw new ProducerAuthorityReadinessError([
      "pictureLockHash",
      "transcriptTimingHash",
      "timelineMapHash",
      "projectionReceiptHash",
    ]);
  }
  const stored = assertObjectHashSync(
    path.join(input.producerDir, "compatibility_projections"),
    lock.projectionReceiptHash,
  );
  const projection = parseCompatibilityProjection(
    stored, lock.approvedCutPlanHash);
  if (projection.timelineMapHash !== lock.timelineMapHash) {
    throw new Error("compatibility lock and projection timeline disagree");
  }
  return { lock, projection };
}

function stagedGeneration(
  input: AutoEditGenesisExpectation,
): {
  staged: StagedRenderGraphAuthority;
  graph: RenderGraphV1;
  receipt: Record<string, unknown>;
} {
  const staged = observeStagedRenderGraphAuthoritySync({
    producerDir: input.producerDir,
    candidatePath: input.candidatePath,
    expectedCandidateHash: input.expectedCandidateHash,
  });
  const generation = path.join(
    input.producerDir,
    ".render-graph-v1",
    "generations",
    staged.graphHash,
  );
  const graphJson = stableJson(
    path.join(generation, "graph.json"), "staged render graph");
  const receiptJson = stableJson(
    path.join(generation, "receipts", `${staged.receiptHash}.json`),
    "staged render graph receipt",
  );
  if (canonicalJsonSha256(graphJson.value) !== staged.graphHash
      || canonicalJsonSha256(receiptJson.value) !== staged.receiptHash) {
    throw new Error("staged render graph generation identity changed");
  }
  return {
    staged,
    graph: parseRenderGraphV1(graphJson.value),
    receipt: receiptJson.value,
  };
}

function stagedCandidatePointer(
  input: AutoEditGenesisExpectation,
  staged: StagedRenderGraphAuthority,
): Record<string, unknown> {
  const pointer = {
    schemaVersion: 1,
    kind: "current-render-graph-candidate",
    candidatePath: path.resolve(input.candidatePath),
    candidateSha256: staged.candidateMediaHash,
    graphHash: staged.graphHash,
    receiptHash: staged.receiptHash,
    previousGraphHash: staged.previousGraphHash,
    previousReceiptHash: staged.previousReceiptHash,
  };
  if (canonicalJsonSha256(pointer) !== staged.candidatePointerHash) {
    throw new Error("staged candidate pointer cannot be reconstructed");
  }
  return pointer;
}

function sourceSetHash(
  manifest: Record<string, unknown>,
  graph: RenderGraphV1,
  manifestHash: string,
): string {
  let binding;
  try {
    binding = requireSourceSetAdmission(
      manifest as unknown as AssetManifest);
  } catch {
    throw new ProducerAuthorityReadinessError(["sourceSnapshotSetHash"]);
  }
  const source = graph.nodes.find((node) =>
    node.nodeId === "node-source" && node.kind === "source-snapshot");
  if (source?.inputDigests["source.manifest"] !== manifestHash
      || source.inputDigests["source.set"] !== binding.sourceSetDigest) {
    throw new Error("staged graph does not bind the admitted source set");
  }
  return binding.sourceSetDigest;
}

function assertGraphPlan(
  graph: RenderGraphV1,
  planContentHash: string,
): void {
  const root = graph.nodes.find((node) => node.nodeId === graph.rootNodeId);
  const timeline = graph.nodes.find((node) =>
    node.nodeId === "node-timeline" && node.kind === "timeline-map");
  if (root?.kind !== "final-export"
      || root.inputDigests["final.plan"] !== planContentHash
      || !timeline?.outputArtifactHash) {
    throw new Error("staged graph does not bind the rendered plan and timeline");
  }
}

function assertInputsUnchanged(
  input: AutoEditGenesisExpectation,
  planHash: string,
  manifestHash: string,
): void {
  if (stableJson(input.planPath, "rendered plan").hash !== planHash
      || stableJson(input.manifestPath, "render manifest").hash !== manifestHash) {
    throw new Error("producer authority inputs changed during initialization");
  }
}

/** Reopen every fact needed by a non-approved READY_TO_FINALIZE genesis. */
export function observeAutoEditGenesisFactsSync(
  input: AutoEditGenesisExpectation): AutoEditGenesisFacts {
  const plan = stableJson(input.planPath, "rendered plan");
  const manifest = stableJson(input.manifestPath, "render manifest");
  if (plan.hash !== input.expectedPlanHash
      || manifest.hash !== input.expectedManifestHash) {
    throw new Error("rendered plan or manifest checkpoint is stale");
  }
  const planContentHash = planObjectContentHash(plan.value);
  if (!planContentHash) {
    throw new ProducerAuthorityReadinessError(["planContentHash"]);
  }
  const compatibility = compatibilityFacts(input, plan.value);
  const generation = stagedGeneration(input);
  assertGraphPlan(generation.graph, planContentHash);
  const sourceSnapshotSetHash = sourceSetHash(
    manifest.value, generation.graph, manifest.hash);
  const projectionReceipt = autoEditProjectionReceipt({
    planContentHash,
    manifestHash: manifest.hash,
    sourceSnapshotSetHash,
    projection: compatibility.projection,
  });
  const profile = targetProfile(plan.value);
  assertInputsUnchanged(input, plan.hash, manifest.hash);
  return autoEditGenesisValue({
    planObject: plan.value,
    planContentHash,
    planFileHash: plan.hash,
    manifestHash: manifest.hash,
    sourceSnapshotSetHash,
    sourceSetAdmissionReceipt: (
      manifest.value.sourceSetAdmission as Record<string, unknown>
    ).receiptSha256 as string,
    canvasProfileHash: profile.canvas,
    destinationProfileHashes: profile.destinations,
    lock: compatibility.lock,
    graph: generation.graph,
    graphReceipt: generation.receipt,
    candidatePointer: stagedCandidatePointer(input, generation.staged),
    staged: generation.staged,
    projection: compatibility.projection,
    projectionReceipt,
  });
}
