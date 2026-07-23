import { spawn } from "child_process";
import path from "path";
import { pythonInterpreter, SCRIPTS_DIR } from "../../_lib/spawn-python";
import {
  shouldDetachProcessGroup,
  terminateProcessTree,
  trackProcessTree,
} from "../../_lib/child-process-lifecycle";
import type { AutoEditIntent, AutoEditScope } from "./stream";
import {
  type GateBundleInput,
  type GateBundleOperatorIntent,
  type GateBundleVerdict,
  type PlanningGateCommand,
  type PlanningGateDependencies,
  type PlanningGateId,
  type PlanningGateProcessResult,
  type PlanningGateVerdict,
} from "./planning-gate-contract";

export { PLANNING_GATE_IDS } from "./planning-gate-contract";
export type {
  GateBundleFinding,
  GateBundleInput,
  GateBundleOperatorIntent,
  GateBundleReference,
  GateBundleVerdict,
  PlanningGateCommand,
  PlanningGateDependencies,
  PlanningGateId,
  PlanningGateProcessResult,
  PlanningGateRunner,
  PlanningGateVerdict,
} from "./planning-gate-contract";

const PRODUCER = path.join(SCRIPTS_DIR, "producer");
export const PLANNING_GATE_TIMEOUT_MS = 5 * 60 * 1000;

/** Convert the validated job context into the explicit gate authority. */
export function gateBundleOperatorIntent(
  scope: AutoEditScope,
  intent: AutoEditIntent | undefined,
): GateBundleOperatorIntent {
  if (!intent?.mode || intent.lanes === undefined) {
    throw new Error("validated stored operator intent requires mode and lanes");
  }
  return {
    mode: intent.mode,
    scope,
    lanes: intent.lanes,
    ...(intent.excerpt !== undefined ? { excerpt: intent.excerpt } : {}),
    ...(intent.brief ? { brief: intent.brief } : {}),
    ...(intent.pace ? { pace: intent.pace } : {}),
    ...(intent.style ? { style: intent.style } : {}),
    ...(intent.reference ? { reference: intent.reference } : {}),
    ...(intent.music !== undefined ? { music: intent.music } : {}),
    ...(intent.audioEnhance ? { audioEnhance: intent.audioEnhance } : {}),
  };
}

function gateScript(filename: string): string {
  return path.join(PRODUCER, filename);
}

function referenceCommand(input: GateBundleInput): PlanningGateCommand | null {
  if (!input.reference) return null;
  const { intent, profilePath } = input.reference;
  const args = [
    input.planPath,
    profilePath,
    "--reference-id", intent.id,
    "--mode", intent.mode,
    "--strategy", intent.strategy,
  ];
  if (intent.strategy === "extend" && intent.targetStyle) {
    args.push("--target-style", intent.targetStyle);
  }
  return { gate: "reference_lint", script: gateScript("reference_profile_lint.py"), args };
}

function operatorIntentCommand(input: GateBundleInput): PlanningGateCommand {
  if (!input.operatorIntent) {
    throw new Error("planning gates require authoritative stored operator intent");
  }
  return {
    gate: "operator_intent",
    script: gateScript("operator_intent_contract.py"),
    args: [input.planPath, "--expected-json", JSON.stringify(input.operatorIntent)],
  };
}

/** Transcript gate command for the cut-only wall or the immutable final cut. */
export function transcriptCutCommand(
  input: Pick<GateBundleInput, "planPath" | "transcriptsDir" | "manifestPath" | "cutApprovalPath">,
  stage: "previsual" | "approved" = "approved",
): PlanningGateCommand {
  const args = [input.planPath, input.transcriptsDir, input.manifestPath];
  if (stage === "previsual") args.push("--previsual");
  else if (!input.cutApprovalPath) throw new Error("planning gates require cut approval receipt");
  else args.push("--approval", input.cutApprovalPath);
  return {
    gate: "transcript_cut",
    script: gateScript("transcript_cut_contract.py"),
    args,
  };
}

