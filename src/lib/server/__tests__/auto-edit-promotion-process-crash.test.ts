import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { planContentHash } from "../auto-edit-authority";
import { fileSha256 } from "../auto-edit-hash";
import {
  candidateFinalPath,
  prepareQcRound,
  promoteApprovedCandidate,
  readApproval,
} from "../auto-edit-quality-artifacts";
import { writeApprovalFixture } from
  "../../producer/__tests__/auto-edit-approval-fixture";

const WORKER = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "helpers",
  "auto-edit-promotion-crash-worker.ts",
);

function fixture(name: string) {
  const root = fs.mkdtempSync(path.join(
    os.tmpdir(), `sniper-auto-promotion-crash-${name}-`));
  const producer = path.join(root, "producer");
  const source = path.join(root, "source");
  fs.mkdirSync(source, { recursive: true });
  prepareQcRound(producer, name, 1);
  const planPath = path.join(producer, "edit_plan.json");
  const manifestPath = path.join(source, "manifest.json");
  fs.writeFileSync(planPath, '{"planVersion":1,"cutTrack":[]}');
  fs.writeFileSync(manifestPath, '{"sources":[]}');
  const candidate = candidateFinalPath(producer, name, 1);
  fs.writeFileSync(candidate, "candidate-media");
  const candidateHash = fileSha256(candidate)!;
  fs.writeFileSync(`${candidate}.assembled.json`, JSON.stringify({
    planHash: planContentHash(planPath),
    authorityHash: candidateHash,
  }));
  const record = writeApprovalFixture({
    ctx: {
      dir: producer,
      scope: "light",
      planPath,
      manifestPath,
      transcriptsDir: source,
    },
    token: name,
    candidate,
    qcRound: 1,
  });
  fs.writeFileSync(path.join(producer, "final.mp4"), "old-media");
  fs.writeFileSync(path.join(producer, "final.proxy.mp4"), "old-proxy");
  fs.writeFileSync(
    path.join(producer, "graphics_placements.json"), "old-graphics");
  fs.writeFileSync(
    path.join(root, "approval-record.json"),
    `${JSON.stringify(record)}\n`,
  );
  return { root, producer, candidate, record, candidateHash };
}

function run(
  boundary: "after-committed" | "after-move-cleanup"
  | "after-intent-removed",
): void {
  const item = fixture(boundary);
  try {
    const crashed = spawnSync(
      process.execPath,
      ["--import", "tsx", WORKER, item.root, item.candidate, boundary],
      { encoding: "utf8" },
    );
    assert.equal(crashed.status, 71, crashed.stderr || crashed.stdout);
    if (["after-move-cleanup", "after-intent-removed"].includes(boundary)) {
      assert.equal(fs.existsSync(item.candidate), false);
    }
    assert.doesNotThrow(() => promoteApprovedCandidate(
      item.candidate, item.producer, item.record));
    assert.equal(
      fileSha256(path.join(item.producer, "final.mp4")),
      item.candidateHash,
    );
    assert.equal(fs.existsSync(item.candidate), false);
    assert.equal(
      fs.existsSync(path.join(item.producer, "final.proxy.mp4")), false);
    assert.equal(
      fs.existsSync(
        path.join(item.producer, "graphics_placements.json")), false);
    assert.ok(readApproval(item.producer));
    assert.equal(fs.existsSync(path.join(
      item.producer, ".sniper-qc-promotion-reconciliation.json")), false);
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

run("after-committed");
run("after-move-cleanup");
run("after-intent-removed");
console.log("auto-edit promotion process-crash replay tests passed");
