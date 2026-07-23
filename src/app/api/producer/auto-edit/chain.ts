import { spawn } from "child_process";
import path from "path";
import { runAuditGate, type AuditGateOutcome } from "../../_lib/audit-gate";
import { pythonInterpreter, SCRIPTS_DIR } from "../../_lib/spawn-python";
import { dlog } from "@/lib/debug";
import type { ReferenceIntent } from "@/lib/producer/intent-presets";
import { AutoEditError, Send, SendRaw, lineSplitter, tailCollector } from "./stream";
import { lookupProducerManifest } from "@/lib/server/producer-manifest";

// PHASE 2 plumbing — everything deterministic that wraps the authoring:
// manifest resolution, the route-side plan_lint gate (belt over suspenders —
// claude already converged both gates), the fresh-plan base guard, and the
// assemble.py --auto-base chain (same spawn/stream pattern as the assemble
// route; assemble.py's own .assemble.lock is the cross-process backstop).

const PRODUCER = path.join(SCRIPTS_DIR, "producer");
const ASSEMBLE = path.join(PRODUCER, "assemble.py");
const PLAN_LINT = path.join(PRODUCER, "plan_lint.py");
const REFERENCE_LINT = path.join(PRODUCER, "reference_profile_lint.py");
const BASE_GUARD = path.join(PRODUCER, "edit", "auto_base_guard.py");

export interface ManifestResolution {
  manifestPath: string;
  transcriptsDir: string;
}

/**
 * Resolve the manifest for a producer dir: the fingerprint's recorded
 * manifestPath when usable, else exactly one <dir>/../source/*manifest*.json.
 * Throws AutoEditError (→ 409) with the precise reason otherwise.
 */
export function resolveManifest(dir: string): ManifestResolution {
  const result = lookupProducerManifest(dir);
  if (!result.path || !result.transcriptsDir) {
    throw new AutoEditError(`${result.error} — re-ingest or record the intended manifest in base.fingerprint.json`);
  }
  return { manifestPath: result.path, transcriptsDir: result.transcriptsDir };
}

export interface LintVerdict {
  ok: boolean;
  errors: string[];
  warnings: string[];
  exit: number;
}

export interface ReferenceLintVerdict extends LintVerdict {
  metrics: Record<string, unknown>;
}

/** Route-side plan_lint.py check on the authored plan (verdict JSON on stdout). */
export function runLintGate(planPath: string, manifestPath: string): Promise<LintVerdict> {
  return new Promise((resolve) => {
    const proc = spawn(pythonInterpreter(), [PLAN_LINT, planPath, manifestPath], {
      env: { ...process.env },
    });
    let stdout = "";
    proc.stdout.on("data", (d: Buffer) => (stdout += d.toString()));
    proc.stderr.on("data", (d: Buffer) => process.stderr.write(d));
    proc.on("close", (code) => {
      try {
        const v = JSON.parse(stdout.trim()) as { ok: boolean; errors: string[]; warnings: string[] };
        resolve({ ...v, exit: code ?? 1 });
      } catch {
        resolve({
          ok: false,
          errors: [`plan_lint produced no verdict (exit ${code})`, stdout.slice(-300)],
          warnings: [],
          exit: code ?? 1,
        });
      }
    });
    proc.on("error", (err) => resolve({ ok: false, errors: [err.message], warnings: [], exit: 1 }));
  });
}

/** Enforce reference identity/mode and compare authored mechanics to its profile. */
export function runReferenceGate(
  planPath: string,
  profilePath: string,
  reference: ReferenceIntent,
): Promise<ReferenceLintVerdict> {
  const args = [REFERENCE_LINT, planPath, profilePath, "--reference-id", reference.id,
    "--mode", reference.mode, "--strategy", reference.strategy];
  if (reference.strategy === "extend" && reference.targetStyle) {
    args.push("--target-style", reference.targetStyle);
  }
  return new Promise((resolve) => {
    const proc = spawn(pythonInterpreter(), args, { env: { ...process.env } });
    let stdout = "";
    proc.stdout.on("data", (data: Buffer) => (stdout += data.toString()));
    proc.stderr.on("data", (data: Buffer) => process.stderr.write(data));
    proc.on("close", (code) => resolve(parseReferenceVerdict(stdout, code)));
    proc.on("error", (error) => resolve({
      ok: false, errors: [error.message], warnings: [], metrics: {}, exit: 1,
    }));
  });
}

function parseReferenceVerdict(stdout: string, code: number | null): ReferenceLintVerdict {
  try {
    const value = JSON.parse(stdout.trim()) as Omit<ReferenceLintVerdict, "exit">;
    return { ...value, metrics: value.metrics ?? {}, exit: code ?? 1 };
  } catch {
    return {
      ok: false,
      errors: [`reference_profile_lint produced no verdict (exit ${code})`, stdout.slice(-300)],
      warnings: [],
      metrics: {},
      exit: code ?? 1,
    };
  }
}

