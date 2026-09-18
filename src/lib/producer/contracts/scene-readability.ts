import {
  exactKeys,
  objectValue,
} from "./validation";
import { parsePositiveRationalV1 } from "./positive-rational";
import { parseSceneSpecV1, type SceneSpecV1 } from "./scene-spec";
import {
  sceneDigest,
  sceneInteger,
} from "./scene-validation";

export interface SceneReadabilityReceiptV1 {
  schemaVersion: 1;
  passed: true;
  method: "actual-footage-box-worst-pixel-v1";
  sourceSha256: string;
  sourceFps: { numerator: string; denominator: string };
  frameRange: { startFrame: number; endFrameExclusive: number };
  sampleFrames: number[];
  samplePixelCount: number;
  textBoxPixels: [number, number, number, number];
  textColor: string;
  backing: {
    color: string;
    opacity: number;
    assetProofSha256: string;
  } | null;
  minimumContrast: number;
  requiredContrast: number;
  ffmpegSha256: string;
}

export interface SceneReadabilityRequirementV1 {
  required: boolean;
  sourceSha256: string;
}

const ROOT_KEYS = [
  "schemaVersion", "passed", "method", "sourceSha256", "sourceFps",
  "frameRange", "sampleFrames", "samplePixelCount", "textBoxPixels",
  "textColor", "backing", "minimumContrast", "requiredContrast",
  "ffmpegSha256",
] as const;

function color(value: unknown, label: string): string {
  if (typeof value !== "string" || !/^#[0-9A-Fa-f]{6}$/u.test(value)) {
    throw new Error(`${label} must be #RRGGBB`);
  }
  return value;
}

function ratio(value: unknown, label: string): number {
  if (typeof value !== "number"
      || !Number.isFinite(value)
      || value < 1 || value > 21) {
    throw new Error(`${label} must be a finite contrast ratio in 1..21`);
  }
  return value;
}

function parseFrameRange(
  value: unknown,
): SceneReadabilityReceiptV1["frameRange"] {
  const range = objectValue(value, "readability.frameRange");
  const keys = ["startFrame", "endFrameExclusive"];
  exactKeys(range, keys, keys, "readability.frameRange");
  const startFrame = sceneInteger(range.startFrame, "frameRange.startFrame", 0);
  const endFrameExclusive = sceneInteger(
    range.endFrameExclusive,
    "frameRange.endFrameExclusive",
    1,
  );
  if (endFrameExclusive <= startFrame) {
    throw new Error("readability frameRange must be nonempty");
  }
  return { startFrame, endFrameExclusive };
}

function parseBacking(
  value: unknown,
): SceneReadabilityReceiptV1["backing"] {
  if (value === null) return null;
  const backing = objectValue(value, "readability.backing");
  const keys = ["color", "opacity", "assetProofSha256"];
  exactKeys(backing, keys, keys, "readability.backing");
  if (typeof backing.opacity !== "number"
      || !Number.isFinite(backing.opacity)
      || backing.opacity <= 0 || backing.opacity > 1) {
    throw new Error("readability.backing.opacity must be within (0,1]");
  }
  return {
    color: color(backing.color, "backing.color"),
    opacity: backing.opacity,
    assetProofSha256: sceneDigest(
      backing.assetProofSha256,
      "backing.assetProofSha256",
    ),
  };
}

function integerTuple4(value: unknown): [number, number, number, number] {
  if (!Array.isArray(value) || value.length !== 4) {
    throw new Error("readability.textBoxPixels must have four integers");
  }
  return value.map((item, index) =>
    sceneInteger(item, `textBoxPixels[${index}]`, index < 2 ? 0 : 1)) as [
    number, number, number, number,
  ];
}

