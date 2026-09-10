import {
  enumValue,
  exactKeys,
  objectValue,
} from "./validation";
import { parsePositiveRationalV1 } from "./positive-rational";
import { parseSceneSpecV1 } from "./scene-spec";
import { SCENE_READABLE_HYPERFRAMES_VERSIONS } from "./scene-spec-types";
import {
  sceneCanvas,
  sceneDigest,
  sceneHtmlPath,
  sceneInteger,
  sceneScalar,
  sceneStableId,
  sceneVariableId,
  stringArray,
  uniqueBy,
} from "./scene-validation";
import type {
  SceneBundleManifestV1,
  SceneBundleVariableV1,
  SceneScalarV1,
  SceneSpecV1,
} from "./scene-spec-types";

const ROOT_KEYS = [
  "schemaVersion", "bundleId", "fullEntry", "unitEntries",
  "supportedCanvases", "supportedFps", "variables", "assetIds", "seed",
  "runtime",
] as const;
const VARIABLE_KEYS = [
  "id", "type", "required", "elementIds", "default", "values", "maxLength",
] as const;
const VARIABLE_REQUIRED = ["id", "type", "required", "elementIds"] as const;

function sameRecord(left: object, right: object): boolean {
  const ordered = (value: object) =>
    JSON.stringify(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)));
  return ordered(left) === ordered(right);
}

function parseVariableValue(
  value: unknown,
  definition: Pick<SceneBundleVariableV1, "type" | "values" | "maxLength">,
  label: string,
): SceneScalarV1 {
  const parsed = sceneScalar(value, label);
  const valid = definition.type === "boolean"
    ? typeof parsed === "boolean"
    : definition.type === "number"
      ? typeof parsed === "number"
      : typeof parsed === "string";
  if (!valid) throw new Error(`${label} does not match ${definition.type}`);
  if (definition.type === "color"
      && !/^#[0-9A-Fa-f]{6}$/u.test(parsed as string)) {
    throw new Error(`${label} must be #RRGGBB`);
  }
  if (definition.type === "enum" && !definition.values?.includes(parsed)) {
    throw new Error(`${label} is outside the closed enum`);
  }
  if (definition.type === "string"
      && Array.from(parsed as string).length > (definition.maxLength ?? 4_000)) {
    throw new Error(`${label} exceeds its maximum length`);
  }
  return parsed;
}

function parseVariable(value: unknown, index: number): SceneBundleVariableV1 {
  const label = `SceneBundleManifestV1.variables[${index}]`;
  const variable = objectValue(value, label);
  exactKeys(variable, VARIABLE_KEYS, VARIABLE_REQUIRED, label);
  const type = enumValue(
    variable.type,
    ["string", "number", "boolean", "color", "enum"] as const,
    `${label}.type`,
  );
  if (typeof variable.required !== "boolean") {
    throw new Error(`${label}.required must be boolean`);
  }
  if (type !== "enum" && variable.values !== undefined) {
    throw new Error(`${label}.values is enum-only`);
  }
  const values = variable.values === undefined ? undefined
    : parseEnumValues(variable.values, `${label}.values`);
  if (type === "enum" && values === undefined) {
    throw new Error(`${label}.values must close the enum`);
  }
  const maxLength = variable.maxLength === undefined ? undefined
    : sceneInteger(variable.maxLength, `${label}.maxLength`, 1, 4_000);
  if (maxLength !== undefined && type !== "string") {
    throw new Error(`${label}.maxLength is string-only`);
  }
  const parsed: SceneBundleVariableV1 = {
    id: sceneVariableId(variable.id, `${label}.id`),
    type,
    required: variable.required,
    elementIds: stringArray(
      variable.elementIds,
      `${label}.elementIds`,
      sceneStableId,
      true,
    ),
    ...(values === undefined ? {} : { values }),
    ...(maxLength === undefined ? {} : { maxLength }),
  };
  return variable.default === undefined ? parsed : {
    ...parsed,
    default: parseVariableValue(variable.default, parsed, `${label}.default`),
  };
}

