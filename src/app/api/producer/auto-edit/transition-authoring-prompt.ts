import type { AutoEditCtx } from "./stream";

function automaticTransitions(ctx: AutoEditCtx): boolean {
  if (!(ctx.scope === "produced" || ctx.scope === "full")) return false;
  const directive = ctx.intent?.lanes?.transitions;
  return directive !== "off" && directive !== "operator" && !Array.isArray(directive);
}

/** Authoring instructions that mirror the fail-closed intro seam contract. */
export function transitionAuthoringSteps(ctx: AutoEditCtx): string[] {
  if (!automaticTransitions(ctx)) return [];
  return [
    `3e. TRANSITION SOURCE — inspect the HyperFrames catalog when an intro seam needs a visual bridge. Mount the selected component in the native project and bind its source decision. The compatibility transitions[] preset lane is retired and must remain empty; migrate to native catalog authoring when a transition is needed. Never add a transition merely to inflate density.`,
    `3f. INTRO SEAM MAP — resolve EVERY internal cut seam deliberately. For an intentional clean hard cut, persist transitionRationale={decision:"clean-hook",reason:<20+ chars>,seams:[{outTime:<exact seam>,evidence:<12+ chars>}]} with evidence for that seam. Inspect any native catalog transition with adjacent moving picture and mastered audio before full export.`,
  ];
}
