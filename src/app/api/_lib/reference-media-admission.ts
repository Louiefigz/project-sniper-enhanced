import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import {
  pythonInterpreter,
  SCRIPTS_DIR,
} from "./spawn-python";
import {
  shouldDetachProcessGroup,
  terminateProcessTree,
  trackProcessTree,
} from "./child-process-lifecycle";
import { ReferenceMediaError } from "./reference-intake-policy";

const SCRIPT = path.join(
  SCRIPTS_DIR, "producer", "headless", "admit_external_media_cli.py",
);
const SHA256 = /^[0-9a-f]{64}$/u;
const ADMISSION_KEYS = [
  "durationSeconds", "mediaKind", "policy", "receiptPath",
  "receiptSha256", "schemaVersion", "sizeBytes", "snapshotPath",
  "snapshotSha256",
].sort();
export const REFERENCE_ADMISSION_TIMEOUT_MS = 25 * 60 * 1_000;

export interface ReferenceAdmission {
  schemaVersion: 1;
  policy: "sniper-reference-media-admission-v1";
  snapshotPath: string;
  snapshotSha256: string;
  sizeBytes: number;
  mediaKind: "timed-media";
  durationSeconds: number;
  receiptPath: string;
  receiptSha256: string;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

export function parseReferenceAdmission(
  value: unknown,
  store: string,
): ReferenceAdmission {
  const row = record(value);
  if (!validAdmissionShape(row, store)) {
    throw new ReferenceMediaError(
      "sandbox returned malformed reference admission authority",
    );
  }
  const admission = row as unknown as ReferenceAdmission;
  assertAdmissionFiles(admission);
  return admission;
}

function validAdmissionShape(
  row: Record<string, unknown>,
  store: string,
): boolean {
  const expectedSnapshot = typeof row.snapshotSha256 === "string"
    ? path.join(path.resolve(store), `${row.snapshotSha256}.media`)
    : "";
  const expectedReceipt = typeof row.receiptSha256 === "string"
    ? path.join(
      path.resolve(store), ".sniper-reference-admission",
      `${row.receiptSha256}.json`,
    )
    : "";
  return JSON.stringify(Object.keys(row).sort()) === JSON.stringify(ADMISSION_KEYS)
    && row.schemaVersion === 1
    && row.policy === "sniper-reference-media-admission-v1"
    && row.mediaKind === "timed-media"
    && typeof row.snapshotPath === "string"
    && typeof row.receiptPath === "string"
    && typeof row.snapshotSha256 === "string"
    && typeof row.receiptSha256 === "string"
    && SHA256.test(row.snapshotSha256)
    && SHA256.test(row.receiptSha256)
    && Number.isSafeInteger(row.sizeBytes) && Number(row.sizeBytes) > 0
    && Number.isFinite(row.durationSeconds)
    && Number(row.durationSeconds) > 0
    && Number(row.durationSeconds) <= 3600
    && row.snapshotPath === expectedSnapshot
    && row.receiptPath === expectedReceipt;
}

function assertAdmissionFiles(admission: ReferenceAdmission): void {
  try {
    [admission.snapshotPath, admission.receiptPath].forEach((file) => {
      const stat = fs.lstatSync(file);
      if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1) {
        throw new ReferenceMediaError(
          "reference admission authority is not one regular file",
        );
      }
    });
    if (fs.statSync(admission.snapshotPath).size !== admission.sizeBytes) {
      throw new ReferenceMediaError(
        "reference snapshot size changed after admission",
      );
    }
  } catch (error) {
    if (error instanceof ReferenceMediaError) throw error;
    throw new ReferenceMediaError(
      `reference admission authority is unavailable: ${(error as Error).message}`,
    );
  }
}

function finalObject(stdout: string): Record<string, unknown> {
  for (const line of stdout.trim().split("\n").reverse()) {
    try {
      return record(JSON.parse(line));
    } catch {}
  }
  return {};
}

type AdmissionFinish = (
  error?: Error,
  value?: ReferenceAdmission,
) => void;

interface AdmissionResult {
  code: number | null;
  stdout: string;
  stderr: string;
  terminationError: ReferenceMediaError | null;
  store: string;
  finish: AdmissionFinish;
}

function finishAdmissionProcess(result: AdmissionResult): void {
  if (result.terminationError) {
    result.finish(result.terminationError);
    return;
  }
  const value = finalObject(result.stdout);
  if (result.code !== 0 || value.ok !== true) {
    const detail = typeof value.error === "string"
      ? value.error
      : result.stderr || `sandbox admission exited ${String(result.code)}`;
    result.finish(new ReferenceMediaError(detail));
    return;
  }
  const authority = { ...value };
  delete authority.ok;
  try {
    result.finish(undefined, parseReferenceAdmission(authority, result.store));
  } catch (error) {
    result.finish(error as Error);
  }
}

function spawnReferenceAdmission(source: string, store: string) {
  return trackProcessTree(spawn(
    pythonInterpreter(), [SCRIPT, source, "--store", store],
    { env: { ...process.env }, detached: shouldDetachProcessGroup() },
  ));
}

export function admitReferenceMedia(
  source: string,
  store: string,
  signal?: AbortSignal,
): Promise<ReferenceAdmission> {
  return new Promise((resolve, reject) => {
    const child = spawnReferenceAdmission(source, store);
    let stdout = "";
    let stderr = "";
    let settled = false;
    let terminationError: ReferenceMediaError | null = null;
    const finish = (error?: Error, value?: ReferenceAdmission) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      if (error) reject(error);
      else resolve(value as ReferenceAdmission);
    };
    const abort = () => {
      terminationError ??=
        new ReferenceMediaError("reference admission was cancelled");
      terminateProcessTree(child, 20_000);
    };
    const timer = setTimeout(() => {
      terminationError ??=
        new ReferenceMediaError("reference admission exceeded twenty-five minutes");
      terminateProcessTree(child, 20_000);
    }, REFERENCE_ADMISSION_TIMEOUT_MS);
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
    child.stdout.on("data", (data: Buffer) => {
      stdout += data.toString();
    });
    child.stderr.on("data", (data: Buffer) => {
      stderr = (stderr + data.toString()).slice(-2_000);
    });
    child.on("error", (error) => finish(new ReferenceMediaError(error.message)));
    child.on("close", (code) => {
      finishAdmissionProcess({
        code, stdout, stderr, terminationError, store, finish,
      });
    });
  });
}
