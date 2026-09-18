import fs from "node:fs";
import path from "node:path";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { stripVTControlCharacters } from "node:util";
import { pythonInterpreter } from "@/app/api/_lib/spawn-python";
import { captureProcessIdentity, processGroupAlive } from "./process-liveness";
import { readBytes, sha } from "@/app/api/producer/studio/import/files";
import { checkTime, object, SHA } from "./grade-observation-store";

export interface GradeProcessResult {
  resultSha256: string | null; cleanupVerified: boolean; status: "complete" | "failed" | "interrupted";
  handshake: { remainingMs: number; startupMs: number } | null;
  failure?: PrivateGradeProcessFailure;
}
export interface PrivateGradeProcessFailure {
  reason: string; exitCode: number | null; exitSignal: string | null; workExpired: boolean;
  identityAtLastProbe: "verified" | "unavailable"; cleanupState: "unverified";
  stderr: string; stderrTruncated: boolean;
}
export interface GradeInvocation { root: string; directory: string; inputHash: string; deadline: bigint }
const FAILURE: GradeProcessResult = { resultSha256: null, cleanupVerified: false, status: "interrupted", handshake: null };

/** Private diagnostics only: strip terminal/control codes and retain at most 4KiB. */
export function privateStderr(raw: Buffer): string {
  const clean = stripVTControlCharacters(raw.subarray(0, 4096).toString("utf8"))
    .replace(/\p{Cc}/gu, value => value === "\n" || value === "\t" ? value : "");
  return Buffer.from(clean).subarray(0, 4092).toString("utf8");
}

/** The child's sample precedes receipt, so this translation can only shorten its budget. */
export function translatedDeadline(sample: unknown, deadline: bigint, received = process.hrtime.bigint()): string {
  if (typeof sample !== "string" || !/^[0-9]{1,24}$/u.test(sample)) throw new Error("Invalid observation clock sample");
  const remaining = deadline - received;
  if (remaining <= BigInt(0) || remaining > BigInt(120_000_000_000)) throw new Error("Observation remaining budget is invalid");
  return (BigInt(sample) + remaining).toString();
}
/** Fully awaited process; only a live-held stdout hash selects retained evidence. */
export async function runGradeProcess(input: GradeInvocation): Promise<GradeProcessResult> {
  checkTime(input.deadline);
  const configured = pythonInterpreter();
  if (!path.isAbsolute(configured) || process.platform === "win32") throw new Error("An explicit local POSIX venv is required");
  const python = fs.realpathSync(configured), pythonHash = sha(readBytes(python, 128 * 1024 * 1024));
  const script = path.join(input.root, "scripts/producer/color/grade_project_worker.py");
  const scriptHash = sha(readBytes(script, 128 * 1024));
  const result = await ownedProcess(input, { python, script });
  if (pythonHash !== sha(readBytes(python, 128 * 1024 * 1024)) || scriptHash !== sha(readBytes(script, 128 * 1024)))
    return { ...FAILURE, handshake: result.handshake };
  return result;
}
function ownedProcess(input: GradeInvocation, tools: { python: string; script: string }): Promise<GradeProcessResult> {
  const child = spawn(tools.python, ["-I", "-S", "-B", "-X", `pycache_prefix=${path.join(input.directory, "pycache")}`,
    tools.script, path.join(input.directory, "input.json"), input.inputHash],
  { cwd: input.root, env: { ...process.env }, detached: true, stdio: ["pipe", "pipe", "pipe"] });
  const held = child.pid ? captureProcessIdentity(child.pid) : null;
  const identity = () => {
    if (!child.pid || !held?.startToken || !held.bootSession) return false;
    const current = captureProcessIdentity(child.pid);
    return current.startToken === held.startToken && current.bootSession === held.bootSession;
  };
  return watchGradeProcess(input, child, { identity, now: process.hrtime.bigint,
    signal: signal => { if (child.pid) process.kill(signal === "SIGKILL" ? -child.pid : child.pid, signal); },
    groupAlive: () => !!child.pid && processGroupAlive(child.pid), timer: setTimeout, clear: clearTimeout });
}

export interface GradeProcessControls {
  identity: () => boolean; now: () => bigint; signal: (signal: "SIGUSR1" | "SIGKILL") => void;
  groupAlive: () => boolean; timer: (callback: () => void, ms: number) => ReturnType<typeof setTimeout>;
  clear: (timer: ReturnType<typeof setTimeout>) => void;
}

/** Testable owned-pipe monitor. Unknown identity never authorizes work or a PID kill. */
export function watchGradeProcess(input: GradeInvocation, child: ChildProcessWithoutNullStreams,
  controls: GradeProcessControls): Promise<GradeProcessResult> {
  return new Promise(resolve => new GradeProcessMonitor(input, child, controls, resolve).start());
}

