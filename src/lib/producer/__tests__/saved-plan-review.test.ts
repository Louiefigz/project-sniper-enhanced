import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, unlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { prepareSavedPlanReview } from "../../../app/api/producer/auto-edit/saved-plan-request";
import { readProjectJson } from "../../../app/api/_lib/workspace";
import { fileSha256, startAutoEditJob } from "../../server/auto-edit-job-store";

const root = mkdtempSync(path.join(os.tmpdir(), "sniper-saved-plan-review-"));
const producer = path.join(root, "producer");
const source = path.join(root, "source");
const planPath = path.join(producer, "edit_plan.json");
const manifestPath = path.join(source, "asset_manifest.json");
mkdirSync(producer);
mkdirSync(source);
writeFileSync(path.join(root, "project.json"), JSON.stringify({
  origin: "raw",
  history: [],
  intent: {
    mode: "longform",
    scope: "produced",
    lanes: {},
    brief: "Keep the proof sequence intact.",
    music: false,
    audioEnhance: { preset: "voice" },
    preset: "longform-produced",
  },
}));
writeFileSync(manifestPath, JSON.stringify({ sources: [], broll: [] }));
writeFileSync(planPath, JSON.stringify({
  planVersion: 8,
  target: { mode: "longform", pace: "talking-head" },
  cutTrack: [],
}));

try {
  const prepared = prepareSavedPlanReview(producer);
  assert.equal(prepared.resume, false);
  assert.equal(prepared.bootstrapPlanHash, fileSha256(planPath));
  assert.equal(prepared.ctx.planPath, planPath);
  assert.equal(prepared.ctx.manifestPath, manifestPath);
  assert.equal(prepared.ctx.scope, "produced");
  assert.equal(prepared.ctx.intent?.mode, "longform");
  assert.deepEqual(prepared.ctx.intent?.lanes, { broll: "off" });
  assert.equal(prepared.ctx.intent?.brief, "Keep the proof sequence intact.");
  assert.equal(prepared.ctx.intent?.music, false);
  assert.deepEqual(prepared.ctx.intent?.audioEnhance, { preset: "voice" });
  const migrated = readProjectJson(root)!;
  assert.deepEqual(migrated.requestedIntent?.lanes, {});
  assert.equal(migrated.resolvedIntent?.lanes.broll, "off");
  assert.equal(migrated.intentDecisions?.[0].status, "resolved");
  const job = startAutoEditJob({
    ctx: prepared.ctx,
    token: "saved-plan-review",
    snapshots: 0,
    bootstrapPlanHash: prepared.bootstrapPlanHash,
  });
  assert.equal(job.checkpoint, "plan_authored");
  assert.equal(job.phase, "planning_review");

  unlinkSync(planPath);
  assert.throws(
    () => prepareSavedPlanReview(producer),
    /requires a saved edit_plan\.json/,
  );
} finally {
  rmSync(root, { recursive: true, force: true });
}

console.log("saved-plan-review.test.ts: all assertions passed");
