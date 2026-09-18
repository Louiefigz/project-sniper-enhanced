import assert from "node:assert/strict";
import {
  gateBundleOperatorIntent,
  parsePlanningGateVerdict,
  planningGateBundleEvent,
  planningGateCommands,
  runPlanningGateBundle,
  transcriptCutCommand,
  type GateBundleInput,
  type PlanningGateCommand,
  type PlanningGateRunner,
  type PlanningGateRunOptions,
} from "../../../app/api/producer/auto-edit/planning-gates";
import { PLANNING_GATE_TIMEOUT_MS, planningGateTimeoutMs } from "@/app/api/producer/auto-edit/planning-gate-runner";

assert.deepEqual(gateBundleOperatorIntent("produced", {
  mode: "longform",
  excerpt: true,
  lanes: { broll: "off" },
  music: false,
}), {
  mode: "longform",
  excerpt: true,
  scope: "produced",
  lanes: { broll: "off" },
  music: false,
});
assert.throws(() => gateBundleOperatorIntent("produced", undefined), /requires mode and lanes/);

const baseInput: GateBundleInput = {
  planPath: "/project/producer/edit_plan.json",
  manifestPath: "/project/source/asset_manifest.json",
  transcriptsDir: "/project/source",
  cutApprovalPath: "/project/producer/cut-approval.json",
  templateUsagePath: "/project/producer/template-usage.json",
  templateUsageDigest: "a".repeat(64),
  operatorIntent: {
    mode: "longform",
    scope: "produced",
    lanes: { broll: "off" },
    music: false,
  },
};

const baseCommands = planningGateCommands(baseInput);
assert.deepEqual(baseCommands.map((command) => command.gate), [
  "operator_intent",
  "transcript_cut",
  "plan_lint",
  "hook_contract",
  "template_usage",
  "claims_contract",
  "comp_size",
  "geometry_feasibility",
]);
assert.deepEqual(baseCommands[0].args.slice(0, 2), [
  baseInput.planPath,
  "--expected-json",
]);
assert.deepEqual(JSON.parse(baseCommands[0].args[2]), baseInput.operatorIntent);
assert.deepEqual(baseCommands[1].args, [
  baseInput.planPath,
  baseInput.transcriptsDir,
  baseInput.manifestPath,
  "--approval",
  baseInput.cutApprovalPath,
], "transcript/cut approval must precede every visual/retention gate");
assert.deepEqual(transcriptCutCommand(baseInput, "previsual").args, [
  baseInput.planPath, baseInput.transcriptsDir, baseInput.manifestPath, "--previsual",
]);
assert.deepEqual(transcriptCutCommand(baseInput, "saved-plan").args, [
  baseInput.planPath, baseInput.transcriptsDir, baseInput.manifestPath,
], "saved full plans validate exact cut authority without the cut-writer lane restriction");
assert.throws(
  () => planningGateCommands({ ...baseInput, cutApprovalPath: "" }),
  /require cut approval receipt/,
);
assert.deepEqual(baseCommands[2].args, [
  baseInput.planPath,
  baseInput.manifestPath,
  baseInput.transcriptsDir,
], "plan_lint must receive transcriptsDir so content-aware checks run");
assert.deepEqual(baseCommands[3].args, [
  baseInput.planPath,
  baseInput.transcriptsDir,
  baseInput.manifestPath,
]);
assert.deepEqual(baseCommands[4].args, [
  baseInput.planPath,
  baseInput.transcriptsDir,
  baseInput.manifestPath,
  baseInput.templateUsagePath,
  "--expected-digest",
  baseInput.templateUsageDigest,
]);
assert.deepEqual(baseCommands[6].args, [baseInput.planPath],
  "comp_size measures the plan's comps (shared render cache resolves internally)");
assert.match(baseCommands[6].script, /graphics[/\\]comp_measure\.py$/);
assert.deepEqual(baseCommands[7].args, [
  baseInput.planPath,
  baseInput.manifestPath,
  "/project/producer",
], "geometry_feasibility writes geometry_predictions.json into the producer dir");
assert.match(baseCommands[7].script, /planner[/\\]geometry_feasibility\.py$/);

const referenceInput: GateBundleInput = {
  ...baseInput,
  reference: {
    profilePath: "/references/restrained/style_profile.json",
    intent: {
      id: "ref-restrained",
      title: "Measured Restrained edit",
      mode: "short",
      strategy: "extend",
      targetStyle: "restrained",
    },
  },
};
const referenceCommand = planningGateCommands(referenceInput).at(-1)!;
assert.equal(referenceCommand.gate, "reference_lint");
assert.deepEqual(referenceCommand.args.slice(-2), ["--target-style", "restrained"]);

function jsonResult(value: unknown, exit = 0) {
  return { stdout: JSON.stringify(value), stderr: "", exit, processGroupStopped: true };
}

const invalid = parsePlanningGateVerdict(
  "plan_lint",
  { stdout: "not json", stderr: "trace", exit: 1 },
);
assert.equal(invalid.ok, false);
assert.match(invalid.errors.join(" "), /no valid JSON verdict/);

const timedOut = parsePlanningGateVerdict("plan_lint", {
  stdout: "",
  stderr: "",
  exit: 124,
  timedOut: true,
  spawnError: "plan_lint timed out after 300s",
});
assert.equal(timedOut.ok, false);
assert.match(timedOut.errors.join(" "), /timed out after 300s/);

