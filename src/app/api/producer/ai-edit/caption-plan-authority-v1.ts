import type { EditPlan } from "@/lib/producer/edit-plan";
import {
  reconcileCaptionAuthority,
  type CaptionReconcileResult,
} from "./caption-operations-v1";
import { reconcileCaptionChapters } from "./caption-chapters-v1";

export function reconcileCaptionPlanAuthority(
  plan: EditPlan,
): CaptionReconcileResult {
  const captions = reconcileCaptionAuthority(plan);
  return {
    ...captions,
    plan: reconcileCaptionChapters(captions.plan),
  };
}
