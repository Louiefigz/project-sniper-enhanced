import { spawn } from "child_process";

export interface CmdResult {
  status: number | null;
  stdout: Buffer;
  stderr: Buffer;
}

/**
 * Async replacement for `spawnSync(cmd, args)`: same shape of result (exit status +
 * buffered stdout/stderr) WITHOUT blocking the Node event loop — a cold
 * filmstrip generation was measured stalling every other route by ~1.7s.
 * Rejects on spawn failure (e.g. binary not on PATH) — fail loudly.
 */
export function runCmd(cmd: string, args: string[]): Promise<CmdResult> {
  return new Promise((resolve, reject) => {
    const proc = spawn(cmd, args);
    const out: Buffer[] = [];
    const err: Buffer[] = [];
    proc.stdout.on("data", (d: Buffer) => out.push(d));
    proc.stderr.on("data", (d: Buffer) => err.push(d));
    proc.on("close", (status) =>
      resolve({ status, stdout: Buffer.concat(out), stderr: Buffer.concat(err) }),
    );
    proc.on("error", reject);
  });
}
