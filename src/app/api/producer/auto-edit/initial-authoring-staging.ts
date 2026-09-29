import { randomUUID } from "node:crypto";
import {
  copyFileSync, existsSync, mkdtempSync,
  renameSync, rmSync, writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileSha256 } from "@/lib/server/auto-edit-hash";
import {
  resolveVisualPlanBinding, visualPlanValidationAuthority,
  type VisualPlanBinding,
} from "@/lib/server/visual-plan-binding";
import { ordinaryVisualPlanRequired, type AutoEditCtx } from "./stream";
import {
  visualPlanCatalogAuthorityPath,
  visualPlanContextPath, visualPlanRelatedUsageAuthorityPath,
  visualPlanTranscriptAuthorityPath,
} from "./visual-plan-context";
import type { AuthoringPassStage } from "./authoring";
import { readBoundedAuthoringFile } from "./initial-authoring-capture";
import {
  objectBytes, validateVisualCandidate,
} from "./initial-authoring-visual-validation";
import {
  captureVisualSearchAuthority, type CapturedVisualSearch,
} from "./initial-authoring-search-relocation";

const MAX_JSON_BYTES = 4 * 1024 * 1024;
export interface InitialAuthoringStaging {
  ctx: AutoEditCtx;
  original: AutoEditCtx;
  originalPlanHash?: string;
  stage: AuthoringPassStage;
  dispose: () => void;
}
export interface CapturedInitialAuthoring {
  staging: InitialAuthoringStaging;
  planBytes: Buffer;
  visualPlanBytes?: Buffer;
  visualSearch?: CapturedVisualSearch;
}
export interface ValidatedAuthoringPaths {
  planPath: string;
  visualPlanPath?: string;
}
type AfterValidation = (paths: ValidatedAuthoringPaths) => void;
interface ValidatedAuthoring {
  planBytes: Buffer;
  visualPlanBytes?: Buffer;
  visualPlanBinding?: VisualPlanBinding;
  promotePlan: boolean;
}

function atomicPromote(bytes: Buffer, destination: string): void {
  const temporary = `${destination}.${randomUUID()}.authoring.tmp`;
  try {
    writeFileSync(temporary, bytes, { flag: "wx", mode: 0o600 });
    renameSync(temporary, destination);
  } finally {
    rmSync(temporary, { force: true });
  }
}

function assertOriginalPlanUnchanged(staging: InitialAuthoringStaging): void {
  if (fileSha256(staging.original.planPath) !== staging.originalPlanHash) {
    throw new Error("edit_plan.json changed while isolated authoring was running");
  }
}

/** Give the initial provider one disposable writable root outside the project. */
export function prepareInitialAuthoringStaging(
  ctx: AutoEditCtx,
  stage: AuthoringPassStage,
): InitialAuthoringStaging {
  const authoringDir = mkdtempSync(path.join(os.tmpdir(), "sniper-plan-authoring-"));
  const planPath = path.join(authoringDir, "edit_plan.json");
  try {
    if (existsSync(ctx.planPath)) copyFileSync(ctx.planPath, planPath);
    if (stage === "visual" && ctx.visualPlan) {
      copyFileSync(ctx.visualPlan.path, path.join(authoringDir, "VISUAL-PLAN.json"));
    }
    return {
      ctx: { ...ctx, authoringDir, planPath }, original: ctx,
      originalPlanHash: fileSha256(ctx.planPath), stage,
      dispose: () => rmSync(authoringDir, { recursive: true, force: true }),
    };
  } catch (error) {
    rmSync(authoringDir, { recursive: true, force: true });
    throw error;
  }
}

/** Freeze provider bytes in controller memory after its process tree is fenced. */
export function captureInitialAuthoring(
  staging: InitialAuthoringStaging,
): CapturedInitialAuthoring {
  const planBytes = readBoundedAuthoringFile(
    staging.ctx.planPath, "staged edit_plan.json", MAX_JSON_BYTES,
  );
  const visualRequired = (staging.stage === "visual"
      || staging.stage === "visual-plan")
    && ordinaryVisualPlanRequired(staging.original);
  if (!visualRequired) return { staging, planBytes };
  const visualPlanBytes = readBoundedAuthoringFile(
    path.join(staging.ctx.authoringDir!, "VISUAL-PLAN.json"),
    "staged VISUAL-PLAN.json", MAX_JSON_BYTES,
  );
  const visualSearch = staging.stage === "visual-plan"
    ? captureVisualSearchAuthority(staging.ctx.authoringDir!, visualPlanBytes)
    : undefined;
  return { staging, planBytes, visualPlanBytes,
    ...(visualSearch ? { visualSearch } : {}) };
}

