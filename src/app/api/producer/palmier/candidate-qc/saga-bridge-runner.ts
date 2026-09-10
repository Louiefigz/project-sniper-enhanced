import { spawnSync } from "node:child_process";
import {
  parsePalmierSagaCandidateProofV1,
  parsePalmierSagaObservationV1,
} from "@/lib/producer/contracts/palmier-saga-bridge";
import type { PalmierNativeSagaBridgeV1 } from
  "@/lib/server/producer-palmier-native-commit";
import { pythonInterpreter } from "../../../_lib/spawn-python";

const BRIDGE_TIMEOUT_MS = 90_000;

function parsedObject(line: string): Record<string, unknown> | null {
  try {
    const value = JSON.parse(line) as unknown;
    return value && typeof value === "object" && !Array.isArray(value)
      ? value as Record<string, unknown> : null;
  } catch {
    return null;
  }
}

function lastObject(stdout: string): Record<string, unknown> {
  for (const line of stdout.trim().split("\n").filter(Boolean).reverse()) {
    const value = parsedObject(line);
    if (value) return value;
  }
  throw new Error("Palmier saga bridge returned no JSON event");
}

function runBridge(
  cliPath: string,
  producerDir: string,
  action: "--saga-prove" | "--saga-observe" | "--promote",
  signal?: AbortSignal,
): Record<string, unknown> {
  if (signal?.aborted) throw new Error("Palmier saga bridge was cancelled");
  const result = spawnSync(
    pythonInterpreter(),
    [cliPath, producerDir, action],
    {
      cwd: process.cwd(),
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
      encoding: "utf8",
      maxBuffer: 4 * 1024 * 1024,
      timeout: BRIDGE_TIMEOUT_MS,
    },
  );
  if (result.error) throw result.error;
  const event = lastObject(result.stdout ?? "");
  if (result.status !== 0 || event.ok !== true) {
    const detail = String(event.error ?? result.stderr
      ?? `Palmier saga bridge exited ${String(result.status)}`);
    throw new Error(detail);
  }
  if (signal?.aborted) {
    throw new Error("Palmier saga bridge completed after cancellation");
  }
  return event;
}

/** Bind the saga only to the candidate's pinned native-QC executable. */
export function createPalmierNativeSagaBridge(
  producerDir: string,
  cliPath: string,
  signal?: AbortSignal,
): PalmierNativeSagaBridgeV1 {
  return {
    proveCandidate: () => parsePalmierSagaCandidateProofV1(
      runBridge(cliPath, producerDir, "--saga-prove", signal),
    ),
    observeHead: () => parsePalmierSagaObservationV1(
      runBridge(cliPath, producerDir, "--saga-observe", signal),
    ),
    promoteCandidate: (expectedParentId, candidateId) => {
      const event = runBridge(
        cliPath, producerDir, "--promote", signal);
      const parent = event.parent as Record<string, unknown> | undefined;
      const approved = event.approvedHead as
        Record<string, unknown> | undefined;
      if (event.status !== "candidate-promoted"
          || parent?.timelineId !== expectedParentId
          || approved?.timelineId !== candidateId) {
        throw new Error(
          "Palmier saga promotion did not select the reserved candidate");
      }
    },
  };
}
