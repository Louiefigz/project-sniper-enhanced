import { spawn } from "node:child_process";
import path from "node:path";
import { pythonInterpreter, SCRIPTS_DIR } from "../../../_lib/spawn-python";

export type PalmierOwnershipAction = "handoff" | "reclaim" | "invalidate";

export interface PalmierOwnershipResult {
  ok?: boolean;
  status?: string;
  error?: string;
  action?: PalmierOwnershipAction;
  ownership?: "sniper" | "palmier";
  freshMirrorRequired?: boolean;
}

const OWNERSHIP = path.join(
  SCRIPTS_DIR,
  "producer",
  "palmier",
  "ownership.py",
);

export function ownershipArgs(dir: string, action: PalmierOwnershipAction): string[] {
  return [OWNERSHIP, dir, `--${action}`];
}

export function runPalmierOwnership(
  dir: string,
  action: PalmierOwnershipAction,
): Promise<{ code: number; verdict: PalmierOwnershipResult }> {
  return new Promise((resolve) => {
    const child = spawn(pythonInterpreter(), ownershipArgs(dir, action), {
      env: { ...process.env },
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (data: Buffer) => (stdout += data.toString()));
    child.stderr.on("data", (data: Buffer) => (stderr = (stderr + data.toString()).slice(-800)));
    child.on("close", (code) => {
      const line = stdout.trim().split("\n").filter(Boolean).pop() ?? "";
      try {
        resolve({ code: code ?? 1, verdict: JSON.parse(line) as PalmierOwnershipResult });
      } catch {
        resolve({ code: code ?? 1, verdict: { error: stderr || "ownership action produced no verdict" } });
      }
    });
    child.on("error", (error) => resolve({ code: 1, verdict: { error: error.message } }));
  });
}
