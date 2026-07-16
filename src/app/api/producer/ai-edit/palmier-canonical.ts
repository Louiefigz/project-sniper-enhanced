import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { pythonInterpreter, SCRIPTS_DIR } from "../../_lib/spawn-python";
import { palmierStatePath } from "../palmier/_lib";

export interface PalmierAuthorityVerdict {
  ok?: boolean;
  status?: string;
  error?: string;
  timelineId?: string;
  fingerprint?: string;
  authority?: "palmier";
}

interface GuardDependencies {
  stateExists: (dir: string) => boolean;
  run: (dir: string) => Promise<{ code: number; verdict: PalmierAuthorityVerdict }>;
}

const GUARD_SCRIPT = path.join(
  SCRIPTS_DIR, "producer", "palmier", "timeline_authority_cli.py",
);

const DEFAULT_DEPENDENCIES: GuardDependencies = {
  stateExists: (dir) => existsSync(palmierStatePath(dir)),
  run: runPalmierAuthorityGuard,
};

export class PalmierCanonicalError extends Error {
  constructor(message: string, readonly statusCode: number) {
    super(message);
  }
}

/** Fail closed before a plan-only model can erase a visible Palmier revision. */
export async function guardPalmierCanonicalForAiEdit(
  dir: string,
  dependencies: GuardDependencies = DEFAULT_DEPENDENCIES,
): Promise<void> {
  if (!dependencies.stateExists(dir)) return;
  const result = await dependencies.run(dir);
  if (result.code === 0 && result.verdict.ok === true) return;
  const message = result.verdict.error
    || "Could not prove the visible Palmier timeline is the saved baseline.";
  const statusCode = result.code === 65 || result.code === 75 ? 409 : 503;
  throw new PalmierCanonicalError(message, statusCode);
}

export function runPalmierAuthorityGuard(
  dir: string,
): Promise<{ code: number; verdict: PalmierAuthorityVerdict }> {
  return new Promise((resolve) => {
    const child = spawn(pythonInterpreter(), [GUARD_SCRIPT, dir], {
      env: { ...process.env },
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (data: Buffer) => (stdout += data.toString()));
    child.stderr.on("data", (data: Buffer) => {
      stderr = (stderr + data.toString()).slice(-800);
    });
    child.on("close", (code) => {
      const line = stdout.trim().split("\n").filter(Boolean).pop() ?? "";
      try {
        resolve({ code: code ?? 1, verdict: JSON.parse(line) as PalmierAuthorityVerdict });
      } catch {
        resolve({ code: code ?? 1,
          verdict: { error: stderr || "Palmier authority guard produced no verdict" } });
      }
    });
    child.on("error", (error) => resolve({
      code: 1, verdict: { error: error.message },
    }));
  });
}
