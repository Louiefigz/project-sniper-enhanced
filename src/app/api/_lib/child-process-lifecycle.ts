import type { ChildProcess } from "child_process";
import { AsyncLocalStorage } from "node:async_hooks";

export const PROCESS_TERM_GRACE_MS = 5_000;
const trackedProcessTrees = new Set<ChildProcess>();
const processObserver = new AsyncLocalStorage<(child: ChildProcess) => void>();

/** Opt-in observation only; historical tracking/termination semantics remain unchanged. */
export function withTrackedProcessObserver<T>(observer: (child: ChildProcess) => void, run: () => T): T {
  if (processObserver.getStore()) throw new Error("Nested process-tree observation is unsupported");
  return processObserver.run(observer, run);
}

type SignalProcess = (target: number, signal: NodeJS.Signals | 0) => void;
type ScheduledTimer = ReturnType<typeof setTimeout> & { unref?: () => void };
type Schedule = (callback: () => void, delayMs: number) => ScheduledTimer;

export interface ProcessTreeDependencies {
  platform?: NodeJS.Platform;
  signal?: SignalProcess;
  schedule?: Schedule;
  alive?: (target: number) => boolean;
}

export interface ProcessTreeTermination {
  termSent: boolean;
  escalationScheduled: boolean;
}

/** A detached child owns a POSIX process group; Windows addresses the child. */
export function processTreeTarget(pid: number, platform: NodeJS.Platform): number {
  if (!Number.isInteger(pid) || pid < 1) throw new Error("child PID must be a positive integer");
  return platform === "win32" ? pid : -pid;
}

/** `spawn(..., {detached:true})` is required before negative-PID signaling. */
export function shouldDetachProcessGroup(platform: NodeJS.Platform = process.platform): boolean {
  return platform !== "win32";
}

/** Register a detached subgroup so its owning worker can stop it on shutdown. */
export function trackProcessTree<T extends ChildProcess>(child: T): T {
  trackedProcessTrees.add(child);
  processObserver.getStore()?.(child);
  const forget = () => trackedProcessTrees.delete(child);
  child.once("close", forget);
  child.once("error", forget);
  return child;
}

function defaultAlive(target: number, signal: SignalProcess): boolean {
  try {
    signal(target, 0);
    return true;
  } catch {
    return false;
  }
}

function sendSignal(
  child: ChildProcess,
  signalName: NodeJS.Signals,
  dependencies: ProcessTreeDependencies,
): boolean {
  if (!child.pid) return false;
  const platform = dependencies.platform ?? process.platform;
  const signal = dependencies.signal ?? process.kill;
  try {
    signal(processTreeTarget(child.pid, platform), signalName);
    return true;
  } catch {
    try {
      return child.kill(signalName);
    } catch {
      return false;
    }
  }
}

/**
 * Terminate a detached child tree, then hard-kill the same group after grace.
 * The escalation timer is intentionally not cancelled when the group leader
 * exits: a grandchild may have survived TERM after its parent closed.
 */
export function terminateProcessTree(
  child: ChildProcess,
  graceMs = PROCESS_TERM_GRACE_MS,
  dependencies: ProcessTreeDependencies = {},
): ProcessTreeTermination {
  const termSent = sendSignal(child, "SIGTERM", dependencies);
  if (!termSent || !child.pid) return { termSent, escalationScheduled: false };
  const platform = dependencies.platform ?? process.platform;
  const target = processTreeTarget(child.pid, platform);
  const signal = dependencies.signal ?? process.kill;
  const alive = dependencies.alive ?? ((value: number) => defaultAlive(value, signal));
  const schedule = dependencies.schedule ?? setTimeout;
  const timer = schedule(() => {
    if (alive(target)) sendSignal(child, "SIGKILL", dependencies);
  }, graceMs);
  timer.unref?.();
  return { termSent, escalationScheduled: true };
}

/** Stop every detached subgroup created in this Node process. */
export function terminateTrackedProcessTrees(
  graceMs = PROCESS_TERM_GRACE_MS,
): number {
  let signaled = 0;
  for (const child of trackedProcessTrees) {
    if (terminateProcessTree(child, graceMs).termSent) signaled += 1;
  }
  return signaled;
}
