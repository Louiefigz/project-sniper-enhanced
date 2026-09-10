import assert from "node:assert/strict";
import test from "node:test";
import path from "node:path";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ProjectTimingDetails from "@/components/producer/project-timing-details";
import { freshJob } from "../auto-edit-job-builders";
import { summarizeJobTimings } from "../stage-timing-summary";

const epoch = Date.parse("2026-09-06T07:00:00.000Z");
const job = { ...freshJob({ token: "root", snapshots: 0, ctx: {
  dir: "/tmp/timing-fixture", planPath: path.join("/tmp/timing-fixture", "edit_plan.json"),
  manifestPath: "/tmp/timing-fixture/asset_manifest.json", transcriptsDir: "/tmp/timing-fixture",
  scope: "produced", intent: { mode: "longform" }, deliveryPolicy: "mp4-only",
} }, new Date(epoch).toISOString()), status: "treatment_admitted" as const,
updatedAt: new Date(epoch + 60_000).toISOString() };

function rows() {
  const start = { schemaVersion: 2, runId: "root", attemptId: "actual-private-execution", attemptNo: 1,
    writerId: "writer", writerPid: 1, spanId: "private", stage: "proposal_independent_critic",
    clock: "process-monotonic", event: "start", mono: 10, ts: (epoch + 70_000) / 1000 };
  return [start, { ...start, event: "end", mono: 130, ts: (epoch + 190_000) / 1000,
    elapsedMs: 120_000, status: "failed" }];
}
const raw = (values: unknown[]) => values.map((value) => JSON.stringify(value)).join("\n");

test("failed private activity after journal CAS is visible without inventing a new job wall clock", () => {
  const report = summarizeJobTimings(raw(rows()), job, epoch + 200_000);
  assert.equal(report.wallMs, 60_000);
  assert.deepEqual(report.observedActivity, { throughAt: new Date(epoch + 190_000).toISOString(), sinceRequestMs: 190_000 });
  assert.equal(report.stages[0].failed, 1);
  const html = renderToStaticMarkup(createElement(ProjectTimingDetails, { report }));
  assert.match(html, /Recorded work extends to 3m 10s/);
  assert.match(html, /lower bound, not total active time or confirmed running work/);
});

test("unclosed private activity is not declared stopped or confirmed running", () => {
  const report = summarizeJobTimings(raw(rows().slice(0, 1)), job, epoch + 200_000);
  assert.equal(report.observedActivity?.sinceRequestMs, 70_000);
  assert.equal(report.openSpans, 0); assert.equal(report.incompleteSpans, 1);
  const html = renderToStaticMarkup(createElement(ProjectTimingDetails, { report }));
  assert.match(html, /may be active, interrupted or lost/);
  assert.doesNotMatch(html, /unfinished span\(s\) from stopped attempts/);
});

test("foreign, duplicate, future and wall-clock inconsistent activity cannot extend the observed window", () => {
  const input = rows();
  const cases = [input.map((row) => ({ ...row, runId: "foreign" })), [...input, input[1]],
    input.map((row) => ({ ...row, ts: row.ts + 1000 })),
    [input[0], { ...input[1], ts: input[0].ts - 1 }]];
  for (const values of cases) assert.equal(summarizeJobTimings(raw(values), job, epoch + 200_000).observedActivity, undefined);
});
