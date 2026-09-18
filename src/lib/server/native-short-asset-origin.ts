/** Freeze source declarations once and reuse the same origin record at every native entry. */
import { lstatSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import path from "node:path";
import { parseAssetRecordV1, type AssetRecordV1 } from "@/lib/producer/contracts/asset-record";
import { canonicalJson, fileSha256 } from "./auto-edit-hash";
import { readNativeAssetOrigin } from "./native-short-asset-use-origins";
import type { NativeAssetOriginReceipt } from "./native-short-asset-use-types";
import type { NativeAssetBinding } from "./native-short-strategy";
import { assertNativeWebCapture } from "./native-web-capture";

export interface NativeOriginInput {
  asset: NativeAssetBinding;
  record: AssetRecordV1;
  acquisition: NativeAssetOriginReceipt["acquisition"];
}

/** This records the caller's source evidence; it never creates editorial/publication approval. */
export function writeNativeAssetOrigin(input: NativeOriginInput, destination: string): NativeAssetBinding {
  const { asset, acquisition } = input;
  const record = parseAssetRecordV1(input.record, { maxSizeBytes: asset.role === "source" ? 64 * 1024 ** 3 : 1024 ** 3 });
  if (asset.origin || !["source", "supporting-video", "image"].includes(asset.role)
      || record.sha256 !== asset.sha256 || fileSha256(asset.path) !== asset.sha256
      || record.sizeBytes !== lstatSync(asset.path).size) throw new Error("Origin must bind the exact unbound production asset");
  const file = path.resolve(destination);
  if (realpathSync(path.dirname(file)) !== path.dirname(file)) throw new Error("Origin destination must have a canonical parent");
  const receipt: NativeAssetOriginReceipt = { schemaVersion: 1, kind: "native-short-asset-origin",
    assetFile: asset.file, record, acquisition };
  writeFileSync(file, canonicalJson(receipt), { flag: "wx", mode: 0o600 });
  const bound = { ...asset, origin: { path: file, sha256: fileSha256(file)! } };
  readNativeAssetOrigin(bound);
  return bound;
}

/** Adapt an actual successful public recording without discarding its origin or rights uncertainty. */
export function bindNativeWebOrigin(asset: NativeAssetBinding, destination: string): NativeAssetBinding {
  if (!asset.webCapture) throw new Error("Web origin adapter requires the original capture binding");
  assertNativeWebCapture(asset);
  const receipt = JSON.parse(readFileSync(asset.webCapture.path, "utf8"));
  const owner = JSON.parse(readFileSync(asset.webCapture.supervisionPath, "utf8"));
  const capture = receipt.capture;
  return writeNativeAssetOrigin({ asset,
    record: { schemaVersion: 1, assetId: `web-${asset.sha256.slice(0, 24)}`, sha256: asset.sha256,
      sizeBytes: lstatSync(asset.path).size, mime: "video/mp4", origin: "reference-derived", acquiredAt: owner.startedAt,
      rights: { license: "Public page captured for requested local editorial review; publication rights unresolved",
        allowedUses: ["editorial"], allowedPlatforms: ["local-review"], consent: "unknown", attributionRequired: false },
      media: { width: capture.width, height: capture.height, durationFrames: capture.frames },
      provenance: { source: receipt.page.url }, publicationDisposition: "needs-review" },
    acquisition: { kind: "public-web-capture", accessScope: "public", sourceFrameRate: `${capture.fps}/1`,
      evidence: [{ path: asset.webCapture.path, sha256: asset.webCapture.sha256 }], webCapture: asset.webCapture },
  }, destination);
}
