import { runCutRepairAnalysis } from "./cut-repair-route-runner";
import { runCutRepairApproval } from "./cut-repair-approve-runner";
import { runCutRepairExecution } from "./cut-repair-execute-runner";
import { runCutRepairPreparation } from "./cut-repair-prepare-runner";
import { runCutRepairReview } from "./cut-repair-review-runner";
import { runCutRepairRippleReopen } from
  "./cut-repair-ripple-reopen-runner";
import type { CutRepairDirectiveV1 } from "./cut-repair-route-policy";

export function cutRepairHeader(
  mode: CutRepairDirectiveV1["mode"],
): string {
  return {
    analyze: "cut-repair-analysis",
    reopen: "cut-repair-ripple-picture-lock-reopen",
    prepare: "cut-repair-rendered-plan-preparation",
    review: "cut-repair-candidate-review",
    approve: "cut-repair-promotion-package-sealing",
    execute: "cut-repair-promotion",
  }[mode];
}

export function cutRepairOperation(
  mode: CutRepairDirectiveV1["mode"],
): string {
  return {
    analyze: "analyzing a word-safe cut repair",
    reopen: "reopening picture lock for an explicit ripple repair",
    prepare: "preparing a private full-plan word-safe repair candidate",
    review: "reviewing a word-safe cut repair candidate",
    approve: "sealing an approved word-safe cut repair",
    execute: "executing a word-safe cut repair",
  }[mode];
}

/** Dispatch exactly one lifecycle phase; no phase calls another phase. */
export async function runCutRepairMode(
  dir: string,
  manifestPath: string,
  directive: CutRepairDirectiveV1,
): Promise<Record<string, unknown>> {
  if (directive.mode === "execute") {
    return runCutRepairExecution(dir, manifestPath, directive);
  }
  if (directive.mode === "approve") {
    return runCutRepairApproval(dir, manifestPath, directive);
  }
  if (directive.mode === "review") {
    return runCutRepairReview(dir, manifestPath, directive);
  }
  if (directive.mode === "prepare") {
    return runCutRepairPreparation(dir, manifestPath, directive);
  }
  if (directive.mode === "reopen") {
    return runCutRepairRippleReopen(dir, manifestPath, directive);
  }
  return runCutRepairAnalysis(dir, manifestPath, directive);
}
