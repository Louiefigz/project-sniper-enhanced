/** Exact candidate/intake/current-runtime binding for the existing worker's opt-in cut review. */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { parseAutoEditIntent } from "@/app/api/producer/auto-edit/stream";
import { readCutPreviewObject, observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { autoEditJobPath, parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import { restoreAutoEditPipeline } from "./auto-edit-pipeline-authority";
import { assertBootstrapBytes, assertBootstrapJob, assertNoBootstrapFailure, bootstrapSeedPath } from "./guided-project-bootstrap-store";
import { assertBootstrapIntent } from "./guided-project-bootstrap-contract";
import { exactKeys, objectValue } from "@/lib/producer/contracts/validation";
import { authoredCutSeed } from "./guided-project-bootstrap-inputs";
import { autoEditTranscriptDigest } from "./auto-edit-authority-snapshot";
import { authoredPreparationRemainingMs } from "./guided-project-preparation-deadline";
import type { AutoEditJob } from "./auto-edit-job-types";

export function assertBootstrapCode(job: AutoEditJob): void {
  if (!job.ctx.pipeline || !job.ctx.doctrine) throw new Error("Existing-cut review requires pinned Producer context");
  const pinned = restoreAutoEditPipeline(job.ctx.pipeline);
  const rows = pinned.files.filter((row) => /\.(?:tsx?|[cm]?js)$/u.test(row.path) || /^package(?:-lock)?\.json$/u.test(row.path));
  const required = ["src/app/api/producer/auto-edit/worker.ts", "src/app/api/producer/auto-edit/authoring-stage.ts",
    "src/lib/server/guided-project-bootstrap-guard.ts", "src/lib/server/guided-project-bootstrap-stage.ts"];
  if (job.ctx.authoredCut) required.push("src/lib/server/guided-project-author-cut-stage.ts",
    "src/app/api/producer/auto-edit/authoring-writer.ts", "src/lib/server/guided-project-preparation-deadline.ts");
  if (!required.every((file) => rows.some((row) => row.path === file))) throw new Error("Bootstrap runtime closure is incomplete");
  for (const row of rows) {
    const actual = observeCutPreviewFile(path.join(process.cwd(), row.path), 16 * 1024 * 1024);
    if (actual.sha256 !== row.hash) throw new Error(`Live bootstrap runtime changed: ${row.path}`);
  }
}

/** Fixed runtime seam for metadata guard tests; never selected by a request or environment. */
export const bootstrapRuntimeGuards = { code: assertBootstrapCode };

/** Only existing save-plan's version increment may change the submitted cut-only object. */
export function assertBootstrapSavedPlan(original: Record<string, unknown>, saved: Record<string, unknown>): void {
  const version = original.planVersion ?? 0;
  if (!Number.isSafeInteger(version) || Number(version) < 0 || Number(version) >= Number.MAX_SAFE_INTEGER
      || saved.planVersion !== Number(version) + 1) throw new Error("Saved bootstrap plan has an invalid version increment");
  const { planVersion: _old, ...before } = original, { planVersion: _new, ...after } = saved;
  void _old; void _new;
  if (!isDeepStrictEqual(before, after)) throw new Error("Bootstrap save changed candidate content beyond planVersion");
}

/** The seed carries fixed target intent; only predicted duration and cut fields may evolve. */
function assertAuthoredPlan(job: AutoEditJob, intake: ReturnType<typeof assertBootstrapJob>): string {
  if (!job.ctx.authoredCut || intake.request.operation !== "author-cut") throw new Error("Authored cut lacks its exact intake policy");
  const seed = readCutPreviewObject(bootstrapSeedPath(job.ctx.dir));
  if (seed.sha256 !== job.ctx.authoredCut.initialPlanSha256) throw new Error("Authored cut seed bytes changed");
  assertBootstrapSavedPlan(authoredCutSeed(intake.request), seed.value);
  const saved = readCutPreviewObject(job.ctx.planPath), plan = saved.value;
  const keys = ["planVersion", "target", "cutTrack", "cutDecisions"];
  exactKeys(plan, keys, keys, "authored previsual plan");
  const { durationTargetS: _before, ...fixed } = objectValue(seed.value.target, "seed target");
  const { durationTargetS: duration, ...actual } = objectValue(plan.target, "authored target");
  void _before;
  if (!isDeepStrictEqual(fixed, actual)) throw new Error("Authored cut changed protected target fields");
  if (!Number.isSafeInteger(plan.planVersion) || Number(plan.planVersion) < Number(seed.value.planVersion)) {
    throw new Error("Authored cut planVersion must preserve or advance the seed version");
  }
  if (autoEditTranscriptDigest(job.ctx) !== job.ctx.authoredCut.transcriptDigest) throw new Error("Authored cut transcript identity changed");
  if (saved.sha256 === seed.sha256) return saved.sha256; // Unapproved initial scaffold only, never a draft.
  if (typeof duration !== "number" || !Number.isFinite(duration) || duration <= 0) throw new Error("Authored cut needs its predicted positive duration");
  if (!Array.isArray(plan.cutTrack) || !plan.cutTrack.length || plan.cutTrack.length > 500) throw new Error("Authored cut needs 1..500 proposed cuts");
  for (const item of plan.cutTrack) {
    const cut = objectValue(item, "authored cut");
    if ((cut.speed !== undefined && cut.speed !== 1) || (cut.audioLeadMs !== undefined && cut.audioLeadMs !== 0)) {
      throw new Error("Authored previsual cut cannot retime speech or add J-cut leads");
    }
  }
  assertBootstrapIntent(plan, intake.request.intent);
  return saved.sha256;
}

function assertCurrentPlan(job: AutoEditJob, intake: ReturnType<typeof assertBootstrapJob>): string {
  if (intake.request.operation === "author-cut") return assertAuthoredPlan(job, intake);
  const original = readCutPreviewObject(intake.request.candidate.path).value;
  const saved = readCutPreviewObject(job.ctx.planPath);
  assertBootstrapSavedPlan(original, saved.value); assertBootstrapIntent(saved.value, intake.request.intent);
  return saved.sha256;
}

export function assertBootstrapCurrent(job: AutoEditJob): string {
  const intake = assertBootstrapJob(job);
  authoredPreparationRemainingMs(job.ctx);
  const journal = readCutPreviewObject(autoEditJobPath(job.ctx.dir)), current = parseAutoEditJobRecord(journal.value);
  if (current.token !== job.token || current.requestKey !== job.requestKey || current.status !== "running"
      || current.attempts !== 1 || current.cutAcceptance || current.guidedHandoffV2
      || !isDeepStrictEqual(current.ctx, job.ctx)) throw new Error("Bootstrap worker lost its exact new job or runtime context");
  assertNoBootstrapFailure(job.ctx.dir);
  if (job.ctx.scope !== intake.request.intent.scope
      || !isDeepStrictEqual(job.ctx.intent, parseAutoEditIntent(intake.request.intent as unknown as Record<string, unknown>))) {
    throw new Error("Bootstrap context changed operator intent");
  }
  assertBootstrapBytes(job);
  const planHash = assertCurrentPlan(job, intake);
  const projectPath = path.join(path.dirname(job.ctx.dir), "project.json");
  const heldProject = readCutPreviewObject(projectPath), project = heldProject.value;
  if (!isDeepStrictEqual(project.intent, intake.request.intent) || !isDeepStrictEqual(project.requestedIntent, intake.request.intent)
      || !isDeepStrictEqual(project.resolvedIntent, intake.request.intent)) throw new Error("Stored bootstrap operator intent changed");
  bootstrapRuntimeGuards.code(job);
  assertBootstrapBytes(job);
  const held = [{ path: job.ctx.planPath, sha256: planHash },
    { path: autoEditJobPath(job.ctx.dir), sha256: journal.sha256 }, { path: projectPath, sha256: heldProject.sha256 }];
  for (const ref of held) {
    if (observeCutPreviewFile(ref.path, 16 * 1024 * 1024).sha256 !== ref.sha256) throw new Error("Bootstrap checked plan, journal or project changed during authorization");
  }
  if (job.ctx.authoredCut && autoEditTranscriptDigest(job.ctx) !== job.ctx.authoredCut.transcriptDigest) {
    throw new Error("Authored cut transcript identity changed during authorization");
  }
  authoredPreparationRemainingMs(job.ctx);
  return planHash;
}

/** A new writer starts only from the exact retained empty scaffold, never a reusable draft. */
export function assertAuthoredBootstrapSeed(job: AutoEditJob): void {
  const checked = assertBootstrapCurrent(job);
  if (!job.ctx.authoredCut || checked !== job.ctx.authoredCut.initialPlanSha256) {
    throw new Error("Authored cut must start from its exact unapproved seed");
  }
}

/** Run after editor outcome checks and before normalization, recovery or session binding. */
export function assertAuthoredBootstrapDraft(job: AutoEditJob): void {
  const checked = assertBootstrapCurrent(job);
  if (!job.ctx.authoredCut || checked === job.ctx.authoredCut.initialPlanSha256) {
    throw new Error("Authored cut wrote no proposed cut; the empty seed is not a draft");
  }
}
