import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import {
  recoverCandidatePromotionSync,
  type PromotionTopology,
} from "../candidate-promotion-transaction";

const WORKER = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "helpers",
  "candidate-promotion-crash-worker.ts",
);

function fixture(name: string): {
  root: string;
  producer: string;
  topology: PromotionTopology;
} {
  const root = fs.mkdtempSync(path.join(
    os.tmpdir(), `sniper-promotion-crash-${name}-`));
  const producer = path.join(root, "producer");
  fs.mkdirSync(producer);
  fs.writeFileSync(path.join(producer, "candidate.mp4"), "new-media");
  fs.writeFileSync(path.join(producer, "candidate-audit.json"), "new-audit");
  fs.writeFileSync(path.join(producer, "final.mp4"), "old-media");
  fs.writeFileSync(path.join(producer, "audit.json"), "old-audit");
  fs.writeFileSync(path.join(producer, "edit_plan.json"), "old-plan");
  return {
    root,
    producer,
    topology: {
      scopeRoot: producer,
      transactionId: "a".repeat(64),
      recoveryRoot: path.join(producer, ".recovery"),
      reconciliationPath: path.join(producer, ".promotion-intent.json"),
      moves: [{
        source: path.join(producer, "candidate.mp4"),
        destination: path.join(producer, "final.mp4"),
      }],
      copies: [{
        source: path.join(producer, "candidate-audit.json"),
        destination: path.join(producer, "audit.json"),
      }],
      mutablePaths: [path.join(producer, "edit_plan.json")],
    },
  };
}

function crash(root: string, boundary: string): void {
  const result = spawnSync(
    process.execPath,
    ["--import", "tsx", WORKER, root, boundary],
    { encoding: "utf8" },
  );
  assert.equal(result.status, 70, result.stderr || result.stdout);
}

function assertOld(producer: string): void {
  assert.equal(fs.readFileSync(
    path.join(producer, "candidate.mp4"), "utf8"), "new-media");
  assert.equal(fs.readFileSync(
    path.join(producer, "final.mp4"), "utf8"), "old-media");
  assert.equal(fs.readFileSync(
    path.join(producer, "audit.json"), "utf8"), "old-audit");
  assert.equal(fs.readFileSync(
    path.join(producer, "edit_plan.json"), "utf8"), "old-plan");
}

function assertNew(producer: string): void {
  assert.equal(fs.existsSync(
    path.join(producer, "candidate.mp4")), false);
  assert.equal(fs.readFileSync(
    path.join(producer, "final.mp4"), "utf8"), "new-media");
  assert.equal(fs.readFileSync(
    path.join(producer, "audit.json"), "utf8"), "new-audit");
  assert.equal(fs.readFileSync(
    path.join(producer, "edit_plan.json"), "utf8"), "new-plan");
}

function recoverOld(boundary: string): void {
  const item = fixture(boundary);
  try {
    crash(item.root, boundary);
    const outcome = recoverCandidatePromotionSync(item.topology, {
      allowMutableRollback: () => true,
    });
    assert.equal(outcome, "recovered-old");
    assertOld(item.producer);
    assert.equal(fs.existsSync(
      item.topology.reconciliationPath), false);
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

function recoverNew(boundary: string): void {
  const item = fixture(boundary);
  try {
    crash(item.root, boundary);
    assert.equal(
      recoverCandidatePromotionSync(item.topology),
      "recovered-new",
    );
    assertNew(item.producer);
    assert.equal(fs.existsSync(
      item.topology.reconciliationPath), false);
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

[
  "after-intent",
  "after-backups",
  "after-transfers",
  "during-commit",
  "after-commit",
  "after-rollback-marked",
].forEach(recoverOld);
[
  "after-committed",
  "after-move-cleanup",
  "after-recovery-directory-removed",
  "after-intent-removed",
].forEach(recoverNew);
console.log("candidate promotion process-crash recovery tests passed");