/** Parse one passing real-footage readability receipt. */
export function parseSceneReadabilityReceiptV1(
  value: unknown,
): SceneReadabilityReceiptV1 {
  const receipt = objectValue(value, "SceneReadabilityReceiptV1");
  exactKeys(receipt, ROOT_KEYS, ROOT_KEYS, "SceneReadabilityReceiptV1");
  if (receipt.schemaVersion !== 1
      || receipt.passed !== true
      || receipt.method !== "actual-footage-box-worst-pixel-v1"
      || !Array.isArray(receipt.sampleFrames)
      || receipt.sampleFrames.length === 0) {
    throw new Error("readability receipt is not a passing released measurement");
  }
  const frameRange = parseFrameRange(receipt.frameRange);
  const sampleFrames = receipt.sampleFrames.map((frame, index) =>
    sceneInteger(frame, `sampleFrames[${index}]`, frameRange.startFrame));
  if (sampleFrames.some((frame) => frame >= frameRange.endFrameExclusive)
      || new Set(sampleFrames).size !== sampleFrames.length
      || sampleFrames.some((frame, index) => index > 0 && frame <= sampleFrames[index - 1])) {
    throw new Error("readability sampleFrames are outside or not strictly ordered");
  }
  const samplePixelCount = sceneInteger(
    receipt.samplePixelCount,
    "samplePixelCount",
    1,
  );
  if (samplePixelCount !== sampleFrames.length * 64) {
    throw new Error("readability samplePixelCount does not bind the 8x8 samples");
  }
  const minimumContrast = ratio(receipt.minimumContrast, "minimumContrast");
  const requiredContrast = ratio(receipt.requiredContrast, "requiredContrast");
  if (minimumContrast + 1e-9 < requiredContrast) {
    throw new Error("readability passing verdict contradicts measured contrast");
  }
  return {
    schemaVersion: 1,
    passed: true,
    method: "actual-footage-box-worst-pixel-v1",
    sourceSha256: sceneDigest(receipt.sourceSha256, "sourceSha256"),
    sourceFps: parsePositiveRationalV1(receipt.sourceFps),
    frameRange,
    sampleFrames,
    samplePixelCount,
    textBoxPixels: integerTuple4(receipt.textBoxPixels),
    textColor: color(receipt.textColor, "textColor"),
    backing: parseBacking(receipt.backing),
    minimumContrast,
    requiredContrast,
    ffmpegSha256: sceneDigest(receipt.ffmpegSha256, "ffmpegSha256"),
  };
}

function assertSceneBinding(
  scene: SceneSpecV1,
  receipt: SceneReadabilityReceiptV1,
): void {
  const sameRate = scene.timing.fps.numerator === receipt.sourceFps.numerator
    && scene.timing.fps.denominator === receipt.sourceFps.denominator;
  const sameRange = scene.timing.startFrame === receipt.frameRange.startFrame
    && scene.timing.endFrameExclusive === receipt.frameRange.endFrameExclusive;
  const [x, y, width, height] = receipt.textBoxPixels;
  if (!sameRate || !sameRange
      || x + width > scene.canvas.width
      || y + height > scene.canvas.height) {
    throw new Error("readability receipt does not bind the scene timing/canvas");
  }
}

/** Require and bind measured readability when the package exposes text over footage. */
export function assertSceneReadabilityBindingV1(
  sceneValue: unknown,
  receiptValue: unknown,
  requirement: SceneReadabilityRequirementV1,
): SceneReadabilityReceiptV1 | null {
  const scene = parseSceneSpecV1(sceneValue);
  const sourceSha256 = sceneDigest(
    requirement.sourceSha256,
    "readability requirement sourceSha256",
  );
  if (receiptValue === null || receiptValue === undefined) {
    if (requirement.required) {
      throw new Error("footage-exposed text lacks a readability receipt");
    }
    return null;
  }
  const receipt = parseSceneReadabilityReceiptV1(receiptValue);
  if (receipt.sourceSha256 !== sourceSha256) {
    throw new Error("readability receipt binds a different source snapshot");
  }
  assertSceneBinding(scene, receipt);
  return receipt;
}
