import {
  exactKeys,
  objectValue,
  sha256,
} from "./validation";
import type {
  SceneCanvasV1,
  SceneScalarV1,
  SceneVariablesV1,
} from "./scene-spec-types";

const SCENE_ID_RE = /^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/u;
const VARIABLE_RE = /^[A-Za-z][A-Za-z0-9_]*$/u;
const RELATIVE_PATH_RE = /^[A-Za-z0-9][A-Za-z0-9._/-]*$/u;

export function sceneStableId(value: unknown, label: string): string {
  if (typeof value !== "string"
      || Array.from(value).length > 96
      || !SCENE_ID_RE.test(value)) {
    throw new Error(`${label} must be a stable kebab-case id`);
  }
  return value;
}

export function sceneVariableId(value: unknown, label: string): string {
  if (typeof value !== "string" || !VARIABLE_RE.test(value)) {
    throw new Error(`${label} must be a declared variable identifier`);
  }
  return value;
}

export function sceneRelativePath(value: unknown, label: string): string {
  const parts = typeof value === "string" ? value.split("/") : [];
  if (typeof value !== "string"
      || Array.from(value).length > 240
      || value.startsWith("/")
      || !RELATIVE_PATH_RE.test(value)
      || parts.some((part) => part === "" || part === "." || part === "..")) {
    throw new Error(`${label} must be a safe relative path`);
  }
  return value;
}

export function sceneHtmlPath(value: unknown, label: string): string {
  const result = sceneRelativePath(value, label);
  if (!result.endsWith(".html")) {
    throw new Error(`${label} must be a safe relative HTML path`);
  }
  return result;
}

export function sceneInteger(
  value: unknown,
  label: string,
  minimum: number,
  maximum = Number.MAX_SAFE_INTEGER,
): number {
  if (!Number.isSafeInteger(value)
      || Number(value) < minimum
      || Number(value) > maximum) {
    throw new Error(`${label} must be an integer in ${minimum}..${maximum}`);
  }
  return Number(value);
}

export function sceneScalar(value: unknown, label: string): SceneScalarV1 {
  const valid = typeof value === "string"
    || typeof value === "boolean"
    || typeof value === "number" && Number.isFinite(value);
  if (!valid) throw new Error(`${label} must be a finite scalar`);
  if (typeof value === "string" && Array.from(value).length > 4_000) {
    throw new Error(`${label} exceeds 4000 characters`);
  }
  return value as SceneScalarV1;
}

export function sceneVariables(value: unknown, label: string): SceneVariablesV1 {
  const variables = objectValue(value, label);
  return Object.fromEntries(Object.entries(variables).map(([key, item]) => [
    sceneVariableId(key, `${label} variable`),
    sceneScalar(item, `${label}.${key}`),
  ]));
}

export function sceneCanvas(value: unknown, label: string): SceneCanvasV1 {
  const canvas = objectValue(value, label);
  exactKeys(canvas, ["width", "height"], ["width", "height"], label);
  const width = sceneInteger(canvas.width, `${label}.width`, 2, 8192);
  const height = sceneInteger(canvas.height, `${label}.height`, 2, 8192);
  if (width % 2 !== 0 || height % 2 !== 0) {
    throw new Error(`${label} dimensions must be even`);
  }
  return { width, height };
}

export function sceneDigest(value: unknown, label: string): string {
  return sha256(value, label);
}

export function uniqueBy<T>(
  values: T[],
  key: (value: T) => string,
  label: string,
): T[] {
  if (new Set(values.map(key)).size !== values.length) {
    throw new Error(`${label} must be unique`);
  }
  return values;
}

export function stringArray(
  value: unknown,
  label: string,
  parser: (item: unknown, itemLabel: string) => string,
  nonempty = false,
): string[] {
  if (!Array.isArray(value) || (nonempty && value.length === 0)) {
    throw new Error(`${label} must be ${nonempty ? "a non-empty" : "an"} array`);
  }
  const result = value.map((item, index) => parser(item, `${label}[${index}]`));
  if (new Set(result).size !== result.length) {
    throw new Error(`${label} must contain unique values`);
  }
  return result;
}
