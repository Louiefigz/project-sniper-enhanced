import fs from "node:fs";
import path from "node:path";
import { parseCutRestoreSpeechV1 } from
  "@/lib/producer/contracts/cut-restore-speech-v1";
import { parseProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import {
  cutRestoreAction,
  fixtureSha,
} from "@/lib/producer/__tests__/_cut-restore-speech-fixture";
import { canonicalJsonSha256, fileSha256 } from "../auto-edit-hash";
import { planObjectContentHash } from "../auto-edit-authority";
import { stageCutRepairReviewSync } from "../cut-repair-review-store";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
  writeAuthorityObjectSync,
} from "../producer-authority-files";
import {
  bootstrapRevisionFixture,
  revisionCommitInput,
} from "./_producer-revision-fixture";
import {
  currentRenderToolchainHash,
  writeRealCutRepairCandidate,
} from
  "./_p2-cut-repair-rendered-promotion-fixture";
import {
  EMPTY_SOURCE_SET_DIGEST,
  stageAutoEditGraphFixture,
} from "./_producer-auto-edit-render-graph-fixture";
import { observeStagedRenderGraphAuthoritySync } from
  "../staged-render-graph-authority";

const POLICY = {
  schemaVersion: 1,
  kind: "cut-repair-selection-policy",
  order: [
    "audio-only-before-picture",
    "fewest-picture-dirty-frames",
    "fewest-audio-dirty-frames",
    "shortest-source-extension",
    "operation-hash-tiebreak",
  ],
} as const;

function preservedPlanValue() {
  return {
    planVersion: 2,
    target: { width: 1920, height: 1080, fps: 30 },
    cutTrack: [
      {
        id: "prior-disjoint-repair", sourceId: "raw",
        start: 0, end: 1, audioLeadMs: 120,
      },
      { id: "repaired-segment", sourceId: "raw", start: 1, end: 3 },
    ],
    graphicsTrack: [{
      id: "preserved-title-card", type: "text",
      start: 1.25, end: 2.25, text: "Still here",
    }],
    music: { path: "music/preserved-bed.wav", volume: 0.18 },
    captions: {
      enabled: true, style: "karaoke",
      words: [{ id: "caption-1", text: "Still", start: 1.25, end: 1.6 }],
    },
  };
}

function stagedCandidate(
  producer: string,
  planValue: ReturnType<typeof preservedPlanValue>,
  manifestHash: string,
) {
  const candidatePath = path.join(
    producer, ".sniper-cut-repair-staging", "v2-promotion",
    "full-plan-candidate.mp4");
  fs.mkdirSync(path.dirname(candidatePath), { recursive: true });
  writeRealCutRepairCandidate(candidatePath);
  const graphHash = stageAutoEditGraphFixture({
    producer,
    candidatePath,
    planContentHash: planObjectContentHash(planValue)!,
    manifestHash,
    sourceSetHash: EMPTY_SOURCE_SET_DIGEST,
    toolchainHash: currentRenderToolchainHash(),
  });
  const graphPath = path.join(
    producer, ".render-graph-v1", "generations",
    graphHash, "graph.json");
  const graphValue = JSON.parse(
    fs.readFileSync(graphPath, "utf8")) as unknown;
  const paths = producerAuthorityPaths(producer);
  const graph = writeAuthorityObjectSync(paths.objects.graphs, graphValue);
  const staged = observeStagedRenderGraphAuthoritySync({
    producerDir: producer,
    candidatePath,
    expectedCandidateHash: fileSha256(candidatePath)!,
  });
  return { candidatePath, graph, staged };
}

interface ReviewActionSeed {
  parent: string;
  operation: ReturnType<typeof parseCutRestoreSpeechV1>;
  planHash: string;
  planContentHash: string;
  graphHash: string;
}

function reviewAction(seed: ReviewActionSeed) {
  return {
    schemaVersion: 1,
    kind: "cut-repair-review-action",
    idempotencyKey: "74000000-0000-4000-8000-000000000001",
    expectedParentRevisionHash: seed.parent,
    operation: seed.operation,
    operationHash: canonicalJsonSha256(seed.operation),
    selectionPolicy: POLICY,
    selectionPolicyHash: canonicalJsonSha256(POLICY),
    reviewPlanObjectHash: seed.planHash,
    reviewPlanContentHash: seed.planContentHash,
    reviewTimelineMapHash: fixtureSha("7"),
    reviewRenderGraphHash: seed.graphHash,
    reviewProjectionReceiptHash: null,
    workflowPolicy: "cut-first",
    requestedAt: "2026-07-29T12:00:00.000Z",
  } as const;
}

/** Real media/graph plus exact plan lanes for V2 activation tests. */
export function renderedPromotionReviewSetup() {
  const fixture = bootstrapRevisionFixture(EMPTY_SOURCE_SET_DIGEST);
  const base = revisionCommitInput(fixture.producer, fixture.genesis, "c");
  const operation = parseCutRestoreSpeechV1(cutRestoreAction(
    base.batch.base.pictureLockHash, base.batch.base.timelineMapHash));
  const paths = producerAuthorityPaths(fixture.producer);
  const planValue = preservedPlanValue();
  const plan = writeAuthorityObjectSync(paths.objects.plans, planValue);
  const candidate = stagedCandidate(
    fixture.producer, planValue, base.revision.manifestHash);
  const action = reviewAction({
    parent: fixture.genesis,
    operation,
    planHash: plan.hash,
    planContentHash: planObjectContentHash(planValue)!,
    graphHash: candidate.graph.hash,
  });
  const review = stageCutRepairReviewSync({
    producerDir: fixture.producer, action});
  const revision = parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions, review.childRevisionHash));
  return {
    fixture, operation, paths, plan, reviewAction: action, review, revision,
    planValue, ...candidate,
  };
}
