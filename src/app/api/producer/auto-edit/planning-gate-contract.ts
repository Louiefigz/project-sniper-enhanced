import type {
  ProjectIntent,
  ReferenceIntent,
} from "@/lib/producer/intent-presets";

export const PLANNING_GATE_IDS = [
  "operator_intent",
  "transcript_cut",
  "plan_lint",
  "hook_contract",
  "template_usage",
  "claims_contract",
  "comp_size",
  "geometry_feasibility",
  "reference_lint",
] as const;

export type PlanningGateId = (typeof PLANNING_GATE_IDS)[number];

export interface PlanningGateCommand {
  gate: PlanningGateId;
  script: string;
  args: string[];
}

export interface PlanningGateProcessResult {
  stdout: string;
  stderr: string;
  exit: number | null;
  spawnError?: string;
  timedOut?: boolean;
}

export type PlanningGateRunner = (
  command: PlanningGateCommand,
) => Promise<PlanningGateProcessResult>;

export interface PlanningGateVerdict {
  gate: PlanningGateId;
  ok: boolean;
  errors: string[];
  warnings: string[];
  exit: number;
  scope?: string;
  metrics?: Record<string, unknown>;
}

export interface GateBundleFinding {
  gate: PlanningGateId;
  message: string;
}

export interface GateBundleVerdict {
  ok: boolean;
  errors: GateBundleFinding[];
  warnings: GateBundleFinding[];
  gates: {
    operatorIntent: PlanningGateVerdict;
    transcriptCut: PlanningGateVerdict;
    planLint: PlanningGateVerdict;
    hookContract: PlanningGateVerdict;
    templateUsage: PlanningGateVerdict;
    claimsContract: PlanningGateVerdict;
    compSize: PlanningGateVerdict;
    geometryFeasibility: PlanningGateVerdict;
    referenceLint: PlanningGateVerdict | null;
  };
}

export interface GateBundleReference {
  profilePath: string;
  intent: ReferenceIntent;
}

export type GateBundleOperatorIntent = Omit<ProjectIntent, "preset">;

export interface GateBundleInput {
  planPath: string;
  manifestPath: string;
  transcriptsDir: string;
  /** Controller-owned receipt created before visual authoring. */
  cutApprovalPath: string;
  /** Immutable, digest-bound approved-project form history captured for this run. */
  templateUsagePath: string;
  templateUsageDigest: string;
  /** Controller-supplied authority, validated against project.json at launch. */
  operatorIntent?: GateBundleOperatorIntent;
  reference?: GateBundleReference;
}

export interface PlanningGateDependencies {
  run?: PlanningGateRunner;
}
