import { existsSync, readFileSync, renameSync, rmSync, writeFileSync } from "fs";
import path from "path";
import {
  autoEditJobPath,
  readAutoEditJob,
  recoverAutoEditJob,
  type AutoEditJob,
} from "./auto-edit-job-store";
import {
  captureProcessIdentity,
  durableProcessAlive,
  validProcessIdentity,
  type ProcessIdentity,
} from "./process-liveness";
import type {
  ProducerRunPhase,
  ProducerRunState,
  ProducerRunStatus,
} from "@/lib/producer/project-state";

interface StoredRun extends ProducerRunState {
  token: string;
  ownerPid: number;
  ownerIdentity?: ProcessIdentity;
  ownerGroup?: boolean;
}
interface RunStoreGlobal {
  __sniperProducerRuns?: Map<string, StoredRun>;
}
const MAX_EVENTS = 24;
const RUN_STATE_FILE = ".sniper-run-state.json";
function store(): Map<string, StoredRun> {
  const root = globalThis as typeof globalThis & RunStoreGlobal;
  root.__sniperProducerRuns ??= new Map<string, StoredRun>();
  return root.__sniperProducerRuns;
}
function cleanDir(dir: string): string {
  return dir.replace(/\/$/, "");
}
function statePath(dir: string): string {
  return path.join(cleanDir(dir), RUN_STATE_FILE);
}
function saveRun(dir: string, run: StoredRun): void {
  if (!existsSync(dir)) return;
  const destination = statePath(dir);
  const temporary = `${destination}.${process.pid}.tmp`;
  try {
    writeFileSync(temporary, `${JSON.stringify(run, null, 2)}\n`, { mode: 0o600 });
    renameSync(temporary, destination);
  } catch {
    rmSync(temporary, { force: true });
  }
}
function validStoredRun(value: unknown): value is StoredRun {
  if (!value || typeof value !== "object") return false;
  const run = value as Partial<StoredRun>;
  return typeof run.token === "string"
    && typeof run.ownerPid === "number"
    && (run.ownerIdentity === undefined || validProcessIdentity(run.ownerIdentity))
    && ["running", "failed", "interrupted"].includes(String(run.status))
    && Array.isArray(run.events);
}
function readRun(dir: string): StoredRun | null {
  try {
    const parsed: unknown = JSON.parse(readFileSync(statePath(dir), "utf8"));
    return validStoredRun(parsed) ? parsed : null;
  } catch {
    return null;
  }
}
function ownerAlive(run: StoredRun): boolean {
  return durableProcessAlive(run.ownerPid, run.ownerIdentity, run.updatedAt);
}
function latestRun(dir: string, recover: boolean): StoredRun | null {
  const memory = store().get(dir) ?? null;
  const disk = readRun(dir);
  if (disk && (!memory || disk.token !== memory.token || disk.updatedAt >= memory.updatedAt)) {
    return disk;
  }
  if (disk) return memory;
  if (recover && memory && memory.ownerPid !== process.pid && !ownerAlive(memory)) {
    store().delete(dir); // detached worker completed and removed its durable run file
    return null;
  }
  return memory;
}
function recoverInterruptedRun(dir: string, run: StoredRun): StoredRun {
  if (run.status !== "running" || ownerAlive(run)) return run;
  const now = new Date().toISOString();
  const message = "The worker stopped before Auto Edit completed. Saved checkpoints are intact; choose Resume Edit to continue.";
  const recovered: StoredRun = {
    ...run,
    status: "interrupted",
    updatedAt: now,
    message,
    events: [...run.events, event(message, now)].slice(-MAX_EVENTS),
  };
  saveRun(dir, recovered);
  return recovered;
}
function storedRun(dir: string, recover = true): StoredRun | null {
  const key = cleanDir(dir);
  const current = latestRun(key, recover);
  if (!current || !recover) return current;
  const recovered = recoverInterruptedRun(key, current);
  store().set(key, recovered);
  return recovered;
}
function event(message: string, at = new Date().toISOString()) {
  return { at, message };
}
interface BeginRunArgs {
  dir: string;
  kind: ProducerRunState["kind"];
  phase: ProducerRunPhase;
  message: string;
  token: string;
}
export function newProducerRunToken(): string {
  return `${new Date().toISOString()}:${Math.random().toString(36).slice(2)}`;
}
export function beginProducerRunWithToken(args: BeginRunArgs): void {
  const key = cleanDir(args.dir);
  const now = new Date().toISOString();
  const run: StoredRun = {
    token: args.token,
    ownerPid: process.pid,
    ownerIdentity: captureProcessIdentity(process.pid),
    ownerGroup: false,
    kind: args.kind,
    status: "running",
    phase: args.phase,
    startedAt: now,
    updatedAt: now,
    message: args.message,
    events: [event(args.message, now)],
  };
  store().set(key, run);
  saveRun(key, run);
}
export function beginProducerRun(
  dir: string,
  kind: ProducerRunState["kind"],
  phase: ProducerRunPhase,
  message: string,
): string {
  const token = newProducerRunToken();
  beginProducerRunWithToken({ dir, kind, phase, message, token });
  return token;
}
export function setProducerRunOwner(
  dir: string,
  token: string,
  ownerPid: number,
  ownerGroup = false,
): void {
  const key = cleanDir(dir);
  const current = storedRun(key);
  if (!current || current.token !== token) return;
  const updated = {
    ...current,
    ownerPid,
    ownerIdentity: captureProcessIdentity(ownerPid),
    ownerGroup,
    updatedAt: new Date().toISOString(),
  };
  store().set(key, updated);
  saveRun(key, updated);
}
interface AutoEditAuthorityOptions {
  job: AutoEditJob | null;
  recover: boolean;
}
function autoEditAuthority(
  dir: string,
  current: StoredRun | null,
  options: AutoEditAuthorityOptions,
): StoredRun | null {
  if (current?.kind === "render") return current;
  const job = options.recover && options.job?.status === "running"
    ? recoverAutoEditJob(autoEditJobPath(dir)) : options.job;
  if (!job) return current;
  if (job.status === "complete") {
    if (options.recover && current?.kind === "auto_edit") {
      store().delete(dir);
      rmSync(statePath(dir), { force: true });
    }
    return null;
  }
  const run: StoredRun = {
    token: job.token,
    ownerPid: job.workerPid ?? 0,
    ownerIdentity: job.workerIdentity,
    ownerGroup: true,
    kind: "auto_edit",
    status: job.status,
    phase: job.phase,
    startedAt: job.requestedAt,
    updatedAt: job.updatedAt,
    message: job.message,
    events: current?.token === job.token ? current.events : [event(job.message, job.updatedAt)],
  };
  if (options.recover) {
    store().set(dir, run);
    saveRun(dir, run);
  }
  return run;
}
export function producerRun(
  dir: string,
  options: { recover?: boolean } = {},
): ProducerRunState | null {
  const key = cleanDir(dir);
  const recover = options.recover !== false;
  const job = readAutoEditJob(autoEditJobPath(key));
  const snapshot = storedRun(key, false);
  const current = recover && (!job || snapshot?.kind === "render")
    ? storedRun(key) : snapshot;
  const resolved = autoEditAuthority(key, current, { job, recover });
  if (!resolved) return null;
  const { kind, status, phase, startedAt, updatedAt, message, events } = resolved;
  return {
    kind, status, phase, startedAt, updatedAt, message, events,
    ...(kind === "auto_edit" ? { controlToken: resolved.token } : {}),
  };
}
export function producerRunActive(dir: string): boolean {
  return producerRun(dir)?.status === "running";
}
export function updateProducerRun(
  dir: string,
  token: string,
  phase: ProducerRunPhase,
  message: string,
): void {
  changeRun(dir, token, "running", phase, message);
}

