import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { linkSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ProjectTimingDetails from "@/components/producer/project-timing-details";
import { timingDuration } from "@/lib/producer/run-timing";
import { freshJob, resumedJob } from "../auto-edit-job-builders";
import { autoEditJobPath, writeJobUnlocked } from "../auto-edit-job-persistence";
import { projectRunTimings, summarizeJobTimings } from "../stage-timing-summary";
import { timedStage, stageTimingsPath } from "../stage-timing";
import { stageTimingEnv, withStageTimingContext } from "../stage-timing-context";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { NextRequest } from "next/server";
import { GET as projectStatus } from "@/app/api/producer/project-status/route";

type Row = Record<string, unknown>;
const epoch = "2026-09-06T07:00:00.000Z";
const later = "2026-09-06T07:10:00.000Z";
const ctx = (dir: string): AutoEditCtx => ({ dir, planPath: path.join(dir, "edit_plan.json"),
  manifestPath: path.join(dir, "asset_manifest.json"), transcriptsDir: dir,
  scope: "produced", intent: { mode: "longform" }, deliveryPolicy: "mp4-only" });
const job = (dir = "/tmp/test") => freshJob({ ctx: ctx(dir), token: "a", snapshots: 0 }, epoch);
const raw = (rows: Row[]) => rows.map((row) => JSON.stringify(row)).join("\n");
function pair(spanId: string, elapsedMs: number, overrides: Row = {}): Row[] {
  const start = { schemaVersion: 2, runId: "a", attemptId: "a", attemptNo: 1,
    writerId: "writer", writerPid: 1, spanId, stage: "critic", clock: "process-monotonic",
    ts: 100, mono: 10, ...overrides, event: "start" };
  return [start, { ...start, event: "end", mono: Number(start.mono) + elapsedMs / 1000,
    ts: Number(start.ts) + elapsedMs / 1000, elapsedMs, status: "completed" }];
}

function pairTests(): void {
  const a = pair("a", 5000), b = pair("b", 7000);
  const rows = [a[0], b[0], a[1], b[1]];
  const report = summarizeJobTimings(raw(rows), job(), Date.parse(later));
  assert.equal(report.wallMs, 600_000);
  assert.equal(report.stages[0].inclusiveMs, 12_000);
  assert.equal(report.stages[0].calls, 2);
  assert.equal(report.coverage, "partial-instrumentation");
  const duplicate = summarizeJobTimings(raw([...a, a[1]]), job());
  assert.equal(duplicate.invalidRows, 1);
  assert.equal(duplicate.stages.length, 0, "a later duplicate must invalidate the first apparent pair");
  for (const field of ["stage", "attemptNo", "parentSpanId", "writerPid", "clock", "elapsedMs", "status"]) {
    const changed = pair("bad", 1000);
    changed[1][field] = "invalid";
    const result = summarizeJobTimings(raw(changed), job());
    assert.ok(result.invalidRows, field);
    assert.equal(result.stages.length, 0, field);
  }
  const other = pair("a", 500, { runId: "unrelated" });
  const filtered = summarizeJobTimings(raw([...a, ...other]), job());
  assert.equal(filtered.stages[0].calls, 1);
  assert.equal(filtered.invalidRows, 0);
  assert.equal(summarizeJobTimings(raw([a[1], a[0]]), job()).invalidRows, 1);
}

function resumeAndClockTests(): void {
  const old = { ...job(), status: "failed" as const, updatedAt: later };
  const current = resumedJob({ ctx: old.ctx, token: "b", snapshots: 0, resume: old }, old, later);
  const first = pair("first", 3000);
  first[1].status = "failed";
  const second = pair("second", 4000, { attemptId: "b", attemptNo: 2 });
  second[1].status = "interrupted";
  const rows = [...first, ...second, pair("lost", 0)[0], pair("open", 0, { attemptId: "b", attemptNo: 2 })[0]];
  const result = summarizeJobTimings(raw(rows), current, Date.parse(later) + 1000);
  assert.equal(result.wallMs, 601_000, "resume must retain original job wall start");
  assert.equal(result.attempts, 2);
  assert.equal(result.openSpans, 1);
  assert.equal(result.incompleteSpans, 1);
  assert.equal(result.stages[0].failed, 1);
  assert.equal(result.stages[0].interrupted, 1);
  const stopped = summarizeJobTimings(raw(first), old, Date.parse(later) + 999_999);
  assert.equal(stopped.wallMs, 600_000, "stopped display must freeze instead of aging forever");
  const changedClock = pair("clock", 1000);
  changedClock[1].ts = 90;
  const changed = summarizeJobTimings(raw(changedClock), current, 0);
  assert.equal(changed.wallMs, null);
  assert.equal(changed.clockWarnings, 2);
  assert.equal(changed.stages[0].inclusiveMs, 1000, "same-writer monotonic evidence survives wall-clock change");
}

function malformedAndUiTests(): void {
  const report = summarizeJobTimings('null\n{}\n{broken\n' + raw([
    { stage: "old", mono: 1, event: "start" }, ...pair("ok", 4000)]), job());
  assert.equal(report.invalidRows, 3);
  assert.equal(report.legacyRows, 1);
  assert.equal(report.stages[0].inclusiveMs, 4000);
  assert.equal(summarizeJobTimings("x".repeat(4 * 1024 * 1024 + 1), job()).state, "unavailable");
  assert.equal(summarizeJobTimings("\n".repeat(20_001), job()).state, "unavailable");
  const html = renderToStaticMarkup(createElement(ProjectTimingDetails, { report }));
  assert.match(html, /partial instrumentation/);
  assert.match(html, /do not add them as total elapsed time/);
  assert.match(html, /does not mean QC passed/);
  assert.equal(timingDuration(null), "unavailable");
  assert.equal(timingDuration(7_200_000), "2h 0m");
}

async function realWriterTests(dir: string): Promise<void> {
  const current = job(dir);
  const childDir = path.join(dir, "base_work");
  mkdirSync(childDir);
  await withStageTimingContext({ runId: "a", attemptId: "a", attemptNo: 1 }, () =>
    timedStage(dir, "worker_run", async () => {
      const python = spawnSync(path.resolve(".venv/bin/python"), ["-c",
        "import sys; sys.path.insert(0, sys.argv[1]); from stage_timing import stage_span\n"
        + "with stage_span(sys.argv[2], 'actual_python'): pass", path.resolve("scripts/producer"), childDir],
      { env: stageTimingEnv(), encoding: "utf8" });
      assert.equal(python.status, 0, python.stderr);
    }));
  const content = [dir, childDir].map((source) => readFileSync(stageTimingsPath(source), "utf8")).join("\n");
  const report = summarizeJobTimings(content, current);
  assert.equal(report.invalidRows, 0);
  assert.equal(report.stages.length, 2);
  const joined = path.join(dir, "joined-timings.jsonl");
  writeFileSync(joined, content);
  const oracle = spawnSync(path.resolve(".venv/bin/python"), ["scripts/producer/stage_timing_report.py", joined], { encoding: "utf8" });
  assert.equal(oracle.status, 0, oracle.stderr);
  const expected = JSON.parse(oracle.stdout).stagesInclusiveMs;
  for (const stage of report.stages) assert.ok(Math.abs(stage.inclusiveMs - expected[stage.stage]) < 0.001);
  writeJobUnlocked(autoEditJobPath(dir), current);
  assert.equal(projectRunTimings(dir)?.stages.length, 2);
  const before = readFileSync(autoEditJobPath(dir));
  assert.equal(projectRunTimings(dir)?.coverage, "partial-instrumentation");
  assert.deepEqual(readFileSync(autoEditJobPath(dir)), before, "report is read-only");
  const response = await projectStatus(new NextRequest(
    `http://localhost/api/producer/project-status?recover=0&dir=${encodeURIComponent(dir)}`));
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.timing.stages.length, 2, "actual status route exposes the measurements");
  assert.equal(body.timing.scope, "auto-edit-job");
  assert.deepEqual(body.timing.sources.map((source: { state: string }) => source.state), ["read", "read"]);
}

