import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import { trackProcessTree } from "../../_lib/child-process-lifecycle";
import { currentCallerProcessDeadline } from "@/lib/server/caller-process-deadline";

const MAX_OUTPUT = 2 * 1024 * 1024;

export interface CutPreviewProcessInput {
  command: string;
  args: string[];
  cwd: string;
  env: NodeJS.ProcessEnv;
  timeoutMs: number;
  /** Caller still supplies its actual remaining deadline; omission preserves the legacy cut ceiling. */
  purpose?: "cut-preview" | "guided-opening" | "guided-body" | "guided-body-command";
  /** Optional caller cancellation; completion still waits for owned-group stop verification. */
  signal?: AbortSignal;
  /** Planning callers retain their existing worker-shutdown registration. */
  trackForShutdown?: boolean;
  /** Optional bounded live diagnostics; never observes bytes beyond the retained stderr cap. */
  onStderr?: (chunk: Buffer) => void;
  /** Optional metadata frontier, after ancestor deadline callbacks and before the actual spawn. Its cost consumes the captured timeout. */
  beforeSpawn?: () => void;
  /** Optional actual-settlement metadata capture, before any later ancestor deadline callback. Never supplies work authority. */
  afterSettled?: (details: Readonly<CutPreviewProcessError["details"]>) => void;
}

/** Preserve actual stop facts if a metadata hook fails; never relabel a settled group as unstarted or forcibly killed. */
function notifySettlement(hook: NonNullable<CutPreviewProcessInput["afterSettled"]>, details: CutPreviewProcessError["details"], exitCode?: number | null): void {
  const fixed = Object.freeze({ ...details });
  try { hook(fixed); }
  catch (error) { throw new CutPreviewProcessError(`Owned settlement metadata failed: ${String(error)}`, fixed, exitCode); }
}

function heldSettlement(result: Promise<{ stdout: string; stderr: string }>, hook: NonNullable<CutPreviewProcessInput["afterSettled"]>) {
  return result.then(output => {
    notifySettlement(hook, { ...output, timedOut: false, groupStopped: true, forcedStop: false }, 0); return output;
  }, error => {
    if (error instanceof CutPreviewProcessError) notifySettlement(hook, error.details, error.exitCode);
    throw error;
  });
}

export class CutPreviewProcessError extends Error {
  constructor(message: string, readonly details: {
    timedOut: boolean; groupStopped: boolean;
    /** True whenever THIS runner signalled the outer group (deadline, output bound, live descendants).
     * Nested sessions started by the child (e.g. ffprobe under a new session) were never observed. */
    forcedStop: boolean; stdout: string; stderr: string;
  }, readonly exitCode?: number | null) { super(message); }
}

export function groupAlive(pid: number): boolean {
  try { process.kill(-pid, 0); return true; }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ESRCH") return false;
    throw error;
  }
}

function signalGroup(pid: number, signal: NodeJS.Signals): void {
  try { process.kill(-pid, signal); }
  catch (error) { if ((error as NodeJS.ErrnoException).code !== "ESRCH") throw error; }
}

export async function stopGroup(pid: number): Promise<boolean> {
  try {
    signalGroup(pid, "SIGTERM");
    for (let index = 0; index < 10 && groupAlive(pid); index += 1) await delay(25);
    if (groupAlive(pid)) signalGroup(pid, "SIGKILL");
    for (let index = 0; index < 40 && groupAlive(pid); index += 1) await delay(25);
    return !groupAlive(pid);
  } catch { return false; }
}

function validateInput(input: CutPreviewProcessInput): void {
  const purpose = input.purpose === undefined ? "cut-preview" : input.purpose;
  const limits = { "cut-preview": 900_000, "guided-opening": 1_500_000, "guided-body": 3_300_000, "guided-body-command": 3_610_000 };
  const maximum = limits[purpose];
  if (process.platform === "win32" || !Number.isInteger(input.timeoutMs)
      || !Object.hasOwn(limits, purpose)
      || input.timeoutMs < 1 || input.timeoutMs > maximum) {
    throw new Error("cut preview requires a bounded POSIX process-group runner");
  }
}

function spawnOwnedChild(input: CutPreviewProcessInput) {
  const child = spawn(input.command, input.args, { cwd: input.cwd, env: input.env,
    detached: true, stdio: ["ignore", "pipe", "pipe"] });
  if (input.trackForShutdown) trackProcessTree(child);
  return child;
}

interface OwnedProcessState {
  child: ReturnType<typeof spawnOwnedChild>; input: CutPreviewProcessInput;
  stdout: Buffer; stderr: Buffer; finishing: boolean;
  timer?: ReturnType<typeof setTimeout>; cancel: () => void;
  resolve: (output: { stdout: string; stderr: string }) => void;
  reject: (error: CutPreviewProcessError) => void;
}

