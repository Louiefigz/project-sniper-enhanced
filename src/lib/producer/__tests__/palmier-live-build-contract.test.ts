import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { buildLiveBuildArgs } from "../../../app/api/producer/live-build/args";
import { isLiveBuildMutationTool } from "../../../app/api/producer/live-build/process";
import { recordLiveBuildOperation } from "../../../app/api/producer/live-build/runner";
import { buildLiveBuildPrompt } from "../../../app/api/producer/live-build/prompt";
import {
  liveBuildParentTimeline,
  type LiveBuildPreflight,
} from "../../../app/api/producer/live-build/preflight";
import type { LiveBuildState } from "../../../app/api/producer/live-build/state";
import {
  appendLiveBuildJournal,
  liveBuildJournalPath,
  prepareLiveBuildState,
  readLiveBuildJournal,
} from "../../../app/api/producer/live-build/state";
import { palmierOpEvents } from "../palmier-op-event";

const args = buildLiveBuildArgs({
  prompt: "execute", sessionId: "session-1", resume: true,
  readDirs: ["/tmp/project"],
});
const allowed = args[args.indexOf("--allowedTools") + 1].split(",");
assert.deepEqual(args.slice(args.indexOf("--resume"), args.indexOf("--resume") + 2),
  ["--resume", "session-1"]);
assert.ok(allowed.includes("Skill(producer)"));
assert.ok(allowed.includes("mcp__palmier-pro__import_media"));
assert.ok(allowed.includes("mcp__palmier-pro__add_clips"));
assert.ok(allowed.includes("mcp__palmier-pro__add_texts"));
assert.equal(allowed.includes("mcp__palmier-pro__new_project"), false);
assert.equal(allowed.includes("mcp__palmier-pro__open_project"), false);
assert.equal(allowed.includes("mcp__palmier-pro__export_project"), false);
assert.equal(args.includes("--safe-mode"), false);
assert.equal(isLiveBuildMutationTool("add_texts"), true);
assert.equal(isLiveBuildMutationTool("get_timeline"), false);

const repairPrompt = buildLiveBuildPrompt({
  dir: "/tmp/project/producer", planPath: "/tmp/project/producer/edit_plan.json",
  planHash: "a".repeat(64), manifestPath: "/tmp/project/source/asset_manifest.json",
  doctrineHash: "b".repeat(64), doctrineFiles: {}, ctx: {} as never,
  planningReviews: [], projectId: "project", projectPath: "/tmp/project.palmier",
  timelineId: "candidate", timelineFingerprint: "c".repeat(64), timeline: {},
  qcFailure: { lens: "composition", materialIssues: [{ message: "White frame" }],
    evidencePaths: ["/tmp/project/frame.png"], candidateFingerprint: "d".repeat(64),
    message: "composition rejected", failedAt: "2026-07-13T00:00:00Z" },
} satisfies LiveBuildPreflight, true);
assert.match(repairPrompt, /White frame/);
assert.match(repairPrompt, /Repair only the failed operations or lane/);

const retained = {
  schemaVersion: 1, runId: "run", sessionId: "session", sessionEstablished: true,
  planHash: "a".repeat(64), doctrineHash: "b".repeat(64), projectId: "project",
  projectPath: "/tmp/project.palmier", parentTimelineId: "parent",
  parentFingerprint: "c".repeat(64), candidateTimelineId: "candidate",
  latestFingerprint: "d".repeat(64), status: "qc_failed",
  operationsSeen: 1, operationsCompleted: 1,
  startedAt: "2026-07-13T00:00:00Z", updatedAt: "2026-07-13T00:00:01Z",
} satisfies LiveBuildState;
assert.equal(liveBuildParentTimeline({ kind: "pending-candidate",
  timelineId: "candidate" }, retained, true), "parent");
assert.throws(() => liveBuildParentTimeline({ kind: "working-draft",
  timelineId: "parent" }, retained, true), /not the current governed/);

const events = palmierOpEvents({ message: { content: [{
  type: "tool_use", id: "op-1", name: "mcp__palmier-pro__add_texts",
  input: { entries: [{ content: "Proof" }] },
}, {
  type: "tool_result", tool_use_id: "op-1", content: "ok",
}] } }, 1234);
assert.deepEqual(events.map((event) => [event.event, event.status]), [
  ["palmier_op", "applying"], ["palmier_op_result", "applied"],
]);

const dir = mkdtempSync(path.join(os.tmpdir(), "sniper-live-state-"));
try {
  let state = prepareLiveBuildState({
    dir, planHash: "a".repeat(64), doctrineHash: "b".repeat(64),
    projectId: "project", projectPath: "/tmp/project.palmier",
    parentTimelineId: "parent", parentFingerprint: "c".repeat(64),
    candidateTimelineId: "candidate", candidateFingerprint: "d".repeat(64),
  }, false);
  assert.equal(state.status, "running");
  appendLiveBuildJournal(dir, { event: "palmier_op", operationId: "large",
    input: { content: "x".repeat(30_000) }, status: "applying" });
  const journal = readLiveBuildJournal(dir);
  assert.equal(journal.length, 1);
  assert.match(String(journal[0].payloadHash), /^[0-9a-f]{64}$/);
  const mutations = new Set<string>();
  state = recordLiveBuildOperation(dir, state, {
    event: "palmier_op", operationId: "ok", tool: "add_texts",
    status: "applying", elapsedMs: 10,
  }, mutations);
  state = recordLiveBuildOperation(dir, state, {
    event: "palmier_op_result", operationId: "ok",
    status: "applied", elapsedMs: 20,
  }, mutations);
  state = recordLiveBuildOperation(dir, state, {
    event: "palmier_op", operationId: "failed", tool: "add_clips",
    status: "applying", elapsedMs: 30,
  }, mutations);
  state = recordLiveBuildOperation(dir, state, {
    event: "palmier_op_result", operationId: "failed",
    status: "failed", elapsedMs: 40,
  }, mutations);
  assert.deepEqual([state.operationsSeen, state.operationsCompleted], [2, 1]);
  assert.doesNotThrow(() => JSON.parse(readFileSync(liveBuildJournalPath(dir), "utf8")));
} finally {
  rmSync(dir, { recursive: true, force: true });
}

console.log("palmier-live-build-contract.test.ts: all assertions passed");
