import {
  enumValue,
  exactKeys,
  objectValue,
  sha256,
  stringValue,
} from "./validation";
import {
  sceneInteger,
  sceneStableId,
  stringArray,
} from "./scene-validation";

export const ASSET_USES = [
  "editorial", "commercial", "thumbnail", "cover", "loop",
] as const;
export const ASSET_PLATFORMS = [
  "youtube", "instagram", "linkedin", "tiktok", "facebook", "local-review",
] as const;
export const ASSET_MIMES = [
  "image/png", "image/jpeg", "image/webp", "image/svg+xml",
  "audio/wav", "audio/mpeg", "video/mp4", "video/quicktime",
  "font/ttf", "font/otf",
] as const;

export type AssetUseV1 = typeof ASSET_USES[number];
export type AssetPlatformV1 = typeof ASSET_PLATFORMS[number];

export interface AssetRecordV1 {
  schemaVersion: 1;
  assetId: string;
  sha256: string;
  sizeBytes: number;
  mime: typeof ASSET_MIMES[number];
  origin:
    | "operator-upload"
    | "approved-library"
    | "generated"
    | "reference-derived";
  acquiredAt: string;
  rights: {
    license: string;
    allowedUses: AssetUseV1[];
    allowedPlatforms: AssetPlatformV1[];
    consent: "not-applicable" | "verified" | "missing" | "unknown";
    attributionRequired: boolean;
    attribution?: string;
    expiresAt?: string;
  };
  media: {
    width?: number;
    height?: number;
    durationFrames?: number;
    sampleRate?: number;
    channels?: number;
    hasAlpha?: boolean;
    colorSpace?: string;
  };
  provenance: {
    source: string;
    generator?: {
      model: string;
      version: string;
      requestHash: string;
    };
  };
  publicationDisposition: "approved" | "blocked" | "expired" | "needs-review";
}

function timestamp(value: unknown, label: string): string {
  const result = stringValue(value, label, 64);
  if (!/(?:Z|[+-]\d{2}:\d{2})$/u.test(result)
      || !Number.isFinite(Date.parse(result))) {
    throw new Error(`${label} must be an RFC3339 timestamp with timezone`);
  }
  return result;
}

function parseRights(value: unknown): AssetRecordV1["rights"] {
  const rights = objectValue(value, "AssetRecordV1.rights");
  const keys = [
    "license", "allowedUses", "allowedPlatforms", "consent",
    "attributionRequired", "attribution", "expiresAt",
  ] as const;
  const required = [
    "license", "allowedUses", "allowedPlatforms", "consent",
    "attributionRequired",
  ] as const;
  exactKeys(rights, keys, required, "AssetRecordV1.rights");
  if (typeof rights.attributionRequired !== "boolean") {
    throw new Error("asset attributionRequired must be boolean");
  }
  const attribution = rights.attribution === undefined ? undefined
    : stringValue(rights.attribution, "asset attribution", 1_000);
  if (rights.attributionRequired && attribution === undefined) {
    throw new Error("required asset attribution is missing");
  }
  return {
    license: stringValue(rights.license, "asset license", 240),
    allowedUses: stringArray(
      rights.allowedUses,
      "asset allowedUses",
      (item, label) => enumValue(item, ASSET_USES, label),
      true,
    ) as AssetUseV1[],
    allowedPlatforms: stringArray(
      rights.allowedPlatforms,
      "asset allowedPlatforms",
      (item, label) => enumValue(item, ASSET_PLATFORMS, label),
      true,
    ) as AssetPlatformV1[],
    consent: enumValue(
      rights.consent,
      ["not-applicable", "verified", "missing", "unknown"] as const,
      "asset consent",
    ),
    attributionRequired: rights.attributionRequired,
    ...(attribution === undefined ? {} : { attribution }),
    ...(rights.expiresAt === undefined ? {} : {
      expiresAt: timestamp(rights.expiresAt, "asset expiresAt"),
    }),
  };
}