function validateCaptured(
  captured: CapturedInitialAuthoring,
  afterValidation?: AfterValidation,
): ValidatedAuthoring {
  const dir = mkdtempSync(path.join(os.tmpdir(), "sniper-plan-validation-"));
  const planPath = path.join(dir, "edit_plan.json");
  writeFileSync(planPath, captured.planBytes, { flag: "wx", mode: 0o600 });
  try {
    if (!captured.visualPlanBytes) {
      objectBytes(captured.planBytes, "captured edit_plan.json");
      const planBytes = readBoundedAuthoringFile(
        planPath, "validated edit_plan.json", MAX_JSON_BYTES,
      );
      afterValidation?.({ planPath });
      return { planBytes, promotePlan: true };
    }
    const visualPlanPath = path.join(dir, "VISUAL-PLAN.json");
    const paths = { planPath, visualPlanPath };
    const binding = validateVisualCandidate(captured, paths);
    const planBytes = readBoundedAuthoringFile(
      planPath, "validated edit_plan.json", MAX_JSON_BYTES,
    );
    const visualPlanBytes = readBoundedAuthoringFile(
      visualPlanPath, "validated VISUAL-PLAN.json", MAX_JSON_BYTES,
    );
    afterValidation?.(paths);
    return { planBytes, visualPlanBytes, visualPlanBinding: binding,
      promotePlan: captured.staging.stage !== "visual-plan" };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

function promoteValidated(
  captured: CapturedInitialAuthoring,
  validated: ValidatedAuthoring,
): void {
  const { staging } = captured;
  assertOriginalPlanUnchanged(staging);
  if (!validated.visualPlanBytes || !validated.visualPlanBinding) {
    atomicPromote(validated.planBytes, staging.original.planPath);
    return;
  }
  const destination = path.join(staging.original.dir, "VISUAL-PLAN.json");
  atomicPromote(validated.visualPlanBytes, destination);
  if (validated.promotePlan) {
    atomicPromote(validated.planBytes, staging.original.planPath);
  }
  const final = resolveVisualPlanBinding(
    destination, visualPlanValidationAuthority(staging.original),
    validated.visualPlanBinding.catalogReceiptAuthority,
  );
  if (!final || final.byteHash !== validated.visualPlanBinding.byteHash
      || final.visualPlanSha256 !== validated.visualPlanBinding.visualPlanSha256) {
    throw new Error("promoted visual plan differs from its validated candidate");
  }
  staging.original.visualPlan = final;
}

/** Validate memory snapshots and promote only those exact controller-held bytes. */
export function promoteCapturedInitialAuthoring(
  captured: CapturedInitialAuthoring,
  afterValidation?: AfterValidation,
): void {
  promoteValidated(captured, validateCaptured(captured, afterValidation));
}

export function promoteInitialAuthoring(staging: InitialAuthoringStaging): void {
  promoteCapturedInitialAuthoring(captureInitialAuthoring(staging));
}

/** Confirm controller-owned authority artifacts never resolve into staging. */
export function assertAuthoringAuthorityOutsideStaging(
  staging: InitialAuthoringStaging,
): void {
  const root = `${path.resolve(staging.ctx.authoringDir!)}${path.sep}`;
  const files = [staging.original.pipeline?.snapshotRoot,
    staging.original.visualPlanPipeline?.snapshotRoot,
    staging.original.doctrine?.snapshotPath,
    visualPlanContextPath(staging.original),
    visualPlanCatalogAuthorityPath(staging.original),
    visualPlanTranscriptAuthorityPath(staging.original),
    visualPlanRelatedUsageAuthorityPath(staging.original)].filter(
    (value): value is string => Boolean(value),
  );
  if (files.some((file) => path.resolve(file).startsWith(root))) {
    throw new Error("controller authority unexpectedly resolves inside authoring staging");
  }
}
