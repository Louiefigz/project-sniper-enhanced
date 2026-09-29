import { randomUUID } from "crypto";
import {
  copyFileSync,
  chmodSync,
  existsSync,
  lstatSync,
  mkdtempSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "fs";
import os from "os";
import path from "path";
import { planContentHash } from "@/lib/server/auto-edit-authority";
import { fileSha256 } from "@/lib/server/auto-edit-hash";
import type { AutoEditCtx } from "./stream";
import { reconcileGraphicIds, type EditPlan } from "@/lib/producer/edit-plan";
import {
  assertVisualPlanBinding,
  resolveVisualPlanBinding,
  visualPlanValidationAuthority,
  type VisualPlanBinding,
  type VisualPlanValidationAuthority,
} from "@/lib/server/visual-plan-binding";

export interface RevisionStaging {
  ctx: AutoEditCtx;
  originalPlanPath: string;
  originalFileHash: string;
  originalContentHash: string;
  originalVisualPlan?: VisualPlanBinding;
  stagedVisualPlanHash?: string;
  visualPlanAuthority?: VisualPlanValidationAuthority;
  dispose: () => void;
}

export class RevisionNoChangeError extends Error {
  readonly code = "REVISION_NO_RENDER_CHANGE";

  constructor() {
    super(
      "revision receipt claimed a plan change, but staged edit_plan.json had no render-affecting change",
    );
    this.name = "RevisionNoChangeError";
  }
}

const CUT_MUTABLE_KEYS = new Set(["planVersion", "cutTrack", "cutDecisions"]);

function planRecord(filePath: string): Record<string, unknown> {
  const value: unknown = JSON.parse(readFileSync(filePath, "utf8"));
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("revision output must be a JSON object");
  }
  return value as Record<string, unknown>;
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, item]) => [key, stableValue(item)]));
}

/** Fail closed if a cut-stage writer touches a downstream plan lane. */
export function assertCutOnlyRevision(staging: RevisionStaging): void {
  const before = planRecord(staging.originalPlanPath);
  const after = planRecord(staging.ctx.planPath);
  const protectedKeys = new Set([...Object.keys(before), ...Object.keys(after)]
    .filter((key) => key !== "target" && !CUT_MUTABLE_KEYS.has(key)));
  for (const key of protectedKeys) {
    if (JSON.stringify(stableValue(before[key])) !== JSON.stringify(stableValue(after[key]))) {
      throw new Error(`cut revision changed protected plan field: ${key}`);
    }
  }
  const protectedTarget = (value: unknown): unknown => {
    if (value === undefined) return {};
    if (!value || typeof value !== "object" || Array.isArray(value)) return value;
    const { durationTargetS: _duration, ...protectedFields } = value as Record<string, unknown>;
    void _duration;
    return stableValue(protectedFields);
  };
  if (JSON.stringify(protectedTarget(before.target))
      !== JSON.stringify(protectedTarget(after.target))) {
    throw new Error("cut revision changed protected plan field: target");
  }
}

function required(value: string | undefined, label: string): string {
  if (!value) throw new Error(`cannot stage ${label}`);
  return value;
}

function stageVisualPlan(
  ctx: AutoEditCtx,
  dir: string,
  authority?: VisualPlanValidationAuthority,
): { binding: VisualPlanBinding; source: VisualPlanBinding } | null {
  if (!ctx.visualPlan) return null;
  const source = assertVisualPlanBinding(ctx.visualPlan, authority);
  const destination = path.join(dir, "VISUAL-PLAN.json");
  copyFileSync(source.path, destination);
  chmodSync(destination, 0o400);
  const binding = resolveVisualPlanBinding(destination, authority);
  if (!binding || binding.byteHash !== source.byteHash
      || binding.visualPlanSha256 !== source.visualPlanSha256) {
    throw new Error("staged VISUAL-PLAN.json differs from its bound source");
  }
  return { binding, source };
}

