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
    `3e. TRANSITION DELIVERABLE — transitions is a checked/automatic lane, so author at least one real transitions[] event on an eligible internal intro seam. A transition outside the intro cannot satisfy this lane, and a transitionRationale receipt cannot waive it. Use only the measured, renderer-supported grammar (white-flash, light-leak, or a fully specified zoom-pull); never use stock xfade/wipe/slide/dissolve effects and never add a transition merely to inflate density.`,
    `3f. INTRO SEAM MAP — resolve EVERY internal cut seam inside the intro individually. Put an actual transitions[].outTime within ±0.25s when the seam changes visual world or earns a bridge. For an intentionally clean hard cut, persist transitionRationale={decision:"clean-hook",reason:<20+ chars>,seams:[{outTime:<exact seam>,evidence:<12+ chars>}]} with one evidence row for that seam. Mixed real-transition and clean-hook decisions are valid; an unresolved seam is not.`,
  ];
}
