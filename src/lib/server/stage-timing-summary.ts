import { closeSync, constants, fstatSync, lstatSync, openSync, readSync, realpathSync, type Stats } from "node:fs";
import path from "node:path";
import { TextDecoder } from "node:util";
import type { RunTimingReport, RunTimingSource, RunTimingStage } from "@/lib/producer/run-timing";
import { autoEditJobPath, readAutoEditJob, type AutoEditJob } from "./auto-edit-job-store";
import { stageTimingsPath } from "./stage-timing";
import { accountTimingInputs } from "./stage-timing-inputs";

const MAX_BYTES = 4 * 1024 * 1024;
const MAX_ROWS = 20_000;
type Row = Record<string, unknown>;
interface Pair { start?: Row; end?: Row; invalid: boolean }
interface Directory { path: string; stat: Stats }
interface JournalBudget { bytes: number; rows: number }
interface JournalSources { raw: string; sources: RunTimingSource[]; limited: boolean }
class JournalLimitError extends Error {}
const LIMIT_REASON = "Timing journals exceed the aggregate UI read limit; use the full diagnostic report.";

function number(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && Math.abs(value) <= Number.MAX_SAFE_INTEGER;
}

function text(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 256;
}

function validRow(row: Row): boolean {
  return row.schemaVersion === 2 && row.clock === "process-monotonic"
    && ["runId", "attemptId", "writerId", "spanId", "stage"].every((key) => text(row[key]))
    && ["start", "end"].includes(String(row.event)) && number(row.mono)
    && number(row.ts) && Number.isSafeInteger(row.writerPid) && Number(row.writerPid) > 0
    && Number.isSafeInteger(row.attemptNo) && Number(row.attemptNo) > 0
    && (row.parentSpanId === undefined || row.parentSpanId === null || text(row.parentSpanId));
}

function collect(raw: string, runId: string, report: RunTimingReport): Map<string, Pair> {
  const pairs = new Map<string, Pair>();
  for (const line of raw.split("\n")) {
    if (!line.trim()) continue;
    consume(line, runId, { pairs, report });
  }
  return pairs;
}

function consume(line: string, runId: string, state: { pairs: Map<string, Pair>; report: RunTimingReport }): void {
  let row: Row;
  try { row = JSON.parse(line); } catch { state.report.invalidRows += 1; return; }
  if (!row || typeof row !== "object" || Array.isArray(row)) { state.report.invalidRows += 1; return; }
  if (row.schemaVersion === undefined || row.schemaVersion === 1) {
    if (text(row.stage) && number(row.mono) && ["start", "end"].includes(String(row.event))) state.report.legacyRows += 1;
    else state.report.invalidRows += 1;
    return;
  }
  if (text(row.runId) && row.runId !== runId) return;
  if (!validRow(row)) { state.report.invalidRows += 1; return; }
  const key = JSON.stringify([row.runId, row.attemptId, row.writerId, row.spanId]);
  const pair = state.pairs.get(key) ?? { invalid: false };
  const event = row.event as "start" | "end";
  if (pair[event] || (event === "start" && pair.end)) pair.invalid = true;
  pair[event] = row;
  state.pairs.set(key, pair);
}

function validPair(start: Row, end: Row): boolean {
  const stable = ["stage", "clock", "writerPid", "parentSpanId", "attemptNo"];
  const elapsed = (Number(end.mono) - Number(start.mono)) * 1000;
  return stable.every((key) => start[key] === end[key]) && elapsed >= 0
    && number(end.elapsedMs) && Math.abs(end.elapsedMs - elapsed) <= 0.1
    && ["completed", "failed", "interrupted"].includes(String(end.status));
}

