import { spawn } from "child_process";
import { existsSync } from "fs";
import path from "path";

// Computed at call time, not at module load, so Turbopack's static analyzer
// doesn't follow the .venv symlink chain (which can escape the project root
// and panic the bundler).
function scriptsDir(): string {
  return path.join(pipelineRepositoryRoot(), ...["scripts"]);
}

function venvPython(): string {
  return path.join(process.cwd(), ...[".venv", "bin", "python3"]);
}

export const SCRIPTS_DIR = scriptsDir();

/** Immutable run tree in detached Auto Edit workers; live repo elsewhere. */
export function pipelineRepositoryRoot(): string {
  const pinned = process.env.SNIPER_PIPELINE_ROOT;
  return pinned && path.isAbsolute(pinned) ? pinned : process.cwd();
}

export function pythonInterpreter(): string {
  const candidate = venvPython();
  return existsSync(candidate) ? candidate : "python3";
}

/**
 * Run a Python script and return its stdout as a string.
 * Rejects with a descriptive error on non-zero exit.
 */
export function spawnPython(scriptPath: string, args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    const proc = spawn(pythonInterpreter(), [scriptPath, ...args], { env: { ...process.env } });

    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });

    proc.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(`Script exited with code ${code}:\n${stderr || stdout}`));
      } else {
        resolve(stdout);
      }
    });

    proc.on("error", (err) => reject(err));
  });
}
