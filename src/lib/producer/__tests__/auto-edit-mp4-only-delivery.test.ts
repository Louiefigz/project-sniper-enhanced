import assert from "node:assert/strict";
import test from "node:test";
import {
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  guardAutoEditDeliveryForLaunch,
} from "../../../app/api/producer/auto-edit/launch";
import { runAutoEditPipeline } from
  "../../../app/api/producer/auto-edit/pipeline";
import {
  AUTO_EDIT_DELIVERY_POLICIES,
  parseAutoEditDeliveryPolicy,
} from "../auto-edit-delivery-policy";
import {
  autoEditRequestKey,
  failAutoEditJob,
  fileSha256,
  readAutoEditJob,
  resumableAutoEditJob,
  startAutoEditJob,
} from "../../server/auto-edit-job-store";
import {
  dependencies,
  fixture,
  runtime,
} from "./_auto-edit-pipeline-resume-fixture";

interface Mp4Harness {
  ctx: ReturnType<typeof fixture>;
  run: ReturnType<typeof runtime>;
  events: Record<string, unknown>[];
  counts: { author: number; planning: number; assemble: number; quality: number };
  deps: ReturnType<typeof dependencies>;
  rawPalmierCalls: string[];
}

function createMp4Harness(root: string): Mp4Harness {
  const ctx = { ...fixture(root), deliveryPolicy: "mp4-only" as const };
  const job = startAutoEditJob({
    ctx, token: "mp4-only-run", snapshots: 0,
    bootstrapPlanHash: "bootstrap-plan",
  });
  const events: Record<string, unknown>[] = [];
  const counts = { author: 0, planning: 0, assemble: 0, quality: 0 };
  return {
    ctx, events, counts,
    run: runtime(job, events),
    deps: dependencies(counts),
    rawPalmierCalls: [],
  };
}

function instrumentMp4Harness(harness: Mp4Harness): void {
  const { ctx, run, counts, deps, rawPalmierCalls } = harness;
  const originalPlanning = deps.planning!;
  deps.palmierPrimary = async () => {
    rawPalmierCalls.push("native-primary");
    return false;
  };
  deps.checkpoint = async (_ctx, spec) => {
    rawPalmierCalls.push(`${spec.stage}-checkpoint`);
    return { status: "committed" as const };
  };
  deps.approvedMirror = async () => {
    rawPalmierCalls.push("approved-mirror");
  };
  deps.planning = async (planningRun, overrides = {}) => {
    const checkpoint = overrides.checkpoint!;
    await checkpoint(ctx, { stage: "cut", round: 0 }, run.io.send);
    await checkpoint(ctx, { stage: "plan", round: 1 }, run.io.send);
    await checkpoint(ctx, { stage: "revision", round: 1 }, run.io.send);
    return originalPlanning(planningRun, overrides);
  };
  deps.quality = async (qualityRun, overrides = {}) => {
    counts.quality += 1;
    await overrides.checkpoint!(
      ctx, { stage: "revision", round: 2 }, run.io.send,
    );
    await overrides.renderCheckpointSettled?.();
    const finalHash = qualityRun.job.candidateHash!;
    qualityRun.job = qualityRun.io.advance({
      checkpoint: "quality_check", phase: "quality_check",
      message: "approved fixture", finalHash,
    });
    return { status: "approved" as const, finalHash };
  };
}

