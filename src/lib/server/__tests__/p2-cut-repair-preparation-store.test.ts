import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {
  CUT_REPAIR_PREPARATION_BLOCKERS,
  parseCutRepairPreparationPackageV1,
} from "@/lib/producer/contracts/cut-repair-preparation";
import { parseCutRestoreSpeechV1 } from
  "@/lib/producer/contracts/cut-restore-speech-v1";
import { parseRenderGraphV1 } from
  "@/lib/producer/contracts/render-graph";
import {
  cutRestoreAction,
  fixtureSha,
} from "@/lib/producer/__tests__/_cut-restore-speech-fixture";
import { canonicalJsonSha256, fileSha256 } from "../auto-edit-hash";
import { planObjectContentHash } from "../auto-edit-authority";
import {
  loadCutRepairPreparationSync,
  storeCutRepairPreparationSync,
} from "../cut-repair-preparation-store";
import {
  producerAuthorityPaths,
  writeAuthorityObjectSync,
} from "../producer-authority-files";
import {
  bootstrapRevisionFixture,
  cleanRevisionFixture,
} from "./_producer-revision-fixture";

const ID = "7a000000-0000-4000-8000-000000000001";
const TARGET = fixtureSha("5");
const CONTEXT = fixtureSha("6");
const TIMELINE = fixtureSha("7");
const ORDER = [
  "audio-only-before-picture",
  "fewest-picture-dirty-frames",
  "fewest-audio-dirty-frames",
  "shortest-source-extension",
  "operation-hash-tiebreak",
];

function graph(planHash: string, candidateHash: string) {
  return parseRenderGraphV1({
    schemaVersion: 1,
    graphId: "cut-repair-preparation-test",
    toolchainHash: fixtureSha("8"),
    rootNodeId: "node-final",
    nodes: [{
      nodeId: "node-base",
      kind: "base-segment",
      dependencies: [],
      inputDigests: { "cut.restoreSpeech.fixture": fixtureSha("9") },
      outputArtifactHash: null,
      frameRange: null,
    }, {
      nodeId: "node-final",
      kind: "final-export",
      dependencies: ["node-base"],
      inputDigests: { "final.plan": planHash },
      outputArtifactHash: candidateHash,
      frameRange: null,
    }],
  });
}

function media(producer: string) {
  const directory = path.join(
    producer, ".sniper-cut-repair-staging", "prepared");
  fs.mkdirSync(directory, { recursive: true });
  const fragment = path.join(directory, "fragment.mov");
  const composite = path.join(directory, "candidate.mov");
  const candidate = path.join(directory, "review-candidate.mp4");
  fs.writeFileSync(fragment, "prepared fragment bytes\n");
  fs.writeFileSync(composite, "prepared composite bytes\n");
  fs.writeFileSync(candidate, "rendered review candidate bytes\n");
  return {
    fragment,
    composite,
    candidate,
    fragmentHash: fileSha256(fragment)!,
    compositeHash: fileSha256(composite)!,
    candidateHash: fileSha256(candidate)!,
  };
}

