import path from "node:path";
import type { ApprovalRecord } from "./auto-edit-approval";
import {
  recoverApprovedCandidatePromotionSync,
  type CandidatePromotionHooks,
} from "./auto-edit-quality-artifacts";
import { recoverProducerQcPromotionIntentSync } from
  "./producer-qc-promotion-intent";
import {
  classifyQcPromotionCrashSync,
  settleExactQcPromotionChildSync,
  settleOldQcPromotionSync,
} from "./producer-qc-promotion-recovery";
import type { CandidateCommand } from
  "./current-render-graph-candidate-command";

export interface RenderGraphPromotionCrashInput {
  candidate: string;
  producerDir: string;
  expectedSha256: string;
  command: CandidateCommand;
  productionQc: boolean;
}

function activePointer(input: RenderGraphPromotionCrashInput): string {
  return path.join(input.producerDir, ".render-graph-v1", "ACTIVE.json");
}

function candidateIsActive(input: RenderGraphPromotionCrashInput): boolean {
  try {
    return input.command([
      "candidate-active",
      "--producer-dir", input.producerDir,
      "--candidate", input.candidate,
      "--final", `${input.producerDir}/final.mp4`,
      "--expected-sha256", input.expectedSha256,
    ]).ok === true;
  } catch {
    return false;
  }
}

function confirmExactCandidate(input: RenderGraphPromotionCrashInput): void {
  if (!candidateIsActive(input)) {
    throw new Error("committed render graph candidate is not exact");
  }
  if (input.productionQc) {
    settleExactQcPromotionChildSync(input.producerDir);
  }
}

function candidateArgs(
  input: RenderGraphPromotionCrashInput,
): string[] {
  return [
    "rollback",
    "--producer-dir", input.producerDir,
    "--candidate", input.candidate,
    "--final", `${input.producerDir}/final.mp4`,
    "--expected-sha256", input.expectedSha256,
  ];
}

function rollback(input: RenderGraphPromotionCrashInput): void {
  input.command(candidateArgs(input));
  if (input.productionQc) {
    settleOldQcPromotionSync(input.producerDir);
  } else {
    recoverProducerQcPromotionIntentSync(input.producerDir);
  }
}

export function renderGraphPromotionCrashHooks(
  input: RenderGraphPromotionCrashInput,
): CandidatePromotionHooks {
  return {
    authorityMutablePaths: [activePointer(input)],
    rollbackAuthority: () => rollback(input),
    acceptCommitReady: input.productionQc
      ? () => classifyQcPromotionCrashSync(input.producerDir) === "exact-child"
        && candidateIsActive(input)
      : undefined,
    confirmCommitted: () => confirmExactCandidate(input),
    allowMutableRollback: (destination) =>
      destination === activePointer(input) && candidateIsActive(input),
  };
}

/** Recover before any candidate/graph preflight that assumes private media. */
export function recoverRenderGraphPromotionSync(
  input: RenderGraphPromotionCrashInput,
  record: ApprovalRecord,
): "none" | "recovered-old" | "recovered-new" {
  return recoverApprovedCandidatePromotionSync(
    input.candidate,
    input.producerDir,
    record,
    renderGraphPromotionCrashHooks(input),
  );
}
