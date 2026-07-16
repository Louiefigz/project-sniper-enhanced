import { spawn } from "child_process";
import path from "path";
import { pythonInterpreter, SCRIPTS_DIR } from "../../../_lib/spawn-python";
import { findManifest } from "../_lib";

const PUSH = path.join(SCRIPTS_DIR, "producer", "palmier", "push.py");

export interface CurrentPreflight {
  ok?: boolean;
  planHash?: string;
  blocked?: string;
}

/** Recompute the canonical disk-plan hash and parity without touching Palmier. */
export async function currentPreflight(dir: string): Promise<CurrentPreflight> {
  const planPath = path.join(dir, "edit_plan.json");
  const manifestPath = findManifest(dir);
  if (!manifestPath) throw new Error("No asset manifest exists for this project.");
  const result = await run([PUSH, planPath, manifestPath, "--preflight"]);
  const line = result.stdout.trim().split("\n").filter(Boolean).pop() ?? "";
  try {
    return JSON.parse(line) as CurrentPreflight;
  } catch {
    throw new Error(`Palmier preflight produced no verdict (exit ${result.code}).`);
  }
}

function run(args: string[]): Promise<{ stdout: string; code: number }> {
  return new Promise((resolve) => {
    const child = spawn(pythonInterpreter(), args, { env: { ...process.env } });
    let stdout = "";
    child.stdout.on("data", (data: Buffer) => (stdout += data.toString()));
    child.stderr.on("data", (data: Buffer) => process.stderr.write(data));
    child.on("close", (code) => resolve({ stdout, code: code ?? 1 }));
    child.on("error", () => resolve({ stdout, code: 1 }));
  });
}