class GradeProcessMonitor {
  private output = "";
  private bytes = 0;
  private done = false;
  private ready = false;
  private expired = false;
  private stderr = Buffer.alloc(0);
  private stderrSeen = 0;
  private identityAtLastProbe: PrivateGradeProcessFailure["identityAtLastProbe"] = "unavailable";
  private exitCode: number | null = null;
  private exitSignal: string | null = null;
  private handshake: GradeProcessResult["handshake"] = null;
  private timers: ReturnType<typeof setTimeout>[] = [];
  private readonly started: bigint;
  constructor(private input: GradeInvocation, private child: ChildProcessWithoutNullStreams,
    private controls: GradeProcessControls, private resolve: (result: GradeProcessResult) => void) {
    this.started = controls.now();
  }
  start(): void {
    this.child.stdout.on("data", this.onOutput);
    this.child.stderr.on("data", this.onErrorOutput);
    this.child.stdin.on("error", this.stop);
    this.child.once("error", this.stop);
    this.child.once("close", this.onClose);
    if (!this.verifiedIdentity()) { this.interrupt("identity-unavailable-before-handshake"); return; }
    const remaining = Number(this.input.deadline - this.controls.now()) / 1e6;
    if (remaining <= 0) { this.stop(); return; }
    this.timers.push(this.controls.timer(() => { if (!this.ready) this.interrupt("startup-deadline"); }, Math.min(5000, remaining)));
    this.timers.push(this.controls.timer(this.expire, remaining));
    // 90s exact-daemon cleanup plus 10s evidence/pipe headroom, from ORIGINAL
    // admission deadline, not a fresh lifecycle budget after source capture.
    this.timers.push(this.controls.timer(() => this.interrupt("lifecycle-deadline"), remaining + 100_000));
  }
  private finish(result: GradeProcessResult): void {
    if (this.done) return;
    this.done = true;
    this.timers.forEach(this.controls.clear);
    this.child.stdout.off("data", this.onOutput); this.child.stderr.off("data", this.onErrorOutput);
    this.output = "";
    this.child.stdout.destroy(); this.child.stderr.destroy(); this.child.stdin.destroy();
    this.resolve(result);
  }
  private signal(signal: "SIGUSR1" | "SIGKILL"): void {
    try { if (this.verifiedIdentity()) this.controls.signal(signal); }
    catch { /* No signal outcome is evidence of exact daemon absence. */ }
  }
  private verifiedIdentity(): boolean {
    const valid = this.controls.identity();
    this.identityAtLastProbe = valid ? "verified" : "unavailable";
    return valid;
  }
  private failed(reason: string): GradeProcessResult {
    return { ...FAILURE, handshake: this.handshake, failure: { reason, exitCode: this.exitCode,
      exitSignal: this.exitSignal, workExpired: this.expired, identityAtLastProbe: this.identityAtLastProbe,
      cleanupState: "unverified", stderr: privateStderr(this.stderr), stderrTruncated: this.stderrSeen > this.stderr.length } };
  }
  private interrupt(reason: string): void {
    if (this.done) return;
    this.signal("SIGKILL");
    this.finish(this.failed(reason));
  }
  private stop = (): void => { this.interrupt("transport-error"); };
  private expire = (): void => {
    if (this.done) return;
    this.expired = true;
    this.signal("SIGUSR1"); // Python masks this only during mandatory cleanup.
  };
  private acceptBytes(chunk: Buffer): boolean {
    if (this.done) return false;
    if (chunk.length > 128 * 1024 - this.bytes) { this.interrupt("output-limit"); return false; }
    this.bytes += chunk.length;
    return true;
  }
  private onErrorOutput = (chunk: Buffer): void => {
    if (this.done) return;
    this.stderrSeen = Math.min(128 * 1024 + 1, this.stderrSeen + chunk.length);
    this.stderr = Buffer.concat([this.stderr, chunk.subarray(0, 4096 - this.stderr.length)]);
    this.acceptBytes(chunk);
  };
  private onOutput = (chunk: Buffer): void => {
    if (!this.acceptBytes(chunk)) return;
    this.output += chunk.toString("utf8");
    if (this.ready || !this.output.includes("\n")) return;
    try { this.acceptHandshake(); } catch { this.interrupt("invalid-or-unverified-handshake"); }
  };
  private acceptHandshake(): void {
    const newline = this.output.indexOf("\n"), row = object(JSON.parse(this.output.slice(0, newline)));
    if (Object.keys(row).join() !== "readyMonotonicNs" || !this.verifiedIdentity()) throw new Error("Unverified worker handshake");
    const received = this.controls.now();
    const deadlineMonotonicNs = translatedDeadline(row.readyMonotonicNs, this.input.deadline, received);
    this.child.stdin.end(JSON.stringify({ deadlineMonotonicNs }) + "\n");
    this.handshake = { remainingMs: Number(this.input.deadline - received) / 1e6, startupMs: Number(received - this.started) / 1e6 };
    this.ready = true; this.output = this.output.slice(newline + 1);
  }
  private onClose = (code: number | null, signal: NodeJS.Signals | null): void => {
    if (this.done) return;
    this.exitCode = code; this.exitSignal = signal;
    if (code !== 0 || signal) { this.finish(this.failed("worker-exit")); return; }
    try {
      if (!this.ready || code !== 0 || signal || this.controls.groupAlive()) throw new Error("Worker closure is unverified");
      const row = object(JSON.parse(this.output));
      if (Object.keys(row).sort().join() !== "cleanupVerified,resultSha256,status"
          || typeof row.resultSha256 !== "string" || !SHA.test(row.resultSha256)
          || typeof row.cleanupVerified !== "boolean" || !["complete", "failed"].includes(String(row.status))) throw new Error("Invalid observation completion");
      if (row.status === "complete" && (this.expired || this.controls.now() >= this.input.deadline)) throw new Error("Late worker completion is not selectable");
      this.finish({ resultSha256: row.resultSha256, cleanupVerified: row.cleanupVerified,
        status: row.status as "complete" | "failed", handshake: this.handshake });
    } catch { this.finish(this.failed(this.expired || this.controls.now() >= this.input.deadline
      ? "late-completion" : "invalid-completion-or-live-process-group")); }
  };
}
