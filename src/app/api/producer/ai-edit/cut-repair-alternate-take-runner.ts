import { mkdtempSync, realpathSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  exactKeys,
  objectValue,
  sha256,
} from "@/lib/producer/contracts/validation";
import { atomicWriteJsonSync } from "@/lib/server/atomic-file";
import type { CutRepairAlternateTakeRequestV1 } from
  "./cut-repair-alternate-take-policy";
import {
  runCutRepairPython,
  type CutRepairProcessResult,
} from "./cut-repair-route-runner";
import { SCRIPTS_DIR } from "../../_lib/spawn-python";

const CONTROLLER = path.join(
  SCRIPTS_DIR, "producer", "edit", "alternate_take_controller.py");
const TIMEOUT_MS = 60_000;

export type CutRepairAlternateTakeResult =
  | {
    ok: true;
    status: "not-applicable-audio-only";
    preparationHash: string;
  }
  | {
    ok: true;
    status: "selection-published";
    preparationHash: string;
    selectionReceiptHash: string;
    selectionHash: string;
    selectionReceiptPath: string;
    candidateSetHash: string;
    selectedCandidateId: string;
    visualSpeechRegion: Record<string, unknown>;
  };

export interface AlternateTakeSelectionInput {
  producerDir: string;
  preparationHash: string;
  manifestPath: string;
  request?: CutRepairAlternateTakeRequestV1;
}

export interface AlternateTakeRunnerServices {
  run: typeof runCutRepairPython;
}

const DEFAULT_SERVICES: AlternateTakeRunnerServices = {
  run: runCutRepairPython,
};

function processValue(result: CutRepairProcessResult): Record<string, unknown> {
  let value: unknown;
  try {
    value = JSON.parse(result.stdout.trim());
  } catch {
    throw new Error(
      result.stderr.trim()
      || "alternate-take controller returned no JSON");
  }
  const row = objectValue(value, "alternate-take controller result");
  if (result.code !== 0) {
    throw new Error(
      typeof row.error === "string"
        ? row.error : "alternate-take selection failed closed");
  }
  return row;
}

function notApplicable(
  row: Record<string, unknown>,
  preparationHash: string,
  request: CutRepairAlternateTakeRequestV1 | undefined,
): CutRepairAlternateTakeResult {
  exactKeys(
    row, ["ok", "status", "preparationHash"],
    ["ok", "status", "preparationHash"],
    "audio-only alternate-take result");
  if (request !== undefined || row.ok !== true
      || row.status !== "not-applicable-audio-only"
      || row.preparationHash !== preparationHash) {
    throw new Error("audio-only alternate-take result is stale");
  }
  return {
    ok: true,
    status: "not-applicable-audio-only",
    preparationHash,
  };
}

function selected(
  row: Record<string, unknown>,
  preparationHash: string,
  request: CutRepairAlternateTakeRequestV1 | undefined,
): CutRepairAlternateTakeResult {
  const keys = [
    "ok", "status", "preparationHash", "selectionReceiptHash",
    "selectionHash", "selectionReceiptPath", "candidateSetHash",
    "selectedCandidateId", "visualSpeechRegion",
  ];
  exactKeys(row, keys, keys, "selected alternate-take result");
  const observedRegion = objectValue(
    row.visualSpeechRegion, "alternate-take visual speech region");
  const regionKeys = ["xPpm", "yPpm", "widthPpm", "heightPpm"] as const;
  exactKeys(
    observedRegion, regionKeys, regionKeys,
    "alternate-take visual speech region");
  if (!request || row.ok !== true || row.status !== "selection-published"
      || row.preparationHash !== preparationHash
      || typeof row.selectionReceiptPath !== "string"
      || !path.isAbsolute(row.selectionReceiptPath)
      || typeof row.selectedCandidateId !== "string"
      || !/^take-[0-9a-f]{24}$/u.test(row.selectedCandidateId)
      || regionKeys.some((key) =>
        observedRegion[key] !== request.visualSpeechRegion[key])) {
    throw new Error("selected alternate-take result is stale");
  }
  return {
    ok: true,
    status: "selection-published",
    preparationHash,
    selectionReceiptHash: sha256(
      row.selectionReceiptHash, "alternate-take receipt hash"),
    selectionHash: sha256(
      row.selectionHash, "alternate-take selection hash"),
    selectionReceiptPath: row.selectionReceiptPath,
    candidateSetHash: sha256(
      row.candidateSetHash, "alternate-take candidate-set hash"),
    selectedCandidateId: row.selectedCandidateId,
    visualSpeechRegion: observedRegion,
  };
}

function parseResult(
  row: Record<string, unknown>,
  preparationHash: string,
  request: CutRepairAlternateTakeRequestV1 | undefined,
): CutRepairAlternateTakeResult {
  if (row.status === "not-applicable-audio-only") {
    return notApplicable(row, preparationHash, request);
  }
  return selected(row, preparationHash, request);
}

/** Invoke the system-owned selector after durable private preparation. */
export async function ensureAlternateTakeSelection(
  input: AlternateTakeSelectionInput,
  services: AlternateTakeRunnerServices = DEFAULT_SERVICES,
): Promise<CutRepairAlternateTakeResult> {
  const expectedHash = sha256(
    input.preparationHash, "alternate-take preparation hash");
  const temporary = mkdtempSync(path.join(
    realpathSync(os.tmpdir()), "sniper-alternate-take-"));
  const requestPath = path.join(temporary, "request.json");
  try {
    atomicWriteJsonSync(requestPath, {
      schemaVersion: 1,
      kind: "cut-repair-alternate-take-controller-input",
      alternateTake: input.request ?? null,
    });
    const result = await services.run(
      CONTROLLER,
      [input.producerDir, expectedHash, input.manifestPath, requestPath],
      "cut repair alternate-take selection",
      TIMEOUT_MS,
    );
    return parseResult(
      processValue(result), expectedHash, input.request);
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
}
