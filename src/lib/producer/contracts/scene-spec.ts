import {
  enumValue,
  exactKeys,
  objectValue,
} from "./validation";
import { parsePositiveRationalV1 } from "./positive-rational";
import {
  sceneCanvas,
  sceneDigest,
  sceneHtmlPath,
  sceneInteger,
  sceneStableId,
  sceneVariableId,
  sceneVariables,
  stringArray,
  uniqueBy,
} from "./scene-validation";
import type {
  SceneCompositionV1,
  SceneDependencyV1,
  SceneElementV1,
  SceneProvenanceV1,
  SceneRenderUnitV1,
  SceneSpecV1,
  SceneTimingV1,
} from "./scene-spec-types";

const ROOT_KEYS = [
  "schemaVersion", "sceneId", "version", "timing", "canvas", "renderMode",
  "composition", "elements", "renderUnits", "captionPolicy",
  "dependencies", "provenance",
] as const;
const ELEMENT_KEYS = [
  "elementId", "role", "exposedProperties", "values",
] as const;
const UNIT_KEYS = [
  "unitId", "elementIds", "zIndex", "entry", "sharedGroupId",
  "maskDependencyUnitIds", "compositeMode", "palmierGranularity",
] as const;
const UNIT_REQUIRED_KEYS = [
  "unitId", "elementIds", "zIndex", "entry",
  "compositeMode", "palmierGranularity",
] as const;

function parseTiming(value: unknown): SceneTimingV1 {
  const timing = objectValue(value, "SceneSpecV1.timing");
  const keys = ["startFrame", "endFrameExclusive", "fps", "timelineMapHash"];
  exactKeys(timing, keys, keys, "SceneSpecV1.timing");
  const startFrame = sceneInteger(timing.startFrame, "timing.startFrame", 0);
  const endFrameExclusive = sceneInteger(
    timing.endFrameExclusive,
    "timing.endFrameExclusive",
    1,
  );
  if (endFrameExclusive <= startFrame) {
    throw new Error("SceneSpecV1.timing must be a non-empty half-open range");
  }
  return {
    startFrame,
    endFrameExclusive,
    fps: parsePositiveRationalV1(timing.fps),
    timelineMapHash: sceneDigest(timing.timelineMapHash, "timing.timelineMapHash"),
  };
}

function parseComposition(value: unknown): SceneCompositionV1 {
  const composition = objectValue(value, "SceneSpecV1.composition");
  const variables = sceneVariables(
    composition.variables,
    "SceneSpecV1.composition.variables",
  );
  if (composition.type === "catalog") {
    const keys = ["type", "kind", "variables"];
    exactKeys(composition, keys, keys, "SceneSpecV1.composition");
    return {
      type: "catalog",
      kind: sceneStableId(composition.kind, "composition.kind"),
      variables,
    };
  }
  if (composition.type !== "project") {
    throw new Error("SceneSpecV1.composition.type is unsupported");
  }
  const keys = ["type", "bundleId", "bundleHash", "entry", "variables"];
  exactKeys(composition, keys, keys, "SceneSpecV1.composition");
  return {
    type: "project",
    bundleId: sceneStableId(composition.bundleId, "composition.bundleId"),
    bundleHash: sceneDigest(composition.bundleHash, "composition.bundleHash"),
    entry: sceneHtmlPath(composition.entry, "composition.entry"),
    variables,
  };
}

function parseElement(value: unknown, index: number): SceneElementV1 {
  const label = `SceneSpecV1.elements[${index}]`;
  const element = objectValue(value, label);
  exactKeys(element, ELEMENT_KEYS, ELEMENT_KEYS, label);
  const exposedProperties = stringArray(
    element.exposedProperties,
    `${label}.exposedProperties`,
    sceneVariableId,
  );
  const values = sceneVariables(element.values, `${label}.values`);
  const valueIds = Object.keys(values).sort();
  if (valueIds.join("\0") !== [...exposedProperties].sort().join("\0")) {
    throw new Error(`${label}.values must match exposedProperties`);
  }
  return {
    elementId: sceneStableId(element.elementId, `${label}.elementId`),
    role: sceneStableId(element.role, `${label}.role`),
    exposedProperties,
    values,
  };
}

function parseUnit(value: unknown, index: number): SceneRenderUnitV1 {
  const label = `SceneSpecV1.renderUnits[${index}]`;
  const unit = objectValue(value, label);
  exactKeys(unit, UNIT_KEYS, UNIT_REQUIRED_KEYS, label);
  const maskDependencyUnitIds = unit.maskDependencyUnitIds === undefined
    ? undefined
    : stringArray(
      unit.maskDependencyUnitIds,
      `${label}.maskDependencyUnitIds`,
      sceneStableId,
    );
  return {
    unitId: sceneStableId(unit.unitId, `${label}.unitId`),
    elementIds: stringArray(
      unit.elementIds,
      `${label}.elementIds`,
      sceneStableId,
      true,
    ),
    zIndex: sceneInteger(unit.zIndex, `${label}.zIndex`, -10_000, 10_000),
    entry: sceneHtmlPath(unit.entry, `${label}.entry`),
    ...(unit.sharedGroupId === undefined ? {} : {
      sharedGroupId: sceneStableId(
        unit.sharedGroupId,
        `${label}.sharedGroupId`,
      ),
    }),
    ...(maskDependencyUnitIds === undefined ? {} : { maskDependencyUnitIds }),
    compositeMode: enumValue(
      unit.compositeMode,
      ["normal", "screen", "multiply", "declared"] as const,
      `${label}.compositeMode`,
    ),
    palmierGranularity: enumValue(
      unit.palmierGranularity,
      ["scene", "unit"] as const,
      `${label}.palmierGranularity`,
    ),
  };
}