function assertVisualPlanUnchanged(staging: RevisionStaging): void {
  if (!staging.originalVisualPlan) return;
  assertVisualPlanBinding(staging.originalVisualPlan, staging.visualPlanAuthority);
  const binding = staging.ctx.visualPlan;
  if (!binding || !existsSync(binding.path)
      || assertVisualPlanBinding(binding, staging.visualPlanAuthority).byteHash
        !== staging.stagedVisualPlanHash) {
    throw new Error("staged VISUAL-PLAN.json changed during plan revision");
  }
}

/** Give a model one disposable writable directory, never the producer dir. */
export function prepareRevisionStaging(ctx: AutoEditCtx): RevisionStaging {
  const dir = mkdtempSync(path.join(os.tmpdir(), "sniper-plan-revision-"));
  const planPath = path.join(dir, "edit_plan.json");
  try {
    copyFileSync(ctx.planPath, planPath);
    const visualPlanAuthority = visualPlanValidationAuthority(ctx);
    const visualPlan = stageVisualPlan(ctx, dir, visualPlanAuthority);
    return {
      ctx: { ...ctx, dir, planPath,
        ...(visualPlan ? { visualPlan: visualPlan.binding } : {}) },
      originalPlanPath: ctx.planPath,
      originalFileHash: required(fileSha256(ctx.planPath), "original plan bytes"),
      originalContentHash: required(planContentHash(ctx.planPath), "original plan content"),
      ...(visualPlan ? {
        originalVisualPlan: visualPlan.source,
        stagedVisualPlanHash: visualPlan.binding.byteHash,
        ...(visualPlanAuthority ? { visualPlanAuthority } : {}),
      } : {}),
      dispose: () => rmSync(dir, { recursive: true, force: true }),
    };
  } catch (error) {
    rmSync(dir, { recursive: true, force: true });
    throw error;
  }
}

function validPlanBytes(planPath: string): Buffer {
  if (!lstatSync(planPath).isFile()) throw new Error("revision output is not a regular plan file");
  const bytes = readFileSync(planPath);
  const value: unknown = JSON.parse(bytes.toString("utf8"));
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("revision output must be a JSON object");
  }
  return bytes;
}

function normalizeGraphicBindings(planPath: string): void {
  const value = JSON.parse(readFileSync(planPath, "utf8")) as EditPlan;
  const normalized = reconcileGraphicIds(value).plan;
  if (normalized !== value) {
    writeFileSync(planPath, `${JSON.stringify(normalized, null, 2)}\n`);
  }
}

/** Accept a truthful all-deferred receipt only when the staged plan stayed unchanged. */
export function assertRevisionPlanUnchanged(staging: RevisionStaging): void {
  assertVisualPlanUnchanged(staging);
  if (fileSha256(staging.originalPlanPath) !== staging.originalFileHash) {
    throw new Error("edit_plan.json changed while the isolated revision writer was running");
  }
  const stagedHash = planContentHash(staging.ctx.planPath);
  if (!stagedHash || stagedHash !== staging.originalContentHash) {
    throw new Error("revision receipt reported no plan change, but staged content changed");
  }
}

/** Atomically promote only a content-changing staged edit_plan.json. */
export function promoteRevisionPlan(
  staging: RevisionStaging,
  normalizeGraphics = true,
): void {
  assertVisualPlanUnchanged(staging);
  if (fileSha256(staging.originalPlanPath) !== staging.originalFileHash) {
    throw new Error("edit_plan.json changed while the isolated revision writer was running");
  }
  if (normalizeGraphics) normalizeGraphicBindings(staging.ctx.planPath);
  const nextContentHash = planContentHash(staging.ctx.planPath);
  if (!nextContentHash || nextContentHash === staging.originalContentHash) {
    throw new RevisionNoChangeError();
  }
  const bytes = validPlanBytes(staging.ctx.planPath);
  const temporary = `${staging.originalPlanPath}.${randomUUID()}.revision.tmp`;
  try {
    writeFileSync(temporary, bytes, { flag: "wx", mode: 0o600 });
    renameSync(temporary, staging.originalPlanPath);
  } finally {
    rmSync(temporary, { force: true });
  }
}
