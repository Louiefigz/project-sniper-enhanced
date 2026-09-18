import { mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import type { CutRepairPreparationPackageV1 } from
  "@/lib/producer/contracts/cut-repair-preparation";
import type { CutRepairSelectedApprovalV1 } from
  "@/lib/producer/contracts/cut-repair-promotion-transition";
import type { ProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import { objectValue } from "@/lib/producer/contracts/validation";
import { atomicWriteJsonSync } from "@/lib/server/atomic-file";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { buildCutRepairPromotionCandidateV2Sync } from
  "@/lib/server/cut-repair-promotion-candidate-v2";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
} from "@/lib/server/producer-authority-files";
import { SCRIPTS_DIR } from "../../_lib/spawn-python";
import { runCutRepairPython } from "./cut-repair-route-runner";

const PROOF_BUILDER = path.join(
  SCRIPTS_DIR, "producer", "edit", "cut_repair_promotion_proof.py");

export interface PromotionProofBuildInput {
  producerDir: string;
  preparation: CutRepairPreparationPackageV1;
  reviewRevision: ProjectRevision;
  reviewRevisionHash: string;
  reviewReceiptHash: string;
  promotionEvidence: Record<string, unknown>;
  selectedApproval: CutRepairSelectedApprovalV1;
}

function planInputs(
  producerDir: string,
  preparation: CutRepairPreparationPackageV1,
): {
  cutTrack: unknown[];
  fps: unknown;
  captionDialogueAuthority: unknown;
} {
  const paths = producerAuthorityPaths(producerDir);
  const plan = objectValue(assertObjectHashSync(
    paths.objects.plans,
    preparation.proposedReviewAction.reviewPlanObjectHash,
  ), "cut repair review plan");
  const hasCaptionTrack = plan.captionsTrack !== undefined
    && plan.captionsTrack !== null;
  const captionDialogueAuthority = plan.dialogueCaptionAuthority ?? null;
  if (hasCaptionTrack && captionDialogueAuthority === null) {
    throw new Error(
      "CAPTION_DIALOGUE_REVALIDATION_REQUIRED: promotion stays private");
  }
  if (!hasCaptionTrack && captionDialogueAuthority !== null) {
    throw new Error("caption dialogue authority exists without CaptionTrackV1");
  }
  const cutTrack = plan.cutTrack;
  const target = objectValue(plan.target, "cut repair review target");
  if (!Array.isArray(cutTrack) || !cutTrack.length) {
    throw new Error("cut repair review plan has no child cut track");
  }
  return { cutTrack, fps: target.fps, captionDialogueAuthority };
}

function proofInput(value: PromotionProofBuildInput): Record<string, unknown> {
  const paths = producerAuthorityPaths(value.producerDir);
  const context = objectValue(assertObjectHashSync(
    paths.objects.cutRepairs,
    value.preparation.contextObjectHash,
  ), "stored cut repair context");
  if (!Array.isArray(context.segments) || !context.segments.length) {
    throw new Error("stored cut repair context has no exact segment map");
  }
  const plan = planInputs(value.producerDir, value.preparation);
  return {
    schemaVersion: 1,
    kind: "cut-repair-promotion-proof-input",
    operation: value.preparation.proposedReviewAction.operation,
    operationHash: value.preparation.proposedReviewAction.operationHash,
    fragmentReceipt: value.preparation.fragmentReceipt,
    compositeReceipt: value.preparation.compositeReceipt,
    reviewRevision: value.reviewRevision,
    reviewRevisionHash: value.reviewRevisionHash,
    reviewReceiptHash: value.reviewReceiptHash,
    promotionEvidenceHash: canonicalJsonSha256(value.promotionEvidence),
    selectedApproval: value.selectedApproval,
    workflowPolicy: value.preparation.proposedReviewAction.workflowPolicy,
    contextSegments: context.segments,
    childCutTrack: plan.cutTrack,
    projectFps: plan.fps,
    palmierSelected: false,
    captionDialogueAuthority: plan.captionDialogueAuthority,
  };
}

function parseCandidate(stdout: string): Record<string, unknown> {
  let value: unknown;
  try {
    value = JSON.parse(stdout.trim());
  } catch {
    throw new Error("cut repair promotion proof builder returned no JSON");
  }
  const row = objectValue(value, "cut repair diagnostic candidate");
  if (row.schemaVersion !== 1
      || row.kind !== "cut-repair-candidate"
      || row.status !== "candidate-proved") {
    throw new Error(
      typeof row.error === "string"
        ? row.error : "cut repair promotion proof builder failed");
  }
  return row;
}

/** Mint Python lineage proof, then replace its terminal with the exact MP4. */
export async function buildCutRepairPromotionProofV2(
  value: PromotionProofBuildInput,
): Promise<Record<string, unknown>> {
  const temporary = mkdtempSync(path.join(
    os.tmpdir(), "sniper-cut-repair-promotion-proof-"));
  const inputPath = path.join(temporary, "input.json");
  try {
    atomicWriteJsonSync(inputPath, proofInput(value));
    const result = await runCutRepairPython(
      PROOF_BUILDER, [inputPath],
      "cut repair promotion proof", 30_000);
    if (result.code !== 0) {
      throw new Error(result.stderr.trim() || result.stdout.trim()
        || "cut repair promotion proof builder failed");
    }
    return buildCutRepairPromotionCandidateV2Sync({
      producerDir: value.producerDir,
      preparation: value.preparation,
      reviewRevision: value.reviewRevision,
      diagnosticCandidate: parseCandidate(result.stdout),
    });
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
}
