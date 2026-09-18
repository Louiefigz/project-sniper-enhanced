import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  renderCutRepairPrivatePlan,
  type CutRepairRenderExecutor,
} from "@/app/api/producer/ai-edit/cut-repair-private-render";
import { canonicalJsonSha256, fileSha256 } from "../auto-edit-hash";
import { planObjectContentHash } from "../auto-edit-authority";
import { captureCutRepairPreparedRenderSync } from
  "../cut-repair-prepared-render-authority";
import { producerAuthorityPaths } from "../producer-authority-files";
import { stageCutRepairRenderedCandidateSync } from
  "../cut-repair-rendered-candidate-store";
import type { CutRepairReviewActionV1 } from
  "@/lib/producer/contracts/cut-repair-review-transition";

interface StagedFacts {
  graphHash: string;
  receiptHash: string;
  pointerHash: string;
}

interface Fixture {
  root: string;
  producer: string;
  staging: string;
  manifest: string;
  plan: Record<string, unknown>;
}

function fixture(): Fixture {
  const root = fs.realpathSync(
    fs.mkdtempSync(path.join(os.tmpdir(), "sniper-private-render-")));
  const producer = path.join(root, "producer");
  const staging = path.join(producer, ".sniper-cut-repair-staging", "attempt");
  const manifest = path.join(root, "asset_manifest.json");
  fs.mkdirSync(staging, { recursive: true });
  fs.writeFileSync(manifest, "{}\n");
  return { root, producer, staging, manifest, plan: {
    planVersion: 1,
    target: { mode: "longform" },
    cutTrack: [{
      id: "segment-a", sourceId: "raw-a",
      start: 0, end: 2, speed: 1, audioLeadMs: 50,
    }],
  } };
}

function stageGraph(
  producer: string,
  artifactDir: string,
  staged: StagedFacts,
): void {
  const plan = JSON.parse(
    fs.readFileSync(path.join(artifactDir, "edit_plan.json"), "utf8"),
  ) as Record<string, unknown>;
  const candidate = path.join(artifactDir, "final.mp4");
  const graph = {
    schemaVersion: 1,
    graphId: "private-render-test",
    toolchainHash: "4".repeat(64),
    rootNodeId: "node-final",
    nodes: [{
      nodeId: "node-final",
      kind: "final-export",
      dependencies: [],
      inputDigests: { "final.plan": planObjectContentHash(plan) },
      outputArtifactHash: fileSha256(candidate),
      frameRange: null,
    }],
  };
  staged.graphHash = canonicalJsonSha256(graph);
  const generation = path.join(
    producer, ".render-graph-v1", "generations", staged.graphHash);
  const receipts = path.join(generation, "receipts");
  fs.mkdirSync(receipts, { recursive: true });
  fs.writeFileSync(
    path.join(generation, "graph.json"),
    `${JSON.stringify(graph, null, 2)}\n`,
  );
  const receipt = {
    schemaVersion: 1,
    kind: "current-render-graph-execution",
    graphHash: staged.graphHash,
    executionMode: "incremental",
    previousGraphHash: null,
    dirtyNodeIds: ["node-final"],
    reusedNodeIds: [],
    artifacts: [{
      nodeId: "node-final",
      path: candidate,
      sha256: fileSha256(candidate),
      sizeBytes: fs.statSync(candidate).size,
    }],
  };
  staged.receiptHash = canonicalJsonSha256(receipt);
  fs.writeFileSync(
    path.join(receipts, `${staged.receiptHash}.json`),
    `${JSON.stringify(receipt, null, 2)}\n`,
  );
  const pointer = {
    schemaVersion: 1,
    kind: "current-render-graph-candidate",
    candidatePath: candidate,
    candidateSha256: fileSha256(candidate),
    graphHash: staged.graphHash,
    receiptHash: staged.receiptHash,
    previousGraphHash: null,
    previousReceiptHash: null,
  };
  staged.pointerHash = canonicalJsonSha256(pointer);
  const pointerKey = canonicalJsonSha256({
    kind: "current-render-candidate-path",
    path: candidate,
  });
  const candidates = path.join(producer, ".render-graph-v1", "candidates");
  fs.mkdirSync(candidates, { recursive: true });
  fs.writeFileSync(
    path.join(candidates, `${pointerKey}.json`),
    `${JSON.stringify(pointer, null, 2)}\n`,
  );
}

