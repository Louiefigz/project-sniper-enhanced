import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { parseProjectionReceiptV1 } from
  "@/lib/producer/contracts/projection-receipt";
import { parseRenderGraphV1 } from
  "@/lib/producer/contracts/render-graph";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { planObjectContentHash } from "../auto-edit-authority";
import {
  producerAuthorityPaths,
  writeAuthorityObjectSync,
} from "../producer-authority-files";
import { initializeProducerAuthoritySync } from "../producer-revision-head";

const hash = (value: string): string => value.repeat(64);
export const REOPEN_TARGET = {
  phrase: "the clipped phrase",
  sourceId: "raw",
  occurrence: 1,
};
export const REOPEN_PLAN = {
  schemaVersion: 1,
  cutTrack: [{ id: "cut-main", sourceId: "raw", start: 0, end: 10 }],
  graphicsTrack: [{ id: "graphic-after", startFrame: 160, durationFrames: 20 }],
  musicTrack: [{ id: "music-after", startFrame: 200, durationFrames: 90 }],
  captions: [{ id: "caption-crossing", startFrame: 145, endFrame: 155 }],
};

function graph() {
  return parseRenderGraphV1({
    schemaVersion: 1,
    graphId: "ripple-preserved-graph",
    toolchainHash: hash("1"),
    rootNodeId: "final",
    nodes: [{
      nodeId: "final",
      kind: "final-export",
      dependencies: [],
      inputDigests: { plan: planObjectContentHash(REOPEN_PLAN) },
      outputArtifactHash: hash("2"),
      frameRange: null,
    }],
  });
}

function rippleImpact() {
  return {
    exact: true,
    requiredDurationDeltaFrames: 12,
    newTotalOutputFrames: 312,
    rippleFromFrame: 150,
    reopensPictureLock: true,
    semanticClosureRequired: true,
    movedDependents: [
      {
        stableId: "graphic-after",
        elementKind: "graphic",
        from: { startFrame: 160, endFrameExclusive: 180 },
        to: { startFrame: 172, endFrameExclusive: 192 },
      },
      {
        stableId: "music-after",
        elementKind: "music",
        from: { startFrame: 200, endFrameExclusive: 290 },
        to: { startFrame: 212, endFrameExclusive: 302 },
      },
    ],
    invalidatedDependents: ["caption-crossing"],
    unchangedOutputLockedIds: ["title-output-locked"],
  } as const;
}

function analysis(parentRevisionHash: string) {
  return {
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    status: "NON_RIPPLE_IMPOSSIBLE",
    resolvedTarget: {
      kind: "word-range",
      sourceId: "raw",
      wordIds: ["w-1234567890abcdef"],
      occurrence: 1,
      sourceSampleRange: {
        startSample: 230_400,
        endSampleExclusive: 232_000,
      },
      transcriptTimingHash: hash("3"),
    },
    candidates: [],
    recommendedCandidate: null,
    rippleImpact: rippleImpact(),
    evidencePolicy: {
      alignment: "bounded-evidence-not-sole-audibility-proof",
      operatorReport: "ground-truth-when-audition-disagrees",
    },
    routeStatus: "analysis-only-no-mutation",
    contextAuthorityHash: hash("4"),
    parentRevisionHash,
  } as const;
}

export interface ReopenFixture {
  root: string;
  producer: string;
  parentRevisionHash: string;
  action: ReturnType<typeof reopenAction>;
}

interface ReopenActionInput {
  parentRevisionHash: string,
  planHash: string,
  graphHash: string,
  projectionHash: string,
  variant: string,
}

function reopenAction(input: ReopenActionInput) {
  const value = analysis(input.parentRevisionHash);
  return {
    schemaVersion: 1,
    kind: "cut-repair-ripple-reopen-action",
    idempotencyKey:
      `8${input.variant}000000-0000-4000-8000-000000000001`,
    expectedParentRevisionHash: input.parentRevisionHash,
    parentPictureLockHash: hash("5"),
    target: REOPEN_TARGET,
    targetHash: canonicalJsonSha256(REOPEN_TARGET),
    analysis: value,
    analysisHash: canonicalJsonSha256(value),
    impactHash: canonicalJsonSha256(value.rippleImpact),
    preservedPlanObjectHash: input.planHash,
    preservedPlanContentHash: planObjectContentHash(REOPEN_PLAN),
    preservedTimelineMapHash: hash("6"),
    preservedRenderGraphHash: input.graphHash,
    preservedProjectionReceiptHash: input.projectionHash,
    requestedAt: "2026-07-30T12:00:00.000Z",
  } as const;
}

export function createReopenFixture(variant = "1"): ReopenFixture {
  const root = fs.realpathSync(fs.mkdtempSync(
    path.join(os.tmpdir(), "sniper-ripple-reopen-")));
  const producer = path.join(root, "producer");
  fs.mkdirSync(producer);
  const paths = producerAuthorityPaths(producer);
  const plan = writeAuthorityObjectSync(paths.objects.plans, REOPEN_PLAN);
  const storedGraph = writeAuthorityObjectSync(paths.objects.graphs, graph());
  const projection = parseProjectionReceiptV1({
    schemaVersion: 1,
    canonicalPlanHash: planObjectContentHash(REOPEN_PLAN),
    manifestHash: hash("7"),
    sourceSnapshotSetHash: hash("8"),
    compilerHash: hash("9"),
    timelineMapHash: hash("6"),
    projectionHash: hash("a"),
    generationPath: "compiled/ripple/edit_plan.render.json",
  });
  const storedProjection = writeAuthorityObjectSync(
    paths.objects.projections, projection);
  const parent = initializeProducerAuthoritySync(producer, {
    schemaVersion: 1,
    parentRevisionHash: null,
    planContentHash: planObjectContentHash(REOPEN_PLAN),
    manifestHash: hash("7"),
    sourceSnapshotSetHash: hash("8"),
    transcriptTimingHash: hash("3"),
    timelineMapHash: hash("6"),
    canvasProfileHash: hash("b"),
    destinationProfileHashes: [hash("c")],
    pictureLockHash: hash("5"),
    workflowState: "PICTURE_LOCKED",
    requestLedgerHash: hash("d"),
    renderGraphHash: storedGraph.hash,
    projectionReceiptHash: storedProjection.hash,
    authoritativeSidecars: { pictureLock: hash("5") },
  }, REOPEN_PLAN);
  return {
    root,
    producer,
    parentRevisionHash: parent.revisionHash,
    action: reopenAction({
      parentRevisionHash: parent.revisionHash,
      planHash: plan.hash,
      graphHash: storedGraph.hash,
      projectionHash: storedProjection.hash,
      variant,
    }),
  };
}

export function cleanReopenFixture(value: ReopenFixture): void {
  fs.rmSync(value.root, { recursive: true, force: true });
}
