import type { SceneSpecV1 } from "./scene-spec";
import type { SceneScalarV1 } from "./scene-spec-types";

interface SceneMutationBaseV1 {
  schemaVersion: 1;
  sceneId: string;
  expectedSceneVersion: number;
}

export interface SceneAddV1 {
  schemaVersion: 1;
  operation: "scene.add";
  scene: SceneSpecV1;
}

export interface SceneSetVariableV1 extends SceneMutationBaseV1 {
  operation: "scene.setVariable";
  elementId: string;
  variable: string;
  value: SceneScalarV1;
  expectedValue: SceneScalarV1;
}

export interface SceneMoveV1 extends SceneMutationBaseV1 {
  operation: "scene.move";
  startFrame: number;
  endFrameExclusive: number;
  timelineMapHash: string;
}

export interface SceneRemoveV1 extends SceneMutationBaseV1 {
  operation: "scene.remove";
}

export interface TitleSetTextV1 extends SceneMutationBaseV1 {
  operation: "title.setText";
  elementId: string;
  variable: string;
  text: string;
  expectedText: string;
}

export interface TransitionValueV1 {
  id: string;
  outFrame: number;
  kind: "white-flash" | "light-leak" | "zoom-pull";
  sfx: boolean | string;
}

export interface TransitionSetV1 {
  schemaVersion: 1;
  operation: "transition.set";
  transitionId: string;
  expectedValue: TransitionValueV1 | null;
  value: TransitionValueV1;
}

export interface SfxSetV1 {
  schemaVersion: 1;
  operation: "sfx.set";
  transitionId: string;
  expectedSfx: boolean | string;
  sfx: boolean | string;
}

export interface GradeSetV1 {
  schemaVersion: 1;
  operation: "grade.set";
  expectedGrade: "warm" | "none";
  grade: "warm" | "none";
}

export type TreatmentOperationV1 =
  | SceneAddV1
  | SceneSetVariableV1
  | SceneMoveV1
  | SceneRemoveV1
  | TitleSetTextV1
  | TransitionSetV1
  | SfxSetV1
  | GradeSetV1;
