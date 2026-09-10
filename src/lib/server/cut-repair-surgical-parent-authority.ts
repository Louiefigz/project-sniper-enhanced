import path from "node:path";
import type { CutRepairPreparationPackageV1 } from
  "@/lib/producer/contracts/cut-repair-preparation";
import type { ProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import { parseRenderGraphV1 } from
  "@/lib/producer/contracts/render-graph";
import {
  objectValue,
  sha256,
} from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { observeCurrentRenderGraphAuthoritySync } from
  "./current-render-graph-authority";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
} from "./producer-authority-files";

function rootArtifact(
  receipt: Record<string, unknown>,
  rootNodeId: string,
): Record<string, unknown> {
  if (!Array.isArray(receipt.artifacts)) {
    throw new Error("picture repair parent receipt has no artifacts");
  }
  const matches = receipt.artifacts.map((item) =>
    objectValue(item, "picture repair parent artifact")).filter(
    (item) => item.nodeId === rootNodeId);
  if (matches.length !== 1) {
    throw new Error("picture repair parent root artifact is not unique");
  }
  return matches[0];
}

/** Reopen ACTIVE and reproduce the Python terminal's exact parent digest. */
export function surgicalParentRenderAuthorityHashSync(
  producerDir: string,
  parent: ProjectRevision,
  packageValue: CutRepairPreparationPackageV1,
): string {
  const paths = producerAuthorityPaths(producerDir);
  const graphHash = packageValue.previousRenderGraphHash;
  const receiptHash = packageValue.previousRenderGraphReceiptHash;
  if (!graphHash || !receiptHash || parent.renderGraphHash !== graphHash) {
    throw new Error("picture repair lacks its exact ACTIVE parent graph");
  }
  const graph = parseRenderGraphV1(assertObjectHashSync(
    paths.objects.graphs, graphHash));
  const receipt = objectValue(assertObjectHashSync(
    paths.objects.receipts, receiptHash), "picture repair parent receipt");
  const root = graph.nodes.find((item) => item.nodeId === graph.rootNodeId);
  const artifact = rootArtifact(receipt, graph.rootNodeId);
  const compositeInputs = objectValue(
    packageValue.compositeReceipt.inputs, "picture repair composite inputs");
  const parentMedia = sha256(
    compositeInputs.parentSha256, "picture repair parent media");
  const expectedPath = path.join(producerDir, "final.mp4");
  const active = observeCurrentRenderGraphAuthoritySync({
    producerDir, expectedGraphHash: graphHash, expectedFinalHash: parentMedia,
  });
  if (active.receiptHash !== receiptHash
      || receipt.graphHash !== graphHash
      || root?.kind !== "final-export"
      || root.inputDigests["final.plan"] !== parent.planContentHash
      || root.outputArtifactHash !== parentMedia
      || artifact.path !== expectedPath || artifact.sha256 !== parentMedia) {
    throw new Error("picture repair ACTIVE parent authority is stale");
  }
  return canonicalJsonSha256({
    graphHash, receiptHash, rootNodeId: graph.rootNodeId,
    rootArtifactPath: expectedPath, rootMediaSha256: parentMedia,
    rootPlanContentHash: parent.planContentHash,
  });
}