const contradictory = parsePlanningGateVerdict(
  "hook_contract",
  jsonResult({ ok: true, errors: [], warnings: [] }, 3),
);
assert.equal(contradictory.ok, false);
assert.match(contradictory.errors.join(" "), /exited 3 despite reporting ok/);

const silentFailure = parsePlanningGateVerdict(
  "claims_contract",
  jsonResult({ ok: false, errors: [], warnings: [] }, 1),
);
assert.equal(silentFailure.ok, false);
assert.match(silentFailure.errors.join(" "), /failure without diagnostics/);

function fixtureFor(command: PlanningGateCommand): Record<string, unknown> {
  if (command.gate === "hook_contract") {
    return { scope: "produced", ok: true, errors: [], warnings: ["soft hook note"] };
  }
  if (command.gate === "reference_lint") {
    return { ok: true, errors: [], warnings: [], metrics: { cutsPerMin: 8 } };
  }
  return { ok: true, errors: [], warnings: [] };
}

async function main(): Promise<void> {
  const seen: PlanningGateCommand[] = [];
  const runner: PlanningGateRunner = async (command) => {
    seen.push(command);
    return jsonResult(fixtureFor(command));
  };
  const bundle = await runPlanningGateBundle(referenceInput, { run: runner });
  assert.equal(bundle.ok, true);
  assert.deepEqual(seen.map((command) => command.gate), [
    "operator_intent", "transcript_cut", "plan_lint", "hook_contract",
    "template_usage", "claims_contract", "comp_size", "geometry_feasibility",
    "reference_lint",
  ]);
  assert.equal(bundle.gates.hookContract.scope, "produced");
  assert.deepEqual(bundle.gates.referenceLint?.metrics, { cutsPerMin: 8 });
  // The caller's remaining budget and per-gate owned environment reach EVERY gate spawn; the runner's own ceiling still caps.
  const seenOptions: Array<[string, PlanningGateRunOptions | undefined]> = [];
  const optionRunner: PlanningGateRunner = async (command, options) => { seenOptions.push([command.gate, options]); return jsonResult(fixtureFor(command)); };
  const bounded = await runPlanningGateBundle(referenceInput, { run: optionRunner, timeoutMs: 1234,
    env: (gate) => ({ SNIPER_RENDER_CONTAINER_NAME: `sniper-readiness-TEST-${gate}` }) });
  assert.equal(bounded.ok, true); assert.equal(seenOptions.length, 9);
  for (const [gate, options] of seenOptions) {
    assert.ok(options?.timeoutMs && options.timeoutMs > 0 && options.timeoutMs <= 1234);
    assert.deepEqual(options?.env, { SNIPER_RENDER_CONTAINER_NAME: `sniper-readiness-TEST-${gate}` });
  }
  assert.equal(planningGateTimeoutMs(undefined), PLANNING_GATE_TIMEOUT_MS);
  assert.equal(planningGateTimeoutMs(1234.9), 1234); assert.equal(planningGateTimeoutMs(-5), 1);
  assert.equal(planningGateTimeoutMs(PLANNING_GATE_TIMEOUT_MS * 4), PLANNING_GATE_TIMEOUT_MS);
  assert.throws(() => planningGateTimeoutMs(Number.NaN));
  assert.deepEqual(bundle.warnings, [{ gate: "hook_contract", message: "soft hook note" }]);
  assert.equal(planningGateBundleEvent(bundle).event, "planning_gate_bundle");

  const rejectingRunner: PlanningGateRunner = async (command) => jsonResult({
    ok: command.gate !== "claims_contract",
    errors: command.gate === "claims_contract" ? ["ungrounded number"] : [],
    warnings: [],
  }, command.gate === "claims_contract" ? 1 : 0);
  const rejected = await runPlanningGateBundle(baseInput, { run: rejectingRunner });
  assert.equal(rejected.ok, false);
  assert.equal(rejected.gates.referenceLint, null);
  assert.deepEqual(rejected.errors, [
    { gate: "claims_contract", message: "ungrounded number" },
  ]);

  const cutSeen: PlanningGateCommand[] = [];
  const cutRejectingRunner: PlanningGateRunner = async (command) => {
    cutSeen.push(command);
    const rejectedCut = command.gate === "transcript_cut";
    return jsonResult({
      ok: !rejectedCut,
      errors: rejectedCut ? ["cutTrack[0] cuts through word 'hello'"] : [],
      warnings: [],
    }, rejectedCut ? 1 : 0);
  };
  const cutRejected = await runPlanningGateBundle(baseInput, { run: cutRejectingRunner });
  assert.equal(cutRejected.ok, false);
  assert.deepEqual(cutSeen.map((command) => command.gate), [
    "operator_intent", "transcript_cut",
  ], "visual/retention gates must not run after transcript/cut preflight fails");
  assert.deepEqual(cutRejected.errors, [{
    gate: "transcript_cut", message: "cutTrack[0] cuts through word 'hello'",
  }]);

  assert.throws(
    () => planningGateCommands({ ...baseInput, operatorIntent: undefined }),
    /authoritative stored operator intent/,
  );
}

main()
  .then(() => console.log("planning-gates.test.ts: all assertions passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
