import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  invalidateRenderGraphV1,
  parseRenderGraphV1,
} from "@/lib/producer/contracts/render-graph";
import { planObjectContentHash } from "../auto-edit-authority";
import { initializeProducerAuthoritySync } from "../producer-revision-head";
import type { ProducerRevisionCommitInput } from "../producer-revision-materialize";

export const fixtureHash = (value: string): string => value.repeat(64);
const GENESIS_PLAN = {
  schemaVersion: 1,
  planVersion: "fixture-before",
  graphicsTrack: [],
};
const PLAN_BEFORE = planObjectContentHash(GENESIS_PLAN)!;
const MANIFEST = fixtureHash("b");
const SNAPSHOTS = fixtureHash("c");
const TRANSCRIPT = fixtureHash("d");
const TIMELINE = fixtureHash("e");
const CANVAS = fixtureHash("f");
const DESTINATION = fixtureHash("1");
const PICTURE_LOCK = fixtureHash("2");

function genesisRevision(sourceSnapshotSetHash = SNAPSHOTS) {
  return {
    schemaVersion: 1,
    parentRevisionHash: null,
    planContentHash: PLAN_BEFORE,
    manifestHash: MANIFEST,
    sourceSnapshotSetHash,
    transcriptTimingHash: TRANSCRIPT,
    timelineMapHash: TIMELINE,
    canvasProfileHash: CANVAS,
    destinationProfileHashes: [DESTINATION],
    pictureLockHash: PICTURE_LOCK,
    workflowState: "PICTURE_LOCKED",
    requestLedgerHash: fixtureHash("3"),
    renderGraphHash: fixtureHash("4"),
    projectionReceiptHash: null,
    authoritativeSidecars: { compatibilityLock: PICTURE_LOCK },
  } as const;
}

export function bootstrapRevisionFixture(
  sourceSnapshotSetHash = SNAPSHOTS,
): {
  root: string;
  producer: string;
  genesis: string;
} {
  const root = fs.realpathSync(
    fs.mkdtempSync(path.join(os.tmpdir(), "sniper-revision-v1-")),
  );
  const producer = path.join(root, "producer");
  fs.mkdirSync(producer);
  const genesis = initializeProducerAuthoritySync(
    producer,
    genesisRevision(sourceSnapshotSetHash),
    GENESIS_PLAN,
  ).revisionHash;
  return { root, producer, genesis };
}

function graph(copyHash = fixtureHash("5")) {
  return parseRenderGraphV1({
    schemaVersion: 1,
    graphId: "graph-revision-store",
    toolchainHash: fixtureHash("6"),
    rootNodeId: "node-final",
    nodes: [
      {
        nodeId: "node-scene",
        kind: "scene-unit",
        dependencies: [],
        inputDigests: { "graphic.g-00000001.text": copyHash },
        outputArtifactHash: fixtureHash("7"),
        frameRange: { startFrame: 45, endFrameExclusive: 90 },
      },
      {
        nodeId: "node-final",
        kind: "final-export",
        dependencies: ["node-scene"],
        inputDigests: {},
        outputArtifactHash: fixtureHash("8"),
        frameRange: null,
      },
    ],
  });
}

function uuid(prefix: string, variant: string, index = 0): string {
  const tail = `${variant}${String(index + 1).padStart(11, "0")}`;
  return `${prefix}0000000-0000-4000-8000-${tail}`;
}

function clauses(variant: string, count: number) {
  return Array.from({ length: count }, (_, index) => ({
    schemaVersion: 1 as const,
    clauseId: uuid("3", variant, index),
    text: `Change statement card ${index + 1}.`,
    state: "candidate-executed" as const,
    disposition: "compiled to SetGraphicTextV1",
    blockingClauseIds: [],
  }));
}

function operations(variant: string, count: number) {
  return Array.from({ length: count }, (_, index) => ({
    schemaVersion: 1 as const,
    operationId: uuid("5", variant, index),
    clauseId: uuid("3", variant, index),
    action: {
      schemaVersion: 1 as const,
      operation: "SetGraphicTextV1" as const,
      target: {
        lane: "graphicsTrack" as const,
        id: `g-${(index + 1).toString(36).padStart(8, "0")}`,
      },
      text: `New copy ${variant}-${index + 1}`,
      expectedCurrentText: `Old copy ${index + 1}`,
    },
  }));
}

function requestAndBatch(
  parent: string,
  variant: string,
  count: number,
): Pick<ProducerRevisionCommitInput, "request" | "batch"> {
  const requestId = uuid("1", variant);
  const idempotencyKey = uuid("2", variant);
  return {
    request: {
      schemaVersion: 1,
      requestId,
      idempotencyKey,
      parentRevisionHash: parent,
      workflow: "cut-first",
      rawIntent: `Change ${count} statement-card value(s).`,
      submittedAt: "2026-07-29T12:00:00.000Z",
      clauses: clauses(variant, count),
    },
    batch: {
      schemaVersion: 1,
      batchId: uuid("4", variant),
      requestId,
      idempotencyKey,
      stage: "treatment",
      atomic: true,
      preserveUnrelated: true,
      base: {
        projectRevisionHash: parent,
        planContentHash: PLAN_BEFORE,
        manifestHash: MANIFEST,
        sourceSnapshotSetHash: SNAPSHOTS,
        timelineMapHash: TIMELINE,
        canvasProfileHash: CANVAS,
        destinationProfileHashes: [DESTINATION],
        pictureLockHash: PICTURE_LOCK,
      },
      operations: operations(variant, count),
    },
  };
}

export function revisionCommitInput(
  producer: string,
  parent: string,
  variant: string,
  clauseCount = 1,
): ProducerRevisionCommitInput {
  const nextGraph = invalidateRenderGraphV1(graph(), {
    "graphic.g-00000001.text": fixtureHash("9"),
  });
  const authority = requestAndBatch(parent, variant, clauseCount);
  const planObject = {
    schemaVersion: 1,
    planVersion: `fixture-${variant}`,
    graphicsTrack: operations(variant, clauseCount),
  };
  const planHash = planObjectContentHash(planObject)!;
  return {
    producerDir: producer,
    ...authority,
    planObject,
    revision: {
      planContentHash: planHash,
      manifestHash: MANIFEST,
      sourceSnapshotSetHash: SNAPSHOTS,
      transcriptTimingHash: TRANSCRIPT,
      timelineMapHash: TIMELINE,
      canvasProfileHash: CANVAS,
      destinationProfileHashes: [DESTINATION],
      pictureLockHash: PICTURE_LOCK,
      workflowState: "TREATMENT_DRAFT",
      authoritativeSidecars: { compatibilityLock: PICTURE_LOCK },
    },
    renderGraph: nextGraph.graph,
    projectionReceipt: {
      schemaVersion: 1,
      canonicalPlanHash: planHash,
      manifestHash: MANIFEST,
      sourceSnapshotSetHash: SNAPSHOTS,
      compilerHash: fixtureHash("6"),
      timelineMapHash: TIMELINE,
      projectionHash: fixtureHash("7"),
      generationPath: `compiled/${variant}/edit_plan.render.json`,
    },
    invalidationReceipt: nextGraph.receipt,
    invariantProofHash: fixtureHash("8"),
  };
}

export function cleanRevisionFixture(root: string): void {
  fs.rmSync(root, { recursive: true, force: true });
}
