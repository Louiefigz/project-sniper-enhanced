import type { EditPlan } from "@/lib/producer/edit-plan";
import type { SetGraphicTextV1 } from "@/lib/producer/set-graphic-text-v1";
import { assertPlanVisualSources } from "@/lib/producer/visual-source-policy";

export interface TypedCompatibilityEdit {
  adapterVersion: 1;
  kind: "set-graphic-text";
  operation: SetGraphicTextV1;
  operationHash: string;
}


/** Historical receipt type remains readable; retired designs cannot acquire an edit path. */
export function compileTypedCompatibilityEdit(
  parent: EditPlan,
  candidate: EditPlan,
): TypedCompatibilityEdit | null {
  assertPlanVisualSources(parent as Record<string, unknown>);
  assertPlanVisualSources(candidate as Record<string, unknown>);
  return null;
}
