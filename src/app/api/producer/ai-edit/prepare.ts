import { lstatSync, readFileSync } from "fs";
import path from "path";
import { brainProvider, type BrainProvider } from "../../_lib/ai-provider";
import { planCanvas } from "@/lib/producer/comps-catalog";
import type { EditPlan } from "@/lib/producer/edit-plan";
import { validateRequestedSurgicalEditScope,
  type SurgicalEditScope } from "@/lib/producer/surgical-edit";
import { resolveManifest } from "../auto-edit/chain";
import { AutoEditError } from "../auto-edit/stream";
import { AiEditInvalidationError, invalidateAiEditAuthority } from "./authority";
import { guardPalmierCanonicalForAiEdit,
  PalmierCanonicalError } from "./palmier-canonical";
import {
  assertNoPromotionReconciliation,
  PromotionReconciliationError,
} from "./promotion-recovery";

export interface PreparedSurgicalRequest {
  dir: string;
  request: string;
  scope: SurgicalEditScope;
  planPath: string;
  plan: EditPlan;
  canvas: ReturnType<typeof planCanvas>;
  manifestPath: string;
  transcriptsDir: string;
  provider: BrainProvider;
}

export function prepareSurgicalRequest(body: unknown): PreparedSurgicalRequest | Response {
  const row = body && typeof body === "object" ? body as Record<string, unknown> : {};
  const dir = typeof row.dir === "string" ? row.dir.replace(/\/$/, "") : "";
  const request = typeof row.request === "string" ? row.request.trim() : "";
  if (!dir || !request) return json({ error: "Missing dir or request" }, 400);
  let scope: SurgicalEditScope;
  try {
    scope = validateRequestedSurgicalEditScope(request, row.scope);
  } catch (error) {
    return json({ error: `Choose a specific edit lane (cuts, graphics, motion, captions, b-roll, audio, music, or reframe): ${(error as Error).message}` }, 422);
  }
  const planPath = path.join(dir, "edit_plan.json");
  let planText: string;
  try {
    const before = lstatSync(planPath);
    if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1) {
      throw new Error("edit_plan.json must be one regular non-symlink authority file");
    }
    planText = readFileSync(planPath, "utf8");
    const after = lstatSync(planPath);
    if (!after.isFile() || after.isSymbolicLink() || after.nlink !== 1
        || before.dev !== after.dev || before.ino !== after.ino) {
      throw new Error("edit_plan.json changed identity while it was being read");
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      return json({ error: (error as Error).message }, 409);
    }
    return json({ error: `No edit_plan.json in ${dir}` }, 404);
  }
  let provider: BrainProvider;
  try { provider = brainProvider(); } catch (error) {
    return json({ error: `AI provider configuration failed: ${(error as Error).message}` }, 500);
  }
  try {
    const plan = JSON.parse(planText) as EditPlan;
    const canvas = planCanvas(plan.target);
    const { manifestPath, transcriptsDir } = resolveManifest(dir);
    return { dir, request, scope, planPath, plan, canvas,
      manifestPath, transcriptsDir, provider };
  } catch (error) {
    const status = error instanceof AutoEditError ? 409 : 422;
    return json({ error: `Could not prepare this edit: ${(error as Error).message}` }, status);
  }
}

export async function surgicalAuthorityFailure(dir: string): Promise<Response | null> {
  try {
    assertNoPromotionReconciliation(dir);
    await guardPalmierCanonicalForAiEdit(dir);
    await invalidateAiEditAuthority(dir);
    return null;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (error instanceof PalmierCanonicalError) {
      return json({ error: `Palmier is the source of truth: ${message}` }, error.statusCode);
    }
    const status = error instanceof PromotionReconciliationError
      || (error instanceof AiEditInvalidationError && error.retryable) ? 409 : 500;
    return json({ error: `Could not invalidate stale preview authority: ${message}` }, status);
  }
}

function json(obj: unknown, status: number): Response {
  return new Response(JSON.stringify(obj), { status,
    headers: { "Content-Type": "application/json" } });
}
