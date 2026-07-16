import assert from "node:assert/strict";
import test from "node:test";
import path from "node:path";
import {
  PalmierPrimaryError,
  runPalmierPrimaryAutoEdit,
  selectPalmierPrimaryBuild,
} from "../../../app/api/producer/auto-edit/palmier-primary";
import {
  runAutoEditPipeline,
  type PipelineRuntime,
} from "../../../app/api/producer/auto-edit/pipeline";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import type {
  AutoEditJob,
  CheckpointUpdate,
} from "../../server/auto-edit-job-store";

function context(scope: AutoEditCtx["scope"] = "light"): AutoEditCtx {
  const dir = path.join("/tmp", "palmier-primary-contract", "producer");
  return {
    dir,
    scope,
    planPath: path.join(dir, "edit_plan.json"),
    manifestPath: path.join(path.dirname(dir), "source", "asset_manifest.json"),
    transcriptsDir: path.join(path.dirname(dir), "source"),
  };
}

function editableWorkspace() {
  return {
    state: "managed" as const,
    workspaceMode: "managed-draft" as const,
    assetKind: "source" as const,
  };
}

function runtime(ctx: AutoEditCtx): {
  run: PipelineRuntime;
  events: Record<string, unknown>[];
} {
  const events: Record<string, unknown>[] = [];
  const now = new Date().toISOString();
  const job = {
    version: 1,
    token: "palmier-primary-contract",
    requestKey: "request-key",
    ctx,
    status: "running",
    checkpoint: "queued",
    phase: "authoring",
    message: "queued",
    snapshots: 0,
    attempts: 1,
    requestedAt: now,
    updatedAt: now,
    logPath: path.join(ctx.dir, "auto-edit.log"),
    nextEventId: 1,
    activeEventStartId: 1,
    events: [],
  } as AutoEditJob;
  let current = job;
  const updateJob = (update: CheckpointUpdate): AutoEditJob => {
    current = { ...current, ...update };
    return current;
  };
  const run: PipelineRuntime = {
    job,
    io: {
      send: (event: Record<string, unknown>) => events.push(event),
      sendRaw: () => {},
      advance: updateJob,
      invalidate: updateJob,
    },
  };
  return { run, events };
}

test("managed rich initial builds route through the full governed plan", () => {
  const ctx = context("produced");
  ctx.intent = { music: true };
  const selected = selectPalmierPrimaryBuild(ctx, editableWorkspace);

  assert.equal(selected.kind, "governed-plan");
  if (selected.kind !== "governed-plan") return;
  assert.ok(selected.requiredLanes.includes("graphics"));
  assert.ok(selected.requiredLanes.includes("transitions"));
  assert.ok(selected.requiredLanes.includes("music"));
  assert.match(selected.message, /full transcript-grounded edit-plan/);
});

test("catalog graphics and seam transitions cannot enter the primitive native planner", () => {
  const ctx = context("produced");
  ctx.intent = { lanes: { broll: "off" }, music: false };
  const selected = selectPalmierPrimaryBuild(ctx, editableWorkspace);

  assert.equal(selected.kind, "governed-plan");
  if (selected.kind !== "governed-plan") return;
  assert.deepEqual(selected.requiredLanes, [
    "graphics", "transitions", "credibility",
  ]);
});

test("invalid managed state fails closed instead of using the flat legacy path", () => {
  const selected = selectPalmierPrimaryBuild(context(), () => ({
    state: "invalid", error: "missing editable timeline identity",
  }));

  assert.equal(selected.kind, "blocked");
  if (selected.kind !== "blocked") return;
  assert.equal(selected.code, "PALMIER_MANAGED_STATE_INVALID");
  assert.match(selected.message, /Refusing to fall back/);
});

test("legacy flat mirrors cannot masquerade as an editable source bootstrap", () => {
  const selected = selectPalmierPrimaryBuild(context(), () => ({
    state: "managed", workspaceMode: "verified-mirror",
  }));

  assert.equal(selected.kind, "blocked");
  if (selected.kind !== "blocked") return;
  assert.deepEqual(selected.unsupported, ["editable-source-bootstrap"]);
  assert.match(selected.message, /cannot truthfully recover separated edits/);
});

