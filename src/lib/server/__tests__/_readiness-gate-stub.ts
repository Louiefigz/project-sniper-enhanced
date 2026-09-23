import { combinePlanningGateVerdicts, type GateBundleInput, type GateBundleVerdict,
  type PlanningGateId, type PlanningGateVerdict } from "@/app/api/producer/auto-edit/planning-gates";
import type { ProposalBrainInput } from "../guided-proposal-compiler";

/** Every gate the bundle reducer treats as required; reference_lint stays optional. */
const REQUIRED: PlanningGateId[] = ["operator_intent", "transcript_cut", "plan_lint", "hook_contract",
  "template_usage", "claims_contract", "comp_size", "geometry_feasibility"];

function gateVerdict(gate: PlanningGateId, errors: string[]): PlanningGateVerdict {
  return { gate, ok: errors.length === 0, errors, warnings: [], exit: errors.length ? 1 : 0, processGroupStopped: true };
}

/** TEST ONLY. Builds a real reducer verdict without ever spawning a gate subprocess.
 * `failures` names the gates that report errors; `before` runs when the bundle is invoked. */
export function stubGateBundle(options: {
  failures?: Partial<Record<PlanningGateId, string[]>>; before?: () => void;
} = {}) {
  const calls: GateBundleInput[] = [];
  const run = async (input: GateBundleInput): Promise<GateBundleVerdict> => {
    calls.push(input);
    options.before?.();
    return combinePlanningGateVerdicts(REQUIRED.map((gate) =>
      gateVerdict(gate, options.failures?.[gate] ?? [])));
  };
  return { run, calls };
}

/** Convenience for suites that only need readiness to get past the deterministic wall. */
export function passingGateBundle() {
  return stubGateBundle().run;
}

/** TEST ONLY, no creative claim. The same preserve-the-cut proposal the shared fixture
 * authors, emitted at whatever schema version the controller's own evidence demands, so a
 * readiness test never fails merely because the evidence version moved underneath it. */
export function guidedProposalOutput(input: ProposalBrainInput, rawIntent = "Preserve the accepted cut exactly."): Record<string, unknown> {
  const data = JSON.parse(input.prompt.split("INPUT_DATA_JSON\n")[1]) as {
    evidence: { anchors: number[]; schemaVersion: number };
  };
  const last = data.evidence.anchors.length - 1;
  const base = { summary: "TEST ONLY no creative quality claim.",
    clauses: [{ start: 0, end: rawIntent.length, quote: rawIntent, disposition: "supported",
      rationale: "Exact cut retained.", operationIndices: [0] }],
    beats: [{ startAnchor: 0, endAnchorExclusive: last, purpose: "opening",
      summary: "TEST entire short program", supportsBeatIndices: [] }],
    openingEndAnchor: last, continuityEndAnchor: last,
    audioPolicy: "preserve-full-program", colorPolicy: "preserve" };
  const operation = { type: "preserve-cut", clauseIndex: 0, beatIndex: null, catalogKind: null,
    variables: null, grade: null, startAnchor: null, endAnchorExclusive: null, presentation: null };
  if (data.evidence.schemaVersion < 4) return { schemaVersion: data.evidence.schemaVersion, ...base, operations: [operation] };
  if (![4, 5].includes(data.evidence.schemaVersion)) throw new Error("TEST proposal fixture does not support this evidence version");
  return { schemaVersion: data.evidence.schemaVersion, ...base,
    operations: [{ ...operation, reason: null, ...(data.evidence.schemaVersion === 5 ? { captions: null } : {}) }],
    graphicsStyle: "catalog-first", graphicsStyleRationale: "TEST ONLY: the accepted cut is preserved without any authored graphic.",
    beatDecisions: [], hookSeamDecisions: [] };
}
