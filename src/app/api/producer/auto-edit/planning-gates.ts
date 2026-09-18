import path from "path";
import { SCRIPTS_DIR } from "../../_lib/spawn-python";
import type { AutoEditIntent, AutoEditScope } from "./stream";
import {
  parsePlanningGateVerdict,
  planningGateTimeoutMs,
  spawnPlanningGate,
} from "./planning-gate-runner";
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
export {
  PLANNING_GATE_TIMEOUT_MS,
  parsePlanningGateVerdict,
  spawnPlanningGate,
} from "./planning-gate-runner";
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
  PlanningGateRunOptions,
  PlanningGateVerdict,
} from "./planning-gate-contract";

const PRODUCER = path.join(SCRIPTS_DIR, "producer");

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
    ...(intent.shortDirection ? { shortDirection: intent.shortDirection } : {}),
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
  stage: "previsual" | "saved-plan" | "approved" = "approved",
): PlanningGateCommand {
  const args = [input.planPath, input.transcriptsDir, input.manifestPath];
  if (stage === "previsual") args.push("--previsual");
  if (stage === "approved") {
    if (!input.cutApprovalPath) throw new Error("planning gates require cut approval receipt");
    args.push("--approval", input.cutApprovalPath);
  }
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
    processesStopped: completed.every((verdict) => verdict.processGroupStopped === true),
    errors: findings("errors"),
    warnings: findings("warnings"),
    gates,
  };
}

function gateBudget(timeoutMs: number | undefined): () => number {
  const ceiling = planningGateTimeoutMs(timeoutMs);
  const maximum = timeoutMs === undefined ? ceiling : Math.max(1, Math.floor(timeoutMs));
  const wall = Date.now(), mono = performance.now();
  return () => {
    const elapsed = Math.max(Date.now() - wall, performance.now() - mono);
    const remaining = Math.floor(maximum - elapsed);
    if (Date.now() < wall || remaining < 1) throw new Error("Planning gate bundle deadline exceeded");
    return remaining;
  };
}

function gateFailure(command: PlanningGateCommand, error: unknown, stopped: boolean): PlanningGateVerdict {
  return { gate: command.gate, ok: false, exit: 1, warnings: [],
    errors: [String(error).slice(0, 2000)], processGroupStopped: stopped };
}

function observedGateVerdict(command: PlanningGateCommand, result: PlanningGateProcessResult, remaining: () => number): PlanningGateVerdict {
  const verdict = parsePlanningGateVerdict(command.gate, result);
  if (!verdict.ok) return verdict;
  try { remaining(); return verdict; }
  catch (error) { return gateFailure(command, error, true); }
}

/** Never return a failed wave while a sibling can still create renderer resources. */
async function runGateWave(commands: PlanningGateCommand[], runtime: {
  dependencies: PlanningGateDependencies; cancellation: AbortController; remaining: () => number;
}): Promise<PlanningGateVerdict[]> {
  const run = runtime.dependencies.run ?? spawnPlanningGate;
  const settled = await Promise.allSettled(commands.map(async (command) => {
    let invoked = false;
    try {
      const env = runtime.dependencies.env?.(command.gate), timeoutMs = runtime.remaining();
      if (runtime.cancellation.signal.aborted) throw new Error("Planning gate bundle cancelled before spawn");
      invoked = true;
      const result = await run(command, { env, timeoutMs, signal: runtime.cancellation.signal });
      if (result.processGroupStopped !== true) {
        runtime.cancellation.abort();
        return gateFailure(command, "Planning gate owned process-group stop is unverified", false);
      }
      return observedGateVerdict(command, result, runtime.remaining);
    } catch (error) {
      runtime.cancellation.abort();
      return gateFailure(command, error, !invoked);
    }
  }));
  return settled.map((result, index) => result.status === "fulfilled" ? result.value
    : gateFailure(commands[index], result.reason, false));
}

/** Run the complete transcript-aware planning gate bundle before any render. */
export async function runPlanningGateBundle(
  input: GateBundleInput,
  dependencies: PlanningGateDependencies = {},
): Promise<GateBundleVerdict> {
  const remaining = gateBudget(dependencies.timeoutMs), cancellation = new AbortController();
  const commands = planningGateCommands(input);
  const preflight = commands.filter((command) =>
    command.gate === "operator_intent" || command.gate === "transcript_cut");
  const downstream = commands.filter((command) => !preflight.includes(command));
  const cancel = () => cancellation.abort();
  dependencies.signal?.addEventListener("abort", cancel, { once: true });
  if (dependencies.signal?.aborted) cancel();
  try {
    const runtime = { dependencies, cancellation, remaining };
    const preflightVerdicts = await runGateWave(preflight, runtime);
    if (preflightVerdicts.some((verdict) => !verdict.ok)) {
      const skipped = downstream.map((command): PlanningGateVerdict => ({
        gate: command.gate, ok: false, errors: [], warnings: [], exit: 125, processGroupStopped: true,
        scope: "skipped: transcript/cut preflight did not pass",
      }));
      return combinePlanningGateVerdicts([...preflightVerdicts, ...skipped]);
    }
    const downstreamVerdicts = await runGateWave(downstream, runtime);
    return combinePlanningGateVerdicts([...preflightVerdicts, ...downstreamVerdicts]);
  } finally { dependencies.signal?.removeEventListener("abort", cancel); }
}

/** One SSE payload replaces independent, easy-to-miss gate events. */
export function planningGateBundleEvent(
  verdict: GateBundleVerdict,
): Record<string, unknown> {
  return { event: "planning_gate_bundle", ...verdict };
}
