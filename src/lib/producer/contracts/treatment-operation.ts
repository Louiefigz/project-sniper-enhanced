import {
  enumValue,
  exactKeys,
  objectValue,
} from "./validation";
import { parseSceneSpecV1 } from "./scene-spec";
import {
  sceneDigest,
  sceneInteger,
  sceneScalar,
  sceneStableId,
  sceneVariableId,
} from "./scene-validation";
import type {
  GradeSetV1,
  SceneAddV1,
  SceneMoveV1,
  SceneRemoveV1,
  SceneSetVariableV1,
  SfxSetV1,
  TitleSetTextV1,
  TransitionSetV1,
  TransitionValueV1,
  TreatmentOperationV1,
} from "./treatment-operation-types";

export const TREATMENT_OPERATION_NAMES = [
  "scene.add",
  "scene.setVariable",
  "scene.move",
  "scene.remove",
  "title.setText",
  "transition.set",
  "sfx.set",
  "grade.set",
] as const;

export type TreatmentOperationNameV1 =
  typeof TREATMENT_OPERATION_NAMES[number];

function assertVersion(row: Record<string, unknown>): void {
  if (row.schemaVersion !== 1) {
    throw new Error("TreatmentOperationV1.schemaVersion must be 1");
  }
}

function expectedSceneVersion(value: unknown): number {
  return sceneInteger(value, "expectedSceneVersion", 1);
}

function boundedText(
  value: unknown,
  label: string,
  nonblank: boolean,
): string {
  if (typeof value !== "string"
      || nonblank && !/\S/u.test(value)
      || Array.from(value).length > 1_000) {
    throw new Error(`${label} must be ${nonblank ? "nonblank and " : ""}<=1000 chars`);
  }
  return value;
}

function sfxValue(value: unknown, label: string): boolean | string {
  if (typeof value === "boolean") return value;
  if (typeof value !== "string"
      || !value.trim()
      || Array.from(value).length > 96) {
    throw new Error(`${label} must be boolean or a nonblank pack name`);
  }
  return value;
}

function transitionValue(
  value: unknown,
  label: string,
  nullable: boolean,
): TransitionValueV1 | null {
  if (value === null && nullable) return null;
  const transition = objectValue(value, label);
  const keys = ["id", "outFrame", "kind", "sfx"];
  exactKeys(transition, keys, keys, label);
  return {
    id: sceneStableId(transition.id, `${label}.id`),
    outFrame: sceneInteger(transition.outFrame, `${label}.outFrame`, 0),
    kind: enumValue(
      transition.kind,
      ["white-flash", "light-leak", "zoom-pull"] as const,
      `${label}.kind`,
    ),
    sfx: sfxValue(transition.sfx, `${label}.sfx`),
  };
}

function parseSceneAdd(row: Record<string, unknown>): SceneAddV1 {
  const keys = ["schemaVersion", "operation", "scene"];
  exactKeys(row, keys, keys, "scene.add");
  return {
    schemaVersion: 1,
    operation: "scene.add",
    scene: parseSceneSpecV1(row.scene),
  };
}

function parseSceneSetVariable(
  row: Record<string, unknown>,
): SceneSetVariableV1 {
  const keys = [
    "schemaVersion", "operation", "sceneId", "elementId", "variable",
    "value", "expectedValue", "expectedSceneVersion",
  ];
  exactKeys(row, keys, keys, "scene.setVariable");
  return {
    schemaVersion: 1,
    operation: "scene.setVariable",
    sceneId: sceneStableId(row.sceneId, "sceneId"),
    elementId: sceneStableId(row.elementId, "elementId"),
    variable: sceneVariableId(row.variable, "variable"),
    value: sceneScalar(row.value, "value"),
    expectedValue: sceneScalar(row.expectedValue, "expectedValue"),
    expectedSceneVersion: expectedSceneVersion(row.expectedSceneVersion),
  };
}

function parseSceneMove(row: Record<string, unknown>): SceneMoveV1 {
  const keys = [
    "schemaVersion", "operation", "sceneId", "startFrame",
    "endFrameExclusive", "timelineMapHash", "expectedSceneVersion",
  ];
  exactKeys(row, keys, keys, "scene.move");
  const startFrame = sceneInteger(row.startFrame, "startFrame", 0);
  const endFrameExclusive = sceneInteger(
    row.endFrameExclusive,
    "endFrameExclusive",
    1,
  );
  if (endFrameExclusive <= startFrame) {
    throw new Error("scene.move range must be nonempty");
  }
  return {
    schemaVersion: 1,
    operation: "scene.move",
    sceneId: sceneStableId(row.sceneId, "sceneId"),
    startFrame,
    endFrameExclusive,
    timelineMapHash: sceneDigest(row.timelineMapHash, "timelineMapHash"),
    expectedSceneVersion: expectedSceneVersion(row.expectedSceneVersion),
  };
}