function packageFixture(producer: string, parent: string) {
  const paths = producerAuthorityPaths(producer);
  const operationValue = cutRestoreAction(
    fixtureSha("2"), fixtureSha("e"));
  const segment = operationValue.segment as Record<string, unknown>;
  segment.edge = "start";
  const operation = parseCutRestoreSpeechV1(operationValue);
  const operationHash = canonicalJsonSha256(operation);
  const policy = {
    schemaVersion: 1,
    kind: "cut-repair-selection-policy",
    order: ORDER,
  };
  const policyHash = canonicalJsonSha256(policy);
  const planValue = {
    planVersion: 1,
    cutTrack: [{
      id: "seg-0001", sourceId: "raw-1",
      start: 1, end: 4, speed: 1, audioLeadMs: 50,
    }],
    cutDecisions: { schemaVersion: 1, removals: [] },
  };
  const planContentHash = planObjectContentHash(planValue)!;
  const plan = writeAuthorityObjectSync(paths.objects.plans, planValue);
  const files = media(producer);
  const storedGraph = writeAuthorityObjectSync(
    paths.objects.graphs, graph(planContentHash, files.candidateHash));
  const graphReceipt = writeAuthorityObjectSync(paths.objects.receipts, {
    schemaVersion: 1,
    kind: "current-render-graph-execution",
    graphHash: storedGraph.hash,
    executionMode: "incremental",
    previousGraphHash: null,
    dirtyNodeIds: ["node-base", "node-final"],
    reusedNodeIds: [],
    artifacts: [{
      nodeId: "node-final",
      path: files.candidate,
      sha256: files.candidateHash,
      sizeBytes: fs.statSync(files.candidate).size,
    }],
  });
  const candidatePointer = writeAuthorityObjectSync(paths.objects.receipts, {
    schemaVersion: 1,
    kind: "current-render-graph-candidate",
    candidatePath: files.candidate,
    candidateSha256: files.candidateHash,
    graphHash: storedGraph.hash,
    receiptHash: graphReceipt.hash,
    previousGraphHash: null,
    previousReceiptHash: null,
  });
  const projection = writeAuthorityObjectSync(paths.objects.cutRepairs, {
    approvedCutPlanHash: plan.hash,
    timelineMapHash: TIMELINE,
  });
  const context = writeAuthorityObjectSync(paths.objects.cutRepairs, {
    schemaVersion: 1,
    kind: "cut-repair-analysis-context",
    authorityHash: CONTEXT,
  });
  const analysis = writeAuthorityObjectSync(paths.objects.cutRepairs, {
    status: "eligible",
    parentRevisionHash: parent,
    contextAuthorityHash: CONTEXT,
    recommendedCandidate: {
      operation,
      operationHash,
      selectionPolicy: policy,
      selectionPolicyHash: policyHash,
    },
  });
  const receipt = (
    kind: string,
    outputPath: string,
    hash: string,
  ) => ({
    schemaVersion: 1,
    kind,
    operationHash,
    exactOutputDurationPreserved: true,
    output: { path: outputPath, sha256: hash },
  });
  const action = {
    schemaVersion: 1,
    kind: "cut-repair-review-action",
    idempotencyKey: ID,
    expectedParentRevisionHash: parent,
    operation,
    operationHash,
    selectionPolicy: policy,
    selectionPolicyHash: policyHash,
    reviewPlanObjectHash: plan.hash,
    reviewPlanContentHash: planContentHash,
    reviewTimelineMapHash: TIMELINE,
    reviewRenderGraphHash: storedGraph.hash,
    reviewProjectionReceiptHash: null,
    workflowPolicy: "cut-first",
    requestedAt: "2026-07-29T12:00:00.000Z",
  };
  const candidateDescriptorPath = path.join(
    path.dirname(files.candidate),
    "cut-repair-rendered-candidate.json",
  );
  const candidateDescriptor = writeAuthorityObjectSync(
    paths.objects.cutRepairs, {
      schemaVersion: 1,
      kind: "cut-repair-rendered-plan-candidate",
      status: "candidate-proved",
      operationHash,
      reviewPlanObjectHash: plan.hash,
      reviewPlanContentHash: planContentHash,
      reviewTimelineMapHash: TIMELINE,
      reviewRenderGraphHash: storedGraph.hash,
      reviewRenderGraphReceiptHash: graphReceipt.hash,
      reviewRenderGraphCandidatePointerHash: candidatePointer.hash,
      candidatePath: files.candidate,
      candidateSha256: files.candidateHash,
    });
  return {
    value: {
      schemaVersion: 1,
      kind: "cut-repair-preparation-package",
      status: "rendered-plan-candidate-prepared",
      idempotencyKey: ID,
      targetDirectiveHash: TARGET,
      contextAuthorityHash: CONTEXT,
      contextObjectHash: context.hash,
      analysisObjectHash: analysis.hash,
      parentRevisionHash: parent,
      proposedReviewAction: action,
      reviewProjectionHash: projection.hash,
      renderInvalidationStrategy: "base-segment-fallback",
      fragmentReceipt: receipt(
        "cut-repair-fragment", files.fragment, files.fragmentHash),
      compositeReceipt: receipt(
        "cut-repair-composite", files.composite, files.compositeHash),
      fragmentMediaSha256: files.fragmentHash,
      compositeMediaSha256: files.compositeHash,
      reviewRenderGraphReceiptHash: graphReceipt.hash,
      reviewRenderGraphCandidatePointerHash: candidatePointer.hash,
      reviewCandidateMediaSha256: files.candidateHash,
      reviewCandidatePath: files.candidate,
      reviewCandidateDescriptorHash: candidateDescriptor.hash,
      reviewCandidateDescriptorPath: candidateDescriptorPath,
      previousRenderGraphHash: null,
      previousRenderGraphReceiptHash: null,
      blockingRequirements: [...CUT_REPAIR_PREPARATION_BLOCKERS],
      preparedAt: "2026-07-29T12:00:00.000Z",
    },
    files,
  };
}

const fixture = bootstrapRevisionFixture();
try {
  const prepared = packageFixture(fixture.producer, fixture.genesis);
  const parsed = parseCutRepairPreparationPackageV1(prepared.value);
  assert.equal(parsed.status, "rendered-plan-candidate-prepared");
  const stored = storeCutRepairPreparationSync(
    fixture.producer, prepared.value);
  assert.equal(stored.package.status, "rendered-plan-candidate-prepared");
  assert.equal(
    storeCutRepairPreparationSync(fixture.producer, prepared.value).packageHash,
    stored.packageHash,
  );
  const paths = producerAuthorityPaths(fixture.producer);
  assert.ok(fs.existsSync(path.join(
    paths.objects.media, `${prepared.files.fragmentHash}.mov`)));
  assert.ok(fs.existsSync(path.join(
    paths.objects.media, `${prepared.files.candidateHash}.mp4`)));
  fs.rmSync(path.join(
    fixture.producer, ".sniper-cut-repair-staging"), {
    recursive: true, force: true,
  });
  const recovered = loadCutRepairPreparationSync(
    fixture.producer, ID, TARGET);
  assert.equal(recovered?.packageHash, stored.packageHash);
  assert.equal(
    fileSha256(prepared.files.composite),
    prepared.files.compositeHash,
  );
  assert.equal(
    fileSha256(prepared.files.candidate),
    prepared.files.candidateHash,
  );
  fs.writeFileSync(
    prepared.value.reviewCandidateDescriptorPath,
    "{\"substituted\":true}\n",
  );
  assert.throws(
    () => loadCutRepairPreparationSync(
      fixture.producer, ID, TARGET),
    /immutable authority conflict|substituted/,
  );
  fs.rmSync(prepared.value.reviewCandidateDescriptorPath);
  assert.ok(loadCutRepairPreparationSync(
    fixture.producer, ID, TARGET));
  fs.writeFileSync(prepared.files.composite, "tampered\n");
  assert.throws(
    () => loadCutRepairPreparationSync(fixture.producer, ID, TARGET),
    /tampered/,
  );
  assert.throws(
    () => loadCutRepairPreparationSync(
      fixture.producer, ID, fixtureSha("a")),
    /another target/,
  );
} finally {
  cleanRevisionFixture(fixture.root);
}

console.log("p2-cut-repair-preparation-store tests passed");