/**
 * auto_base_guard.py — quarantine a base the freshly authored plan can't
 * prove current, so assemble rebuilds WITHOUT the (wrong-timebase) refit.
 * Its single NDJSON line is streamed through; non-zero exit throws.
 */
export function runBaseGuard(dir: string, sendRaw: SendRaw): Promise<void> {
  return new Promise((resolve, reject) => {
    const proc = spawn(pythonInterpreter(), [BASE_GUARD, dir], { env: { ...process.env } });
    let stdout = "";
    proc.stdout.on("data", (d: Buffer) => (stdout += d.toString()));
    proc.stderr.on("data", (d: Buffer) => process.stderr.write(d));
    proc.on("close", (code) => {
      for (const line of stdout.split("\n")) if (line.trim()) sendRaw(line);
      if (code === 0) return resolve();
      reject(new AutoEditError(`auto_base_guard failed: ${stdout.trim().slice(-300)}`));
    });
    proc.on("error", (err) => reject(new AutoEditError(`auto_base_guard spawn failed: ${err.message}`)));
  });
}

/**
 * assemble.py --auto-base (the smart re-render): passthrough its NDJSON as
 * SSE data lines; resolves on exit with the code + stderr tail. --manifest is
 * always the resolved manifest (explicit wins), --fingerprint always the
 * dir's path so a rebuild RECORDS its prints there.
 */
export function assembleCommandArgs(
  dir: string,
  manifestPath: string,
  outputPath = path.join(dir, "final.mp4"),
): string[] {
  return [
    ASSEMBLE,
    path.join(dir, "base_final.mp4"),
    path.join(dir, "edit_plan.json"),
    outputPath,
    "--auto-base",
    "--fingerprint", path.join(dir, "base.fingerprint.json"),
    "--manifest", manifestPath,
  ];
}

export function runAssemble(
  dir: string,
  manifestPath: string,
  sendRaw: SendRaw,
  outputPath = path.join(dir, "final.mp4"),
): Promise<{ code: number; errTail: string }> {
  const args = assembleCommandArgs(dir, manifestPath, outputPath);
  dlog("producer:auto-edit", "spawn assemble.py", { dir, args: args.slice(1) });
  return new Promise((resolve) => {
    const proc = spawn(pythonInterpreter(), args, { env: { ...process.env } });
    // One tail over BOTH streams: assemble.py emits its typed errors (e.g.
    // "NoLegalRegion: {...}") as NDJSON on STDOUT via emit(), and the geometry
    // re-plan route keys on that token surviving into errTail (contract v3 A2).
    // Collecting stderr alone would make every render-time NoLegalRegion an
    // untyped terminal failure.
    const tail = tailCollector();
    const lines = lineSplitter(sendRaw);
    proc.stdout.on("data", (d: Buffer) => {
      const text = d.toString();
      lines.push(text);
      tail.push(text);
    });
    proc.stderr.on("data", (d: Buffer) => {
      tail.push(d.toString());
      process.stderr.write(d);
    });
    proc.on("close", (code) => {
      lines.flush();
      resolve({ code: code ?? 1, errTail: tail.get() });
    });
    proc.on("error", (err) => resolve({ code: 1, errTail: err.message }));
  });
}

/** Streamed event for a lint verdict (used by the route). */
export function lintEvent(v: LintVerdict): Record<string, unknown> {
  return { event: "lint", ok: v.ok, errors: v.errors, warnings: v.warnings };
}

/** Streamed event for the reference-specific deterministic gate. */
export function referenceLintEvent(v: ReferenceLintVerdict): Record<string, unknown> {
  return {
    event: "reference_lint", ok: v.ok, errors: v.errors,
    warnings: v.warnings, metrics: v.metrics,
  };
}

/**
 * Audit B outcome for a finished candidate. This boundary is fail-closed:
 * even an unexpected audit-runner exception becomes an explicit failed
 * outcome instead of allowing promotion to continue without a verdict.
 */
export async function runAuditBOutcome(
  dir: string,
  auditRunner: (outDir: string) => Promise<AuditGateOutcome> = runAuditGate,
): Promise<AuditBOutcome> {
  try {
    return await auditRunner(dir);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      event: { event: "audit", overall: "error", message: `Audit B could not run: ${message}` },
      failure: `Audit B could not run; candidate is not approved. ${message}`,
    };
  }
}

export type AuditBOutcome = AuditGateOutcome;

/**
 * Backwards-compatible throwing adapter for routes that surface Audit B
 * failure through their existing error convention.
 */
export async function runAuditB(
  dir: string,
  send: Send,
  auditRunner: (outDir: string) => Promise<AuditGateOutcome> = runAuditGate,
): Promise<void> {
  const audit = await runAuditBOutcome(dir, auditRunner);
  send(audit.event);
  if (audit.failure) throw new AutoEditError(audit.failure);
}

export type { Send };

export {
  planningGateBundleEvent,
  runPlanningGateBundle,
  type GateBundleInput,
  type GateBundleVerdict,
  type PlanningGateDependencies,
} from "./planning-gates";
