/**
 * geometry-replan-stage — the ONE bounded typed-error → re-plan route
 * (Plan-Time Geometry Contract v3 item #3, amendment A2).
 *
 * When render/assemble fails with the typed `NoLegalRegion` signature, the
 * job is NOT terminally failed: the geometry evidence is injected as a
 * critique row (a synthetic critical plan review) and the existing revision
 * machinery rewrites the plan, after which checkpoints are invalidated back
 * to `plan_authored` so the re-planned plan goes through the NORMAL gate +
 * review path — it is a new hash-bound authority, never a patch. Exactly one
 * attempt per job; a second geometry failure (or any non-geometry failure)
 * rethrows terminally with the typed evidence in the message.
 */

import { snapshotPlan } from "../../_lib/plan-snapshots";
import { planContentHash } from "@/lib/server/auto-edit-authority";
import { autoEditAuthoritySnapshot } from "@/lib/server/auto-edit-authority-snapshot";
import { fileSha256 } from "@/lib/server/auto-edit-job-store";
import {
  decideGeometryFailure,
  type GeometryReplanState,
} from "@/lib/producer/geometry-replan";
import { deferredFailure } from "./gate-fix";
import type { runProducerRevision } from "./brain-review-runner";
import type { ProducerReview } from "./review-contract";
import type { PipelineRuntime } from "./pipeline-types";
import { AutoEditError } from "./stream";

export interface GeometryReplanDeps {
  revise: typeof runProducerRevision;
  authority: typeof autoEditAuthoritySnapshot;
  hashFile: typeof fileSha256;
}

function evidenceChunks(evidence: string): string[] {
  const chunks: string[] = [];
  for (let i = 0; i < evidence.length && chunks.length < 20; i += 900) {
    chunks.push(evidence.slice(i, i + 900));
  }
  return chunks.length ? chunks : ["(no evidence payload survived the error tail)"];
}

/** The synthetic critique row carrying the render's anatomy evidence. */
export function geometryCritique(evidence: string): ProducerReview {
  return {
    schemaVersion: 1,
    stage: "plan",
    verdict: "revise",
    summary: "Render-time placement failed closed: no legal free-space region can hold a face-anchored graphic's measured content under the real reframe/punch geometry.",
    materialIssues: [{
      code: "GEOMETRY_NO_LEGAL_REGION",
      severity: "critical",
      lane: "graphics",
      message: `The renderer's placement authority raised NoLegalRegion for a face-anchored graphicsTrack entry. Evidence: ${evidence}`.slice(0, 2000),
      evidence: evidenceChunks(evidence),
      requiredAction: "Swap the failing entry's FORM or window so a legal region exists (smaller anatomy, own-screen takeover, different anchor, or a window where the face is framed wider). Never author placement pixels — placement stays render-owned.",
    }],
    findings: [],
  };
}

/**
 * Route one render/quality failure: re-plan ONCE on the typed geometry
 * signature, rethrow terminally otherwise. On the re-plan path the revised
 * plan's checkpoints are invalidated to `plan_authored`, so the caller's next
 * loop iteration re-runs deterministic gates + bounded independent review on
 * the new authority.
 */
export async function routeGeometryFailure(
  run: PipelineRuntime,
  deps: GeometryReplanDeps,
  state: GeometryReplanState,
  error: unknown,
): Promise<void> {
  const message = error instanceof Error ? error.message : String(error);
  const decision = decideGeometryFailure(state, message);
  if (decision.action === "fail") {
    if (decision.message !== message) throw new AutoEditError(decision.message);
    throw error;
  }
  const { ctx } = run.job;
  run.io.send({
    event: "geometry_replan", stage: "render", attempt: state.attempts,
    evidence: decision.evidence.slice(0, 1000),
  });
  const before = planContentHash(ctx.planPath);
  snapshotPlan(ctx.planPath);
  const round = (run.job.planningRound ?? 0) + 1;
  const result = await deps.revise(ctx, geometryCritique(decision.evidence), round);
  const deferred = deferredFailure(result);
  if (deferred) throw new AutoEditError(deferred);
  if (!result.receipt.changedPlan || planContentHash(ctx.planPath) === before) {
    throw new AutoEditError(
      "geometry re-plan reported an addressed issue but did not change edit_plan.json",
    );
  }
  run.job = run.io.invalidate({
    checkpoint: "plan_authored",
    phase: "planning_review",
    message: "Geometry re-plan revised the plan; restarting bounded gates + review on the new authority.",
    planningCleanRounds: 0,
    planHash: deps.hashFile(ctx.planPath),
    authorityDigest: deps.authority(ctx).digest,
  });
  run.io.send({
    event: "geometry_replan_completed", attempt: state.attempts,
    provider: result.provider,
  });
}
