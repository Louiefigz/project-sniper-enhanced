/** TEST-only blocked supervisor pipe. No claim or inner worker exists at spawn. */
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import path from "node:path";
import { watchGradeProcess, translatedDeadline, type GradeInvocation } from "../../../src/lib/server/grade-observation-process";
import { checkTime } from "../../../src/lib/server/grade-observation-store";
import { exactIdentity, groupState } from "./live_grade_v2_lifecycle";
import type { V2LiveReturn } from "./live_grade_v2_finalization";

export interface V2Supervisor {
  child: ChildProcessWithoutNullStreams; identity: ReturnType<typeof exactIdentity>; deadlineNs: string;
  closed: { code: number | null; signal: string | null; absent: boolean }; close: Promise<void>;
}
async function waitClose(close: Promise<void>, ms: number): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try { await Promise.race([close, new Promise<void>(resolve => { timer = setTimeout(resolve, ms); })]); }
  finally { clearTimeout(timer); }
}
function ready(child: ChildProcessWithoutNullStreams, deadline: bigint): Promise<string> {
  return new Promise((resolve, reject) => {
    let raw = "";
    const cleanup = () => { clearTimeout(timer); child.stdout.off("data", data); child.off("error", failure); child.off("close", failure); };
    const failure = () => { cleanup(); reject(new Error("Blocked supervisor startup failed")); };
    const data = (part: Buffer) => {
      raw += part.toString("utf8");
      if (raw.length > 4096) { failure(); return; }
      if (!raw.includes("\n")) return;
      try {
        const value = JSON.parse(raw);
        if (Object.keys(value).sort().join() !== "readyMonotonicNs,supervisorReady" || value.supervisorReady !== child.pid)
          throw new Error("Invalid supervisor ready");
        const translated = translatedDeadline(value.readyMonotonicNs, deadline);
        cleanup(); resolve(translated);
      } catch { failure(); }
    };
    const timer = setTimeout(failure, Math.max(1, Math.min(5000, Number(deadline - process.hrtime.bigint()) / 1e6)));
    child.stdout.on("data", data); child.once("error", failure); child.once("close", failure);
  });
}
export async function startSupervisor(input: { root: string; python: string; deadline: bigint }): Promise<V2Supervisor> {
  checkTime(input.deadline);
  const waitMs = Math.floor(Number(input.deadline - process.hrtime.bigint()) / 1e6);
  const script = path.join(input.root, "scripts/producer/tests/live_grade_v2_supervisor.py");
  const child = spawn(input.python, ["-I", "-S", "-B", script, String(process.pid), String(waitMs)],
    { cwd: input.root, env: { ...process.env }, detached: true, stdio: ["pipe", "pipe", "pipe"] });
  const closed = { code: null as number | null, signal: null as string | null, absent: false };
  const close = new Promise<void>(resolve => child.once("close", (code, signal) => {
    Object.assign(closed, { code, signal, absent: !!child.pid && groupState(child.pid) === "absent" }); resolve();
  }));
  try {
    const deadlineNs = await ready(child, input.deadline);
    const identity = exactIdentity(child.pid!); checkTime(input.deadline);
    return { child, identity, deadlineNs, closed, close };
  } catch (error) {
    // No permit was sent: EOF cannot fork. Wait for the bounded blocked child.
    child.stdin.end(); await waitClose(close, 1500);
    if (child.pid && groupState(child.pid) !== "absent") throw new AggregateError([error], "Unstarted supervisor absence unproved");
    throw error;
  }
}
function same(value: V2Supervisor): boolean {
  try { return JSON.stringify(exactIdentity(value.identity.pid)) === JSON.stringify(value.identity); }
  catch { return false; }
}

/** Monitor is attached before the one permitted activation line is sent. */
export async function invokeSupervisor(value: V2Supervisor, input: GradeInvocation,
  permit: { directory: string; lifecycleSha256: string; claimPath: string; claimSha256: string }): Promise<V2LiveReturn> {
  const logs = { stdout: Buffer.alloc(0), stderr: Buffer.alloc(0) }, child = value.child;
  for (const channel of ["stdout", "stderr"] as const) child[channel].on("data", (part: Buffer) => {
    logs[channel] = Buffer.concat([logs[channel], part.subarray(0, 128 * 1024 - logs[channel].length)]);
  });
  const pending = watchGradeProcess(input, child, { identity: () => same(value), now: process.hrtime.bigint,
    signal: signal => { if (same(value)) process.kill(signal === "SIGKILL" ? -value.identity.pid : value.identity.pid, signal); },
    groupAlive: () => groupState(value.identity.pid) !== "absent", timer: setTimeout, clear: clearTimeout });
  child.stdin.write(JSON.stringify(permit) + "\n");
  const held = await pending;
  await waitClose(value.close, 2000);
  return { held, closed: { ...value.closed, absent: groupState(value.identity.pid) === "absent" },
    pid: value.identity.pid, stdout: logs.stdout.toString("utf8"), stderr: logs.stderr.toString("utf8") };
}

/** Setup errors close the unactivated pipe; no container can have been launched. */
export async function closeBlockedSupervisor(value: V2Supervisor): Promise<void> {
  value.child.stdin.end(); await waitClose(value.close, 1500);
  if (groupState(value.identity.pid) !== "absent") throw new Error("Blocked supervisor absence unproved");
}