function fileTests(dir: string): void {
  rmSync(stageTimingsPath(dir));
  rmSync(stageTimingsPath(path.join(dir, "base_work")));
  assert.equal(projectRunTimings(dir)?.state, "unavailable");
  const target = path.join(dir, "target");
  writeFileSync(target, "do not read");
  symlinkSync(target, stageTimingsPath(dir));
  assert.equal(projectRunTimings(dir)?.state, "unavailable");
  rmSync(stageTimingsPath(dir));
  writeFileSync(stageTimingsPath(dir), Buffer.from([0xff]));
  assert.equal(projectRunTimings(dir)?.state, "unavailable");
  const wrong = job("/wrong/project");
  writeJobUnlocked(autoEditJobPath(dir), wrong);
  assert.equal(projectRunTimings(dir), null);
  rmSync(autoEditJobPath(dir));
  assert.equal(projectRunTimings(dir), null);
}

function sourceFixture(base: string, name: string): string {
  const dir = path.join(base, name);
  mkdirSync(path.join(dir, "base_work"), { recursive: true });
  writeJobUnlocked(autoEditJobPath(dir), job(dir));
  return dir;
}

function splitSourceTests(base: string): void {
  const dir = sourceFixture(base, "split");
  const stopped = { ...job(dir), status: "failed" as const, updatedAt: later };
  writeJobUnlocked(autoEditJobPath(dir), resumedJob(
    { ctx: stopped.ctx, token: "b", snapshots: 0, resume: stopped }, stopped, later));
  const failed = pair("old", 3000);
  failed[1].status = "failed";
  const child = pair("child", 4000, { attemptId: "b", attemptNo: 2, stage: "master" });
  writeFileSync(stageTimingsPath(dir), raw(failed) + '\n{"unfinished":');
  writeFileSync(stageTimingsPath(path.join(dir, "base_work")), raw([
    ...child, ...pair("foreign", 50_000, { runId: "another-job" })]));
  const report = projectRunTimings(dir)!;
  assert.deepEqual(report.sources.map((source) => source.state), ["read", "read"]);
  assert.equal(report.stages.find((stage) => stage.stage === "critic")?.failed, 1);
  assert.equal(report.stages.find((stage) => stage.stage === "master")?.inclusiveMs, 4000);
  assert.equal(report.invalidRows, 1, "unterminated root JSON must not consume the child row");
  assert.equal(report.stages.reduce((sum, stage) => sum + stage.calls, 0), 2);
  writeFileSync(stageTimingsPath(dir), raw([child[0]]));
  writeFileSync(stageTimingsPath(path.join(dir, "base_work")), raw([child[1]]));
  assert.equal(projectRunTimings(dir)?.stages[0].inclusiveMs, 4000, "pair globally across journal boundaries");
  writeFileSync(stageTimingsPath(path.join(dir, "base_work")), raw(child));
  const duplicate = projectRunTimings(dir)!;
  assert.equal(duplicate.stages.length, 0, "cross-source duplicates poison rather than double-count");
  assert.equal(duplicate.invalidRows, 1);
}

