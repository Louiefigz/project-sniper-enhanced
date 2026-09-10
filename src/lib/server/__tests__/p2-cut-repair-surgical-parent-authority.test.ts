import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { CutRepairPreparationPackageV1 } from
  "@/lib/producer/contracts/cut-repair-preparation";
import type { ProjectRevisionV2 } from
  "@/lib/producer/contracts/project-revision";
import { canonicalJsonSha256, fileSha256 } from "../auto-edit-hash";
import { surgicalParentRenderAuthorityHashSync } from
  "../cut-repair-surgical-parent-authority";
import {
  producerAuthorityPaths,
  writeAuthorityObjectSync,
} from "../producer-authority-files";
import { stageAutoEditGraphFixture } from
  "./_producer-auto-edit-render-graph-fixture";

function writeJson(filePath: string, value: unknown): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`);
}

interface ParentFixture {
  root: string;
  producer: string;
  finalPath: string;
  planContentHash: string;
  graphHash: string;
  receiptHash: string;
  parentMedia: string;
  parent: ProjectRevisionV2;
  packageValue: CutRepairPreparationPackageV1;
}

function parentFixture(): ParentFixture {
  const root = fs.realpathSync(
    fs.mkdtempSync(path.join(os.tmpdir(), "sniper-parent-render-")));
  const producer = path.join(root, "producer");
  fs.mkdirSync(producer);
  const finalPath = path.join(producer, "final.mp4");
  fs.writeFileSync(finalPath, "active parent media\n");
  const planContentHash = "1".repeat(64);
  const graphHash = stageAutoEditGraphFixture({
    producer,
    candidatePath: finalPath,
    planContentHash,
    manifestHash: "2".repeat(64),
    sourceSetHash: "3".repeat(64),
  });
  const generation = path.join(
    producer, ".render-graph-v1", "generations", graphHash);
  const receiptName = fs.readdirSync(
    path.join(generation, "receipts"))[0];
  const receiptHash = receiptName.replace(/\.json$/u, "");
  writeJson(path.join(producer, ".render-graph-v1", "ACTIVE.json"), {
    schemaVersion: 1, graphHash, receiptHash,
  });
  const graph = JSON.parse(
    fs.readFileSync(path.join(generation, "graph.json"), "utf8"));
  const receipt = JSON.parse(fs.readFileSync(
    path.join(generation, "receipts", receiptName), "utf8"));
  const paths = producerAuthorityPaths(producer);
  writeAuthorityObjectSync(paths.objects.graphs, graph);
  writeAuthorityObjectSync(paths.objects.receipts, receipt);
  const parentMedia = fileSha256(finalPath)!;
  const parent = {
    schemaVersion: 2,
    renderGraphHash: graphHash,
    planContentHash,
  } as ProjectRevisionV2;
  const packageValue = {
    previousRenderGraphHash: graphHash,
    previousRenderGraphReceiptHash: receiptHash,
    compositeReceipt: { inputs: { parentSha256: parentMedia } },
  } as unknown as CutRepairPreparationPackageV1;
  return {
    root, producer, finalPath, planContentHash, graphHash, receiptHash,
    parentMedia, parent, packageValue,
  };
}

function run(): void {
  const item = parentFixture();
  try {
    assert.equal(surgicalParentRenderAuthorityHashSync(
      item.producer, item.parent, item.packageValue), canonicalJsonSha256({
      graphHash: item.graphHash,
      receiptHash: item.receiptHash,
      rootNodeId: "node-final",
      rootArtifactPath: item.finalPath,
      rootMediaSha256: item.parentMedia,
      rootPlanContentHash: item.planContentHash,
    }));
    fs.writeFileSync(item.finalPath, "out-of-band replacement\n");
    assert.throws(() => surgicalParentRenderAuthorityHashSync(
      item.producer, item.parent, item.packageValue),
    /artifact bytes changed|does not bind expected media/);
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

run();
console.log("p2-cut-repair-surgical-parent-authority tests passed");
