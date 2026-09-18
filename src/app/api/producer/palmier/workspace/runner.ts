import { spawn } from "child_process";
import path from "path";
import { pythonInterpreter, SCRIPTS_DIR } from "../../../_lib/spawn-python";

const SCRIPT = path.join(SCRIPTS_DIR, "producer", "palmier", "draft.py");

export interface DraftResult {
  code: number;
  event: Record<string, unknown>;
  stderr: string;
}

export function draftArgs(input: {
  manifestPath: string;
  dir: string;
  name: string;
  mode: "short" | "longform";
  workingPath?: string;
}): string[] {
  const args = [
    SCRIPT,
    input.manifestPath,
    input.dir,
    "--require-source-set-admission",
    "--name",
    input.name,
    "--mode",
    input.mode,
  ];
  if (input.workingPath) args.push("--working-media", input.workingPath);
  return args;
}

export function createPalmierDraft(input: Parameters<typeof draftArgs>[0]): Promise<DraftResult> {
  return new Promise((resolve) => {
    const child = spawn(pythonInterpreter(), draftArgs(input), {
      cwd: process.cwd(), env: { ...process.env, PYTHONUNBUFFERED: "1" },
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (data) => (stdout += data.toString()));
    child.stderr.on("data", (data) => (stderr += data.toString()));
    child.on("close", (code) => resolve({
      code: code ?? 1,
      event: lastJson(stdout),
      stderr: stderr.trim(),
    }));
    child.on("error", (error) => resolve({ code: 1, event: { error: error.message }, stderr: "" }));
  });
}

function lastJson(output: string): Record<string, unknown> {
  const rows = output.trim().split("\n").reverse();
  for (const row of rows) {
    try {
      const value = JSON.parse(row) as unknown;
      if (value && typeof value === "object" && !Array.isArray(value)) {
        return value as Record<string, unknown>;
      }
    } catch { /* keep scanning NDJSON */ }
  }
  return { error: "Palmier draft produced no status" };
}