test("native initial Auto Edit keeps one editable candidate through QC and promotion", async () => {
  const ctx = context("light");
  const { run, events } = runtime(ctx);
  const calls: string[] = [];
  let receivedOptions: Record<string, unknown> | undefined;

  const handled = await runPalmierPrimaryAutoEdit(run, {
    classify: editableWorkspace,
    candidate: () => null,
    nativeEdit: async (input, options) => {
      calls.push("native-edit");
      receivedOptions = options as unknown as Record<string, unknown>;
      assert.equal(input.workflow, "initial-auto-edit");
      return {
        timelineId: "editable-candidate-7",
        fingerprint: "f".repeat(64),
        operationCount: 6,
      };
    },
    qc: async () => {
      calls.push("explicit-timeline-qc");
      return { status: "qc-approved", timelineId: "editable-candidate-7" };
    },
    promote: async () => {
      calls.push("promote-editable-head");
      return {
        status: "candidate-promoted",
        approvedHead: { timelineId: "editable-candidate-7" },
      };
    },
  });

  assert.equal(handled, true);
  assert.deepEqual(calls, [
    "native-edit",
    "explicit-timeline-qc",
    "promote-editable-head",
  ]);
  assert.equal(receivedOptions?.planReviewsRequired, 2);
  assert.equal(receivedOptions?.keepCandidateActive, true);
  assert.ok(events.some((event) => event.event === "candidate_promoted"
    && event.timelineId === "editable-candidate-7" && event.editable === true));
  assert.ok(events.some((event) => event.event === "outputs"
    && event.timelineId === "editable-candidate-7" && event.editable === true));
});

test("rich initial intent never starts the primitive native mutation path", async () => {
  const ctx = context("produced");
  const { run, events } = runtime(ctx);
  let mutationCalls = 0;

  const handled = await runPalmierPrimaryAutoEdit(run, {
    classify: editableWorkspace,
    candidate: () => null,
    nativeEdit: async () => {
      mutationCalls += 1;
      throw new Error("must not run");
    },
    qc: async () => {
      mutationCalls += 1;
      return {};
    },
    promote: async () => {
      mutationCalls += 1;
      return {};
    },
  });

  assert.equal(handled, false);
  assert.equal(mutationCalls, 0);
  assert.ok(events.some((event) => event.event === "palmier_governed_plan_selected"
    && Array.isArray(event.requiredLanes)
    && event.requiredLanes.includes("graphics")));
});

test("the main pipeline cannot append a flat render or final mirror after native handling", async () => {
  const { run } = runtime(context("light"));
  let legacyCalls = 0;
  const unexpected = async (): Promise<never> => {
    legacyCalls += 1;
    throw new Error("legacy flat-render path must not run");
  };

  await runAutoEditPipeline(run, {
    palmierPrimary: async (received) => {
      assert.equal(received, run);
      return true;
    },
    author: unexpected,
    planning: unexpected,
    baseGuard: unexpected,
    assemble: unexpected,
    quality: unexpected,
    checkpoint: unexpected,
    approvedMirror: unexpected,
  });

  assert.equal(legacyCalls, 0,
    "native handling must return before plan checkpoints, in-house render, or approved flat mirror");
});

test("promotion cannot substitute a different timeline for the reviewed candidate", async () => {
  const { run, events } = runtime(context("light"));

  await assert.rejects(runPalmierPrimaryAutoEdit(run, {
    classify: editableWorkspace,
    candidate: () => null,
    nativeEdit: async () => ({
      timelineId: "reviewed-editable-candidate",
      fingerprint: "a".repeat(64),
      operationCount: 3,
    }),
    qc: async () => ({
      status: "qc-approved", timelineId: "reviewed-editable-candidate",
    }),
    promote: async () => ({
      status: "candidate-promoted",
      approvedHead: { timelineId: "different-timeline" },
    }),
  }), (error: unknown) => error instanceof PalmierPrimaryError
    && error.code === "PALMIER_NATIVE_PROMOTION_MISMATCH");

  assert.equal(events.some((event) => event.event === "outputs"), false);
  assert.equal(events.some((event) => event.event === "candidate_promoted"), false);
});
