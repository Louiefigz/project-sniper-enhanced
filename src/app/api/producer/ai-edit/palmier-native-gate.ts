import { randomUUID } from "node:crypto";
import { execFile } from "node:child_process";
import { rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { pythonInterpreter, SCRIPTS_DIR } from "../../_lib/spawn-python";

const GATE_CLI = path.join(
  SCRIPTS_DIR, "producer", "palmier", "native_gate_cli.py",
);
const GATE_TIMEOUT_MS = 2 * 60 * 1000;

export interface PalmierNativeGateInput {
  dir: string;
  planPath: string;
  request: string;
  expectedLanes: string[];
  cliPath?: string;
  envelopePath?: string;
}

interface GateVerdict {
  ok?: boolean;
  status?: string;
  error?: string;
}

function executeGate(
  cliPath: string,
  args: string[],
  signal?: AbortSignal,
): Promise<GateVerdict> {
  return new Promise((resolve, reject) => {
    execFile(pythonInterpreter(), [cliPath, ...args], {
      cwd: process.cwd(), env: { ...process.env }, timeout: GATE_TIMEOUT_MS,
      maxBuffer: 64 * 1024, signal,
    }, (error, stdout, stderr) => {
      const line = stdout.trim().split("\n").filter(Boolean).pop() ?? "";
      let verdict: GateVerdict;
      try { verdict = JSON.parse(line) as GateVerdict; } catch {
        reject(new Error(stderr.trim() || error?.message || "Native gate produced no verdict"));
        return;
      }
      if (error || verdict.ok !== true || verdict.status !== "native-gate-passed") {
        reject(new Error(verdict.error || stderr.trim() || error?.message || "Native gate rejected the edit"));
        return;
      }
      resolve(verdict);
    });
  });
}

/** Run the pure native gate against the reconciled authority before criticism. */
export async function runPalmierNativeGate(
  input: PalmierNativeGateInput,
  signal?: AbortSignal,
): Promise<void> {
  const ownEnvelope = !input.envelopePath;
  const envelopePath = input.envelopePath ?? path.join(
    input.dir, `.palmier-native-gate.${randomUUID()}.json`,
  );
  const envelope = {
    schemaVersion: 1,
    request: input.request,
    expectedLanes: input.expectedLanes,
  };
  try {
    if (ownEnvelope) {
      writeFileSync(envelopePath, `${JSON.stringify(envelope, null, 2)}\n`, {
        flag: "wx", mode: 0o600,
      });
    }
    await executeGate(
      input.cliPath ?? GATE_CLI,
      [input.dir, input.planPath, envelopePath],
      signal,
    );
  } finally {
    if (ownEnvelope) rmSync(envelopePath, { force: true });
  }
}

/** Create the exact gate authority reused by the locked mutation executor. */
export function writePalmierNativeGateEnvelope(
  input: Pick<PalmierNativeGateInput, "dir" | "request" | "expectedLanes">,
): string {
  const destination = path.join(
    input.dir, `.palmier-native-gate.${randomUUID()}.json`,
  );
  writeFileSync(destination, `${JSON.stringify({
    schemaVersion: 1,
    request: input.request,
    expectedLanes: input.expectedLanes,
  }, null, 2)}\n`, { flag: "wx", mode: 0o600 });
  return destination;
}
