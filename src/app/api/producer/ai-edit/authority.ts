import { existsSync } from "node:fs";
import { invalidateApprovedPreview } from "@/lib/server/auto-edit-quality-artifacts";
import { palmierStatePath } from "../palmier/_lib";
import { runPalmierOwnership } from "../palmier/ownership/runner";

interface InvalidationDependencies {
  invalidatePreview: (dir: string) => void;
  palmierStateExists: (dir: string) => boolean;
  invalidatePalmier: typeof runPalmierOwnership;
}

const DEFAULT_DEPENDENCIES: InvalidationDependencies = {
  invalidatePreview: (dir) => invalidateApprovedPreview(dir, "ask-ai-edit"),
  palmierStateExists: (dir) => existsSync(palmierStatePath(dir)),
  invalidatePalmier: runPalmierOwnership,
};

export class AiEditInvalidationError extends Error {
  constructor(message: string, readonly retryable: boolean) {
    super(message);
  }
}

/**
 * Revoke disk preview authority synchronously, then revoke Palmier A/B proof
 * under its Python sidecar lock. No model may start until this resolves.
 */
export async function invalidateAiEditAuthority(
  dir: string,
  dependencies: InvalidationDependencies = DEFAULT_DEPENDENCIES,
): Promise<void> {
  dependencies.invalidatePreview(dir);
  if (!dependencies.palmierStateExists(dir)) return;
  const result = await dependencies.invalidatePalmier(dir, "invalidate");
  if (result.code === 0 && result.verdict.ok === true) return;
  const detail = result.verdict.error || "Palmier A/B authority could not be invalidated";
  throw new AiEditInvalidationError(detail, result.code === 75);
}