function assertMp4Evidence(harness: Mp4Harness): void {
  const { events, rawPalmierCalls, run } = harness;
  assert.deepEqual(rawPalmierCalls, []);
  const suppressed = events
    .filter((event) => event.event === "delivery_boundary_suppressed")
    .map((event) => event.boundary);
  for (const boundary of [
    "native-primary-selection", "cut-checkpoint", "plan-checkpoint",
    "revision-checkpoint", "render-checkpoint", "approved-mirror",
  ]) assert.ok(suppressed.includes(boundary), `missing ${boundary}`);
  assert.ok(suppressed.filter(
    (boundary) => boundary === "revision-checkpoint",
  ).length >= 2, "planning revision and QC repair must both be suppressed");
  const receiptEvent = events.find(
    (event) => event.event === "mp4_only_delivery_receipt",
  )!;
  const receipt = JSON.parse(
    readFileSync(String(receiptEvent.receiptPath), "utf8"),
  ) as Record<string, unknown>;
  assert.equal(
    fileSha256(String(receiptEvent.receiptPath)),
    receiptEvent.receiptHash,
  );
  assert.equal(
    path.basename(String(receiptEvent.receiptPath)),
    `${String(receiptEvent.receiptHash)}.json`,
  );
  assert.equal(receipt.observedPalmierAdapterCalls, 0);
  assert.equal(receipt.schemaVersion, 2);
  assert.equal(receipt.observationScope, "render-delivery-adapters");
  assert.equal(receipt.legacyLaunchPreflight, "outside-this-receipt");
  assert.equal(receipt.deliveryPolicy, "mp4-only");
  assert.deepEqual(receipt.protectedBoundaries, [
    "native-primary-selection", "cut-checkpoint",
    "plan-checkpoint", "revision-checkpoint", "render-checkpoint",
    "qc-repair-checkpoint", "approved-mirror",
  ]);
  assert.equal(receipt.requestKey, run.job.requestKey);
  assert.equal(receipt.runId, run.job.token);
  assert.equal(receipt.finalHash, run.job.finalHash);
}

test("delivery policy is closed and preserves the historical hybrid identity", () => {
  assert.deepEqual(AUTO_EDIT_DELIVERY_POLICIES, [
    "palmier-hybrid", "mp4-only",
  ]);
  assert.equal(parseAutoEditDeliveryPolicy(undefined), "palmier-hybrid");
  assert.throws(
    () => parseAutoEditDeliveryPolicy("mp4"),
    /deliveryPolicy must be one of/,
  );
  const legacy = {
    dir: "/tmp/project/producer",
    scope: "light" as const,
    planPath: "/tmp/project/producer/edit_plan.json",
    manifestPath: "/tmp/project/source/asset_manifest.json",
    transcriptsDir: "/tmp/project/source",
  };
  assert.equal(
    autoEditRequestKey(legacy),
    autoEditRequestKey({ ...legacy, deliveryPolicy: "palmier-hybrid" }),
  );
  assert.notEqual(
    autoEditRequestKey(legacy),
    autoEditRequestKey({ ...legacy, deliveryPolicy: "mp4-only" }),
  );
});

test("MP4-only launch performs no Palmier discovery or legacy guard", async () => {
  const ctx = { ...fixture(mkdtempSync(path.join(os.tmpdir(), "mp4-launch-"))),
    deliveryPolicy: "mp4-only" as const };
  let calls = 0;
  try {
    await guardAutoEditDeliveryForLaunch(ctx, {
      classify: () => {
        calls += 1;
        throw new Error("Palmier classifier must not run");
      },
      legacyGuard: async () => {
        calls += 1;
        throw new Error("Palmier guard must not run");
      },
    });
    assert.equal(calls, 0);
  } finally {
    rmSync(path.dirname(ctx.dir), { recursive: true, force: true });
  }
});

test("production MP4-only pipeline suppresses every Palmier adapter and receipts zero calls", async () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "mp4-pipeline-"));
  try {
    const harness = createMp4Harness(root);
    instrumentMp4Harness(harness);
    await runAutoEditPipeline(harness.run, harness.deps);
    assertMp4Evidence(harness);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("durable resume is delivery-bound and invalid stored values fail closed", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "mp4-resume-"));
  try {
    const ctx = { ...fixture(root), deliveryPolicy: "mp4-only" as const };
    const job = startAutoEditJob({
      ctx, token: "mp4-resume", snapshots: 0,
    });
    failAutoEditJob(
      path.join(ctx.dir, ".sniper-auto-edit-job.json"),
      job.token,
      "fixture interruption",
    );
    assert.equal(resumableAutoEditJob(ctx)?.token, job.token);
    assert.equal(resumableAutoEditJob({
      ...ctx, deliveryPolicy: "palmier-hybrid",
    }), null);
    const jobPath = path.join(ctx.dir, ".sniper-auto-edit-job.json");
    const invalid = JSON.parse(readFileSync(jobPath, "utf8"));
    invalid.ctx.deliveryPolicy = "mp4";
    writeFileSync(jobPath, JSON.stringify(invalid));
    assert.equal(readAutoEditJob(jobPath), null);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
