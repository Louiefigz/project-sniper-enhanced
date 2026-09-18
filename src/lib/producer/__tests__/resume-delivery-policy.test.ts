import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { NextRequest } from "next/server";
import { resumeSavedAutoEdit, StageActionButton } from "../../../components/producer/stage-actions";
import { GET as projectStatus } from "../../../app/api/producer/project-status/route";
import type { ProjectStatus } from "../../../components/producer/use-project-status";
import type { AutoEditDeliveryPolicy } from "../auto-edit-delivery-policy";
import type { ProducerRunState } from "../project-state";
import {
  autoEditJobPath, autoEditRequestKey, interruptAutoEditJob, startAutoEditJob,
} from "../../server/auto-edit-job-store";
import {
  beginProducerRun, clearProducerRun, interruptProducerRun, producerRun,
} from "../../server/producer-run-registry";
import { fixture } from "./_auto-edit-pipeline-resume-fixture";

async function withProject(run: (root: string) => Promise<void>): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "resume-delivery-"));
  try { await run(root); } finally {
    clearProducerRun(path.join(root, "producer"));
    rmSync(root, { recursive: true, force: true });
  }
}

function interruptedJob(root: string, policy?: AutoEditDeliveryPolicy) {
  const ctx = { ...fixture(root), ...(policy ? { deliveryPolicy: policy } : {}) };
  const job = startAutoEditJob({ ctx, token: "resume-fixture", snapshots: 0 });
  interruptAutoEditJob(autoEditJobPath(ctx.dir), job.token, "fixture stopped");
  return ctx;
}

function status(deliveryPolicy?: AutoEditDeliveryPolicy): ProjectStatus {
  return {
    dir: "/workspace/project", projectRoot: "/workspace/project",
    producerDir: "/workspace/project/producer", origin: "raw",
    intent: { mode: "short", scope: "light", lanes: {} }, requestedIntent: null,
    intentDecisions: [], segments: [], clipperFiles: [], sourceDir: null, manifestPath: null,
    stages: { ingested: true, transcribed: true, plan: true, base: false, final: false },
    finalArtifact: { state: "missing", path: null, reason: null },
    palmier: { state: "no_workspace", canOpen: false, projectPath: null, projectId: null,
      timelineId: null, verified: false, authorityOrigin: null, detail: "fixture" },
    run: { kind: "auto_edit", status: "interrupted", phase: "authoring",
      startedAt: new Date().toISOString(), updatedAt: new Date().toISOString(),
      message: "stopped", events: [], ...(deliveryPolicy ? { deliveryPolicy } : {}) },
  };
}

test("status derives historical and explicit policies only from a valid durable job", async () => {
  for (const policy of [undefined, "palmier-hybrid", "mp4-only"] as const) {
    await withProject(async (root) => {
      const ctx = interruptedJob(root, policy);
      const run = producerRun(ctx.dir, { recover: false });
      assert.equal(run?.status, "interrupted");
      assert.equal(run.deliveryPolicy, policy ?? "palmier-hybrid");
      const json = JSON.parse(JSON.stringify(run));
      assert.equal(json.deliveryPolicy, policy ?? "palmier-hybrid");
      const response = await projectStatus(new NextRequest(
        `http://localhost:3000/api/producer/project-status?dir=${encodeURIComponent(ctx.dir)}&recover=0`));
      assert.equal(response.status, 200);
      assert.equal((await response.json()).run.deliveryPolicy, policy ?? "palmier-hybrid");
    });
  }
});

test("missing, invalid, and wrong-project journals cannot inherit policy from cached run state", async () => {
  for (const corruption of ["missing", "invalid-policy", "wrong-project", "invalid-hash"]) {
    await withProject(async (root) => {
      const ctx = interruptedJob(root, "palmier-hybrid");
      producerRun(ctx.dir);
      const statePath = path.join(ctx.dir, ".sniper-run-state.json");
      const cached = JSON.parse(readFileSync(statePath, "utf8"));
      writeFileSync(statePath, JSON.stringify({ ...cached, deliveryPolicy: "palmier-hybrid" }));
      const file = autoEditJobPath(ctx.dir);
      const job = JSON.parse(readFileSync(file, "utf8"));
      if (corruption === "invalid-policy") job.ctx.deliveryPolicy = "unknown";
      if (corruption === "invalid-hash") job.requestKey = "wrong-hash";
      if (corruption === "wrong-project") {
        job.ctx.dir = path.join(root, "different-project", "producer");
        job.requestKey = autoEditRequestKey(job.ctx);
      }
      if (corruption === "missing") rmSync(file);
      else writeFileSync(file, JSON.stringify(job));
      assert.equal(producerRun(ctx.dir, { recover: false })?.deliveryPolicy, undefined);
    });
  }
  await withProject(async (root) => {
    const ctx = fixture(root);
    const token = beginProducerRun(ctx.dir, "auto_edit", "authoring", "old run mirror only");
    interruptProducerRun(ctx.dir, token, "no durable job");
    assert.equal(producerRun(ctx.dir)?.deliveryPolicy, undefined);
  });
});

