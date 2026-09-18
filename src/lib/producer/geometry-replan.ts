/**
 * geometry-replan — the typed NoLegalRegion → re-plan routing decision
 * (Plan-Time Geometry Contract v3, item #3 / amendment A2).
 *
 * The fail-closed placement core raises a typed `NoLegalRegion` whose message
 * carries a stable `"NoLegalRegion: {json}"` signature through the
 * render/assemble NDJSON error stream. Without a route, that raise after the
 * review wall would wedge the job (worker.ts has exactly one failure path).
 * This module owns the PURE routing decision: exactly ONE re-plan attempt per
 * job; a second geometry failure — or any non-geometry failure — stays
 * terminal. The pipeline stage (`geometry-replan-stage.ts`) performs the
 * actual revision + checkpoint invalidation.
 */

export const NO_LEGAL_REGION_TOKEN = "NoLegalRegion";

/** Mutable per-job routing state (one attempt budget). */
export interface GeometryReplanState {
  attempts: number;
}

export type GeometryDecision =
  | { action: "replan"; evidence: string }
  | { action: "fail"; message: string };

/**
 * Extract the typed NoLegalRegion evidence from an error/NDJSON text, or null
 * when the failure is not the typed geometry signature.
 */
export function noLegalRegionEvidence(text: string): string | null {
  const at = text.lastIndexOf(`${NO_LEGAL_REGION_TOKEN}:`);
  if (at === -1) return null;
  const evidence = text.slice(at + NO_LEGAL_REGION_TOKEN.length + 1).trim();
  // The python side appends the compact JSON payload; keep whatever survived
  // any tail truncation — the brain only needs the anatomy numbers.
  return evidence.length ? evidence.slice(0, 1800) : null;
}

/**
 * Decide what one render/assemble failure does to the job.
 *
 * First typed geometry failure → route to a single re-plan (state is
 * charged). Second typed failure → terminal, with the typed evidence in the
 * message. Non-geometry failures are never routed.
 */
export function decideGeometryFailure(
  state: GeometryReplanState,
  message: string,
): GeometryDecision {
  const evidence = noLegalRegionEvidence(message);
  if (evidence === null) return { action: "fail", message };
  if (state.attempts >= 1) {
    return {
      action: "fail",
      message: `geometry re-plan already attempted once; render still has no legal region — ${NO_LEGAL_REGION_TOKEN}: ${evidence}`,
    };
  }
  state.attempts += 1;
  return { action: "replan", evidence };
}