/** Refresh current status without turning a periodic heartbeat into run history. */
export function heartbeatProducerRun(
  dir: string,
  token: string,
  phase: ProducerRunPhase,
  message: string,
): void {
  changeRun(dir, token, "running", phase, message, false);
}

export function appendProducerRunEvent(dir: string, token: string, message: string): void {
  const current = storedRun(dir);
  if (!current || current.token !== token) return;
  changeRun(dir, token, current.status, current.phase, message);
}

export function failProducerRun(dir: string, token: string, message: string): void {
  const current = storedRun(dir);
  changeRun(dir, token, "failed", current?.phase ?? "authoring", message);
}

export function interruptProducerRun(dir: string, token: string, message: string): void {
  const current = storedRun(dir);
  changeRun(dir, token, "interrupted", current?.phase ?? "authoring", message);
}

export function completeProducerRun(dir: string, token: string): void {
  const key = cleanDir(dir);
  if (storedRun(key)?.token !== token) return;
  store().delete(key);
  rmSync(statePath(key), { force: true });
}

export function clearProducerRun(dir: string): void {
  const key = cleanDir(dir);
  store().delete(key);
  rmSync(statePath(key), { force: true });
}

function changeRun(
  dir: string,
  token: string,
  status: ProducerRunStatus,
  phase: ProducerRunPhase,
  message: string,
  appendEvent = true,
): void {
  const key = cleanDir(dir);
  const current = storedRun(key);
  if (!current || current.token !== token) return;
  const now = new Date().toISOString();
  const events = appendEvent
    ? [...current.events, event(message, now)].slice(-MAX_EVENTS)
    : current.events;
  const updated = { ...current, status, phase, updatedAt: now, message, events };
  store().set(key, updated);
  saveRun(key, updated);
}
