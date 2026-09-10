import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  planRefitReceiptPath,
  type PlanRefitReceipt,
} from "../../../app/api/_lib/plan-refit-receipt";
import {
  beginSurgicalReview,
  finalizeSurgicalEdit,
} from "../../../app/api/producer/ai-edit/finalize";
import type { ProducerReview } from
  "../../../app/api/producer/auto-edit/review-contract";

const review: ProducerReview = {
  schemaVersion: 1,
  stage: "plan",
  verdict: "pass",
  summary: "The cut candidate is coherent.",
  materialIssues: [],
  findings: [],
};

function plan(end: number): Record<string, unknown> {
  return {
    planVersion: 3,
    target: { mode: "longform" },
    cutTrack: [{ sourceId: "raw", start: 0, end, speed: 1 }],
    cutDecisions: { schemaVersion: 1, removals: [] },
    graphicsTrack: [],
  };
}

async function main(): Promise<void> {
  const dir = mkdtempSync(path.join(os.tmpdir(), "sniper-refit-rollback-"));
  const authority = path.join(dir, "edit_plan.json");
  const candidate = path.join(dir, "candidate.json");
  const manifest = path.join(dir, "asset_manifest.json");
  const previousReceipt = Buffer.from("exact prior committed refit receipt\n");
  const parentText = `${JSON.stringify(plan(10), null, 2)}\n`;
  const staged: PlanRefitReceipt = {
    schemaVersion: 2,
    transactionState: "staged",
    source: "surgical-cut",
    createdAt: "2026-01-01T00:00:00.000Z",
    inputPlanHash: "a".repeat(64),
    planHash: "b".repeat(64),
    sourceCutHash: "c".repeat(64),
    targetCutHash: "d".repeat(64),
    sourceCutTrack: (plan(10).cutTrack as unknown[]),
    targetCutTrack: (plan(9).cutTrack as unknown[]),
    remapped: 0,
    dropped: 0,
    changes: [],
  };
  try {
    writeFileSync(authority, parentText);
    writeFileSync(candidate, JSON.stringify(plan(9)));
    writeFileSync(manifest, JSON.stringify({ sources: [] }));
    writeFileSync(planRefitReceiptPath(dir), previousReceipt);
    beginSurgicalReview(dir, { lanes: ["cuts"] });
    await assert.rejects(finalizeSurgicalEdit({
      provider: "codex",
      dir,
      planPath: candidate,
      authorityPlanPath: authority,
      manifestPath: manifest,
      transcriptsDir: dir,
      request: "Trim the ending without clipping a word",
      scope: { lanes: ["cuts"] },
      originalPlanText: parentText,
      parentPlanHash: createHash("sha256").update(parentText).digest("hex"),
    }, {
      governance: async () => ({ warnings: [] }),
      critic: async () => review,
      refit: async () => staged,
      commitRefit: (receiptDir) => {
        writeFileSync(planRefitReceiptPath(receiptDir), "child refit receipt\n");
        throw new Error("injected failure after refit receipt publication");
      },
    }), /injected failure after refit receipt publication/);
    assert.deepEqual(readFileSync(planRefitReceiptPath(dir)), previousReceipt);
    assert.equal(readFileSync(authority, "utf8"), parentText);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

void main()
  .then(() => console.log("ask-edit-refit-rollback.test.ts: passed"))
  .catch((error) => { console.error(error); process.exitCode = 1; });
