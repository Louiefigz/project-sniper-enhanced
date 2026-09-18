import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { planObjectContentHash } from "../auto-edit-authority";
import { fileSha256 } from "../auto-edit-hash";
import { promoteApprovedCandidateWithRenderGraph } from
  "../current-render-graph-candidate";
import { assertApprovedProducerRevisionSync } from
  "../producer-approved-revision-authority";
import { initializeAutoEditProducerAuthoritySync } from
  "../producer-auto-edit-genesis";
import { autoEditGenesisFixture } from
  "./_producer-auto-edit-genesis-fixture";
import { stageAutoEditGraphFixture } from
  "./_producer-auto-edit-render-graph-fixture";
import { currentRenderToolchainHash } from
  "./_p2-cut-repair-rendered-promotion-fixture";
import { renderGraphPromotionCommand } from
  "./helpers/render-graph-promotion-command";
import { writeApprovalFixture } from
  "../../producer/__tests__/auto-edit-approval-fixture";

const WORKER = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "helpers",
  "render-graph-promotion-crash-worker.ts",
);

function fixture(name: string) {
  const item = autoEditGenesisFixture(name);
  fs.writeFileSync(
    `${item.candidatePath}.assembled.json`,
    JSON.stringify({
      planHash: planObjectContentHash(item.plan),
      authorityHash: fileSha256(item.candidatePath),
    }),
  );
  stageAutoEditGraphFixture({
    producer: item.producer,
    candidatePath: item.candidatePath,
    planContentHash: planObjectContentHash(item.plan)!,
    manifestHash: fileSha256(item.manifestPath)!,
    sourceSetHash: item.sourceSetHash,
    toolchainHash: currentRenderToolchainHash(),
  });
  initializeAutoEditProducerAuthoritySync(item.input);
  const record = writeApprovalFixture({
    ctx: {
      dir: item.producer,
      scope: "light",
      planPath: item.planPath,
      manifestPath: item.manifestPath,
      transcriptsDir: path.dirname(item.manifestPath),
      intent: { mode: "short", lanes: {} },
    },
    token: name,
    candidate: item.candidatePath,
  });
  fs.writeFileSync(
    path.join(item.root, "graph-promotion-record.json"),
    `${JSON.stringify(record)}\n`,
  );
  return { item, record };
}

function run(
  boundary: "after-commit" | "after-committed" | "after-move-cleanup"
  | "after-intent-removed",
): void {
  const { item, record } = fixture(boundary);
  try {
    const crashed = spawnSync(process.execPath, [
      "--import", "tsx", WORKER, item.root, item.producer,
      item.candidatePath, boundary,
    ], { encoding: "utf8", timeout: 30_000 });
    assert.equal(crashed.status, 73, crashed.stderr || crashed.stdout);
    if (boundary === "after-move-cleanup") {
      assert.equal(fs.existsSync(item.candidatePath), false);
    }
    assert.doesNotThrow(() => promoteApprovedCandidateWithRenderGraph(
      item.candidatePath, item.producer, record, {
        command: renderGraphPromotionCommand,
      }));
    assertApprovedProducerRevisionSync({
      producerDir: item.producer,
      planPath: item.planPath,
      manifestPath: item.manifestPath,
      expectedFinalHash: record.finalHash,
    });
    assert.equal(fs.existsSync(item.candidatePath), false);
    assert.equal(fs.existsSync(path.join(
      item.producer, ".sniper-qc-promotion-reconciliation.json")), false);
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

run("after-commit");
run("after-committed");
run("after-move-cleanup");
run("after-intent-removed");
console.log("render graph promotion process-crash recovery tests passed");
