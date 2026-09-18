import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import fs from "node:fs";
import path from "node:path";
import { pipelineRepositoryRoot, pythonInterpreter } from "../../_lib/spawn-python";
import { ColorError, object, UUID } from "./request";
import { hash } from "./files";
import { readBytes } from "../studio/import/files";

export interface ProcessResult { diagnosticId: string | null; cleanupVerified: boolean; interrupted: boolean }
const LIMIT = 256 * 1024;
function alive(pid: number): boolean {
  try { process.kill(-pid, 0); return true; }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ESRCH") return false; throw error; }
}
function signal(pid: number, value: NodeJS.Signals): void {
  try { process.kill(-pid, value); }
  catch (error) { if ((error as NodeJS.ErrnoException).code !== "ESRCH") throw error; }
}
async function terminate(pid: number): Promise<void> {
  signal(pid, "SIGTERM");
  for (let i = 0; i < 240 && alive(pid); i += 1) await delay(250);
  if (alive(pid)) signal(pid, "SIGKILL");
}
/** The HTTP owner awaits this process through cleanup; no unref or detached task. */
export async function runDiagnosticProcess(input: string): Promise<ProcessResult> {
  const root = fs.realpathSync(pipelineRepositoryRoot()), python = pythonInterpreter();
  const script = path.join(root, "src/app/api/producer/color-diagnostic/worker.py");
  if (!path.isAbsolute(python) || !fs.existsSync(python) || process.platform === "win32") {
    throw new ColorError("Configured local venv and POSIX ownership are required", 503);
  }
  const before = hash(readBytes(script, 64 * 1024));
  const result = await ownedProcess({ command: python, args: [script, root, input], cwd: root });
  if (before !== hash(readBytes(script, 64 * 1024))) return { ...result, interrupted: true, cleanupVerified: false };
  return result;
}
interface Invocation { command: string; args: string[]; cwd: string }
function ownedProcess(input: Invocation): Promise<ProcessResult> {
  return new Promise(resolve => {
    const child = spawn(input.command, input.args, { cwd: input.cwd, env: { ...process.env },
      detached: true, stdio: ["ignore", "pipe", "pipe"] });
    let bytes = 0, output = "", ending = false;
    const finish = async (uncertain: boolean) => {
      if (ending) return;
      ending = true; clearTimeout(timer);
      try { if (child.pid && alive(child.pid)) { uncertain = true; await terminate(child.pid); } }
      catch { uncertain = true; }
      child.stdout.destroy(); child.stderr.destroy();
      const fallback = { diagnosticId: null, cleanupVerified: false, interrupted: true };
      if (uncertain) { resolve(fallback); return; }
      try {
        const row = object(JSON.parse(output));
        if (!(row.diagnosticId === null || typeof row.diagnosticId === "string" && UUID.test(row.diagnosticId))
            || typeof row.cleanupVerified !== "boolean") throw new Error("invalid worker result");
        resolve({ diagnosticId: row.diagnosticId as string | null, cleanupVerified: row.cleanupVerified,
          interrupted: row.diagnosticId === null || !row.cleanupVerified });
      } catch { resolve(fallback); }
    };
    const receive = (data: Buffer, stdout: boolean) => {
      bytes += data.length;
      if (bytes > LIMIT) { void finish(true); return; }
      if (stdout) output += data.toString("utf8");
    };
    child.stdout.on("data", (data: Buffer) => receive(data, true));
    child.stderr.on("data", (data: Buffer) => receive(data, false));
    child.once("error", () => void finish(true));
    child.once("close", (code, sig) => void finish(code !== 0 || !!sig));
    const timer = setTimeout(() => void finish(true), 180_000);
  });
}
