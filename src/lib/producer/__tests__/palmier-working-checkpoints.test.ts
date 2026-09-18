import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  approvedMirrorCommand,
  checkpointCommand,
  EXPORT_MIRROR_TIMEOUT_MS,
  publishApprovedPalmierMirror,
  publishPalmierWorkingCheckpoint,
  runPalmierProcess,
  WORKING_CHECKPOINT_TIMEOUT_MS,
  type PalmierProcessResult,
} from "../../../app/api/producer/auto-edit/palmier-checkpoints";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "palmier-checkpoints-"));
const ctx: AutoEditCtx = {
  dir, scope: "produced", planPath: path.join(dir, "edit_plan.json"),
  manifestPath: path.join(dir, "manifest.json"), transcriptsDir: dir,
};
const events: Record<string, unknown>[] = [];
const send = (event: Record<string, unknown>) => events.push(event);

function lastEvent(): Record<string, unknown> {
  const event = events.at(-1);
  if (!event) throw new Error("expected a checkpoint event");
  return event;
}

function writeState(value: Record<string, unknown>): void {
  fs.writeFileSync(path.join(dir, "palmier.sync.json"), JSON.stringify(value));
}

function result(event: Record<string, unknown>): PalmierProcessResult {
  return { code: 0, event, stderr: "", timedOut: false };
}

