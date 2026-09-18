import { spawnSync } from "node:child_process";
import path from "node:path";
import {
  pythonInterpreter,
  SCRIPTS_DIR,
} from "@/app/api/_lib/spawn-python";

const CLI = path.join(
  SCRIPTS_DIR,
  "producer",
  "current_render_graph_candidate_cli.py",
);
const TIMEOUT_MS = 120_000;
const MAX_OUTPUT_BYTES = 1024 * 1024;

export interface CandidateCommandResult {
  ok?: unknown;
  error?: unknown;
  graphHash?: unknown;
}

export type CandidateCommand = (args: string[]) => CandidateCommandResult;

export function runCandidateCommand(args: string[]): CandidateCommandResult {
  const result = spawnSync(pythonInterpreter(), [CLI, ...args], {
    encoding: "utf8",
    timeout: TIMEOUT_MS,
    maxBuffer: MAX_OUTPUT_BYTES,
    env: { ...process.env },
  });
  if (result.error) throw result.error;
  let value: CandidateCommandResult = {};
  try {
    value = JSON.parse(result.stdout.trim()) as CandidateCommandResult;
  } catch {
    throw new Error(
      result.stderr.trim() || "render graph candidate gate returned no JSON",
    );
  }
  if (result.status !== 0 || value.ok !== true) {
    throw new Error(
      typeof value.error === "string"
        ? value.error
        : result.stderr.trim() || "render graph candidate gate failed",
    );
  }
  return value;
}

export function candidateArgs(
  action: "verify" | "activate" | "candidate-active" | "rollback",
  candidate: string,
  producerDir: string,
  expectedSha256: string,
): string[] {
  return [
    action,
    "--producer-dir", producerDir,
    "--candidate", candidate,
    "--final", path.join(producerDir, "final.mp4"),
    "--expected-sha256", expectedSha256,
  ];
}

export function activateOrResolve(
  input: {
    candidate: string;
    producerDir: string;
    expectedSha256: string;
    command: CandidateCommand;
  },
): void {
  const args = (action: "activate" | "candidate-active") => candidateArgs(
    action, input.candidate, input.producerDir, input.expectedSha256);
  try {
    input.command(args("activate"));
  } catch (trigger) {
    try {
      input.command(args("candidate-active"));
    } catch {
      throw trigger;
    }
  }
}

export function verifiedGraphHash(value: CandidateCommandResult): string {
  if (typeof value.graphHash !== "string"
      || !/^[0-9a-f]{64}$/u.test(value.graphHash)) {
    throw new Error("render graph candidate verification returned no graph hash");
  }
  return value.graphHash;
}
