import { ASSET_MIMES } from "./asset-record";
import { parsePositiveRationalV1 } from "./positive-rational";
import { SCENE_READABLE_HYPERFRAMES_VERSIONS } from "./scene-spec-types";
import type {
  SceneCaptionPolicyV1,
  SceneProvenanceV1,
  SceneRenderModeV1,
  SceneTimingV1,
  SceneVariablesV1,
  SceneHyperframesVersion,
} from "./scene-spec-types";
import {
  sceneCanvas,
  sceneDigest,
  sceneInteger,
  sceneRelativePath,
  sceneStableId,
  sceneVariables,
  uniqueBy,
} from "./scene-validation";
import {
  enumValue,
  exactKeys,
  objectValue,
  stringValue,
} from "./validation";

interface AuthoringAssetV1 {
  assetId: string;
  sha256: string;
  mime: typeof ASSET_MIMES[number];
  bundleMember: string;
}

export interface SceneAuthoringPacketV1 {
  schemaVersion: 1;
  attemptId: string;
  brief: string;
  sceneAuthority: {
    sceneId: string;
    timing: SceneTimingV1;
    durationFrames: number;
    canvas: { width: number; height: number };
    renderMode: SceneRenderModeV1;
    captionPolicy: SceneCaptionPolicyV1;
    provenance: SceneProvenanceV1;
  };
  brandTokens: SceneVariablesV1;
  approvedAssets: AuthoringAssetV1[];
  examples: Array<{ bundleId: string; bundleHash: string }>;
  constraints: {
    hyperframesVersion: SceneHyperframesVersion;
    declaredVariables: true;
    pausedSeekableTimeline: true;
    rootDuration: true;
    deterministicSeed: true;
    vendoredRuntimeOnly: true;
    renderTimeNetwork: false;
  };
}

function timing(value: unknown): SceneTimingV1 {
  const row = objectValue(value, "authoring scene timing");
  const keys = ["startFrame", "endFrameExclusive", "fps", "timelineMapHash"];
  exactKeys(row, keys, keys, "authoring scene timing");
  const startFrame = sceneInteger(row.startFrame, "timing.startFrame", 0);
  const endFrameExclusive = sceneInteger(
    row.endFrameExclusive, "timing.endFrameExclusive", 1,
  );
  if (endFrameExclusive <= startFrame) {
    throw new Error("authoring scene timing must be nonempty");
  }
  return {
    startFrame,
    endFrameExclusive,
    fps: parsePositiveRationalV1(row.fps),
    timelineMapHash: sceneDigest(row.timelineMapHash, "timing.timelineMapHash"),
  };
}

function provenance(value: unknown): SceneProvenanceV1 {
  const row = objectValue(value, "authoring scene provenance");
  exactKeys(
    row,
    ["origin", "requestId", "stylePackHash"],
    ["origin"],
    "authoring scene provenance",
  );
  const origin = enumValue(
    row.origin,
    ["operator", "autopilot", "reference-style"] as const,
    "authoring provenance origin",
  );
  if (origin === "reference-style" && row.stylePackHash === undefined) {
    throw new Error("reference-style authoring requires stylePackHash");
  }
  return {
    origin,
    ...(row.requestId === undefined ? {} : {
      requestId: sceneStableId(row.requestId, "authoring requestId"),
    }),
    ...(row.stylePackHash === undefined ? {} : {
      stylePackHash: sceneDigest(row.stylePackHash, "authoring stylePackHash"),
    }),
  };
}

function authority(
  value: unknown,
): SceneAuthoringPacketV1["sceneAuthority"] {
  const row = objectValue(value, "SceneAuthoringPacketV1.sceneAuthority");
  const keys = [
    "sceneId", "timing", "durationFrames", "canvas",
    "renderMode", "captionPolicy", "provenance",
  ];
  exactKeys(row, keys, keys, "SceneAuthoringPacketV1.sceneAuthority");
  const parsedTiming = timing(row.timing);
  const durationFrames = sceneInteger(
    row.durationFrames, "authoring durationFrames", 1, 1_000_000_000,
  );
  if (durationFrames
      !== parsedTiming.endFrameExclusive - parsedTiming.startFrame) {
    throw new Error("authoring durationFrames disagrees with exact timing");
  }
  return {
    sceneId: sceneStableId(row.sceneId, "authoring sceneId"),
    timing: parsedTiming,
    durationFrames,
    canvas: sceneCanvas(row.canvas, "authoring canvas"),
    renderMode: enumValue(
      row.renderMode,
      ["overlay-alpha", "takeover-opaque", "presenter-hole"] as const,
      "authoring renderMode",
    ),
    captionPolicy: enumValue(
      row.captionPolicy,
      ["preserve", "suppress-overlap"] as const,
      "authoring captionPolicy",
    ),
    provenance: provenance(row.provenance),
  };
}

