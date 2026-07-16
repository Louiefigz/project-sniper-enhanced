import { mkdtempSync, readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import {
  claudeModelArgs,
  claudeSettings,
  type BrainProvider,
} from "../../_lib/ai-provider";
import { snapshotPlan } from "../../_lib/plan-snapshots";
import { reconcileGraphicIds, type EditPlan } from "@/lib/producer/edit-plan";
import { atomicWriteFileSync } from "@/lib/server/atomic-file";
import { dlog } from "@/lib/debug";

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

export function preparePlanForAi(planPath: string, plan: EditPlan): StagedAiPlan {
  const snapshots = snapshotPlan(planPath);
  const reconciled = reconcileGraphicIds(plan);
  const stagingDir = mkdtempSync(path.join(os.tmpdir(), "sniper-ai-edit-"));
  const candidatePath = path.join(stagingDir, `edit_plan-${randomUUID()}.json`);
  const originalPlanText = readFileSync(planPath, "utf8");
  atomicWriteFileSync(candidatePath, `${JSON.stringify(reconciled.plan, null, 1)}\n`);
  if (reconciled.minted || reconciled.reminted) {
    dlog("producer:ai-edit", "stamped graphic ids", {
      minted: reconciled.minted,
      reminted: reconciled.reminted,
    });
  }
  return { snapshots, candidatePath, stagingDir, originalPlanText };
}
