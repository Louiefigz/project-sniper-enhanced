import { createHash } from "node:crypto";
import {
  lstatSync,
  readFileSync,
  realpathSync,
} from "node:fs";
import {
  parseProjectRevision,
  type ProjectRevisionV2,
} from "@/lib/producer/contracts/project-revision";
import { parseProjectionReceiptV1 } from
  "@/lib/producer/contracts/projection-receipt";
import { parseRenderGraphV1 } from
  "@/lib/producer/contracts/render-graph";
import { parseApprovalRecord } from "./auto-edit-approval";
import {
  planObjectContentHash,
} from "./auto-edit-authority";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
} from "./producer-authority-files";
import { observeCurrentRenderGraphAuthoritySync } from
  "./current-render-graph-authority";
import { assertRevisionPlanObjectSync } from
  "./producer-plan-authority";
import {
  resolveProducerApprovedHeadSync,
  resolveProducerAuthorityHeadSync,
} from "./producer-revision-head";

export interface ApprovedRevisionExpectation {
  producerDir: string;
  planPath: string;
  manifestPath: string;
  expectedFinalHash: string;
}

function approvedRevision(
  input: ApprovedRevisionExpectation,
): {
  hash: string;
  revision: ProjectRevisionV2;
  plan: Record<string, unknown>;
} {
  const paths = producerAuthorityPaths(input.producerDir);
  const hash = resolveProducerAuthorityHeadSync(input.producerDir);
  const approved = resolveProducerApprovedHeadSync(input.producerDir);
  if (approved !== hash) {
    throw new Error("approved output is not the exact working revision");
  }
  const parsed = parseProjectRevision(
    assertObjectHashSync(paths.objects.revisions, hash));
  if (parsed.schemaVersion !== 2 || parsed.workflowState !== "QC_APPROVED") {
    throw new Error("approved output has no exact QC-approved revision");
  }
  const plan = assertRevisionPlanObjectSync(paths, parsed);
  if (!plan) throw new Error("approved revision has no exact plan");
  return { hash, revision: parsed, plan };
}

interface StableFile {
  bytes: Buffer;
  hash: string;
}

function stableFile(filePath: string, label: string): StableFile {
  const before = lstatSync(filePath);
  if (!before.isFile() || before.isSymbolicLink()
      || realpathSync(filePath) !== filePath) {
    throw new Error(`${label} is not a canonical regular file`);
  }
  const bytes = readFileSync(filePath);
  const after = lstatSync(filePath);
  if (before.dev !== after.dev || before.ino !== after.ino
      || before.size !== after.size || before.mtimeMs !== after.mtimeMs
      || before.ctimeMs !== after.ctimeMs) {
    throw new Error(`${label} changed while read`);
  }
  return {
    bytes,
    hash: createHash("sha256").update(bytes).digest("hex"),
  };
}

function livePlanObject(file: StableFile): Record<string, unknown> {
  const value = JSON.parse(file.bytes.toString("utf8")) as unknown;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("live approved plan is not a JSON object");
  }
  return value as Record<string, unknown>;
}

function assertLiveInputs(
  input: ApprovedRevisionExpectation,
  revision: ProjectRevisionV2,
  storedPlan: Record<string, unknown>,
): void {
  const planFile = stableFile(input.planPath, "live approved plan");
  const manifestFile = stableFile(
    input.manifestPath, "live approved manifest");
  const livePlan = livePlanObject(planFile);
  const semanticHash = planObjectContentHash(livePlan);
  const exactHash = canonicalJsonSha256(livePlan);
  const storedExactHash = canonicalJsonSha256(storedPlan);
  if (!semanticHash
      || semanticHash !== revision.planContentHash
      || exactHash !== storedExactHash
      || planFile.hash
        !== revision.authoritativeSidecars.renderedPlanFile
      || manifestFile.hash !== revision.manifestHash) {
    throw new Error("live inputs differ from the exact approved revision");
  }
}