function parseSceneRemove(row: Record<string, unknown>): SceneRemoveV1 {
  const keys = ["schemaVersion", "operation", "sceneId", "expectedSceneVersion"];
  exactKeys(row, keys, keys, "scene.remove");
  return {
    schemaVersion: 1,
    operation: "scene.remove",
    sceneId: sceneStableId(row.sceneId, "sceneId"),
    expectedSceneVersion: expectedSceneVersion(row.expectedSceneVersion),
  };
}

function parseTitleSetText(row: Record<string, unknown>): TitleSetTextV1 {
  const keys = [
    "schemaVersion", "operation", "sceneId", "elementId", "variable",
    "text", "expectedText", "expectedSceneVersion",
  ];
  exactKeys(row, keys, keys, "title.setText");
  return {
    schemaVersion: 1,
    operation: "title.setText",
    sceneId: sceneStableId(row.sceneId, "sceneId"),
    elementId: sceneStableId(row.elementId, "elementId"),
    variable: sceneVariableId(row.variable, "variable"),
    text: boundedText(row.text, "text", true),
    expectedText: boundedText(row.expectedText, "expectedText", false),
    expectedSceneVersion: expectedSceneVersion(row.expectedSceneVersion),
  };
}

function parseTransitionSet(row: Record<string, unknown>): TransitionSetV1 {
  const keys = [
    "schemaVersion", "operation", "transitionId", "expectedValue", "value",
  ];
  exactKeys(row, keys, keys, "transition.set");
  const transitionId = sceneStableId(row.transitionId, "transitionId");
  const expectedValue = transitionValue(row.expectedValue, "expectedValue", true);
  const value = transitionValue(row.value, "value", false)!;
  if (value.id !== transitionId
      || expectedValue !== null && expectedValue.id !== transitionId) {
    throw new Error("transition target/value IDs differ");
  }
  return {
    schemaVersion: 1,
    operation: "transition.set",
    transitionId,
    expectedValue,
    value,
  };
}

function parseSfxSet(row: Record<string, unknown>): SfxSetV1 {
  const keys = [
    "schemaVersion", "operation", "transitionId", "expectedSfx", "sfx",
  ];
  exactKeys(row, keys, keys, "sfx.set");
  return {
    schemaVersion: 1,
    operation: "sfx.set",
    transitionId: sceneStableId(row.transitionId, "transitionId"),
    expectedSfx: sfxValue(row.expectedSfx, "expectedSfx"),
    sfx: sfxValue(row.sfx, "sfx"),
  };
}

function parseGradeSet(row: Record<string, unknown>): GradeSetV1 {
  const keys = ["schemaVersion", "operation", "expectedGrade", "grade"];
  exactKeys(row, keys, keys, "grade.set");
  return {
    schemaVersion: 1,
    operation: "grade.set",
    expectedGrade: enumValue(
      row.expectedGrade,
      ["warm", "none"] as const,
      "expectedGrade",
    ),
    grade: enumValue(row.grade, ["warm", "none"] as const, "grade"),
  };
}

const PARSERS: Record<
  TreatmentOperationNameV1,
  (row: Record<string, unknown>) => TreatmentOperationV1
> = {
  "scene.add": parseSceneAdd,
  "scene.setVariable": parseSceneSetVariable,
  "scene.move": parseSceneMove,
  "scene.remove": parseSceneRemove,
  "title.setText": parseTitleSetText,
  "transition.set": parseTransitionSet,
  "sfx.set": parseSfxSet,
  "grade.set": parseGradeSet,
};

/** Parse one closed P4 scene/title/transition/SFX/grade action. */
export function parseTreatmentOperationV1(value: unknown): TreatmentOperationV1 {
  const row = objectValue(value, "TreatmentOperationV1");
  assertVersion(row);
  const operation = enumValue(
    row.operation,
    TREATMENT_OPERATION_NAMES,
    "TreatmentOperationV1.operation",
  );
  return PARSERS[operation](row);
}

export type {
  GradeSetV1,
  SceneAddV1,
  SceneMoveV1,
  SceneRemoveV1,
  SceneSetVariableV1,
  SfxSetV1,
  TitleSetTextV1,
  TransitionSetV1,
  TransitionValueV1,
  TreatmentOperationV1,
} from "./treatment-operation-types";
