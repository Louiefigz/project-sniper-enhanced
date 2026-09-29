import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { pythonInterpreter, runtimeScriptsDir } from "../../_lib/spawn-python";
import { stableAuthorityHash } from "@/lib/server/auto-edit-authority-snapshot";
import { executablePipelineRoot } from "@/lib/server/auto-edit-pipeline-authority";
import type { VisualPlanBinding } from "@/lib/server/visual-plan-binding";
import {
  resolveVisualPlanBinding, visualPlanValidationAuthority,
} from "@/lib/server/visual-plan-binding";
import { issueCatalogReceipts } from "./catalog-receipt-controller";
import { allocatedCreativeRoute } from "./creative-route-dispatch";
import type {
  CapturedInitialAuthoring, ValidatedAuthoringPaths,
} from "./initial-authoring-staging";
import { prepareVisualPlanContext, type VisualPlanContext } from "./visual-plan-context";
import {
  relocateSearchReviews, relocateVisualSearchAuthority,
} from "./initial-authoring-search-relocation";

const MAX_JSON_BYTES = 4 * 1024 * 1024;

export function objectBytes(bytes: Buffer, label: string): Record<string, unknown> {
  if (bytes.length < 2 || bytes.length > MAX_JSON_BYTES) {
    throw new Error(`${label} exceeds the bounded JSON size`);
  }
  const value: unknown = JSON.parse(bytes.toString("utf8"));
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must contain one JSON object`);
  }
  return value as Record<string, unknown>;
}

function readObject(file: string, label: string): Record<string, unknown> {
  return objectBytes(readFileSync(file), label);
}

function assertApprovedCutUnchanged(captured: CapturedInitialAuthoring): void {
  const before = readObject(captured.staging.original.planPath, "approved edit_plan.json");
  const after = objectBytes(captured.planBytes, "captured edit_plan.json");
  for (const key of ["cutTrack", "cutDecisions"] as const) {
    if (stableAuthorityHash(before[key] ?? null)
        !== stableAuthorityHash(after[key] ?? null)) {
      throw new Error(`visual authoring changed approved ${key}`);
    }
  }
}

function assertPlanUnchanged(captured: CapturedInitialAuthoring): void {
  const before = readObject(captured.staging.original.planPath, "approved edit_plan.json");
  const after = objectBytes(captured.planBytes, "captured edit_plan.json");
  if (stableAuthorityHash(before) !== stableAuthorityHash(after)) {
    throw new Error("route-neutral visual planning changed edit_plan.json");
  }
}

function writeRelocatedVisual(
  captured: CapturedInitialAuthoring,
  context: VisualPlanContext,
  destination: string,
): void {
  if (!captured.visualPlanBytes) throw new Error("captured VISUAL-PLAN.json is missing");
  const visual = objectBytes(captured.visualPlanBytes, "captured VISUAL-PLAN.json");
  if (stableAuthorityHash(visual.project) !== stableAuthorityHash(context.project)) {
    throw new Error("staged visual plan changed the controller project authority");
  }
  visual.catalogPin = context.catalogPin;
  visual.transcriptAuthority = context.transcriptAuthority;
  visual.mediaAuthority = context.mediaAuthority;
  visual.relatedUsageAuthority = context.relatedUsageAuthority;
  visual.relatedUsage = context.relatedUsage;
  const stagedDigest = (visual.searchAuthority as Record<string, unknown>)?.digest;
  if (typeof stagedDigest !== "string") {
    throw new Error("staged visual plan lacks searchAuthority digest");
  }
  const searchAuthority = relocateVisualSearchAuthority(captured, context, visual);
  relocateSearchReviews(visual, stagedDigest, searchAuthority.digest);
  visual.searchAuthority = searchAuthority;
  writeFileSync(destination, `${JSON.stringify(visual, null, 2)}\n`, {
    flag: "wx", mode: 0o600,
  });
}

function hasCatalogCandidate(file: string): boolean {
  const plan = readObject(file, "relocated VISUAL-PLAN.json");
  if (!Array.isArray(plan.opportunities)) return false;
  return plan.opportunities.some((raw) => {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return false;
    const candidates = (raw as Record<string, unknown>).candidates;
    return Array.isArray(candidates) && candidates.some((candidate) => candidate
      && typeof candidate === "object" && !Array.isArray(candidate)
      && (candidate as Record<string, unknown>).modality === "catalog");
  });
}

function pipelineRoot(captured: CapturedInitialAuthoring): string | undefined {
  const ctx = captured.staging.original;
  const authority = ctx.visualPlanPipeline ?? ctx.pipeline;
  return authority ? executablePipelineRoot(ctx.dir, authority) : undefined;
}

function allocateWithoutReceipts(
  captured: CapturedInitialAuthoring,
  visualPlanPath: string,
): void {
  const script = path.join(
    runtimeScriptsDir(), "producer/planner/visual_plan_cli.py",
  );
  const root = pipelineRoot(captured);
  const allocated = execFileSync(
    pythonInterpreter(), ["-B", script, "allocate", visualPlanPath], {
      encoding: "utf8", timeout: 30_000, maxBuffer: MAX_JSON_BYTES,
      env: { NODE_ENV: "production", PYTHONDONTWRITEBYTECODE: "1", PYTHONUTF8: "1",
        ...(root ? { SNIPER_PIPELINE_ROOT: root } : {}) },
    },
  );
  objectBytes(Buffer.from(allocated), "controller-allocated VISUAL-PLAN.json");
  writeFileSync(visualPlanPath, allocated, { mode: 0o600 });
}

function allocatePlanningCandidate(
  captured: CapturedInitialAuthoring,
  visualPlanPath: string,
): VisualPlanBinding {
  const receipt = hasCatalogCandidate(visualPlanPath)
    ? issueCatalogReceipts(captured.staging.original, visualPlanPath) : undefined;
  if (!receipt) allocateWithoutReceipts(captured, visualPlanPath);
  const binding = resolveVisualPlanBinding(
    visualPlanPath, visualPlanValidationAuthority(captured.staging.original), receipt,
  );
  if (!binding) throw new Error("controller-allocated VISUAL-PLAN.json is missing");
  allocatedCreativeRoute(captured.staging.original, binding);
  return binding;
}

function validatePlanning(
  captured: CapturedInitialAuthoring,
  paths: Required<ValidatedAuthoringPaths>,
): VisualPlanBinding {
  assertPlanUnchanged(captured);
  const context = prepareVisualPlanContext(captured.staging.original);
  if (!context) throw new Error("visual-plan context is unavailable at promotion");
  writeRelocatedVisual(captured, context, paths.visualPlanPath);
  return allocatePlanningCandidate(captured, paths.visualPlanPath);
}

function bindEditPlan(planPath: string, binding: VisualPlanBinding): void {
  const plan = readObject(planPath, "captured edit_plan.json");
  const application = plan.visualPlanApplication;
  if (!application || typeof application !== "object" || Array.isArray(application)) {
    throw new Error("staged edit plan lacks visualPlanApplication");
  }
  (application as Record<string, unknown>).visualPlan = {
    byteHash: binding.byteHash, visualPlanSha256: binding.visualPlanSha256,
  };
  writeFileSync(planPath, `${JSON.stringify(plan, null, 2)}\n`, { mode: 0o600 });
}

function validateApplication(
  captured: CapturedInitialAuthoring,
  paths: Required<ValidatedAuthoringPaths>,
  binding: VisualPlanBinding,
): void {
  const script = path.join(
    runtimeScriptsDir(), "producer/planner/ordinary_visual_plan_lint.py",
  );
  const root = pipelineRoot(captured);
  execFileSync(pythonInterpreter(), ["-B", script, paths.planPath,
    paths.visualPlanPath,
    ...(binding.catalogReceiptAuthority
      ? ["--receipt-authority", binding.catalogReceiptAuthority.path] : [])], {
    encoding: "utf8", timeout: 30_000, maxBuffer: 1024 * 1024,
    env: { NODE_ENV: "production", PYTHONDONTWRITEBYTECODE: "1", PYTHONUTF8: "1",
      ...(root ? { SNIPER_PIPELINE_ROOT: root } : {}) },
  });
}

function validateExisting(
  captured: CapturedInitialAuthoring,
  paths: Required<ValidatedAuthoringPaths>,
): VisualPlanBinding {
  assertApprovedCutUnchanged(captured);
  const expected = captured.staging.original.visualPlan;
  if (!expected || !captured.visualPlanBytes) {
    throw new Error("ordinary execution authoring lacks its allocated visual plan");
  }
  writeFileSync(paths.visualPlanPath, captured.visualPlanBytes, {
    flag: "wx", mode: 0o600,
  });
  const binding = resolveVisualPlanBinding(
    paths.visualPlanPath, visualPlanValidationAuthority(captured.staging.original),
    expected.catalogReceiptAuthority,
  );
  if (!binding || binding.byteHash !== expected.byteHash
      || binding.visualPlanSha256 !== expected.visualPlanSha256) {
    throw new Error("visual execution author changed the allocated visual plan");
  }
  if (allocatedCreativeRoute(captured.staging.original, binding) !== "ordinary") {
    throw new Error("ordinary execution author received a native visual route");
  }
  bindEditPlan(paths.planPath, binding);
  validateApplication(captured, paths, binding);
  return binding;
}

/** Validate either the pending creative proposal or the later ordinary execution. */
export function validateVisualCandidate(
  captured: CapturedInitialAuthoring,
  paths: Required<ValidatedAuthoringPaths>,
): VisualPlanBinding {
  return captured.staging.stage === "visual-plan"
    ? validatePlanning(captured, paths) : validateExisting(captured, paths);
}
