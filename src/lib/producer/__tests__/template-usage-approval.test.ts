import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  assertTemplateUsageApprovalCurrent,
  clearTemplateUsageApproval,
  templateUsageApprovalPath,
  writeTemplateUsageApproval,
} from "@/lib/server/template-usage-approval";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";

function digest(value: unknown): string {
  return canonicalJsonSha256(value);
}

function writeJson(destination: string, value: unknown): void {
  writeFileSync(destination, `${JSON.stringify(value, null, 2)}\n`);
}

function fixture() {
  const root = mkdtempSync(path.join(os.tmpdir(), "template-usage-approval-"));
  const producerDir = path.join(root, "producer");
  const sourceDir = path.join(root, "source");
  const historyDir = path.join(producerDir, ".sniper-learning", "runs", "r1");
  mkdirSync(historyDir, { recursive: true });
  mkdirSync(sourceDir);
  writeJson(path.join(root, "project.json"), {
    origin: "raw", history: [],
    resolvedIntent: { mode: "longform", scope: "produced", lanes: {} },
  });
  const planPath = path.join(producerDir, "edit_plan.json");
  const manifestPath = path.join(sourceDir, "asset_manifest.json");
  const transcriptPath = path.join(sourceDir, "raw.transcript.json");
  const historyPath = path.join(historyDir, "template-usage.json");
  writeJson(planPath, { target: { mode: "longform", scope: "produced" },
    cutTrack: [], graphicsDecisions: [] });
  writeJson(transcriptPath, { words: [] });
  writeJson(manifestPath, { sources: [{ id: "raw", transcriptPath: "raw.transcript.json" }] });
  const historyCore = {
    schemaVersion: 1, kind: "producer-template-usage-history", mode: "longform",
    windowProjects: 8, projectCount: 0, projects: [], counts: {}, overusedKinds: [],
    policy: { minProjects: 3, minProjectShare: 0.5 },
  };
  const historyDigest = digest(historyCore);
  writeJson(historyPath, { ...historyCore, digest: historyDigest });
  return { root, producerDir, sourceDir, planPath, manifestPath, historyPath, historyDigest };
}

function currentReceiptPassesAndBindsEveryInput(): void {
  const item = fixture();
  try {
    writeTemplateUsageApproval({
      producerDir: item.producerDir, planPath: item.planPath,
      manifestPath: item.manifestPath, transcriptsDir: item.sourceDir,
      templateUsage: { schemaVersion: 1, path: item.historyPath, digest: item.historyDigest },
      verdict: { ok: true, metrics: { snapshotDigest: item.historyDigest } },
      operatorIntentVerdict: { ok: true },
    });
    assert.doesNotThrow(() => assertTemplateUsageApprovalCurrent({
      producerDir: item.producerDir, planPath: item.planPath,
      manifestPath: item.manifestPath, transcriptsDir: item.sourceDir,
    }));
    writeJson(item.planPath, { target: { mode: "longform", scope: "produced" },
      cutTrack: [{ sourceId: "raw", start: 0, end: 1 }], graphicsDecisions: [] });
    assert.throws(() => assertTemplateUsageApprovalCurrent({
      producerDir: item.producerDir, planPath: item.planPath,
      manifestPath: item.manifestPath, transcriptsDir: item.sourceDir,
    }), /stale/);
  } finally { rmSync(item.root, { recursive: true, force: true }); }
}

function missingReceiptFailsOnlyGovernedDelivery(): void {
  const item = fixture();
  try {
    clearTemplateUsageApproval(item.producerDir);
    assert.throws(() => assertTemplateUsageApprovalCurrent({
      producerDir: item.producerDir, planPath: item.planPath,
      manifestPath: item.manifestPath,
    }), /review the saved plan first/);
    writeJson(path.join(item.root, "project.json"), {
      origin: "raw", history: [],
      resolvedIntent: { mode: "longform", scope: "light", lanes: {} },
    });
    writeJson(item.planPath, { target: { mode: "longform", scope: "light" } });
    assert.doesNotThrow(() => assertTemplateUsageApprovalCurrent({
      producerDir: item.producerDir, planPath: item.planPath,
      manifestPath: item.manifestPath,
    }));
    assert.equal(templateUsageApprovalPath(item.producerDir).endsWith(
      ".sniper-template-usage-approved.json"), true);
  } finally { rmSync(item.root, { recursive: true, force: true }); }
}

function mutablePlanCannotWaiveStoredGraphicsIntent(): void {
  const item = fixture();
  try {
    clearTemplateUsageApproval(item.producerDir);
    writeJson(item.planPath, {
      target: { mode: "longform", scope: "produced", lanes: { graphics: "off" } },
    });
    assert.throws(() => assertTemplateUsageApprovalCurrent({
      producerDir: item.producerDir, planPath: item.planPath,
      manifestPath: item.manifestPath,
    }), /review the saved plan first/);
  } finally { rmSync(item.root, { recursive: true, force: true }); }
}

currentReceiptPassesAndBindsEveryInput();
missingReceiptFailsOnlyGovernedDelivery();
mutablePlanCannotWaiveStoredGraphicsIntent();
console.log("template-usage-approval.test.ts: all assertions passed");
