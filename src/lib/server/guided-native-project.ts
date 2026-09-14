/** Adapt a reconstructed native proposal through the shared geometry and project paths. */
import { canonicalJson } from "./auto-edit-hash";
import { assembleNativeShortHtml } from "./native-short-project";
import { assertGuidedNativeGeometry, type GuidedNativeVisualPlan, type NativeProjectMedia } from "./guided-native-geometry";
import { assertGuidedNativeBinding } from "./guided-native-binding";
import type { NativeCaptionGroups } from "./guided-native-captions";
export type { GuidedNativeVisualPlan, NativeProjectMedia } from "./guided-native-geometry";

/** Assembly returns the persistent guided binding that the shared writer must retain. */
export function buildNativeShortProjectFiles(candidate: Record<string, unknown>, assets: NativeProjectMedia[],
  groups: NativeCaptionGroups, visual?: GuidedNativeVisualPlan): Record<string, string> {
  const direction = assertGuidedNativeGeometry(candidate, assets, groups, visual);
  if (direction.proposalVersion === 10) {
    if (!visual!.project.guidedBinding) throw new Error("V10 native files require resolved persistent guided binding");
    assertGuidedNativeBinding(visual!.project);
  }
  return { "index.html": assembleNativeShortHtml(visual!.project),
    "GUIDED-PROPOSAL.json": canonicalJson(visual!.project.guidedBinding ?? { candidateHash: visual!.candidateHash, direction }) };
}