function executor(
  calls: string[][],
  fixtureValue: Fixture,
  staged: StagedFacts,
): CutRepairRenderExecutor {
  return async (_script, args, label) => {
    calls.push(args);
    const renderer = args.slice(args.indexOf("--") + 1);
    const artifactDir = args[args.indexOf("--artifact-dir") + 1];
    if (label.includes("base")) {
      fs.copyFileSync(
        renderer[1], path.join(artifactDir, "edit_plan.json"));
      fs.writeFileSync(path.join(artifactDir, "final.mp4"), "base\n");
      return { code: 0, stdout: "", stderr: "" };
    }
    fs.writeFileSync(path.join(artifactDir, "final.mp4"), "candidate\n");
    stageGraph(fixtureValue.producer, artifactDir, staged);
    return {
      code: 0,
      stdout: `${JSON.stringify({
        status: "render_graph_candidate_staged", graphHash: staged.graphHash,
      })}\n`,
      stderr: "",
    };
  };
}

async function run(): Promise<void> {
  const value = fixture();
  const calls: string[][] = [];
  const staged: StagedFacts = {
    graphHash: "", receiptHash: "", pointerHash: "",
  };
  const execute = executor(calls, value, staged);
  try {
    const planObjectHash = canonicalJsonSha256(value.plan);
    const planContentHash = planObjectContentHash(value.plan)!;
    const result = await renderCutRepairPrivatePlan({
      producerDir: value.producer,
      stagingDir: value.staging,
      manifestPath: value.manifest,
      reviewPlan: value.plan,
      planObjectHash,
      planContentHash,
    }, execute);
    assert.equal(result.graphHash, staged.graphHash);
    assert.equal(result.graphReceiptHash, staged.receiptHash);
    assert.equal(result.candidatePointerHash, staged.pointerHash);
    assert.equal(result.candidateSha256, fileSha256(result.candidatePath));
    captureCutRepairPreparedRenderSync(value.producer, result);
    const action = {
      operationHash: "1".repeat(64),
      reviewPlanObjectHash: planObjectHash,
      reviewPlanContentHash: planContentHash,
      reviewTimelineMapHash: "2".repeat(64),
      reviewRenderGraphHash: result.graphHash,
    } as CutRepairReviewActionV1;
    const candidate = stageCutRepairRenderedCandidateSync({
      producerDir: value.producer,
      action,
      render: result,
    });
    assert.equal(
      candidate.descriptor.candidateSha256, result.candidateSha256);
    assert.equal(
      canonicalJsonSha256(candidate.descriptor), candidate.descriptorHash);
    const paths = producerAuthorityPaths(value.producer);
    assert.ok(fs.existsSync(path.join(
      paths.objects.media, `${result.candidateSha256}.mp4`)));
    assert.notEqual(
      path.resolve(calls[0][calls[0].indexOf("--plan") + 1]),
      result.planPath,
    );
    assert.ok(calls[0].includes("--artifact-dir"));
    assert.ok(calls[1].includes("--defer-active"));
    await assert.rejects(
      renderCutRepairPrivatePlan({
        producerDir: value.producer,
        stagingDir: value.staging,
        manifestPath: value.manifest,
        reviewPlan: value.plan,
        planObjectHash: "8".repeat(64),
        planContentHash,
      }, execute),
      /identities disagree/,
    );
    await assert.rejects(
      renderCutRepairPrivatePlan({
        producerDir: value.producer,
        stagingDir: value.root,
        manifestPath: value.manifest,
        reviewPlan: value.plan,
        planObjectHash,
        planContentHash,
      }, execute),
      /escaped controller-owned staging/,
    );
  } finally {
    fs.rmSync(value.root, { recursive: true, force: true });
  }
}

run().then(() => {
  console.log("p2-cut-repair-private-render tests passed");
}).catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