function parseMedia(value: unknown): AssetRecordV1["media"] {
  const media = objectValue(value, "AssetRecordV1.media");
  const keys = [
    "width", "height", "durationFrames", "sampleRate",
    "channels", "hasAlpha", "colorSpace",
  ] as const;
  exactKeys(media, keys, [], "AssetRecordV1.media");
  const bounds = {
    width: [1, 16_384],
    height: [1, 16_384],
    durationFrames: [1, 1_000_000_000],
    sampleRate: [8_000, 384_000],
    channels: [1, 32],
  } as const;
  const parsed: AssetRecordV1["media"] = {};
  for (const [key, [minimum, maximum]] of Object.entries(bounds)) {
    if (media[key] !== undefined) {
      parsed[key as keyof typeof bounds] = sceneInteger(
        media[key],
        `asset.media.${key}`,
        minimum,
        maximum,
      );
    }
  }
  if (media.hasAlpha !== undefined) {
    if (typeof media.hasAlpha !== "boolean") {
      throw new Error("asset.media.hasAlpha must be boolean");
    }
    parsed.hasAlpha = media.hasAlpha;
  }
  if (media.colorSpace !== undefined) {
    parsed.colorSpace = stringValue(media.colorSpace, "asset.media.colorSpace", 80);
  }
  return parsed;
}

function parseProvenance(
  value: unknown,
  origin: AssetRecordV1["origin"],
): AssetRecordV1["provenance"] {
  const provenance = objectValue(value, "AssetRecordV1.provenance");
  exactKeys(
    provenance,
    ["source", "generator"],
    ["source"],
    "AssetRecordV1.provenance",
  );
  const source = stringValue(provenance.source, "asset provenance source", 1_000);
  if (origin === "generated" && provenance.generator === undefined) {
    throw new Error("generated asset needs generator provenance");
  }
  if (provenance.generator === undefined) return { source };
  const generator = objectValue(
    provenance.generator,
    "AssetRecordV1.provenance.generator",
  );
  const keys = ["model", "version", "requestHash"];
  exactKeys(generator, keys, keys, "AssetRecordV1.provenance.generator");
  return {
    source,
    generator: {
      model: stringValue(generator.model, "asset generator model", 160),
      version: stringValue(generator.version, "asset generator version", 160),
      requestHash: sha256(generator.requestHash, "asset generator requestHash"),
    },
  };
}

/** Parse one immutable AssetRecordV1; byte and current-rights admission is downstream. */
export function parseAssetRecordV1(value: unknown): AssetRecordV1 {
  const record = objectValue(value, "AssetRecordV1");
  const keys = [
    "schemaVersion", "assetId", "sha256", "sizeBytes", "mime", "origin",
    "acquiredAt", "rights", "media", "provenance", "publicationDisposition",
  ] as const;
  exactKeys(record, keys, keys, "AssetRecordV1");
  if (record.schemaVersion !== 1) {
    throw new Error("AssetRecordV1.schemaVersion must be 1");
  }
  const origin = enumValue(
    record.origin,
    ["operator-upload", "approved-library", "generated", "reference-derived"] as const,
    "asset origin",
  );
  return {
    schemaVersion: 1,
    assetId: sceneStableId(record.assetId, "asset.assetId"),
    sha256: sha256(record.sha256, "asset.sha256"),
    sizeBytes: sceneInteger(record.sizeBytes, "asset.sizeBytes", 1, 1024 ** 3),
    mime: enumValue(record.mime, ASSET_MIMES, "asset.mime"),
    origin,
    acquiredAt: timestamp(record.acquiredAt, "asset.acquiredAt"),
    rights: parseRights(record.rights),
    media: parseMedia(record.media),
    provenance: parseProvenance(record.provenance, origin),
    publicationDisposition: enumValue(
      record.publicationDisposition,
      ["approved", "blocked", "expired", "needs-review"] as const,
      "asset publicationDisposition",
    ),
  };
}
