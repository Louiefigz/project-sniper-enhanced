import { spawn } from "node:child_process";
import path from "node:path";
import { pythonInterpreter, SCRIPTS_DIR } from "../../../_lib/spawn-python";
import { guardProjectMutation, mutationProjectRoot } from "../../../_lib/project-mutation";

interface RecoveryVerdict {
  ok?: boolean;
  status?: string;
  error?: string;
}

const NATIVE_CLI = path.join(
  SCRIPTS_DIR, "producer", "palmier", "native_delta_cli.py",
);

function runRecovery(dir: string): Promise<{ code: number; verdict: RecoveryVerdict }> {
  return new Promise((resolve) => {
    const child = spawn(pythonInterpreter(), [NATIVE_CLI, dir, "--recover-parent"], {
      env: { ...process.env },
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (data: Buffer) => (stdout += data.toString()));
    child.stderr.on("data", (data: Buffer) => (stderr = (stderr + data.toString()).slice(-800)));
    child.on("close", (code) => {
      const line = stdout.trim().split("\n").filter(Boolean).pop() ?? "";
      try {
        resolve({ code: code ?? 1, verdict: JSON.parse(line) as RecoveryVerdict });
      } catch {
        resolve({ code: code ?? 1, verdict: { error: stderr || "parent recovery produced no verdict" } });
      }
    });
    child.on("error", (error) => resolve({ code: 1, verdict: { error: error.message } }));
  });
}

/** Restore a quarantined parent under both the web writer lease and MCP lock. */
export async function recoverQuarantinedParent(dir: string): Promise<void> {
  const guarded = guardProjectMutation({
    projectRoot: mutationProjectRoot(dir),
    producerDir: dir,
    operation: "restoring a quarantined Palmier parent",
  });
  if (guarded.response) {
    throw new Error("Another project operation is active; wait for it before restoring the parent.");
  }
  try {
    const result = await runRecovery(dir);
    if (result.code !== 0 || result.verdict.ok !== true) {
      throw new Error(result.verdict.error || "Palmier could not verify the preserved parent.");
    }
  } finally {
    guarded.lease.release();
  }
}