async function finishOwnedChild(state: OwnedProcessState, event: { error?: string; timedOut?: boolean; exitCode?: number | null }) {
  if (state.finishing) return;
  state.finishing = true;
  clearTimeout(state.timer); state.input.signal?.removeEventListener("abort", state.cancel);
  let clean = true, forcedStop = false, error = event.error;
  try {
    if (state.child.pid && groupAlive(state.child.pid)) {
      error ??= "cut preview child left a live process group";
      forcedStop = true; clean = await stopGroup(state.child.pid);
    }
  } catch { clean = false; }
  state.child.stdout.destroy(); state.child.stderr.destroy();
  const output = { stdout: state.stdout.toString("utf8"), stderr: state.stderr.toString("utf8") };
  if (error || !clean) state.reject(new CutPreviewProcessError(error ?? "cut preview process group did not stop",
    { ...output, timedOut: event.timedOut ?? false, groupStopped: clean, forcedStop }, event.exitCode));
  else state.resolve(output);
}

function appendOutput(state: OwnedProcessState, which: "stdout" | "stderr", data: Buffer): void {
  if (state.finishing) return;
  const current = state[which];
  const accepted = data.subarray(0, Math.max(0, MAX_OUTPUT - current.length));
  state[which] = Buffer.concat([current, accepted]);
  try { if (which === "stderr") state.input.onStderr?.(accepted); }
  catch (error) { void finishOwnedChild(state, { error: `cut preview diagnostic observer failed: ${String(error)}` }); }
  if (current.length + data.length > MAX_OUTPUT) void finishOwnedChild(state, { error: "cut preview exceeded its output bound" });
}

function observeOwnedChild(input: CutPreviewProcessInput, resolve: OwnedProcessState["resolve"], reject: OwnedProcessState["reject"]): void {
  const child = spawnOwnedChild(input);
  const state: OwnedProcessState = { child, input, resolve, reject, stdout: Buffer.alloc(0), stderr: Buffer.alloc(0),
    finishing: false, cancel: () => { void finishOwnedChild(state, { error: "cut preview cancelled by caller" }); } };
  child.stdout.on("data", (data: Buffer) => appendOutput(state, "stdout", data));
  child.stderr.on("data", (data: Buffer) => appendOutput(state, "stderr", data));
  child.on("error", (error) => void finishOwnedChild(state, { error: error.message }));
  child.on("exit", (code, signal) => {
    if (code !== 0 || signal) void finishOwnedChild(state, { error: `cut preview exited ${code ?? signal}`, exitCode: code });
  });
  child.on("close", (code, signal) => void finishOwnedChild(state,
    { error: code === 0 && !signal ? undefined : `cut preview exited ${code ?? signal}`, exitCode: code }));
  state.timer = setTimeout(() => void finishOwnedChild(state,
    { error: "cut preview process-group deadline exceeded", timedOut: true }), input.timeoutMs);
  input.signal?.addEventListener("abort", state.cancel, { once: true });
  if (input.signal?.aborted) state.cancel();
}

/** Run exactly one new owned POSIX group; bound output/deadline and verify cleanup. */
export function runCutPreviewProcess(input: CutPreviewProcessInput): Promise<{ stdout: string; stderr: string }> {
  const beforeSpawn = input.beforeSpawn, afterSettled = input.afterSettled, began = beforeSpawn ? performance.now() : 0;
  if (beforeSpawn) input = { ...input, args: [...input.args], env: { ...input.env } };
  validateInput(input);
  const caller = currentCallerProcessDeadline();
  if (caller) input = { ...input, timeoutMs: Math.min(input.timeoutMs, caller.timeoutMs),
    signal: input.signal ? AbortSignal.any([input.signal, caller.signal]) : caller.signal };
  if (input.signal?.aborted) return Promise.reject(new CutPreviewProcessError("cut preview cancelled before spawn",
    { stdout: "", stderr: "", timedOut: false, groupStopped: true, forcedStop: false }));
  if (beforeSpawn) {
    beforeSpawn(); const elapsed = performance.now() - began, timeoutMs = Math.floor(input.timeoutMs - elapsed);
    if (!Number.isFinite(elapsed) || elapsed < 0 || timeoutMs < 1 || input.signal?.aborted) {
      throw new Error("Owned pre-spawn metadata exhausted or cancelled the original captured allowance");
    }
    input = { ...input, timeoutMs };
  }
  const result = new Promise<{ stdout: string; stderr: string }>((resolve, reject) => observeOwnedChild(input, resolve, reject));
  const settled = afterSettled ? heldSettlement(result, afterSettled) : result;
  if (!caller) return settled;
  return settled.then((output) => {
    try { currentCallerProcessDeadline(); }
    catch (error) { throw new CutPreviewProcessError(`Caller deadline failed after owned group settled: ${String(error)}`,
      { ...output, timedOut: true, groupStopped: true, forcedStop: false }, 0); }
    return output;
  });
}
