import { pythonInterpreter } from "../../_lib/spawn-python";
import { stageTimingEnv } from "@/lib/server/stage-timing-context";
import { CutPreviewProcessError, runCutPreviewProcess } from "./cut-preview-process";
import type {
  PlanningGateCommand,
  PlanningGateId,
  PlanningGateProcessResult,
  PlanningGateRunOptions,
  PlanningGateVerdict,
} from "./planning-gate-contract";

export const PLANNING_GATE_TIMEOUT_MS = 5 * 60 * 1000;

/** A caller's remaining budget can only tighten the runner's own ceiling, never extend it. */
export function planningGateTimeoutMs(requested: number | undefined): number {
  if (requested === undefined) return PLANNING_GATE_TIMEOUT_MS;
  if (!Number.isFinite(requested)) throw new Error("planning gate timeout must be a finite number of milliseconds");
  return Math.max(1, Math.min(PLANNING_GATE_TIMEOUT_MS, Math.floor(requested)));
}

/** Run one tracked owned group; timeout/cancellation never returns before bounded stop verification. */
export async function spawnPlanningGate(
  command: PlanningGateCommand,
  options: PlanningGateRunOptions = {},
): Promise<PlanningGateProcessResult> {
  const timeoutMs = planningGateTimeoutMs(options.timeoutMs);
  try {
    const result = await runCutPreviewProcess({ command: pythonInterpreter(), args: [command.script, ...command.args],
      cwd: process.cwd(), env: { ...stageTimingEnv(), ...(options.env ?? {}) }, timeoutMs,
      signal: options.signal, trackForShutdown: true, onStderr: (chunk) => { process.stderr.write(chunk); } });
    return { ...result, exit: 0, processGroupStopped: true, forcedStop: false };
  } catch (error) {
    if (!(error instanceof CutPreviewProcessError)) return { stdout: "", stderr: "", exit: 1,
      spawnError: String(error), processGroupStopped: false };
    const { stdout, stderr, timedOut, groupStopped, forcedStop } = error.details;
    const cancelled = options.signal?.aborted === true;
    const normalExit = error.exitCode != null && groupStopped && !forcedStop && !timedOut && !cancelled;
    return { stdout, stderr, exit: timedOut ? 124 : cancelled ? 130 : error.exitCode ?? 1,
      timedOut, cancelled, processGroupStopped: groupStopped, forcedStop,
      ...(!normalExit ? { spawnError: timedOut ? `${command.gate} timed out after ${timeoutMs / 1000}s` : error.message } : {}) };
  }
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function failedVerdict(
  gate: PlanningGateId,
  result: PlanningGateProcessResult,
  reason: string,
): PlanningGateVerdict {
  const diagnostic = result.stderr.trim() || result.stdout.trim();
  const errors = [reason];
  if (diagnostic) errors.push(diagnostic.slice(-300));
  return { gate, ok: false, errors, warnings: [], exit: result.exit ?? 1,
    ...(result.processGroupStopped !== undefined ? { processGroupStopped: result.processGroupStopped } : {}) };
}

/** Parse one gate's JSON contract and fail closed on exit/verdict disagreement. */
export function parsePlanningGateVerdict(
  gate: PlanningGateId,
  result: PlanningGateProcessResult,
): PlanningGateVerdict {
  if (result.spawnError) return failedVerdict(gate, result, result.spawnError);
  if (result.processGroupStopped === false) return failedVerdict(gate, result, `${gate} owned process-group stop is unverified`);
  let value: unknown;
  try {
    value = JSON.parse(result.stdout.trim());
  } catch {
    return failedVerdict(gate, result, `${gate} produced no valid JSON verdict`);
  }
  if (!value || typeof value !== "object") {
    return failedVerdict(gate, result, `${gate} verdict must be a JSON object`);
  }
  const raw = value as Record<string, unknown>;
  if (typeof raw.ok !== "boolean" || !isStringArray(raw.errors)
      || !isStringArray(raw.warnings)) {
    return failedVerdict(gate, result, `${gate} verdict has an invalid contract shape`);
  }
  const exit = result.exit ?? 1;
  const errors = [...raw.errors];
  if (!raw.ok && errors.length === 0) {
    errors.push(`${gate} reported failure without diagnostics`);
  }
  if (raw.ok && exit !== 0) errors.push(`${gate} exited ${exit} despite reporting ok`);
  const verdict: PlanningGateVerdict = {
    gate, ok: raw.ok && exit === 0, errors, warnings: [...raw.warnings], exit,
    ...(result.processGroupStopped !== undefined ? { processGroupStopped: result.processGroupStopped } : {}),
  };
  if (typeof raw.scope === "string") verdict.scope = raw.scope;
  if (raw.metrics && typeof raw.metrics === "object" && !Array.isArray(raw.metrics)) {
    verdict.metrics = raw.metrics as Record<string, unknown>;
  }
  return verdict;
}
