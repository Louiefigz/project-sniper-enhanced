import path from "node:path";
import { runtimeScriptsDir } from "../../_lib/spawn-python";
import {
  boundVisualPlanContent,
  projectVisualPlanBinding,
  visualPlanValidationAuthority,
  type BoundVisualPlan,
} from "@/lib/server/visual-plan-binding";
import type {
  GateBundleInput,
  PlanningGateCommand,
} from "./planning-gate-contract";
import { stableAuthorityHash } from "@/lib/server/auto-edit-authority-snapshot";
import { executablePipelineRoot } from
  "@/lib/server/auto-edit-pipeline-authority";
import { currentVisualPlanContext } from "./visual-plan-context";
import {
  AutoEditError,
  ordinaryVisualPlanActive,
  ordinaryVisualPlanRequired,
  type AutoEditCtx,
} from "./stream";

type VisualGateAuthority = Pick<GateBundleInput,
  "visualPlan" | "visualPlanRequired" | "visualPlanProject"
  | "visualPlanCatalogPinSha256" | "visualPlanControllerAuthoritySha256"
  | "visualPlanPipelineRoot">;

/** Resolve review evidence from disk again and reject absent or changed authority. */
export function currentBoundVisualPlan(ctx: AutoEditCtx): BoundVisualPlan | null {
  if (!ordinaryVisualPlanActive(ctx)) return null;
  const required = ordinaryVisualPlanRequired(ctx);
  const authority = visualPlanValidationAuthority(ctx);
  const current = projectVisualPlanBinding(
    ctx.dir, authority, ctx.visualPlan?.catalogReceiptAuthority,
  );
  if (!current) {
    if (required || ctx.visualPlan) {
      throw new AutoEditError("required VISUAL-PLAN.json is missing before review");
    }
    return null;
  }
  if (ctx.visualPlan && ctx.visualPlan.byteHash !== current.byteHash) {
    throw new AutoEditError("VISUAL-PLAN.json changed after deterministic gates");
  }
  ctx.visualPlan = current;
  return boundVisualPlanContent(current, authority);
}

/** Re-resolve the project artifact and retain legacy absence only when no marker exists. */
export function ordinaryVisualPlanGateAuthority(ctx: AutoEditCtx): VisualGateAuthority {
  if (!ordinaryVisualPlanActive(ctx)) {
    delete ctx.visualPlan;
    return { visualPlanRequired: false };
  }
  const required = ordinaryVisualPlanRequired(ctx);
  const validationAuthority = visualPlanValidationAuthority(ctx);
  const current = projectVisualPlanBinding(
    ctx.dir, validationAuthority, ctx.visualPlan?.catalogReceiptAuthority,
  );
  if (!current) {
    if (required || ctx.visualPlan) {
      throw new AutoEditError("required VISUAL-PLAN.json is missing after context resolution");
    }
    return { visualPlanRequired: false };
  }
  const context = required ? currentVisualPlanContext(ctx) : null;
  if (ctx.visualPlan && ctx.visualPlan.byteHash !== current.byteHash) {
    throw new AutoEditError("VISUAL-PLAN.json changed after context resolution");
  }
  ctx.visualPlan = current;
  const pipelineRoot = validationAuthority
    ? executablePipelineRoot(
      ctx.dir, validationAuthority.pipeline,
    ) : undefined;
  return {
    visualPlanRequired: required,
    visualPlan: current,
    ...(context ? {
      visualPlanProject: context.project,
      visualPlanCatalogPinSha256: stableAuthorityHash(context.catalogPin),
      visualPlanControllerAuthoritySha256: stableAuthorityHash({
        transcriptAuthority: context.transcriptAuthority,
        mediaAuthority: context.mediaAuthority,
        relatedUsageAuthority: context.relatedUsageAuthority,
        relatedUsage: context.relatedUsage,
      }),
    } : {}),
    ...(pipelineRoot ? { visualPlanPipelineRoot: pipelineRoot } : {}),
  };
}

/** Bind one ordinary edit plan to the exact allocated visual-plan authority. */
export function visualPlanApplicationCommand(
  input: GateBundleInput,
): PlanningGateCommand | null {
  const binding = input.visualPlan;
  if (!binding) {
    if (input.visualPlanRequired) {
      throw new Error("new produced/full ordinary edits require allocated VISUAL-PLAN.json");
    }
    return null;
  }
  return {
    gate: "visual_plan_application",
    script: path.join(
      runtimeScriptsDir(),
      "producer",
      "planner",
      "ordinary_visual_plan_lint.py",
    ),
    args: [input.planPath, binding.path,
      "--expected-byte-hash", binding.byteHash,
      "--expected-visual-plan-sha256", binding.visualPlanSha256,
      ...(input.visualPlanProject ? [
        "--expected-project-json", JSON.stringify(input.visualPlanProject),
      ] : []),
      ...(input.visualPlanCatalogPinSha256 ? [
        "--expected-catalog-pin-sha256", input.visualPlanCatalogPinSha256,
      ] : []),
      ...(input.visualPlanControllerAuthoritySha256 ? [
        "--expected-controller-authority-sha256",
        input.visualPlanControllerAuthoritySha256,
      ] : []),
      ...(binding.catalogReceiptAuthority ? [
        "--receipt-authority", binding.catalogReceiptAuthority.path,
      ] : []),
    ],
    ...(input.visualPlanPipelineRoot ? {
      env: { SNIPER_PIPELINE_ROOT: input.visualPlanPipelineRoot },
    } : {}),
  };
}