function sourceCoverageTests(base: string): void {
  const dir = sourceFixture(base, "coverage");
  const child = stageTimingsPath(path.join(dir, "base_work"));
  writeFileSync(stageTimingsPath(dir), raw(pair("root", 1000)));
  let report = projectRunTimings(dir)!;
  assert.equal(report.sources[1].state, "missing");
  assert.equal(report.stages.length, 1);
  let html = renderToStaticMarkup(createElement(ProjectTimingDetails, { report }));
  assert.match(html, /Base-render journal: missing/);
  assert.match(html, /No zero duration was inferred/);
  writeFileSync(child, Buffer.from([0xff]));
  report = projectRunTimings(dir)!;
  assert.equal(report.sources[1].state, "rejected");
  assert.equal(report.stages.length, 1, "unsafe child must not erase valid root work");
  html = renderToStaticMarkup(createElement(ProjectTimingDetails, { report }));
  assert.match(html, /Base-render journal: rejected/);
  rmSync(stageTimingsPath(dir));
  writeFileSync(child, raw(pair("child", 2000)));
  report = projectRunTimings(dir)!;
  assert.equal(report.sources[0].state, "missing");
  assert.equal(report.stages[0].inclusiveMs, 2000, "missing root must not erase valid child work");
}

function sourceLinkTests(base: string): void {
  const dir = sourceFixture(base, "links");
  const childDir = path.join(dir, "base_work"), child = stageTimingsPath(childDir);
  const outside = sourceFixture(base, "outside");
  const outsideJournal = stageTimingsPath(outside);
  writeFileSync(stageTimingsPath(dir), raw(pair("root", 1000)));
  writeFileSync(outsideJournal, raw(pair("escaped", 90_000)));
  rmSync(childDir, { recursive: true });
  symlinkSync(outside, childDir);
  assert.equal(projectRunTimings(dir)?.sources[1].state, "rejected");
  assert.equal(projectRunTimings(dir)?.stages[0].inclusiveMs, 1000);
  unlinkSync(childDir);
  mkdirSync(childDir);
  symlinkSync(outsideJournal, child);
  assert.equal(projectRunTimings(dir)?.sources[1].state, "rejected");
  rmSync(child);
  linkSync(outsideJournal, child);
  assert.equal(projectRunTimings(dir)?.sources[1].state, "rejected");
  rmSync(child);
  const rootJournal = stageTimingsPath(dir);
  rmSync(rootJournal);
  linkSync(outsideJournal, rootJournal);
  assert.equal(projectRunTimings(dir)?.sources[0].state, "rejected");
}