function assertStoredObjects(
  input: ApprovedRevisionExpectation,
  revision: ProjectRevisionV2,
): void {
  const paths = producerAuthorityPaths(input.producerDir);
  assertObjectHashSync(paths.objects.requests, revision.requestLedgerHash);
  const graph = parseRenderGraphV1(
    assertObjectHashSync(paths.objects.graphs, revision.renderGraphHash));
  if (revision.projectionReceiptHash === null) {
    throw new Error("approved revision has no projection receipt");
  }
  const projection = parseProjectionReceiptV1(assertObjectHashSync(
    paths.objects.projections, revision.projectionReceiptHash));
  const root = graph.nodes.find((node) => node.nodeId === graph.rootNodeId);
  if (projection.canonicalPlanHash !== revision.planContentHash
      || projection.manifestHash !== revision.manifestHash
      || projection.sourceSnapshotSetHash !== revision.sourceSnapshotSetHash
      || root?.inputDigests["final.plan"] !== revision.planContentHash) {
    throw new Error("approved graph or projection binds foreign inputs");
  }
}

function assertApproval(
  input: ApprovedRevisionExpectation,
  revision: ProjectRevisionV2,
): void {
  const paths = producerAuthorityPaths(input.producerDir);
  const approvalHash = revision.authoritativeSidecars.qcApprovalV2;
  const approval = parseApprovalRecord(
    assertObjectHashSync(paths.objects.receipts, approvalHash));
  if (!approval
      || approval.planHash
        !== revision.authoritativeSidecars.renderedPlanFile
      || approval.manifestHash !== revision.manifestHash
      || approval.finalHash !== input.expectedFinalHash
      || revision.authoritativeSidecars.approvedFinalMedia
        !== input.expectedFinalHash) {
    throw new Error("approved revision binds foreign QC evidence");
  }
}

function assertCurrentGraph(
  input: ApprovedRevisionExpectation,
  revision: ProjectRevisionV2,
): void {
  const currentHash =
    revision.authoritativeSidecars.currentRenderGraphV1;
  if (currentHash !== revision.renderGraphHash
      || revision.authoritativeSidecars.stagedRenderGraphV1 !== currentHash) {
    throw new Error("approved revision does not select its rendered graph");
  }
  const observed = observeCurrentRenderGraphAuthoritySync({
    producerDir: input.producerDir,
    expectedGraphHash: currentHash,
    expectedFinalHash: input.expectedFinalHash,
  });
  const paths = producerAuthorityPaths(input.producerDir);
  const receiptHash =
    revision.authoritativeSidecars.currentRenderGraphReceiptV1;
  const pointerHash =
    revision.authoritativeSidecars.currentRenderGraphActivePointerV1;
  if (observed.receiptHash !== receiptHash
      || observed.activePointerHash !== pointerHash) {
    throw new Error("live render graph differs from the approved revision");
  }
  assertObjectHashSync(paths.objects.receipts, receiptHash);
  assertObjectHashSync(paths.objects.receipts, pointerHash);
}

/** Reopen every exact revision and graph object required to reuse final.mp4. */
export function assertApprovedProducerRevisionSync(
  input: ApprovedRevisionExpectation,
): string {
  const approved = approvedRevision(input);
  assertLiveInputs(input, approved.revision, approved.plan);
  assertStoredObjects(input, approved.revision);
  assertApproval(input, approved.revision);
  assertCurrentGraph(input, approved.revision);
  return approved.hash;
}

/** Pipeline predicate: any missing or inconsistent authority fails closed. */
export function approvedProducerRevisionReady(
  producerDir: string,
  planPath: string,
  manifestPath: string,
  expectedFinalHash: string,
): boolean {
  try {
    assertApprovedProducerRevisionSync({
      producerDir, planPath, manifestPath, expectedFinalHash,
    });
    return true;
  } catch {
    return false;
  }
}
