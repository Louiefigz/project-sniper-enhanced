import type { PalmierNativePromptInput } from "./palmier-native-prompt";

export interface PalmierNativeCapabilityFailure {
  code:
    | "PALMIER_NATIVE_CUT_AUTHORITY_UNAVAILABLE"
    | "PALMIER_NATIVE_RICH_GRAPHIC_UNSUPPORTED"
    | "PALMIER_NATIVE_TRANSITION_UNSUPPORTED";
  message: string;
}

const RICH_GRAPHIC = /\b(graphic|card|lower[- ]?third|overlay|icon|badge|hyperframe|whiteboard|statement|quote(?:[- ]?card)?|full[- ]?screen|template|slide|takeover|callout)\b/i;
const TRANSITION = /\b(transition|cross[- ]?fade|xfade|wipe|light[- ]?leak|flash|stinger|seam[- ]?effect)\b/i;

/**
 * Palmier's native delta vocabulary is deliberately smaller than edit_plan.
 * Reject requests whose requested result cannot be represented and governed by
 * that vocabulary; a plain text clip must never masquerade as a studied card.
 */
export function palmierNativeCapabilityFailure(
  input: PalmierNativePromptInput,
): PalmierNativeCapabilityFailure | null {
  if (input.scope.lanes.includes("cuts")) {
    return {
      code: "PALMIER_NATIVE_CUT_AUTHORITY_UNAVAILABLE",
      message: "Palmier-native cut changes are paused because the current timeline authority does not yet bind Palmier clips to the source transcript/cut approval receipt. Nothing was changed. Use the governed plan workflow until that mapping is available.",
    };
  }
  if (input.scope.lanes.includes("graphics") && RICH_GRAPHIC.test(input.request)) {
    return {
      code: "PALMIER_NATIVE_RICH_GRAPHIC_UNSUPPORTED",
      message: "This request needs a studied graphic composition, but Palmier-native candidates currently support only editable text and layout changes to existing elements. A plain text clip will not be substituted for a card/template. Nothing was changed.",
    };
  }
  if (input.scope.lanes.includes("motion") && TRANSITION.test(input.request)) {
    return {
      code: "PALMIER_NATIVE_TRANSITION_UNSUPPORTED",
      message: "This request needs a real transition primitive, but Palmier-native candidates currently expose only bounded clip keyframes/properties. A zoom or opacity keyframe will not be mislabeled as a transition. Nothing was changed.",
    };
  }
  return null;
}
