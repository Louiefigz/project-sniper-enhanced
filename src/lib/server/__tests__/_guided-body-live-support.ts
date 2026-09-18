/** TEST-only retained diagnostics. Never a media/approval authority or cleanup controller. */
import assert from "node:assert/strict";
import { constants, accessSync, lstatSync, mkdirSync, readdirSync, realpathSync, writeFileSync } from "node:fs";
import path from "node:path";
import { CutPreviewProcessError, runCutPreviewProcess } from "@/app/api/producer/auto-edit/cut-preview-process";
import { observeCutPreviewFile, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { assertOpeningControllerTools } from "../guided-opening-launch-store";

export interface BodyLiveLog { workspace: string; root: string; sequence: number; began: number }

export function retainBodyLive(log: BodyLiveLog, name: string, value: unknown): string {
  if (!/^[a-z0-9][a-z0-9.-]+$/.test(name)) throw new Error("Unsafe TEST log name");
  const file = path.join(log.root, name);
  writeFileSync(file, JSON.stringify(value, null, 2) + "\n", { flag: "wx", mode: 0o600 });
  return file;
}

export function newBodyLiveLog(workspace: string): BodyLiveLog {
  const root = path.join(workspace, "body-live-evidence"); mkdirSync(root, { mode: 0o700 });
  return { workspace, root, sequence: 0, began: performance.now() };
}

function failureDetails(error: unknown) {
  const processError = error && typeof error === "object" ? error as { stdout?: unknown; stderr?: unknown; status?: unknown; signal?: unknown } : {};
  const bounded = (value: unknown) => typeof value === "string" || Buffer.isBuffer(value) ? String(value).slice(0, 2 * 1024 * 1024) : null;
  return { error: String(error).slice(0, 8000), cause: error instanceof Error ? String(error.cause ?? "").slice(0, 4000) : "",
    childStdout: bounded(processError.stdout), childStderr: bounded(processError.stderr),
    childStatus: typeof processError.status === "number" ? processError.status : null,
    childSignal: typeof processError.signal === "string" ? processError.signal : null,
    ...(error instanceof CutPreviewProcessError ? { process: error.details, exitCode: error.exitCode } : {}) };
}

/** No retry: a failed CLI may have submitted a durable launch; preserve its evidence. */
export async function timedBodyLive<T>(log: BodyLiveLog, name: string, action: () => Promise<T>): Promise<T> {
  const prefix = `${String(++log.sequence).padStart(4, "0")}-${name}`, startedAt = new Date().toISOString(), began = performance.now();
  retainBodyLive(log, `${prefix}.start.json`, { startedAt, scope: "TEST-only", genuineHumanAcceptance: false });
  try {
    const result = await action();
    retainBodyLive(log, `${prefix}.complete.json`, { startedAt, endedAt: new Date().toISOString(), elapsedMs: performance.now() - began });
    return result;
  } catch (error) {
    retainBodyLive(log, `${prefix}.failed.json`, { startedAt, endedAt: new Date().toISOString(), elapsedMs: performance.now() - began,
      ...failureDetails(error), cleanupClaim: "not-inferred-by-test-driver", automaticRetry: false });
    throw error;
  }
}

/** Actual production CLI in a bounded owned group; its detached controller retains its own lifecycle. */
export async function bodyLiveCommand(input: { log: BodyLiveLog; dir: string; command: string; request?: string }, runner = runCutPreviewProcess) {
  assert.ok(["launch", "launch-status", "status", "approve"].includes(input.command));
  return invokeLiveCli({ ...input, script: "guided-opening", label: input.command,
    timeoutMs: input.command === "approve" ? 600_000 : 180_000, purpose: "cut-preview" }, runner);
}

interface LiveCliInvocation {
  log: BodyLiveLog; dir: string; command: string; request?: string;
  script: "guided-opening" | "guided-body"; label: string;
  timeoutMs: number; purpose: Parameters<typeof runCutPreviewProcess>[0]["purpose"];
}

async function invokeLiveCli(input: LiveCliInvocation, runner: typeof runCutPreviewProcess) {
  const { log, command, dir, request, script, label, purpose, timeoutMs } = input;
  assert.equal(path.dirname(path.dirname(dir)), log.workspace, "Only this driver's new project is allowed");
  const args = ["--import", "tsx", `scripts/producer/${script}.ts`, command, dir, ...(request ? [request] : [])];
  return timedBodyLive(log, `cli-${label}`, async () => {
    const prefix = `${String(log.sequence).padStart(4, "0")}-cli-${label}`;
    const output = await runner({ command: process.execPath, args, cwd: process.cwd(),
      env: { ...process.env, SNIPER_WORKSPACE_ROOT: log.workspace, TSX_DISABLE_CACHE: "1" }, timeoutMs, purpose });
    retainBodyLive(log, `${prefix}.output.json`, output);
    const lines = output.stdout.trim().split(/\r?\n/);
    if (lines.length !== 1 || !lines[0]) throw new Error("Production CLI did not return exactly one JSON completion");
    return JSON.parse(lines[0]) as unknown;
  });
}

/** TEST observation only: never passed to the engine as generation allowance or excluded elapsed time. */
export function bodyLiveObserverTimeout(startedAt: string, now = Date.now()): number {
  const start = Date.parse(startedAt), cleanupHeadroom = 5 * 60_000 + 10_000;
  if (!Number.isSafeInteger(start) || new Date(start).toISOString() !== startedAt
      || !Number.isSafeInteger(now) || now < start) throw new Error("TEST body observer clock is malformed or rolled back");
  const remaining = Math.min(55 * 60_000 + cleanupHeadroom, start + 120 * 60_000 - now + cleanupHeadroom);
  if (remaining < 1) throw new Error("TEST body observer original request and cleanup horizon expired");
  return remaining;
}

/** Foreground production body CLI; safety headroom cannot qualify late engine output. Never auto-cleanup/retry. */
export async function bodyLiveBodyCommand(input: {
  log: BodyLiveLog; dir: string; command: "run" | "status"; request?: string; generationStartedAt: string;
}, runner = runCutPreviewProcess) {
  assert.ok(["run", "status"].includes(input.command));
  if ((input.command === "run") !== Boolean(input.request)) throw new Error("TEST body run needs its exact request; status accepts none");
  const timeoutMs = Math.min(bodyLiveObserverTimeout(input.generationStartedAt), input.command === "status" ? 180_000 : Infinity);
  return invokeLiveCli({ ...input, script: "guided-body", label: `body-${input.command}`,
    timeoutMs, purpose: input.command === "run" ? "guided-body-command" : "cut-preview" }, runner);
}

/** Hash the small exact body operation inventory to prove replay did not create or edit an attempt. */
export function bodyOperationInventory(root: string): Record<string, string> {
  const result: Record<string, string> = {}; let bytes = 0;
  const visit = (directory: string): void => {
    for (const name of readdirSync(directory).sort()) inspect(path.join(directory, name));
  };
  const inspect = (file: string): void => {
    const info = lstatSync(file);
    if (info.isSymbolicLink()) throw new Error("Body TEST inventory refuses links");
    if (info.isDirectory()) return visit(file);
    if (!info.isFile() || Object.keys(result).length >= 256) throw new Error("Body TEST inventory exceeded its file class/count bound");
    bytes += info.size;
    if (bytes > 16 * 1024 * 1024) throw new Error("Body TEST inventory exceeded its byte bound");
    result[path.relative(root, file)] = observeCutPreviewFile(file, 16 * 1024 * 1024).sha256;
  };
  visit(root); return result;
}

/** Read only explicit non-secret control paths. No Docker call, model, media decode or credential read. */
export function bodyLiveRuntimeControls() {
  assertOpeningControllerTools();
  const names = ["SNIPER_NODE_PATH", "HYPERFRAMES_BROWSER_PATH", "HYPERFRAMES_FFMPEG_PATH", "HYPERFRAMES_FFPROBE_PATH", "SNIPER_DOCKER_PATH"];
  const tools = names.map((name) => {
    const configured = process.env[name];
    if (!configured || !path.isAbsolute(configured)) throw new Error(`Missing explicit ${name}`);
    const resolved = realpathSync(configured); accessSync(resolved, constants.X_OK);
    if (!lstatSync(resolved).isFile()) throw new Error(`${name} is not a regular executable`);
    return { name, configured, resolved };
  });
  const socket = process.env.SNIPER_DOCKER_SOCKET;
  if (!socket || !path.isAbsolute(socket) || !lstatSync(socket).isSocket()) throw new Error("Missing explicit actual Docker socket");
  const approval = readCutPreviewObject(path.resolve("scripts/producer/headless/render_image_approval.json"));
  if (approval.value.imageId !== process.env.SNIPER_RENDER_IMAGE_ID || !/^\d+:\d+$/.test(process.env.SNIPER_RENDER_UID_GID ?? "")) {
    throw new Error("Explicit image/user controls differ from the current approval");
  }
  const runtime = process.env.SNIPER_RUNTIME_REPO_ROOT;
  if (!runtime || !path.isAbsolute(runtime) || realpathSync(runtime) !== realpathSync(process.cwd())) throw new Error("Explicit runtime repository required");
  return { scope: "TEST-read-only-control-path-preflight-not-runtime-qualification", tools, socket,
    imageId: approval.value.imageId, imageApprovalSha256: approval.sha256, user: process.env.SNIPER_RENDER_UID_GID,
    runtimeRepoRoot: realpathSync(process.cwd()), dockerContacted: false, credentialsRead: false };
}
