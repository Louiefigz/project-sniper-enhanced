import assert from "node:assert/strict";
import {
  mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  approvePrevisualCut,
  cutAuthorityEvidence,
  cutApprovalPath,
  verifyApprovedCut,
} from "../../../app/api/producer/auto-edit/cut-approval";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";

function fixture(root: string): AutoEditCtx {
  const dir = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  const planPath = path.join(dir, "edit_plan.json");
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(path.join(source, "raw.transcript.json"), JSON.stringify({
    transcript: [{ words: [
      { word: "Hello", start: 0.2, end: 0.5 },
      { word: "world", start: 0.6, end: 1.0 },
      { word: "um", start: 1.5, end: 1.7 },
      { word: "Restart", start: 2.2, end: 2.5 },
      { word: "now", start: 2.6, end: 2.9 },
    ] }],
  }));
  writeFileSync(manifestPath, JSON.stringify({ sources: [{
    id: "raw-1", duration: 4, transcriptPath: "raw.transcript.json",
  }] }));
  writeFileSync(planPath, JSON.stringify({
    planVersion: 1,
    target: { mode: "longform", scope: "produced" },
    cutTrack: [
      { sourceId: "raw-1", start: 0, end: 1.1, speed: 1,
        rationale: "Keep the complete opening statement." },
      { sourceId: "raw-1", start: 2.1, end: 3.0, speed: 1,
        rationale: "Keep the clean restarted statement." },
    ],
    cutDecisions: { schemaVersion: 1, removals: [{
      sourceId: "raw-1", start: 1.1, end: 2.1, kind: "filler",
      rationale: "Remove the abandoned filler restart.",
      evidence: { beforeWord: "world", afterWord: "Restart", removedText: "um" },
    }] },
  }));
  return {
    dir, planPath, manifestPath, transcriptsDir: source, scope: "produced",
    intent: { mode: "longform", lanes: {} },
  };
}

async function main(): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-cut-approval-"));
  try {
    const ctx = fixture(root);
    const receipt = await approvePrevisualCut(ctx);
    assert.equal(receipt.stage, "previsual");
    assert.equal(JSON.parse(readFileSync(cutApprovalPath(ctx), "utf8")).cutTrackDigest,
      receipt.cutTrackDigest);
    assert.match(receipt.cutDecisionsDigest, /^[a-f0-9]{64}$/);
    const plan = JSON.parse(readFileSync(ctx.planPath, "utf8"));
    plan.graphicsTrack = [{ id: "g1", outStart: 0, outEnd: 2 }];
    writeFileSync(ctx.planPath, JSON.stringify(plan));
    const approved = await verifyApprovedCut(ctx);
    assert.equal(approved.ok, true);
    assert.equal(cutAuthorityEvidence(approved).cutTrackDigest, receipt.cutTrackDigest);
    const originalRationale = plan.cutDecisions.removals[0].rationale;
    plan.cutDecisions.removals[0].rationale = `${originalRationale} Changed.`;
    writeFileSync(ctx.planPath, JSON.stringify(plan));
    await assert.rejects(verifyApprovedCut(ctx), /cutDecisionsDigest changed/);
    plan.cutDecisions.removals[0].rationale = originalRationale;
    plan.cutTrack[1].start = 2.15;
    plan.cutDecisions.removals[0].end = 2.15;
    writeFileSync(ctx.planPath, JSON.stringify(plan));
    await assert.rejects(verifyApprovedCut(ctx), /cutTrackDigest changed/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("cut-approval.test.ts: all assertions passed");
}

void main();