function observeActivity(pair: Pair, report: RunTimingReport, context: { job: AutoEditJob; now: number }): void {
  const began = Date.parse(context.job.requestedAt), row = pair.end ?? pair.start;
  if (!row || !Number.isSafeInteger(began) || !Number.isSafeInteger(context.now)) return;
  const through = Math.round(Number(row.ts) * 1000);
  if (!Number.isSafeInteger(through) || through < began || through > context.now) return;
  if (pair.start && pair.end && Math.abs((Number(pair.end.ts) - Number(pair.start.ts)) * 1000
      - Number(pair.end.elapsedMs)) > 2000) return;
  if (!report.observedActivity || through - began > report.observedActivity.sinceRequestMs) {
    report.observedActivity = { throughAt: new Date(through).toISOString(), sinceRequestMs: through - began };
  }
}

function account(pair: Pair, report: RunTimingReport, context: { job: AutoEditJob; now: number; stages: Map<string, RunTimingStage> }): void {
  const { start, end } = pair;
  if (pair.invalid || !start || (end && !validPair(start, end))) { report.invalidRows += 1; return; }
  observeActivity(pair, report, context);
  if (!end) {
    if (context.job.status === "running" && start.attemptId === context.job.token) report.openSpans += 1;
    else report.incompleteSpans += 1;
    return;
  }
  const elapsed = Number(end.elapsedMs);
  if (Math.abs((Number(end.ts) - Number(start.ts)) * 1000 - elapsed) > 2000) report.clockWarnings += 1;
  const name = String(start.stage);
  const stage = context.stages.get(name) ?? { stage: name, calls: 0, inclusiveMs: 0, failed: 0, interrupted: 0 };
  stage.calls += 1;
  stage.inclusiveMs += elapsed;
  if (end.status === "failed") stage.failed += 1;
  if (end.status === "interrupted") stage.interrupted += 1;
  accountTimingInputs(stage, start.metadata, end.metadata);
  context.stages.set(name, stage);
}

function emptyReport(job: AutoEditJob, now: number): RunTimingReport {
  const start = Date.parse(job.requestedAt);
  const stop = job.status === "running" ? now : Date.parse(job.updatedAt);
  const valid = Number.isFinite(start) && Number.isFinite(stop) && stop >= start;
  return {
    schemaVersion: 1, scope: "auto-edit-job", state: "observed", reason: null,
    jobStatus: job.status, attempts: Number.isSafeInteger(job.attempts) && job.attempts > 0 ? job.attempts : null,
    wallMs: valid ? stop - start : null, stages: [], openSpans: 0, incompleteSpans: 0,
    invalidRows: 0, legacyRows: 0, clockWarnings: valid ? 0 : 1, coverage: "partial-instrumentation", sources: [],
  };
}

/** Strict, job-bound pairing; duplicates poison their pair rather than double-count. */
export function summarizeJobTimings(raw: string, job: AutoEditJob, now = Date.now()): RunTimingReport {
  const report = emptyReport(job, now);
  if (Buffer.byteLength(raw) > MAX_BYTES || raw.split("\n").length > MAX_ROWS) {
    return { ...report, state: "unavailable", reason: LIMIT_REASON };
  }
  const pairs = collect(raw, job.artifactToken ?? job.token, report);
  const stages = new Map<string, RunTimingStage>();
  for (const pair of pairs.values()) account(pair, report, { job, now, stages });
  report.stages = [...stages.values()].sort((a, b) => b.inclusiveMs - a.inclusiveMs);
  if (!pairs.size) { report.state = "unavailable"; report.reason = "No attributable v2 stage timings were recorded for this job."; }
  return report;
}

function sameFile(left: Stats, right: Stats): boolean {
  return left.dev === right.dev && left.ino === right.ino;
}

function directorySnapshot(dir: string): Directory {
  const stat = lstatSync(dir);
  if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error("unsupported directory");
  return { path: dir, stat };
}

function verifyDirectory(directory: Directory): void {
  const current = directorySnapshot(directory.path);
  if (!sameFile(directory.stat, current.stat)
      || realpathSync(directory.path) !== directory.path) throw new Error("directory changed during read");
}