function parseEnumValues(value: unknown, label: string): SceneScalarV1[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error(`${label} must be a non-empty array`);
  }
  const values = value.map((item, index) => {
    const parsed = sceneScalar(item, `${label}[${index}]`);
    if (typeof parsed !== "string") {
      throw new Error(`${label}[${index}] must be a string`);
    }
    return parsed;
  });
  uniqueBy(values, (item) => `${typeof item}:${JSON.stringify(item)}`, label);
  return values;
}

function parseEntries(value: unknown): Record<string, string> {
  const entries = objectValue(value, "SceneBundleManifestV1.unitEntries");
  if (Object.keys(entries).length === 0) {
    throw new Error("SceneBundleManifestV1.unitEntries must be non-empty");
  }
  const parsed = Object.fromEntries(Object.entries(entries).map(([key, item]) => [
    sceneStableId(key, "bundle unit id"),
    sceneHtmlPath(item, `unitEntries.${key}`),
  ]));
  uniqueBy(Object.values(parsed), (entry) => entry, "bundle unit entries");
  return parsed;
}

function parseRuntime(value: unknown): SceneBundleManifestV1["runtime"] {
  const runtime = objectValue(value, "SceneBundleManifestV1.runtime");
  const keys = ["hyperframesVersion", "gsapSha256"];
  exactKeys(runtime, keys, keys, "SceneBundleManifestV1.runtime");
  return {
    hyperframesVersion: enumValue(
      runtime.hyperframesVersion, SCENE_READABLE_HYPERFRAMES_VERSIONS,
      "bundle runtime.hyperframesVersion",
    ),
    gsapSha256: sceneDigest(runtime.gsapSha256, "runtime.gsapSha256"),
  };
}

function assertReleasedRate(
  rate: ReturnType<typeof parsePositiveRationalV1>,
  label: string,
): void {
  const numerator = BigInt(rate.numerator);
  const denominator = BigInt(rate.denominator);
  if (numerator < denominator || numerator > BigInt(120) * denominator) {
    throw new Error(`${label} must be within 1..120 FPS`);
  }
}

/** Parse the immutable project-scoped SceneBundleManifestV1 contract. */
export function parseSceneBundleManifestV1(value: unknown): SceneBundleManifestV1 {
  const bundle = objectValue(value, "SceneBundleManifestV1");
  exactKeys(bundle, ROOT_KEYS, ROOT_KEYS, "SceneBundleManifestV1");
  if (bundle.schemaVersion !== 1
      || !Array.isArray(bundle.supportedCanvases)
      || bundle.supportedCanvases.length === 0
      || !Array.isArray(bundle.supportedFps)
      || bundle.supportedFps.length === 0
      || !Array.isArray(bundle.variables)) {
    throw new Error("SceneBundleManifestV1 version or collections are invalid");
  }
  const fullEntry = sceneHtmlPath(bundle.fullEntry, "bundle.fullEntry");
  const unitEntries = parseEntries(bundle.unitEntries);
  if (Object.values(unitEntries).includes(fullEntry)) {
    throw new Error("bundle full and unit entries must be distinct");
  }
  const supportedCanvases = bundle.supportedCanvases.map(
    (canvas, index) => sceneCanvas(canvas, `supportedCanvases[${index}]`),
  );
  uniqueBy(
    supportedCanvases,
    (canvas) => `${canvas.width}x${canvas.height}`,
    "supported canvases",
  );
  const supportedFps = bundle.supportedFps.map((rate, index) => {
    const parsed = parsePositiveRationalV1(rate);
    assertReleasedRate(parsed, `supportedFps[${index}]`);
    return parsed;
  });
  uniqueBy(
    supportedFps,
    (rate) => `${rate.numerator}/${rate.denominator}`,
    "supported FPS",
  );
  const variables = bundle.variables.map(parseVariable);
  uniqueBy(variables, (variable) => variable.id, "bundle variable ids");
  return {
    schemaVersion: 1,
    bundleId: sceneStableId(bundle.bundleId, "bundle.bundleId"),
    fullEntry,
    unitEntries,
    supportedCanvases,
    supportedFps,
    variables,
    assetIds: stringArray(bundle.assetIds, "bundle.assetIds", sceneStableId),
    seed: sceneInteger(bundle.seed, "bundle.seed", 0, 0xFFFFFFFF),
    runtime: parseRuntime(bundle.runtime),
  };
}

