import { execFile } from "node:child_process";
import path from "node:path";
import { pythonInterpreter, SCRIPTS_DIR } from "../../../_lib/spawn-python";
import { ImportError, type Capture, type DiffResult, type OriginalSession } from "./model";
import { withBridgeInput } from "./files";

const BRIDGE = path.join(process.cwd(), "src", "app", "api", "producer", "studio", "import", "bridge.py");

function execute(file: string): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    execFile(pythonInterpreter(), [BRIDGE, path.join(SCRIPTS_DIR, "producer"), file], {
      timeout: 20_000, maxBuffer: 8 * 1024 * 1024, encoding: "utf8",
    }, (error, stdout, stderr) => {
      if (error) return reject(new ImportError(`Studio import inspection failed: ${(stderr || error.message).slice(-1_200)}`, 502));
      try { resolve(JSON.parse(stdout)); }
      catch { reject(new ImportError("Studio import inspection returned invalid JSON", 502)); }
    });
  });
}

export async function reconstructOriginal(dir: string): Promise<{ host: string; instances: Record<string, string> }> {
  const result = await withBridgeInput(dir, { dir, action: "baseline" }, execute);
  if (Array.isArray(result.blockers) && result.blockers.length) throw new ImportError(result.blockers.join("; "));
  if (typeof result.host !== "string" || !result.instances) throw new ImportError("Original Studio baseline is unavailable");
  return result as { host: string; instances: Record<string, string> };
}

export async function inspectDiff(dir: string, session: OriginalSession, capture: Capture): Promise<DiffResult> {
  const result = await withBridgeInput(dir, { dir, session, capture, action: "diff" }, execute);
  return result as unknown as DiffResult;
}