test("legacy resume opens Palmier and sends explicit hybrid; MP4 resume contacts only Auto Edit", async () => {
  const previous = globalThis.fetch;
  try {
    for (const policy of ["palmier-hybrid", "mp4-only"] as const) {
      const calls: { url: string; body: Record<string, unknown> }[] = [];
      globalThis.fetch = async (url, init) => {
        calls.push({ url: String(url), body: JSON.parse(String(init?.body)) });
        return new Response('data: {"event":"outputs"}\n\n', { status: 200 });
      };
      await resumeSavedAutoEdit(status(policy), () => {});
      assert.deepEqual(calls.map((call) => call.url), policy === "palmier-hybrid"
        ? ["/api/producer/palmier/view", "/api/producer/auto-edit"] : ["/api/producer/auto-edit"]);
      assert.equal(calls.at(-1)?.body.deliveryPolicy, policy);
      assert.equal(calls.at(-1)?.body.resume, true);
      assert.equal(calls.at(-1)?.body.reviewSavedPlan, undefined);
    }
  } finally { globalThis.fetch = previous; }
});

test("unknown policy and non-interrupted runs never open either editor or launch work", async () => {
  const previous = globalThis.fetch;
  globalThis.fetch = async () => assert.fail("unknown resume must not contact a service");
  try {
    const unavailable = status();
    const running = status("palmier-hybrid");
    running.run!.status = "running";
    const rendering = status("palmier-hybrid");
    rendering.run!.kind = "render";
    const invalid = status();
    invalid.run = { ...invalid.run!, deliveryPolicy: "unknown" } as unknown as ProducerRunState;
    for (const value of [unavailable, running, rendering, invalid]) {
      await assert.rejects(resumeSavedAutoEdit(value, () => {}), /saved delivery policy is unavailable/);
    }
  } finally { globalThis.fetch = previous; }
});

test("guided MP4 resume preserves explicit cut workflow and recognizes its pause without final approval", async () => {
  const previous = globalThis.fetch, calls: Record<string, unknown>[] = [];
  globalThis.fetch = async (url, init) => {
    assert.equal(String(url), "/api/producer/auto-edit");
    calls.push(JSON.parse(String(init?.body)));
    return new Response('data: {"event":"awaiting_cut_approval"}\n\n');
  };
  try {
    const guided = status("mp4-only"); guided.run!.workflowPolicy = "cut-first";
    const events: string[] = [];
    await resumeSavedAutoEdit(guided, (event) => events.push(String(event.event)));
    assert.equal(calls.length, 1); assert.equal(calls[0].workflowPolicy, "cut-first");
    assert.deepEqual(events, ["awaiting_cut_approval"]);
    guided.run!.status = "cut_accepted";
    await assert.rejects(resumeSavedAutoEdit(guided, () => {}), /saved delivery policy is unavailable/);
    assert.equal(calls.length, 1, "accepted pending continuation cannot use ordinary Resume");
  } finally { globalThis.fetch = previous; }
});

test("a rejected resume never retries fresh or changes delivery policy", async () => {
  const previous = globalThis.fetch;
  try {
    for (const policy of ["palmier-hybrid", "mp4-only"] as const) {
      const requests: Record<string, unknown>[] = [];
      globalThis.fetch = async (url, init) => {
        if (String(url).endsWith("/palmier/view")) return new Response("{}", { status: 200 });
        requests.push(JSON.parse(String(init?.body)));
        return new Response(JSON.stringify({ error: "The interrupted job does not match this request" }), { status: 409 });
      };
      await assert.rejects(resumeSavedAutoEdit(status(policy), () => {}), /does not match/);
      assert.equal(requests.length, 1);
      assert.equal(requests[0].resume, true);
      assert.equal(requests[0].deliveryPolicy, policy);
    }
  } finally { globalThis.fetch = previous; }
});

test("a failed legacy Palmier open never falls through to MP4 or creates an Auto Edit job", async () => {
  const previous = globalThis.fetch;
  const calls: string[] = [];
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    return new Response(JSON.stringify({ error: "Palmier is unavailable" }), { status: 503 });
  };
  try {
    await assert.rejects(resumeSavedAutoEdit(status("palmier-hybrid"), () => {}), /Palmier is unavailable/);
    assert.deepEqual(calls, ["/api/producer/palmier/view"]);
  } finally { globalThis.fetch = previous; }
});

test("resume buttons and captions identify the stored route and disable unknown policy", () => {
  const render = (value: ProjectStatus) => renderToStaticMarkup(
    React.createElement(StageActionButton, { status: value, onRefresh: () => {} }));
  const legacy = render(status("palmier-hybrid"));
  assert.match(legacy, /Resume legacy Palmier edit/);
  assert.match(legacy, /Legacy Palmier · original delivery policy/);
  const failed = status("palmier-hybrid");
  failed.run!.status = "failed";
  assert.match(render(failed), /Resume legacy Palmier edit/);
  const modern = render(status("mp4-only"));
  assert.match(modern, /Resume Edit/);
  assert.match(modern, /HyperFrames review · QC-approved MP4/);
  assert.doesNotMatch(modern, /Resume legacy Palmier edit/);
  const unknown = render(status());
  assert.match(unknown, /disabled=""[^>]*>[\s\S]*?Resume unavailable/);
  assert.match(unknown, /Saved policy unavailable · inspect the job journal/);
  assert.doesNotMatch(unknown, /Resume legacy Palmier edit/);
  const fresh = status();
  fresh.run = null;
  assert.match(render(fresh), /HyperFrames review · QC-approved MP4/);
  assert.doesNotMatch(render(fresh), /Resume legacy Palmier edit/);
});
