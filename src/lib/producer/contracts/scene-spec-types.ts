import type { PositiveRationalV1 } from "./positive-rational";

/** New authoring target; readable historical versions are never relabeled. */
export const SCENE_AUTHORING_HYPERFRAMES_VERSION = "0.8.31";
export const SCENE_READABLE_HYPERFRAMES_VERSIONS = [
  "0.7.33", SCENE_AUTHORING_HYPERFRAMES_VERSION,
] as const;
export type SceneHyperframesVersion =
  typeof SCENE_READABLE_HYPERFRAMES_VERSIONS[number];

export type SceneScalarV1 = string | number | boolean;
export type SceneVariablesV1 = Record<string, SceneScalarV1>;
export type SceneRenderModeV1 =
  | "overlay-alpha"
  | "takeover-opaque"
  | "presenter-hole";
export type SceneCaptionPolicyV1 = "preserve" | "suppress-overlap";

export interface SceneTimingV1 {
  startFrame: number;
  endFrameExclusive: number;
  fps: PositiveRationalV1;
  timelineMapHash: string;
}

export interface SceneCanvasV1 {
  width: number;
  height: number;
}

export interface CatalogSceneCompositionV1 {
  type: "catalog";
  kind: string;
  variables: SceneVariablesV1;
}

export interface ProjectSceneCompositionV1 {
  type: "project";
  bundleId: string;
  bundleHash: string;
  entry: string;
  variables: SceneVariablesV1;
}

export type SceneCompositionV1 =
  | CatalogSceneCompositionV1
  | ProjectSceneCompositionV1;

export interface SceneElementV1 {
  elementId: string;
  role: string;
  exposedProperties: string[];
  values: SceneVariablesV1;
}

export interface SceneRenderUnitV1 {
  unitId: string;
  elementIds: string[];
  zIndex: number;
  entry: string;
  sharedGroupId?: string;
  maskDependencyUnitIds?: string[];
  compositeMode: "normal" | "screen" | "multiply" | "declared";
  palmierGranularity: "scene" | "unit";
}

export interface SceneDependencyV1 {
  kind: string;
  id: string;
  sha256: string;
}

export interface SceneProvenanceV1 {
  origin: "operator" | "autopilot" | "reference-style";
  requestId?: string;
  stylePackHash?: string;
}

export interface SceneSpecV1 {
  schemaVersion: 1;
  sceneId: string;
  version: number;
  timing: SceneTimingV1;
  canvas: SceneCanvasV1;
  renderMode: SceneRenderModeV1;
  composition: SceneCompositionV1;
  elements: SceneElementV1[];
  renderUnits: SceneRenderUnitV1[];
  captionPolicy: SceneCaptionPolicyV1;
  dependencies: SceneDependencyV1[];
  provenance: SceneProvenanceV1;
}

export type SceneBundleVariableKindV1 =
  | "string"
  | "number"
  | "boolean"
  | "color"
  | "enum";

export interface SceneBundleVariableV1 {
  id: string;
  type: SceneBundleVariableKindV1;
  required: boolean;
  elementIds: string[];
  default?: SceneScalarV1;
  values?: SceneScalarV1[];
  maxLength?: number;
}

export interface SceneBundleManifestV1 {
  schemaVersion: 1;
  bundleId: string;
  fullEntry: string;
  unitEntries: Record<string, string>;
  supportedCanvases: SceneCanvasV1[];
  supportedFps: PositiveRationalV1[];
  variables: SceneBundleVariableV1[];
  assetIds: string[];
  seed: number;
  runtime: {
    hyperframesVersion: SceneHyperframesVersion;
    gsapSha256: string;
  };
}