/** Fixed snapshot, with link and directory-identity checks before and after opening. */
function readJournal(directory: Directory, root: Directory, budget: JournalBudget): string {
  verifyDirectory(root);
  verifyDirectory(directory);
  const journal = stageTimingsPath(directory.path);
  const expected = lstatSync(journal);
  if (!expected.isFile() || expected.nlink !== 1) throw new Error("unsupported journal");
  if (expected.size > budget.bytes) throw new JournalLimitError(LIMIT_REASON);
  const descriptor = openSync(journal, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = fstatSync(descriptor);
    if (!before.isFile() || before.nlink !== 1 || !sameFile(expected, before)) throw new Error("journal changed during open");
    if (before.size > budget.bytes) throw new JournalLimitError(LIMIT_REASON);
    verifyDirectory(root);
    verifyDirectory(directory);
    // Charge attempted reads too: malformed UTF-8 and changing files still cost IO.
    budget.bytes -= before.size + 1;
    const buffer = Buffer.alloc(before.size);
    let offset = 0;
    while (offset < buffer.length) {
      const count = readSync(descriptor, buffer, offset, buffer.length - offset, offset);
      if (!count) throw new Error("journal changed during read");
      offset += count;
    }
    const after = fstatSync(descriptor);
    if (after.nlink !== 1 || after.size !== before.size || after.mtimeMs !== before.mtimeMs
        || !sameFile(after, lstatSync(journal))) throw new Error("journal changed during read");
    verifyDirectory(root);
    verifyDirectory(directory);
    const raw = new TextDecoder("utf-8", { fatal: true }).decode(buffer);
    const rows = raw.split("\n").length;
    if (rows > budget.rows) throw new JournalLimitError(LIMIT_REASON);
    budget.rows -= rows;
    return raw;
  } finally { closeSync(descriptor); }
}

function sourceFailure(source: RunTimingSource["source"], error: unknown): RunTimingSource {
  const missing = (error as NodeJS.ErrnoException)?.code === "ENOENT";
  return { source, state: missing ? "missing" : "rejected", reason: missing
    ? "No journal was found; reused or uninstrumented work is possible. No zero duration was inferred."
    : "Unsafe, unreadable, oversized or changing source was excluded. Missing durations were not inferred." };
}

function producerSnapshot(dir: string): Directory {
  const supplied = directorySnapshot(path.resolve(dir));
  const root = directorySnapshot(realpathSync(supplied.path));
  if (!sameFile(supplied.stat, root.stat)) throw new Error("producer directory changed");
  return root;
}

/** Only known production anchors; never follow candidate paths or recursively discover logs. */
function readSources(dir: string): JournalSources {
  const raw: string[] = [], sources: RunTimingSource[] = [];
  const budget = { bytes: MAX_BYTES, rows: MAX_ROWS };
  let root: Directory;
  try { root = producerSnapshot(dir); }
  catch (error) { return { raw: "", limited: false,
    sources: ["producer", "base_work"].map((source) => sourceFailure(source as RunTimingSource["source"], error)) }; }
  let limited = false;
  for (const source of ["producer", "base_work"] as const) {
    try {
      const directory = source === "producer" ? root : directorySnapshot(path.join(root.path, "base_work"));
      const content = readJournal(directory, root, budget);
      raw.push(content);
      sources.push({ source, state: "read", reason: null });
    } catch (error) {
      limited ||= error instanceof JournalLimitError;
      sources.push(sourceFailure(source, error));
    }
  }
  return { raw: raw.join("\n"), sources, limited };
}

/** Includes the last completed/failed job; a missing job never fabricates timings. */
export function projectRunTimings(dir: string, now = Date.now()): RunTimingReport | null {
  const job = readAutoEditJob(autoEditJobPath(dir));
  if (!job || job.ctx.dir !== dir) return null;
  try {
    const journals = readSources(dir);
    if (journals.limited) return { ...emptyReport(job, now), sources: journals.sources,
      state: "unavailable", reason: LIMIT_REASON };
    return { ...summarizeJobTimings(journals.raw, job, now), sources: journals.sources };
  }
  catch { return { ...emptyReport(job, now), state: "unavailable",
    reason: "Timing journals could not be read; no stage durations were inferred." }; }
}
