import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { trackProcessTree } from "./child-process-lifecycle";
import { groupAlive, stopGroup } from "../producer/auto-edit/cut-preview-process";

export interface SubscriptionStatusRequest {
  bin: string; args: string[]; cwd: string; env: NodeJS.ProcessEnv;
  timeoutMs: number; signal?: AbortSignal;
}
interface Output { stdout: string; stderr: string }
interface GroupProbe { alive: (pid: number) => boolean; stop: (pid: number) => Promise<boolean> }
const OWNED_GROUP = { alive: groupAlive, stop: stopGroup };
const MAX_BYTES = 32 * 1024;

/** Failure state is sanitized, not an assumption that elapsed cleanup means stopped. */
export class SubscriptionAuthenticationError extends Error {
  readonly retryable = false;
  constructor(message: string, readonly cleanupVerified: boolean, readonly cleanupMs: number) {
    super(message + (cleanupVerified ? "" : "; process-group cleanup is unverified; do not retry automatically"));
  }
}

/** Metadata cannot admit inference until its exact owned POSIX group is absent. */
class StatusCapture {
  private child: ChildProcessWithoutNullStreams;
  private stdout: Buffer[] = [];
  private stderr: Buffer[] = [];
  private bytes = 0;
  private finishing = false;
  private timer?: NodeJS.Timeout;
  private deadline: number;

  constructor(private input: SubscriptionStatusRequest,
    private done: { resolve: (output: Output) => void; reject: (error: Error) => void },
    private group: GroupProbe) {
    this.deadline = performance.now() + input.timeoutMs;
    this.child = trackProcessTree(spawn(input.bin, input.args, {
      cwd: input.cwd, env: input.env, detached: true, stdio: ["pipe", "pipe", "pipe"],
    }));
  }

  start(): void {
    this.child.stdout.on("data", (data: Buffer) => this.capture(data, this.stdout));
    this.child.stderr.on("data", (data: Buffer) => this.capture(data, this.stderr));
    this.child.on("error", () => void this.finish("Subscription authentication process failed to start"));
    this.child.on("close", (code, signal) => void this.finish(code === 0 && !signal
      ? undefined : "Subscription authentication was not confirmed"));
    this.child.stdin.on("error", () => void this.finish("Subscription authentication input failed"));
    this.child.stdin.end();
    this.timer = setTimeout(() => void this.finish("Subscription authentication timed out"), this.input.timeoutMs);
    this.input.signal?.addEventListener("abort", this.abort, { once: true });
    if (this.input.signal?.aborted) this.abort();
  }

  private capture(data: Buffer, target: Buffer[]): void {
    if (this.finishing) return;
    this.bytes += data.length;
    if (this.bytes > MAX_BYTES) {
      this.stdout = []; this.stderr = [];
      this.child.stdout.pause(); this.child.stderr.pause();
      void this.finish("Subscription authentication exceeded its output bound"); return;
    }
    target.push(data);
  }

  private async finish(error?: string): Promise<void> {
    if (this.finishing) return;
    this.finishing = true;
    clearTimeout(this.timer);
    this.input.signal?.removeEventListener("abort", this.abort);
    const started = performance.now();
    let clean = true;
    try {
      if (this.child.pid && this.group.alive(this.child.pid)) {
        error ??= "Subscription authentication left a live process group";
        clean = await this.group.stop(this.child.pid) && !this.group.alive(this.child.pid);
      }
    } catch { clean = false; }
    const cleanupMs = performance.now() - started;
    this.child.stdout.destroy(); this.child.stderr.destroy();
    if (this.input.signal?.aborted) error ??= "Subscription authentication was cancelled";
    if (performance.now() >= this.deadline) error ??= "Subscription authentication timed out";
    if (error || !clean) this.done.reject(new SubscriptionAuthenticationError(
      error ?? "Subscription authentication process-group observation failed", clean, cleanupMs));
    else this.done.resolve({ stdout: Buffer.concat(this.stdout).toString("utf8"), stderr: Buffer.concat(this.stderr).toString("utf8") });
    this.stdout = []; this.stderr = [];
  }

  private abort = () => { void this.finish("Subscription authentication was cancelled"); };
}

/** Cleanup has a bounded separate allowance, never a fresh work/admission deadline. */
export function captureSubscriptionStatus(input: SubscriptionStatusRequest, group: GroupProbe = OWNED_GROUP): Promise<Output> {
  if (input.signal?.aborted) return Promise.reject(new SubscriptionAuthenticationError("Subscription authentication was cancelled", true, 0));
  if (process.platform === "win32" || !Number.isFinite(input.timeoutMs) || input.timeoutMs <= 0 || input.timeoutMs > 10_000) {
    return Promise.reject(new SubscriptionAuthenticationError("Subscription authentication requires a bounded POSIX runner", true, 0));
  }
  return new Promise((resolve, reject) => new StatusCapture(input, { resolve, reject }, group).start());
}
