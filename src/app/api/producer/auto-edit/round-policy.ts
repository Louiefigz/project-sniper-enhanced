import type { AutoEditScope } from "./stream";

/** Cap on paid review CYCLES (one author→review→revise pass). A 2-wide critic
 * batch inside one cycle is still ONE round against this budget — the cap
 * bounds revision cycles, not individual critic spawns. */
export const MAX_PLANNING_REVIEW_ROUNDS = 4;
export const MAX_QC_RENDER_ROUNDS = 3;

export const VISUAL_REVIEW_LENSES = [
  "composition",
  "editorial",
] as const;

export type VisualReviewLens = (typeof VISUAL_REVIEW_LENSES)[number];

export function requiredPlanningRounds(scope: AutoEditScope): number {
  return scope === "produced" || scope === "full" ? 2 : 1;
}

export function planningCanConverge(
  scope: AutoEditScope,
  cleanRoundsOnCurrentPlan: number,
  materialIssues: number,
): boolean {
  return cleanRoundsOnCurrentPlan >= requiredPlanningRounds(scope) && materialIssues === 0;
}

export function planningCapReached(completedRounds: number): boolean {
  return completedRounds >= MAX_PLANNING_REVIEW_ROUNDS;
}

/** True while the remaining cycle budget can still mathematically produce the
 * required clean count — checked BEFORE paying for a revision so the loop
 * stops with the exhaustion verdict instead of funding a doomed revision. */
export function planningBudgetViable(
  remainingCycles: number,
  batchWidth: number,
  cleansNeeded: number,
): boolean {
  return remainingCycles * batchWidth >= cleansNeeded;
}

export function qcCapReached(renderRound: number): boolean {
  return renderRound >= MAX_QC_RENDER_ROUNDS;
}