function asset(value: unknown, index: number): AuthoringAssetV1 {
  const label = `SceneAuthoringPacketV1.approvedAssets[${index}]`;
  const row = objectValue(value, label);
  const keys = ["assetId", "sha256", "mime", "bundleMember"];
  exactKeys(row, keys, keys, label);
  return {
    assetId: sceneStableId(row.assetId, `${label}.assetId`),
    sha256: sceneDigest(row.sha256, `${label}.sha256`),
    mime: enumValue(row.mime, ASSET_MIMES, `${label}.mime`),
    bundleMember: sceneRelativePath(row.bundleMember, `${label}.bundleMember`),
  };
}

function examples(value: unknown): SceneAuthoringPacketV1["examples"] {
  if (!Array.isArray(value) || value.length > 16) {
    throw new Error("authoring examples must contain at most 16 entries");
  }
  const parsed = value.map((item, index) => {
    const label = `SceneAuthoringPacketV1.examples[${index}]`;
    const row = objectValue(item, label);
    const keys = ["bundleId", "bundleHash"];
    exactKeys(row, keys, keys, label);
    return {
      bundleId: sceneStableId(row.bundleId, `${label}.bundleId`),
      bundleHash: sceneDigest(row.bundleHash, `${label}.bundleHash`),
    };
  });
  return uniqueBy(parsed, (item) => item.bundleId, "authoring example bundle ids");
}

function constraints(
  value: unknown,
): SceneAuthoringPacketV1["constraints"] {
  const row = objectValue(value, "SceneAuthoringPacketV1.constraints");
  const expected = {
    hyperframesVersion: enumValue(
      row.hyperframesVersion, SCENE_READABLE_HYPERFRAMES_VERSIONS,
      "authoring constraints.hyperframesVersion",
    ),
    declaredVariables: true,
    pausedSeekableTimeline: true,
    rootDuration: true,
    deterministicSeed: true,
    vendoredRuntimeOnly: true,
    renderTimeNetwork: false,
  } as const;
  const keys = Object.keys(expected);
  exactKeys(row, keys, keys, "SceneAuthoringPacketV1.constraints");
  if (keys.some((key) => row[key] !== expected[key as keyof typeof expected])) {
    throw new Error("authoring constraints differ from the released boundary");
  }
  return expected;
}

/** Parse the only data packet permitted at the coding-agent authoring boundary. */
export function parseSceneAuthoringPacketV1(
  value: unknown,
): SceneAuthoringPacketV1 {
  const row = objectValue(value, "SceneAuthoringPacketV1");
  const keys = [
    "schemaVersion", "attemptId", "brief", "sceneAuthority", "brandTokens",
    "approvedAssets", "examples", "constraints",
  ];
  exactKeys(row, keys, keys, "SceneAuthoringPacketV1");
  if (row.schemaVersion !== 1
      || !Array.isArray(row.approvedAssets)
      || row.approvedAssets.length > 64) {
    throw new Error("SceneAuthoringPacketV1 version or assets are invalid");
  }
  const approvedAssets = row.approvedAssets.map(asset);
  uniqueBy(approvedAssets, (item) => item.assetId, "approved asset ids");
  uniqueBy(approvedAssets, (item) => item.bundleMember, "approved asset members");
  const brandTokens = sceneVariables(row.brandTokens, "authoring brandTokens");
  if (Object.keys(brandTokens).length > 128) {
    throw new Error("authoring brandTokens exceed 128 entries");
  }
  return {
    schemaVersion: 1,
    attemptId: sceneStableId(row.attemptId, "authoring attemptId"),
    brief: stringValue(row.brief, "authoring brief", 12_000),
    sceneAuthority: authority(row.sceneAuthority),
    brandTokens,
    approvedAssets,
    examples: examples(row.examples),
    constraints: constraints(row.constraints),
  };
}