/** Commands for every controller-owned pre-render gate, in stable order. */
export function planningGateCommands(input: GateBundleInput): PlanningGateCommand[] {
  const shared = [input.planPath, input.transcriptsDir, input.manifestPath];
  const commands: PlanningGateCommand[] = [
    operatorIntentCommand(input),
    transcriptCutCommand(input),
    {
      gate: "plan_lint",
      script: gateScript("plan_lint.py"),
      args: [input.planPath, input.manifestPath, input.transcriptsDir],
    },
    { gate: "hook_contract", script: gateScript("hook_contract.py"), args: shared },
    {
      gate: "template_usage", script: gateScript("template_usage_contract.py"),
      args: [...shared, input.templateUsagePath,
        "--expected-digest", input.templateUsageDigest],
    },
    { gate: "claims_contract", script: gateScript("claims_contract.py"), args: shared },
    {
      // Comp-size plan-time measurement (geometry contract v3 item #2):
      // renders every graphicsTrack comp into the shared content-hash cache
      // (assemble then cache-hits) and FAILs measured LL-035-class overflow.
      gate: "comp_size",
      script: gateScript(path.join("graphics", "comp_measure.py")),
      args: [input.planPath],
    },
    {
      // Plan-time geometry feasibility lint (geometry contract v3 item #3):
      // composes the delivery geometry (proxy face track × reframe × punch)
      // and runs the REAL region chooser on the measured comp bbox. Writes
      // geometry_predictions.json into the producer dir — the ONLY feeder of
      // the A3 residual ledger, so the item-#4 WARN→FAIL calibration flip
      // for geometry_feasibility AND placement_verify can actually happen.
      gate: "geometry_feasibility",
      script: gateScript(path.join("planner", "geometry_feasibility.py")),
      args: [input.planPath, input.manifestPath, path.dirname(input.planPath)],
    },
  ];
  const reference = referenceCommand(input);
  if (reference) commands.push(reference);
  return commands;
}

/** Default child-process seam. Tests inject a runner and never spawn Python. */
export function spawnPlanningGate(
  command: PlanningGateCommand,
): Promise<PlanningGateProcessResult> {
  return new Promise((resolve) => {
    const proc = trackProcessTree(spawn(pythonInterpreter(), [command.script, ...command.args], {
      env: { ...process.env },
      detached: shouldDetachProcessGroup(),
    }));
    let stdout = "";
    let stderr = "";
    let settled = false;
    const finish = (result: PlanningGateProcessResult) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(result);
    };
    proc.stdout.on("data", (data: Buffer) => (stdout += data.toString()));
    proc.stderr.on("data", (data: Buffer) => {
      stderr += data.toString();
      process.stderr.write(data);
    });
    proc.on("close", (exit) => finish({ stdout, stderr, exit }));
    proc.on("error", (error) => finish({
      stdout,
      stderr,
      exit: 1,
      spawnError: error.message,
    }));
    const timer = setTimeout(() => {
      terminateProcessTree(proc);
      finish({
        stdout,
        stderr,
        exit: 124,
        timedOut: true,
        spawnError: `${command.gate} timed out after ${PLANNING_GATE_TIMEOUT_MS / 1000}s`,
      });
    }, PLANNING_GATE_TIMEOUT_MS);
    timer.unref();
  });
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
  return { gate, ok: false, errors, warnings: [], exit: result.exit ?? 1 };
}

/** Parse one gate's JSON contract and fail closed on exit/verdict disagreement. */
export function parsePlanningGateVerdict(
  gate: PlanningGateId,
  result: PlanningGateProcessResult,
): PlanningGateVerdict {
  if (result.spawnError) return failedVerdict(gate, result, result.spawnError);
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
  if (typeof raw.ok !== "boolean" || !isStringArray(raw.errors) || !isStringArray(raw.warnings)) {
    return failedVerdict(gate, result, `${gate} verdict has an invalid contract shape`);
  }
  const exit = result.exit ?? 1;
  const errors = [...raw.errors];
  if (!raw.ok && errors.length === 0) errors.push(`${gate} reported failure without diagnostics`);
  if (raw.ok && exit !== 0) errors.push(`${gate} exited ${exit} despite reporting ok`);
  const verdict: PlanningGateVerdict = {
    gate,
    ok: raw.ok && exit === 0,
    errors,
    warnings: [...raw.warnings],
    exit,
  };
  if (typeof raw.scope === "string") verdict.scope = raw.scope;
  if (raw.metrics && typeof raw.metrics === "object" && !Array.isArray(raw.metrics)) {
    verdict.metrics = raw.metrics as Record<string, unknown>;
  }
  return verdict;
}

