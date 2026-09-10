import {
  ASSET_PLATFORMS,
  ASSET_USES,
  parseAssetRecordV1,
  type AssetPlatformV1,
  type AssetRecordV1,
  type AssetUseV1,
} from "./asset-record";
import {
  enumValue,
  exactKeys,
  objectValue,
  sha256,
  stringValue,
} from "./validation";
import {
  assertSceneReadabilityBindingV1,
  parseSceneReadabilityReceiptV1,
  type SceneReadabilityReceiptV1,
} from "./scene-readability";
import { parseSceneSpecV1, type SceneSpecV1 } from "./scene-spec";
import { sceneRelativePath, uniqueBy } from "./scene-validation";

export interface ScenePackageAssetV1 {
  record: AssetRecordV1;
  blobPath: string;
  bundleMember: string | null;
}

export interface ScenePackageV1 {
  schemaVersion: 1;
  scene: SceneSpecV1;
  publicationContext: {
    use: AssetUseV1;
    platform: AssetPlatformV1;
    evaluatedAt: string;
  };
  assets: ScenePackageAssetV1[];
  readability: {
    required: boolean;
    sourceSha256: string | null;
    receipt: SceneReadabilityReceiptV1 | null;
  };
}

function absolutePath(value: unknown): string {
  const result = stringValue(value, "scene package blobPath", 4_096);
  const parts = result.split("/");
  if (!result.startsWith("/")
      || result === "/"
      || parts.slice(1).some((part) =>
        part === "" || part === "." || part === "..")
      || result.includes("\\")) {
    throw new Error("scene package blobPath must be an absolute normalized path");
  }
  return result;
}

function publicationTimestamp(value: unknown): string {
  const result = stringValue(value, "publication evaluatedAt", 64);
  if (!/(?:Z|[+-]\d{2}:\d{2})$/u.test(result)
      || !Number.isFinite(Date.parse(result))) {
    throw new Error("publication evaluatedAt must be RFC3339 with a timezone");
  }
  return result;
}

function parsePublication(
  value: unknown,
): ScenePackageV1["publicationContext"] {
  const context = objectValue(value, "ScenePackageV1.publicationContext");
  const keys = ["use", "platform", "evaluatedAt"];
  exactKeys(context, keys, keys, "ScenePackageV1.publicationContext");
  return {
    use: enumValue(context.use, ASSET_USES, "publication use"),
    platform: enumValue(
      context.platform,
      ASSET_PLATFORMS,
      "publication platform",
    ),
    evaluatedAt: publicationTimestamp(context.evaluatedAt),
  };
}

function parseAsset(value: unknown, index: number): ScenePackageAssetV1 {
  const label = `ScenePackageV1.assets[${index}]`;
  const asset = objectValue(value, label);
  const keys = ["record", "blobPath", "bundleMember"];
  exactKeys(asset, keys, keys, label);
  return {
    record: parseAssetRecordV1(asset.record),
    blobPath: absolutePath(asset.blobPath),
    bundleMember: asset.bundleMember === null
      ? null : sceneRelativePath(asset.bundleMember, `${label}.bundleMember`),
  };
}

function parseReadability(
  value: unknown,
  scene: SceneSpecV1,
): ScenePackageV1["readability"] {
  const readability = objectValue(value, "ScenePackageV1.readability");
  const keys = ["required", "sourceSha256", "receipt"];
  exactKeys(readability, keys, keys, "ScenePackageV1.readability");
  if (typeof readability.required !== "boolean") {
    throw new Error("scene package readability.required must be boolean");
  }
  const sourceSha256 = readability.sourceSha256 === null
    ? null : sha256(readability.sourceSha256, "readability.sourceSha256");
  const receipt = readability.receipt === null
    ? null : parseSceneReadabilityReceiptV1(readability.receipt);
  if ((sourceSha256 === null) !== (receipt === null)
      || readability.required && receipt === null) {
    throw new Error("scene package readability evidence is incomplete");
  }
  if (receipt !== null) {
    assertSceneReadabilityBindingV1(scene, receipt, {
      required: readability.required,
      sourceSha256: sourceSha256!,
    });
  }
  return { required: readability.required, sourceSha256, receipt };
}

function assertAssetBindings(
  scene: SceneSpecV1,
  assets: ScenePackageAssetV1[],
): void {
  uniqueBy(assets, (asset) => asset.record.assetId, "scene package asset ids");
  uniqueBy(assets, (asset) => asset.blobPath, "scene package blob paths");
  uniqueBy(
    assets.filter((asset) => asset.bundleMember !== null),
    (asset) => asset.bundleMember!,
    "scene package bundle members",
  );
  const dependencies = scene.dependencies.filter(
    (dependency) => dependency.kind === "asset",
  );
  const records = new Map(assets.map((asset) => [asset.record.assetId, asset]));
  if (records.size !== dependencies.length
      || dependencies.some((dependency) => {
        const asset = records.get(dependency.id);
        return asset === undefined || asset.record.sha256 !== dependency.sha256;
      })) {
    throw new Error("scene package assets do not bind exact scene dependencies");
  }
  for (const asset of assets) {
    if (scene.composition.type === "project" && asset.bundleMember === null) {
      throw new Error("project scene assets require explicit bundleMember paths");
    }
    if (scene.composition.type === "catalog" && asset.bundleMember !== null) {
      throw new Error("catalog scene assets cannot claim project bundle members");
    }
  }
}

/** Parse the exact package reference consumed by the production scene CLI. */
export function parseScenePackageV1(value: unknown): ScenePackageV1 {
  const packageValue = objectValue(value, "ScenePackageV1");
  const keys = [
    "schemaVersion", "scene", "publicationContext", "assets", "readability",
  ];
  exactKeys(packageValue, keys, keys, "ScenePackageV1");
  if (packageValue.schemaVersion !== 1 || !Array.isArray(packageValue.assets)) {
    throw new Error("ScenePackageV1 version or assets are invalid");
  }
  const scene = parseSceneSpecV1(packageValue.scene);
  const assets = packageValue.assets.map(parseAsset);
  assertAssetBindings(scene, assets);
  return {
    schemaVersion: 1,
    scene,
    publicationContext: parsePublication(packageValue.publicationContext),
    assets,
    readability: parseReadability(packageValue.readability, scene),
  };
}
