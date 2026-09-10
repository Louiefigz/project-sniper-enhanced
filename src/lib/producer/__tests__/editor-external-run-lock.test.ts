import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import {
  editorRunLockReason,
  palmierTimelineLockReason,
} from "../../../components/producer/editor/editor-view";
import type { ProjectStatus } from "../../../components/producer/use-project-status";

const source = (relative: string): string => readFileSync(path.join(process.cwd(), relative), "utf8");
const view = source("src/components/producer/editor/editor-view.tsx");
const controller = source("src/components/producer/editor/use-editor-plan-controller.ts");
const surface = source("src/components/producer/editor/editor-view-sections.tsx");
const overlay = source("src/components/producer/editor/editor-lock-overlay.tsx");
const palmierBar = source("src/components/producer/editor/palmier-bar.tsx");
const timeline = source("src/components/producer/editor/timeline.tsx");
const graphics = source("src/components/producer/editor/timeline-graphics-lane.tsx");
const transcript = source("src/components/producer/editor/transcript-panel.tsx");
const rightRail = source("src/components/producer/editor/right-rail.tsx");

assert.match(view, /useProjectStatus\(dir\)/, "editor must poll shared project run state");
assert.match(view, /status\?\.run\?\.status === "running"/);
assert.match(view, /palmierTimelineLockReason\(project\.status\)/);
assert.match(view, /onProjectStatusChanged=\{project\.refresh\}/,
  "creating or opening a managed workspace must refresh the editor lock immediately");
assert.match(controller, /args\.externalLockReason \?\? args\.palmierLockReason/);
assert.match(surface, /mutationLockReason \?\? \(editor\.ui\.aiBusy/);
assert.match(surface, /busyBlocked = externalLockReason \?\?/);
assert.match(surface, /const blocked = editor\.planState\.externalLockReason \?\?/);
assert.match(surface, /onBeforeRun=\{async \(\) => editor\.planState\.palmierLockReason/,
  "Palmier authority must not disable Ask AI or save a stale Sniper plan first");
assert.match(surface, /locked=\{editor\.planState\.editingLocked\}/);
assert.match(overlay, /Playback, seeking, and project progress remain available/);
assert.match(overlay, /Palmier review, Ask AI, and candidate QC remain available/);
assert.match(palmierBar, /onProjectStatusChanged\?\.\(\)/);
assert.match(overlay, /pointer-events-none/,
  "read-only notice must not cover playback with an interaction-blocking screen");
assert.match(timeline, /!p\.locked && splitSegmentAt/);
assert.match(graphics, /if \(p\.locked\)/);
assert.match(transcript, /locked=\{locked\}/);
assert.match(surface, /lockedReason=\{editor\.planState\.mutationLockReason\}/);
assert.match(rightRail, /lockedReason \?\? "View only while another workflow owns timeline changes\."/,
  "the rail must explain the real Palmier or background-job lock, not promise a permanent lock will finish");

const runningStatus = {
  dir: "/tmp/project/producer",
  projectRoot: "/tmp/project",
  producerDir: "/tmp/project/producer",
  origin: "raw",
  intent: null,
  requestedIntent: null,
  intentDecisions: [],
  stages: { ingested: true, transcribed: true, plan: true, base: false, final: false },
  segments: [],
  clipperFiles: [],
  sourceDir: "/tmp/project/source",
  manifestPath: "/tmp/project/source/asset_manifest.json",
  finalArtifact: { state: "missing", path: null, reason: null },
  palmier: {
    state: "no_workspace", canOpen: false, projectPath: null, projectId: null,
    timelineId: null, verified: false, authorityOrigin: null,
    detail: "No managed Palmier workspace exists yet.",
  },
  run: {
    kind: "auto_edit", status: "running", phase: "rendering",
    startedAt: "2026-07-12T10:00:00.000Z", updatedAt: "2026-07-12T10:01:00.000Z",
    message: "ffmpeg pass 1", events: [],
  },
} satisfies ProjectStatus;
assert.match(editorRunLockReason(runningStatus, null) ?? "", /rendering a private review copy/);
assert.match(editorRunLockReason(null, null) ?? "", /Checking whether/);
assert.match(editorRunLockReason(null, "offline") ?? "", /remain locked/);
assert.equal(editorRunLockReason({ ...runningStatus, run: null }, null), null);
assert.match(editorRunLockReason({ ...runningStatus,
  run: { ...runningStatus.run, status: "awaiting_cut_approval" } }, null) ?? "", /exact cut preview/);

const managedStatus = {
  ...runningStatus,
  run: null,
  palmier: {
    ...runningStatus.palmier,
    state: "manual_working_head" as const,
    canOpen: true,
    projectPath: "/tmp/example.palmier",
    projectId: "project-1",
    timelineId: "timeline-1",
  },
};
assert.match(palmierTimelineLockReason(managedStatus) ?? "", /source of truth/);
assert.equal(palmierTimelineLockReason({ ...runningStatus, run: null }), null);
assert.match(palmierTimelineLockReason({
  ...managedStatus,
  palmier: { ...managedStatus.palmier, state: "unavailable" },
}) ?? "", /cannot verify/);

console.log("editor-external-run-lock.test.ts: all assertions passed");
