import { spawn } from "child_process";
import { accessSync, constants, existsSync, lstatSync, realpathSync } from "fs";
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

/** Explicit installed runtime for an isolated checkout; never creates a venv or falls back. */
export function explicitVenvPython(root: string): string {
  if (!root || root.length > 4096 || /[\0\r\n\\]/u.test(root) || !path.isAbsolute(root)
      || path.normalize(root) !== root || realpathSync(root) !== root || !lstatSync(root).isDirectory()) {
    throw new Error("Explicit Python venv root must be an existing canonical absolute directory");
  }
  const bin = path.join(root, "bin"), candidate = path.join(bin, "python3"), config = path.join(root, "pyvenv.cfg");
  const metadata = lstatSync(config);
  if (realpathSync(bin) !== bin || !lstatSync(bin).isDirectory()
      || !metadata.isFile() || metadata.isSymbolicLink() || metadata.nlink !== 1
      || metadata.size < 1 || metadata.size > 64 * 1024 || !lstatSync(realpathSync(candidate)).isFile()) {
    throw new Error("Explicit Python venv must have a regular config and resolved interpreter; no ambient fallback");
  }
  accessSync(candidate, constants.X_OK);
  return candidate; // Preserve venv launch semantics; existing owners bind resolved binary and config SHA.
}

export const SCRIPTS_DIR = scriptsDir();

/** Immutable run tree in detached Auto Edit workers; live repo elsewhere. */
export function pipelineRepositoryRoot(): string {
  const pinned = process.env.SNIPER_PIPELINE_ROOT;
  return pinned && path.isAbsolute(pinned) ? pinned : process.cwd();
}

export function pythonInterpreter(): string {
  const selected = process.env.SNIPER_PYTHON_VENV_ROOT;
  if (selected !== undefined) return explicitVenvPython(selected);
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