function assertSupported(scene: SceneSpecV1, bundle: SceneBundleManifestV1): void {
  const canvas = `${scene.canvas.width}x${scene.canvas.height}`;
  const canvases = bundle.supportedCanvases.map(
    (item) => `${item.width}x${item.height}`,
  );
  const rate = `${scene.timing.fps.numerator}/${scene.timing.fps.denominator}`;
  const rates = bundle.supportedFps.map(
    (item) => `${item.numerator}/${item.denominator}`,
  );
  if (!canvases.includes(canvas) || !rates.includes(rate)) {
    throw new Error("scene canvas or FPS is outside the bundle support matrix");
  }
}

function assertVariables(scene: SceneSpecV1, bundle: SceneBundleManifestV1): void {
  const definitions = new Map(bundle.variables.map((row) => [row.id, row]));
  const supplied = scene.composition.variables;
  const extras = Object.keys(supplied).filter((key) => !definitions.has(key));
  const missing = bundle.variables.filter(
    (row) => row.required && supplied[row.id] === undefined && row.default === undefined,
  );
  if (extras.length || missing.length) {
    throw new Error("scene variables differ from the bundle manifest");
  }
  Object.entries(supplied).forEach(([key, value]) =>
    parseVariableValue(value, definitions.get(key)!, `scene variable ${key}`));
  const resolved = Object.fromEntries(bundle.variables
    .filter((row) => row.default !== undefined)
    .map((row) => [row.id, row.default!]));
  Object.assign(resolved, supplied);
  const elementValues: Record<string, SceneScalarV1> = {};
  const owners = new Map<string, Set<string>>();
  scene.elements.forEach((element) => {
    Object.entries(element.values).forEach(([key, value]) => {
      if (key in elementValues && elementValues[key] !== value) {
        throw new Error(`shared scene variable ${key} has conflicting values`);
      }
      elementValues[key] = value;
      if (!owners.has(key)) owners.set(key, new Set());
      owners.get(key)!.add(element.elementId);
    });
  });
  const ownership = bundle.variables.every((row) => {
    const actual = [...(owners.get(row.id) ?? [])].sort().join("\0");
    return actual === [...row.elementIds].sort().join("\0");
  });
  if (!ownership || !sameRecord(resolved, elementValues)) {
    throw new Error("scene variable ownership or resolved values differ");
  }
}

/** Bind one SceneSpec to an exact content-addressed project bundle generation. */
export function assertSceneBundleReferenceV1(
  sceneValue: unknown,
  bundleValue: unknown,
  bundleHashValue: unknown,
): { scene: SceneSpecV1; bundle: SceneBundleManifestV1; bundleHash: string } {
  const scene = parseSceneSpecV1(sceneValue);
  const bundle = parseSceneBundleManifestV1(bundleValue);
  const bundleHash = sceneDigest(bundleHashValue, "bundleHash");
  if (scene.composition.type !== "project"
      || scene.composition.bundleId !== bundle.bundleId
      || scene.composition.bundleHash !== bundleHash
      || scene.composition.entry !== bundle.fullEntry) {
    throw new Error("scene does not bind this exact bundle generation");
  }
  const entries = Object.fromEntries(
    scene.renderUnits.map((unit) => [unit.unitId, unit.entry]),
  );
  if (!sameRecord(entries, bundle.unitEntries)) {
    throw new Error("scene render-unit entries differ from the bundle manifest");
  }
  assertSupported(scene, bundle);
  assertVariables(scene, bundle);
  const assets = scene.dependencies
    .filter((dependency) => dependency.kind === "asset")
    .map((dependency) => dependency.id)
    .sort();
  if (assets.join("\0") !== [...bundle.assetIds].sort().join("\0")) {
    throw new Error("scene asset dependencies differ from bundle assetIds");
  }
  return { scene, bundle, bundleHash };
}

export type { SceneBundleManifestV1 } from "./scene-spec-types";