function aggregateLimitTests(base: string): void {
  const dir = sourceFixture(base, "limits");
  const child = stageTimingsPath(path.join(dir, "base_work"));
  const journal = raw(pair("root", 1000));
  writeFileSync(stageTimingsPath(dir), journal + " ".repeat(2 * 1024 * 1024));
  writeFileSync(child, raw(pair("child", 1000)) + " ".repeat(2 * 1024 * 1024));
  let report = projectRunTimings(dir)!;
  assert.equal(report.state, "unavailable");
  assert.match(report.reason!, /aggregate UI read limit/);
  assert.equal(report.stages.length, 0, "aggregate truncation may not imply a complete stage list");
  assert.equal(report.sources[1].state, "rejected");
  writeFileSync(stageTimingsPath(dir), Buffer.alloc(2 * 1024 * 1024, 0xff));
  report = projectRunTimings(dir)!;
  assert.equal(report.state, "unavailable", "rejected source reads also consume the aggregate byte budget");
  assert.deepEqual(report.sources.map((source) => source.state), ["rejected", "rejected"]);
  writeFileSync(stageTimingsPath(dir), journal + "\n".repeat(10_000));
  writeFileSync(child, "\n".repeat(10_000));
  report = projectRunTimings(dir)!;
  assert.equal(report.state, "unavailable");
  assert.match(report.reason!, /aggregate UI read limit/);
}

async function main(): Promise<void> {
  const dir = mkdtempSync(path.join(os.tmpdir(), "sniper-timing-summary-"));
  try {
    pairTests(); resumeAndClockTests(); malformedAndUiTests(); await realWriterTests(dir); fileTests(dir);
    splitSourceTests(dir); sourceCoverageTests(dir); sourceLinkTests(dir); aggregateLimitTests(dir);
  }
  finally { rmSync(dir, { recursive: true, force: true }); }
}
void main().then(() => console.log("stage-timing-summary tests passed"))
  .catch((error) => { console.error(error); process.exitCode = 1; });