function requiredVerdict(
  byGate: Map<PlanningGateId, PlanningGateVerdict>,
  gate: PlanningGateId,
): PlanningGateVerdict {
  return byGate.get(gate) ?? {
    gate,
    ok: false,
    errors: [`controller did not run required gate ${gate}`],
    warnings: [],
    exit: 1,
  };
}

/** Pure reducer used by the controller and focused tests. */
export function combinePlanningGateVerdicts(
  verdicts: PlanningGateVerdict[],
): GateBundleVerdict {
  const byGate = new Map(verdicts.map((verdict) => [verdict.gate, verdict]));
  const operatorIntent = requiredVerdict(byGate, "operator_intent");
  const transcriptCut = requiredVerdict(byGate, "transcript_cut");
  const planLint = requiredVerdict(byGate, "plan_lint");
  const hookContract = requiredVerdict(byGate, "hook_contract");
  const templateUsage = requiredVerdict(byGate, "template_usage");
  const claimsContract = requiredVerdict(byGate, "claims_contract");
  const compSize = requiredVerdict(byGate, "comp_size");
  const geometryFeasibility = requiredVerdict(byGate, "geometry_feasibility");
  const referenceLint = byGate.get("reference_lint") ?? null;
  const gates = { operatorIntent, transcriptCut, planLint,
    hookContract, templateUsage, claimsContract, compSize,
    geometryFeasibility, referenceLint };
  const completed = [operatorIntent, transcriptCut, planLint, hookContract,
    templateUsage, claimsContract, compSize, geometryFeasibility,
    ...(referenceLint ? [referenceLint] : [])];
  const findings = (kind: "errors" | "warnings") => completed.flatMap((verdict) =>
    verdict[kind].map((message) => ({ gate: verdict.gate, message })));
  return {
    ok: completed.every((verdict) => verdict.ok),
    errors: findings("errors"),
    warnings: findings("warnings"),
    gates,
  };
}

/** Run the complete transcript-aware planning gate bundle before any render. */
export async function runPlanningGateBundle(
  input: GateBundleInput,
  dependencies: PlanningGateDependencies = {},
): Promise<GateBundleVerdict> {
  const run = dependencies.run ?? spawnPlanningGate;
  const commands = planningGateCommands(input);
  const preflight = commands.filter((command) =>
    command.gate === "operator_intent" || command.gate === "transcript_cut");
  const downstream = commands.filter((command) => !preflight.includes(command));
  const preflightVerdicts = await Promise.all(preflight.map(async (command) => {
    const result = await run(command);
    return parsePlanningGateVerdict(command.gate, result);
  }));
  if (preflightVerdicts.some((verdict) => !verdict.ok)) {
    const skipped = downstream.map((command): PlanningGateVerdict => ({
      gate: command.gate, ok: false, errors: [], warnings: [], exit: 125,
      scope: "skipped: transcript/cut preflight did not pass",
    }));
    return combinePlanningGateVerdicts([...preflightVerdicts, ...skipped]);
  }
  const downstreamVerdicts = await Promise.all(downstream.map(async (command) => {
    const result = await run(command);
    return parsePlanningGateVerdict(command.gate, result);
  }));
  return combinePlanningGateVerdicts([...preflightVerdicts, ...downstreamVerdicts]);
}

/** One SSE payload replaces independent, easy-to-miss gate events. */
export function planningGateBundleEvent(
  verdict: GateBundleVerdict,
): Record<string, unknown> {
  return { event: "planning_gate_bundle", ...verdict };
}