function assertUnitClosure(
  units: SceneRenderUnitV1[],
  elements: SceneElementV1[],
): void {
  uniqueBy(units, (unit) => unit.unitId, "render unit ids");
  uniqueBy(units, (unit) => String(unit.zIndex), "render unit zIndex values");
  const expected = elements.map((element) => element.elementId).sort();
  const owned = units.flatMap((unit) => unit.elementIds).sort();
  if (new Set(owned).size !== owned.length
      || expected.join("\0") !== owned.join("\0")) {
    throw new Error("render units must own every scene element exactly once");
  }
  const pending = new Map(units.map((unit) => [
    unit.unitId,
    new Set(unit.maskDependencyUnitIds ?? []),
  ]));
  for (const [unitId, dependencies] of pending) {
    if (dependencies.has(unitId)
        || [...dependencies].some((dependency) => !pending.has(dependency))) {
      throw new Error("render-unit mask dependency is invalid");
    }
  }
  while (pending.size > 0) {
    const ready = [...pending].filter(([, dependencies]) =>
      [...dependencies].every((dependency) => !pending.has(dependency)));
    if (ready.length === 0) {
      throw new Error("render-unit mask dependencies contain a cycle");
    }
    ready.forEach(([unitId]) => pending.delete(unitId));
  }
}

function parseDependency(value: unknown, index: number): SceneDependencyV1 {
  const label = `SceneSpecV1.dependencies[${index}]`;
  const dependency = objectValue(value, label);
  const keys = ["kind", "id", "sha256"];
  exactKeys(dependency, keys, keys, label);
  return {
    kind: sceneStableId(dependency.kind, `${label}.kind`),
    id: sceneStableId(dependency.id, `${label}.id`),
    sha256: sceneDigest(dependency.sha256, `${label}.sha256`),
  };
}

function parseProvenance(value: unknown): SceneProvenanceV1 {
  const provenance = objectValue(value, "SceneSpecV1.provenance");
  exactKeys(
    provenance,
    ["origin", "requestId", "stylePackHash"],
    ["origin"],
    "SceneSpecV1.provenance",
  );
  const origin = enumValue(
    provenance.origin,
    ["operator", "autopilot", "reference-style"] as const,
    "provenance.origin",
  );
  if (origin === "reference-style" && provenance.stylePackHash === undefined) {
    throw new Error("reference-style scenes require stylePackHash");
  }
  return {
    origin,
    ...(provenance.requestId === undefined ? {} : {
      requestId: sceneStableId(provenance.requestId, "provenance.requestId"),
    }),
    ...(provenance.stylePackHash === undefined ? {} : {
      stylePackHash: sceneDigest(
        provenance.stylePackHash,
        "provenance.stylePackHash",
      ),
    }),
  };
}

/** Parse all non-template-specific SceneSpecV1 invariants. */
export function parseSceneSpecV1(value: unknown): SceneSpecV1 {
  const scene = objectValue(value, "SceneSpecV1");
  exactKeys(scene, ROOT_KEYS, ROOT_KEYS, "SceneSpecV1");
  if (scene.schemaVersion !== 1
      || !Array.isArray(scene.elements) || scene.elements.length === 0
      || !Array.isArray(scene.renderUnits) || scene.renderUnits.length === 0
      || !Array.isArray(scene.dependencies)) {
    throw new Error("SceneSpecV1 version or collections are invalid");
  }
  const elements = scene.elements.map(parseElement);
  uniqueBy(elements, (element) => element.elementId, "scene element ids");
  const renderUnits = scene.renderUnits.map(parseUnit);
  assertUnitClosure(renderUnits, elements);
  const dependencies = scene.dependencies.map(parseDependency);
  uniqueBy(
    dependencies,
    (dependency) => `${dependency.kind}\0${dependency.id}`,
    "scene dependency identities",
  );
  return {
    schemaVersion: 1,
    sceneId: sceneStableId(scene.sceneId, "SceneSpecV1.sceneId"),
    version: sceneInteger(scene.version, "SceneSpecV1.version", 1),
    timing: parseTiming(scene.timing),
    canvas: sceneCanvas(scene.canvas, "SceneSpecV1.canvas"),
    renderMode: enumValue(
      scene.renderMode,
      ["overlay-alpha", "takeover-opaque", "presenter-hole"] as const,
      "SceneSpecV1.renderMode",
    ),
    composition: parseComposition(scene.composition),
    elements,
    renderUnits,
    captionPolicy: enumValue(
      scene.captionPolicy,
      ["preserve", "suppress-overlap"] as const,
      "SceneSpecV1.captionPolicy",
    ),
    dependencies,
    provenance: parseProvenance(scene.provenance),
  };
}

export type {
  SceneSpecV1,
  SceneBundleManifestV1,
  SceneScalarV1,
} from "./scene-spec-types";
