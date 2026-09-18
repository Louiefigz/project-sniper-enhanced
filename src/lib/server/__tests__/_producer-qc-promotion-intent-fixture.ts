import fs from "node:fs";
import path from "node:path";
import { planObjectContentHash } from "../auto-edit-authority";
import type { ApprovalRecord } from "../auto-edit-approval";
import { approvalPath } from "../auto-edit-quality-artifacts";
import { canonicalJsonSha256, fileSha256 } from "../auto-edit-hash";
import {
  observeCurrentRenderGraphAuthoritySync,
  type CurrentRenderGraphAuthority,
} from "../current-render-graph-authority";
import {
  initializeAutoEditProducerAuthoritySync,
} from "../producer-auto-edit-genesis";
import {
  prepareProducerQcPromotionSync,
  type ProducerQcPromotionPreparation,
} from "../producer-qc-promotion";
import { observeStagedRenderGraphAuthoritySync } from
  "../staged-render-graph-authority";
import {
  autoEditGenesisFixture,
  type AutoEditGenesisFixture,
} from "./_producer-auto-edit-genesis-fixture";
import { writeApprovalFixture } from
  "../../producer/__tests__/auto-edit-approval-fixture";

export interface QcPromotionIntentFixture {
  genesis: AutoEditGenesisFixture;
  approval: ApprovalRecord;
  preparation: ProducerQcPromotionPreparation;
}

function writeJson(filePath: string, value: unknown): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(value)}\n`);
}

function writeAssemblyProof(item: AutoEditGenesisFixture): void {
  fs.writeFileSync(`${item.candidatePath}.assembled.json`, JSON.stringify({
    planHash: planObjectContentHash(item.plan),
    authorityHash: fileSha256(item.candidatePath),
  }));
}

function approval(item: AutoEditGenesisFixture, name: string): ApprovalRecord {
  return writeApprovalFixture({
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
}

export function preparedQcPromotionIntentFixture(
  name: string,
): QcPromotionIntentFixture {
  const genesis = autoEditGenesisFixture(name);
  writeAssemblyProof(genesis);
  initializeAutoEditProducerAuthoritySync(genesis.input);
  const record = approval(genesis, name);
  const staged = observeStagedRenderGraphAuthoritySync({
    producerDir: genesis.producer,
    candidatePath: genesis.candidatePath,
    expectedCandidateHash: record.finalHash,
  });
  const preparation = prepareProducerQcPromotionSync(genesis.producer, {
    graphHash: staged.graphHash,
    approval: record,
  });
  return { genesis, approval: record, preparation };
}

function promotedReceipt(
  item: QcPromotionIntentFixture,
  finalPath: string,
): { graphHash: string; receiptHash: string } {
  const staged = observeStagedRenderGraphAuthoritySync({
    producerDir: item.genesis.producer,
    candidatePath: item.genesis.candidatePath,
    expectedCandidateHash: item.approval.finalHash,
  });
  const generation = path.join(
    item.genesis.producer,
    ".render-graph-v1",
    "generations",
    staged.graphHash,
  );
  const receiptPath = path.join(
    generation, "receipts", `${staged.receiptHash}.json`);
  const receipt = JSON.parse(
    fs.readFileSync(receiptPath, "utf8")) as Record<string, unknown>;
  const artifacts = receipt.artifacts as Array<Record<string, unknown>>;
  receipt.artifacts = artifacts.map((row) =>
    row.nodeId === "node-final" ? { ...row, path: finalPath } : row);
  const receiptHash = canonicalJsonSha256(receipt);
  writeJson(
    path.join(generation, "receipts", `${receiptHash}.json`),
    receipt,
  );
  return { graphHash: staged.graphHash, receiptHash };
}

/** Apply the exact live media/graph/approval boundary preceding revision CAS. */
export function publishQcPromotionLiveState(
  item: QcPromotionIntentFixture,
): CurrentRenderGraphAuthority {
  const finalPath = path.join(item.genesis.producer, "final.mp4");
  const graph = promotedReceipt(item, finalPath);
  fs.renameSync(item.genesis.candidatePath, finalPath);
  fs.renameSync(
    `${item.genesis.candidatePath}.assembled.json`,
    `${finalPath}.assembled.json`,
  );
  writeJson(
    path.join(item.genesis.producer, ".render-graph-v1", "ACTIVE.json"),
    { schemaVersion: 1, ...graph },
  );
  fs.writeFileSync(
    approvalPath(item.genesis.producer),
    `${JSON.stringify(item.approval, null, 2)}\n`,
  );
  return observeCurrentRenderGraphAuthoritySync({
    producerDir: item.genesis.producer,
    expectedGraphHash: graph.graphHash,
    expectedFinalHash: item.approval.finalHash,
  });
}

export function cleanQcPromotionIntentFixture(
  item: QcPromotionIntentFixture,
): void {
  fs.rmSync(item.genesis.root, { recursive: true, force: true });
}
