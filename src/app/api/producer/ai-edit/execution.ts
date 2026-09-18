import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { createHash, randomUUID } from "node:crypto";
import {
  claudeModelArgs,
  claudeSettings,
  type BrainProvider,
} from "../../_lib/ai-provider";
import { snapshotPlan } from "../../_lib/plan-snapshots";
import { reconcileGraphicIds, type EditPlan } from "@/lib/producer/edit-plan";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { atomicWriteFileSync } from "@/lib/server/atomic-file";
import { dlog } from "@/lib/debug";
import { reconcileCaptionPlanAuthority } from "./caption-plan-authority-v1";
import {
  CAPTION_TIMESTAMP_TOLERANCE_S,
  buildCaptionWordIndex,
  resolveCaptionRequestAnchors,
} from "./caption-word-index-v1";

export const AI_EDIT_TIMEOUT_MS = 10 * 60 * 1000;

export type AiEditInvocation =
  | { provider: "legacy"; label: "Claude Code"; model: string; args: string[] }
  | {
      provider: "codex";
      label: "Codex";
      options: {
        prompt: string;
        sandbox: "workspace-write";
        timeoutMs: number;
        cwd: string;
      };
    };

export interface StagedAiPlan {
  snapshots: number;
  candidatePath: string;
  stagingDir: string;
  originalPlanText: string;
  parentPlanHash: string;
  captionWordIndexPath?: string;
}

export interface CaptionStagingInput {
  request: string;
  manifestPath: string;
  transcriptsDir: string;
}

export function claudeAiEditArgs(
  prompt: string,
  dir: string,
  planPath = path.join(dir, "edit_plan.json"),
): string[] {
  const candidateDir = path.dirname(planPath);
  return [
    "-p", prompt,
    ...claudeModelArgs(),
    "--output-format", "stream-json",
    "--verbose",
    "--add-dir", dir,
    ...(candidateDir === dir ? [] : ["--add-dir", candidateDir]),
    "--allowedTools", `Read,Glob,Grep,Edit(${planPath}),Write(${planPath})`,
    "--permission-mode", "acceptEdits",
  ];
}

export function buildAiEditInvocation(
  provider: BrainProvider,
  prompt: string,
  dir: string,
  planPath?: string,
): AiEditInvocation {
  if (provider === "codex") {
    return {
      provider,
      label: "Codex",
      options: {
        prompt,
        sandbox: "workspace-write",
        timeoutMs: AI_EDIT_TIMEOUT_MS,
        cwd: planPath ? path.dirname(planPath) : dir,
      },
    };
  }
  const model = claudeSettings().model;
  return {
    provider,
    label: "Claude Code",
    model,
    args: claudeAiEditArgs(prompt, dir, planPath),
  };
}

function writeCaptionWordIndex(
  stagingDir: string,
  plan: EditPlan,
  input: CaptionStagingInput,
): string {
  const index = buildCaptionWordIndex({
    plan, manifestPath: input.manifestPath,
    transcriptsDir: input.transcriptsDir,
  });
  const requestAnchors = resolveCaptionRequestAnchors(input.request, index);
  const unresolved = requestAnchors.find((row) => row.status !== "resolved");
  if (unresolved) {
    if (unresolved.status === "timestamp-mismatch") {
      throw new Error(
        `caption phrase ${JSON.stringify(unresolved.phrase)} has no occurrence `
        + `within ${CAPTION_TIMESTAMP_TOLERANCE_S} seconds of the requested timestamp`,
      );
    }
    throw new Error(
      `caption phrase ${JSON.stringify(unresolved.phrase)} is `
      + `${unresolved.status}; add an output timestamp or select one occurrence`,
    );
  }
  const core: Record<string, unknown> = {
    ...index, operatorRequest: input.request, requestAnchors,
  };
  delete core.authorityHash;
  const document = {
    ...core, authorityHash: canonicalJsonSha256(core),
  };
  const destination = path.join(stagingDir, "caption-word-index.json");
  atomicWriteFileSync(destination, `${JSON.stringify(document, null, 1)}\n`);
  return destination;
}

function stageCandidate(
  stagingDir: string,
  plan: EditPlan,
  captionInput?: CaptionStagingInput,
): { candidatePath: string; captionWordIndexPath?: string } {
  try {
    const candidatePath = path.join(
      stagingDir, `edit_plan-${randomUUID()}.json`);
    atomicWriteFileSync(candidatePath, `${JSON.stringify(plan, null, 1)}\n`);
    const captionWordIndexPath = captionInput
      ? writeCaptionWordIndex(stagingDir, plan, captionInput) : undefined;
    return {
      candidatePath,
      ...(captionWordIndexPath ? { captionWordIndexPath } : {}),
    };
  } catch (error) {
    rmSync(stagingDir, { recursive: true, force: true });
    throw error;
  }
}

export function preparePlanForAi(
  planPath: string,
  plan: EditPlan,
  captionInput?: CaptionStagingInput,
): StagedAiPlan {
  const snapshots = snapshotPlan(planPath);
  const originalPlanText = readFileSync(planPath, "utf8");
  const capturedPlan = JSON.parse(originalPlanText) as EditPlan;
  if (canonicalJsonSha256(capturedPlan) !== canonicalJsonSha256(plan)) {
    throw new Error("edit_plan.json changed before its Ask Editor candidate could be staged");
  }
  const reconciled = reconcileGraphicIds(capturedPlan);
  const captions = reconcileCaptionPlanAuthority(reconciled.plan);
  const chaptersChanged = canonicalJsonSha256(
    capturedPlan.captionChapters ?? null,
  ) !== canonicalJsonSha256(captions.plan.captionChapters ?? null);
  if (captions.stampedGroups || captions.stampedCorrections
      || captions.stampedCorrectionHash || chaptersChanged) {
    throw new Error(
      "existing caption authority has unstamped ids, a stale correction "
      + "hash, or non-canonical chapters; repair it before Ask Editor",
    );
  }
  const parentPlanHash = createHash("sha256").update(originalPlanText).digest("hex");
  const stagingDir = mkdtempSync(path.join(os.tmpdir(), "sniper-ai-edit-"));
  const staged = stageCandidate(stagingDir, captions.plan, captionInput);
  if (reconciled.minted || reconciled.reminted) {
    dlog("producer:ai-edit", "stamped graphic ids", {
      minted: reconciled.minted,
      reminted: reconciled.reminted,
    });
  }
  return {
    snapshots,
    candidatePath: staged.candidatePath,
    stagingDir,
    originalPlanText,
    parentPlanHash,
    ...(staged.captionWordIndexPath
      ? { captionWordIndexPath: staged.captionWordIndexPath } : {}),
  };
}
