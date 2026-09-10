import { spawn } from "node:child_process";
import { mkdtempSync, realpathSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { atomicWriteJsonSync } from "@/lib/server/atomic-file";
import {
  pythonInterpreter,
  SCRIPTS_DIR,
} from "../../_lib/spawn-python";
import type { CutRepairDirectiveV1 } from "./cut-repair-route-policy";

const PRODUCER_ROOT = path.join(SCRIPTS_DIR, "producer");
const MATERIALIZER = path.join(
  PRODUCER_ROOT, "edit", "cut_repair_context_materialize.py");
const ANALYZER = path.join(
  PRODUCER_ROOT, "edit", "cut_repair_route_cli.py");
const TIMEOUT_MS = 30_000;
const MAX_OUTPUT_BYTES = 2 * 1024 * 1024;

export interface CutRepairProcessResult {
  code: number | null;
  stdout: string;
  stderr: string;
}

function boundedAppend(
  current: Buffer,
  data: Buffer,
  label: string,
  abort: (error: Error) => void,
): Buffer {
  const next = Buffer.concat([current, data]);
  if (next.length > MAX_OUTPUT_BYTES) {
    abort(new Error(`${label} exceeded its output bound`));
  }
  return next;
}

export function runCutRepairPython(
  script: string,
  args: string[],
  label: string,
  timeoutMs = TIMEOUT_MS,
): Promise<CutRepairProcessResult> {
  return new Promise((resolve, reject) => {
    const existing = process.env.PYTHONPATH;
    const pythonPath = [PRODUCER_ROOT, existing].filter(Boolean).join(path.delimiter);
    const child = spawn(
      pythonInterpreter(),
      [script, ...args],
      {
        cwd: PRODUCER_ROOT,
        env: { ...process.env, PYTHONPATH: pythonPath },
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    let stdout: Buffer = Buffer.alloc(0);
    let stderr: Buffer = Buffer.alloc(0);
    let settled = false;
    const finish = (error?: Error, code: number | null = null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) reject(error);
      else resolve({
        code,
        stdout: stdout.toString("utf8"),
        stderr: stderr.toString("utf8"),
      });
    };
    const abort = (error: Error) => {
      child.kill("SIGKILL");
      finish(error);
    };
    child.stdout.on("data", (data: Buffer) => {
      stdout = boundedAppend(stdout, data, label, abort);
    });
    child.stderr.on("data", (data: Buffer) => {
      stderr = boundedAppend(stderr, data, label, abort);
    });
    child.on("error", (error) => finish(error));
    child.on("close", (code) => finish(undefined, code));
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      finish(new Error(`${label} timed out`));
    }, timeoutMs);
  });
}

function materializationFailure(result: CutRepairProcessResult): void {
  if (result.code === 0) return;
  let detail = result.stderr.trim();
  try {
    const row = JSON.parse(result.stdout.trim()) as { error?: unknown };
    if (typeof row.error === "string") detail = row.error;
  } catch {
    // A bounded non-JSON failure remains a closed controller failure.
  }
  throw new Error(detail || `cut repair context materializer exited ${result.code}`);
}

function parseResult(result: CutRepairProcessResult): Record<string, unknown> {
  let value: unknown;
  try {
    value = JSON.parse(result.stdout.trim());
  } catch {
    throw new Error(
      result.stderr.trim() || "cut repair controller returned no JSON result",
    );
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("cut repair controller returned a malformed result");
  }
  const row = value as Record<string, unknown>;
  if (result.code !== 0) {
    throw new Error(
      typeof row.error === "string"
        ? row.error
        : result.stderr.trim() || `cut repair controller exited ${result.code}`,
    );
  }
  if (row.operation !== "cut.restoreSpeech"
      || row.routeStatus !== "analysis-only-no-mutation"
      || !["eligible", "already-complete", "NON_RIPPLE_IMPOSSIBLE"]
        .includes(String(row.status))) {
    throw new Error("cut repair controller result is outside the closed route");
  }
  return row;
}

export interface CutRepairAnalysisWorkspace {
  analysis: Record<string, unknown>;
  contextPath: string;
  directivePath: string;
}

/**
 * Hold the controller-derived context open only for a bounded consumer.
 * Nothing from the HTTP request can inject evidence or media hashes.
 */
export async function withCutRepairAnalysis<T>(
  producerDir: string,
  manifestPath: string,
  directive: CutRepairDirectiveV1,
  consume: (workspace: CutRepairAnalysisWorkspace) => Promise<T>,
): Promise<T> {
  const temporary = mkdtempSync(path.join(
    realpathSync(os.tmpdir()), "sniper-cut-repair-route-"));
  const directivePath = path.join(temporary, "directive.json");
  const contextPath = path.join(temporary, "cut_repair_context_v1.json");
  try {
    atomicWriteJsonSync(directivePath, {
      schemaVersion: 1,
      operation: "cut.restoreSpeech",
      mode: "analyze",
      target: directive.target,
    });
    materializationFailure(await runCutRepairPython(MATERIALIZER, [
      producerDir, manifestPath, directivePath, contextPath,
    ], "cut repair context materialization"));
    const analysis = parseResult(await runCutRepairPython(
      ANALYZER, [producerDir, directivePath, contextPath],
      "cut repair analysis"));
    return await consume({ analysis, contextPath, directivePath });
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
}

/** Invoke Python-owned phrase resolution without accepting evidence hashes. */
export async function runCutRepairAnalysis(
  producerDir: string,
  manifestPath: string,
  directive: CutRepairDirectiveV1,
): Promise<Record<string, unknown>> {
  return withCutRepairAnalysis(
    producerDir,
    manifestPath,
    directive,
    async ({ analysis }) => analysis,
  );
}