async function run(): Promise<void> {
  // Working checkpoint bound must clear the 300s media-import ceiling
  // (mcp_client.py wait_media) yet undercut the export mirror's 10-minute bound.
  assert.equal(WORKING_CHECKPOINT_TIMEOUT_MS, 6 * 60 * 1000);
  assert.equal(EXPORT_MIRROR_TIMEOUT_MS, 10 * 60 * 1000);
  assert.ok(WORKING_CHECKPOINT_TIMEOUT_MS > 300 * 1000);
  assert.ok(WORKING_CHECKPOINT_TIMEOUT_MS < EXPORT_MIRROR_TIMEOUT_MS);

  const streamed: Record<string, unknown>[] = [];
  const processResult = await runPalmierProcess([
    "-c", "print('{\"status\":\"checkpoint_ready\",\"timelineId\":\"streamed\"}')",
  ], (event) => streamed.push(event));
  assert.equal(processResult.code, 0);
  assert.equal(processResult.event.timelineId, "streamed");
  assert.equal(streamed.at(-1)?.timelineId, "streamed");

  const renderCheckpoint = checkpointCommand(ctx, {
    stage: "render", round: 2, mediaPath: "/candidate.mp4",
  });
  assert.ok(renderCheckpoint.includes("--require-source-set-admission"));
  assert.deepEqual(renderCheckpoint.slice(-6),
    ["--stage", "render", "--round", "2", "--media", "/candidate.mp4"]);
  assert.deepEqual(checkpointCommand(ctx, { stage: "cut", round: 0 }).slice(-4),
    ["--stage", "cut", "--round", "0"]);
  const mirrorCommand = approvedMirrorCommand(ctx);
  assert.ok(mirrorCommand.includes("--require-source-set-admission"));
  assert.equal(mirrorCommand.at(-1), path.join(dir, "final.palmier.mp4"));

  const absent = await publishPalmierWorkingCheckpoint(ctx, { stage: "plan", round: 0 }, send,
    async () => { throw new Error("absent workspace must not spawn"); });
  assert.equal(absent.status, "deferred");
  assert.equal(events.length, 0);

  writeState({ schemaVersion: 4, ownership: "sniper", workspaceMode: "managed-draft",
    latestTimelineId: "source" });
  const committed = await publishPalmierWorkingCheckpoint(ctx, { stage: "revision", round: 1 }, send,
    async (args, onEvent, timeoutMs) => {
      assert.equal(args.at(-1), "1");
      assert.equal(timeoutMs, WORKING_CHECKPOINT_TIMEOUT_MS);
      onEvent({ status: "checkpoint_graphic_ready" });
      onEvent({ status: "checkpoint_transition_ready", kind: "white-flash",
        fidelity: "baked", index: 0, path: "/cache/flash.mov" });
      return result({ status: "checkpoint_ready", timelineId: "revision-1",
        timelineName: "Sniper · Revision 1", omissions: [],
        limitations: [{ lane: "transitions", fidelity: "baked" }] });
    });
  assert.equal(committed.status, "committed");
  assert.equal(lastEvent().event, "palmier_checkpoint_ready");
  assert.equal(lastEvent().timelineId, "revision-1");
  assert.deepEqual(lastEvent().limitations,
    [{ lane: "transitions", fidelity: "baked" }]);
  const transitionDetail = events.find(
    (event) => event.status === "checkpoint_transition_ready");
  assert.match(String(transitionDetail?.message), /white-flash transition preview ready/);

  events.length = 0;
  const warned = await publishPalmierWorkingCheckpoint(
    ctx, { stage: "revision", round: 2 }, send,
    async () => ({
      code: 1,
      event: {
        status: "checkpoint_error",
        reason: "required graphicsTrack[0] could not be rendered and proved",
      },
      stderr: "",
      timedOut: false,
    }));
  assert.equal(warned.status, "warned");
  assert.match(String(warned.reason),
    /required graphicsTrack\[0\] could not be rendered and proved/);
  assert.equal(lastEvent().event, "palmier_checkpoint_warned");
  assert.equal(lastEvent().status, "warned");
  assert.ok(!events.some((event) => event.event === "palmier_checkpoint_failed"));
  assert.ok(!events.some((event) => event.event === "palmier_checkpoint_skipped"));

  events.length = 0;
  const hung = await publishPalmierWorkingCheckpoint(ctx, { stage: "cut", round: 1 }, send,
    async () => ({ code: 1, event: {}, stderr: "", timedOut: true }));
  assert.equal(hung.status, "warned");
  assert.match(String(hung.reason), /6-minute safety limit/);
  assert.equal(lastEvent().event, "palmier_checkpoint_warned");

  events.length = 0;
  const busy = await publishPalmierWorkingCheckpoint(ctx, { stage: "cut", round: 0 }, send,
    async () => result({ status: "checkpoint_waiting", reason: "another sync holds the lock" }));
  assert.equal(busy.status, "deferred");
  assert.equal(lastEvent().event, "palmier_checkpoint_deferred");
  assert.equal(lastEvent().status, "deferred");
  assert.match(String(lastEvent().message), /another sync holds the lock/);

  events.length = 0;
  const closed = await publishPalmierWorkingCheckpoint(ctx, { stage: "plan", round: 0 }, send,
    async () => ({
      code: 75,
      event: { status: "checkpoint_waiting", reason: "Palmier MCP unavailable" },
      stderr: "",
      timedOut: false,
    }));
  assert.equal(closed.status, "deferred");
  assert.equal(lastEvent().event, "palmier_checkpoint_deferred");

  events.length = 0;
  const superseded = await publishPalmierWorkingCheckpoint(ctx, { stage: "revision", round: 2 }, send,
    async () => result({
      status: "checkpoint_superseded",
      timelineId: "manual-head",
      fingerprint: "f".repeat(64),
      reason: "Palmier content-changed",
    }));
  assert.equal(superseded.status, "committed");
  assert.deepEqual(superseded.detail, { superseded: true, timelineId: "manual-head" });
  assert.equal(lastEvent().event, "palmier_working_head_advanced");
  assert.equal(lastEvent().timelineId, "manual-head");
  assert.equal(lastEvent().authority, "palmier");
  assert.match(String(lastEvent().message), /working source of truth/);
  assert.match(String(lastEvent().message), /Future governed AI edits/);

  events.length = 0;
  writeState({ schemaVersion: 4, ownership: "palmier", workspaceMode: "managed-draft",
    latestTimelineId: "manual" });
  const humanOwned = await publishPalmierWorkingCheckpoint(ctx, { stage: "revision", round: 2 }, send,
    async () => { throw new Error("manual workspace must not spawn"); });
  assert.equal(humanOwned.status, "deferred");
  assert.equal(lastEvent().event, "palmier_checkpoint_skipped");
  assert.match(String(lastEvent().message), /human-owned/);

  events.length = 0;
  writeState({ schemaVersion: 4, ownership: "sniper", workspaceMode: "managed-draft",
    latestTimelineId: "source" });
  await publishApprovedPalmierMirror(ctx, send,
    async (_args, _onEvent, timeoutMs) => {
      assert.equal(timeoutMs, EXPORT_MIRROR_TIMEOUT_MS);
      return result({ status: "done" });
    });
  assert.equal(lastEvent().event, "palmier_checkpoint_ready");
  assert.equal(lastEvent().stage, "qc-approved");
  assert.equal(lastEvent().verified, true);

  events.length = 0;
  await assert.rejects(
    publishApprovedPalmierMirror(ctx, send, async () => ({
      code: 1,
      event: { error: "selected component import failed" },
      stderr: "",
      timedOut: false,
    })),
    /selected component import failed/,
  );
  assert.equal(lastEvent().event, "palmier_checkpoint_failed");
  assert.ok(!events.some((event) => event.event === "palmier_checkpoint_skipped"));
}

run()
  .then(() => console.log("palmier-working-checkpoints.test.ts: all assertions passed"))
  .finally(() => fs.rmSync(dir, { recursive: true, force: true }));
