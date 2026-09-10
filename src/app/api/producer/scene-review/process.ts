import { spawn } from "node:child_process";
import type { ChildProcessWithoutNullStreams } from "node:child_process";
import { pythonInterpreter } from "../../_lib/spawn-python";

export interface ProcessResult {
  stdout: string;
  stderr: string;
}

function terminate(child: ChildProcessWithoutNullStreams): void {
  if (child.exitCode !== null || !child.pid) return;
  try {
    if (process.platform !== "win32") process.kill(-child.pid, "SIGTERM");
    else child.kill("SIGTERM");
  } catch {
    try { child.kill("SIGTERM"); } catch {}
  }
  const hard = setTimeout(() => {
    if (child.exitCode !== null || !child.pid) return;
    try {
      if (process.platform !== "win32") process.kill(-child.pid, "SIGKILL");
      else child.kill("SIGKILL");
    } catch {}
  }, 5_000);
  hard.unref();
}

function limited(previous: string, chunk: Buffer): string {
  return (previous + chunk.toString()).slice(-64_000);
}

/** Run the scene-review CLI with process-tree cancellation. */
export function runSceneReviewProcess(
  args: string[],
  signal?: AbortSignal,
): Promise<ProcessResult> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new Error("scene review was canceled before launch"));
      return;
    }
    const child = spawn(pythonInterpreter(), args, {
      detached: process.platform !== "win32",
      env: { ...process.env },
    });
    let stdout = "";
    let stderr = "";
    const abort = () => terminate(child);
    signal?.addEventListener("abort", abort, { once: true });
    child.stdout.on("data", (chunk: Buffer) => { stdout = limited(stdout, chunk); });
    child.stderr.on("data", (chunk: Buffer) => { stderr = limited(stderr, chunk); });
    child.once("error", reject);
    child.once("close", (code, killedBy) => {
      signal?.removeEventListener("abort", abort);
      if (signal?.aborted) {
        reject(new Error("scene review was canceled"));
      } else if (code !== 0) {
        reject(new Error(
          `scene review exited ${code ?? killedBy ?? "unknown"}: `
            + `${stderr || stdout}`.slice(-2_000),
        ));
      } else {
        resolve({ stdout, stderr });
      }
    });
  });
}
