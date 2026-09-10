import path from "node:path";
import type { BrainProvider } from "../../_lib/ai-provider";
import type { runCodex } from "../../_lib/codex-cli";
import {
  uniqueBrainDirs, type BrainProcessResult, type LegacyBrainInvocation,
} from "./brain-review-process";
import { REPO_ROOT } from "./authoring-prompt";
import type { AutoEditCtx } from "./stream";

// Existing hard process ceilings, not workload estimates or permission to
// approve an over-budget/failed edit. Provider reasoning policies are unchanged.
function timeoutMinutes(envKey: string, fallbackMin: number): number {
  const raw = process.env[envKey]?.trim();
  if (!raw) return fallbackMin;
  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed < 5 || parsed > 240) {
    throw new Error(`${envKey} must be an integer 5..240 (minutes)`);
  }
  return parsed;
}
export const REVIEW_TIMEOUT_MS = timeoutMinutes("SNIPER_REVIEW_TIMEOUT_MIN", 25) * 60 * 1000;
export const REVIEW_STAGE_DEADLINE_MS =
  timeoutMinutes("SNIPER_REVIEW_STAGE_TIMEOUT_MIN", 20) * 60 * 1000;
export const GATE_FIX_TIMEOUT_MS = 6 * 60 * 1000;
export const PRODUCER_CRITIC_REASONING = "medium" as const;
export const GATE_FIX_REASONING = "low" as const;
export type CodexRunner = typeof runCodex;
export type LegacyRunner = (invocation: LegacyBrainInvocation) => Promise<BrainProcessResult>;

export interface BrainReviewDependencies {
  provider?: () => BrainProvider;
  codex?: CodexRunner;
  legacy?: LegacyRunner;
}

function referenceDirs(ctx: AutoEditCtx): string[] {
  const study = ctx.referenceStudy;
  return study ? [
    path.dirname(study.profilePath),
    path.dirname(study.deepStudyPath),
    ...study.representativeFrames.map(path.dirname),
  ] : [];
}

function authorityDirs(ctx: AutoEditCtx): string[] {
  return [...(ctx.doctrine ? [path.dirname(ctx.doctrine.snapshotPath)] : []),
    ...(ctx.pipeline ? [ctx.pipeline.snapshotRoot] : []),
    ...(ctx.templateUsage ? [path.dirname(ctx.templateUsage.path)] : [])];
}

/** Existing read scope for rendered critics and isolated revision staging. */
export function brainReadDirs(ctx: AutoEditCtx, additional: string[] = []): string[] {
  return uniqueBrainDirs([
    REPO_ROOT, ctx.dir, ctx.transcriptsDir, ...authorityDirs(ctx), ...referenceDirs(ctx), ...additional,
  ]);
}
