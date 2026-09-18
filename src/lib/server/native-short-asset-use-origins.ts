/** Immutable acquisition declarations and existing rights records, for local review only. */
import { lstatSync, readFileSync, realpathSync } from "node:fs";
import path from "node:path";
import { parseAssetRecordV1 } from "@/lib/producer/contracts/asset-record";
import { exactKeys, objectValue } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256, fileSha256 } from "./auto-edit-hash";
import { assertNativeWebCapture } from "./native-web-capture";
import type { NativeAssetOriginBinding, NativeAssetOriginReceipt, NativeAssetUseInput, NativeAssetUseOptions } from "./native-short-asset-use-types";

type Asset = NativeAssetUseInput["assets"][number];
const ACQUISITIONS = ["provided", "local-library", "public-download", "public-web-capture"];

/** Explanations carry observations and limitations, never an inferred approval. */
export function assetUseText(value: unknown): void {
  if (typeof value !== "string" || value.trim().length < 3 || value.length > 2400 || value.includes("\0")) {
    throw new Error("Asset use needs a bounded concrete explanation");
  }
}

function pinnedFile(binding: NativeAssetOriginBinding, maximumBytes = 16 * 1024 ** 2): void {
  const row = objectValue(binding, "asset origin evidence");
  exactKeys(row, ["path", "sha256"], ["path", "sha256"], "asset origin evidence");
  if (typeof binding.path !== "string" || !path.isAbsolute(binding.path) || realpathSync(binding.path) !== binding.path
      || !/^[a-f0-9]{64}$/u.test(binding.sha256)) throw new Error("Asset origin evidence is missing, changed or not canonical");
  const info = lstatSync(binding.path);
  if (!info.isFile() || info.size < 1 || info.size > maximumBytes) throw new Error("Asset origin evidence exceeds its bounded regular-file size");
  if (fileSha256(binding.path) !== binding.sha256) throw new Error("Asset origin evidence is missing, changed or not canonical");
}

/** Read the pinned immutable origin; the caller retains the original receipt binding. */
export function readNativeAssetOrigin(asset: Asset): NativeAssetOriginReceipt {
  if (!asset.origin) throw new Error(`Asset ${asset.file} needs its immutable origin receipt`);
  pinnedFile(asset.origin, 512 * 1024);
  const row = objectValue(JSON.parse(readFileSync(asset.origin.path, "utf8")), "asset origin receipt");
  const keys = ["schemaVersion", "kind", "assetFile", "record", "acquisition"];
  exactKeys(row, keys, keys, "asset origin receipt");
  if (row.schemaVersion !== 1 || row.kind !== "native-short-asset-origin" || row.assetFile !== asset.file) {
    throw new Error("Asset origin receipt identifies a different asset or schema");
  }
  const record = parseAssetRecordV1(row.record, { maxSizeBytes: asset.role === "source" ? 64 * 1024 ** 3 : 1024 ** 3 });
  if (record.sha256 !== asset.sha256 || record.sizeBytes !== lstatSync(asset.path).size) {
    throw new Error("Asset origin record differs from the frozen asset identity");
  }
  if (!(asset.role === "image" ? record.mime.startsWith("image/") : record.mime.startsWith("video/"))) {
    throw new Error("Asset origin media kind differs from its inventory role");
  }
  const receipt = { ...row, record } as unknown as NativeAssetOriginReceipt;
  acquisitionShape(receipt);
  return receipt;
}

function webEvidence(receipt: NativeAssetOriginReceipt): void {
  const web = receipt.acquisition.webCapture;
  if (receipt.acquisition.kind !== "public-web-capture") {
    if (web) throw new Error("Web acquisition cannot be relabeled as ordinary local media");
    return;
  }
  if (!web) throw new Error("Web origin requires its original acquisition and supervision receipts");
  const keys = ["path", "sha256", "supervisionPath", "supervisionSha256"];
  exactKeys(objectValue(web, "web acquisition evidence"), keys, keys, "web acquisition evidence");
  pinnedFile({ path: web.path, sha256: web.sha256 });
  pinnedFile({ path: web.supervisionPath, sha256: web.supervisionSha256 });
}

function acquisitionShape(receipt: NativeAssetOriginReceipt): void {
  const acquisition = objectValue(receipt.acquisition, "asset acquisition");
  exactKeys(acquisition, ["kind", "accessScope", "evidence", "webCapture", "sourceFrameRate"], ["kind", "accessScope", "evidence"], "asset acquisition");
  if (!ACQUISITIONS.includes(receipt.acquisition.kind)
      || !["public", "operator-private", "project-private"].includes(receipt.acquisition.accessScope)
      || !Array.isArray(receipt.acquisition.evidence) || receipt.acquisition.evidence.length > 24) {
    throw new Error("Asset acquisition lacks a bounded explicit source kind and scope");
  }
  receipt.acquisition.evidence.forEach(binding => pinnedFile(binding));
  webEvidence(receipt);
  const rate = receipt.acquisition.sourceFrameRate;
  const numbers = typeof rate === "string" ? rate.split("/").map(Number) : [], fps = numbers[0] / numbers[1];
  if (receipt.record.mime.startsWith("video/") ? typeof rate !== "string" || !/^\d+\/\d+$/u.test(rate)
      || !Number.isFinite(fps) || fps < 1 || fps > 240 || !receipt.record.media.durationFrames : rate !== undefined) {
    throw new Error("Asset origin requires an immutable video duration and source timebase");
  }
  const external = receipt.acquisition.kind.startsWith("public-");
  if (external && (receipt.acquisition.accessScope !== "public" || !receipt.acquisition.evidence.length)) {
    throw new Error("Public acquisition requires attributable pinned source evidence");
  }
  const expected = { provided: "operator-upload", "local-library": "approved-library",
    "public-download": "reference-derived", "public-web-capture": "reference-derived" };
  if (receipt.record.provenance.generator) throw new Error("Current native media policy does not admit generated assets");
  if (receipt.record.origin !== expected[receipt.acquisition.kind]) throw new Error("Asset acquisition contradicts its preserved AssetRecord origin");
  if (external) {
    const source = new URL(receipt.record.provenance.source);
    if (source.protocol !== "https:" || source.username || source.password) throw new Error("Public asset source needs a canonical HTTPS identity");
  }
}

function sourcePolicy(asset: Asset, receipt: NativeAssetOriginReceipt, options: NativeAssetUseOptions): void {
  const kind = receipt.acquisition.kind, policy = options.expectedPolicy;
  if ((policy.sources === "provided-only" && kind !== "provided")
      || (policy.sources === "local-only" && kind.startsWith("public-"))) {
    throw new Error(`Asset ${asset.file} violates the requested source restriction`);
  }
  if (kind === "provided" && options.providedAssets
      && !options.providedAssets.some(row => row.file === asset.file && row.sha256 === asset.sha256)) {
    throw new Error("Provided asset is absent from the prepared request inventory");
  }
}

function webOrigin(asset: Asset, receipt: NativeAssetOriginReceipt): void {
  const web = receipt.acquisition.webCapture;
  if (receipt.acquisition.kind !== "public-web-capture") {
    if (web || asset.webCapture) throw new Error("Web acquisition cannot be relabeled as ordinary local media");
    return;
  }
  if (!web || !asset.webCapture || canonicalJsonSha256(web) !== canonicalJsonSha256(asset.webCapture)) {
    throw new Error("Web origin requires its original acquisition and supervision receipts");
  }
  assertNativeWebCapture(asset);
  const capture = JSON.parse(readFileSync(web.path, "utf8"));
  const [num, den] = receipt.acquisition.sourceFrameRate!.split("/").map(Number);
  if (receipt.record.media.width !== capture.capture.width || receipt.record.media.height !== capture.capture.height
      || receipt.record.media.durationFrames !== capture.capture.frames || num / den !== capture.capture.fps) {
    throw new Error("Web origin dimensions and clock differ from the acquired recording");
  }
  if (capture.page.url !== receipt.record.provenance.source) throw new Error("Web origin differs from the captured canonical page");
}

function reviewRights(receipt: NativeAssetOriginReceipt, input: NativeAssetUseInput): void {
  const record = receipt.record, intended = input.strategy.assetUse!.intendedUse;
  if (intended.platform !== "local-review" || !record.rights.allowedPlatforms.includes("local-review")
      || !record.rights.allowedUses.includes(intended.use)) throw new Error("Asset rights do not allow this intended local review use");
  if (["blocked", "expired"].includes(record.publicationDisposition)
      || (record.rights.expiresAt && Date.parse(record.rights.expiresAt) <= Date.now())) {
    throw new Error("Asset has a blocked or expired disposition");
  }
}

/** Caller verifies frozen media bytes once; these records bind their hash and actual size. */
export function nativeAssetUseOrigins(input: NativeAssetUseInput, options: NativeAssetUseOptions): Map<string, NativeAssetOriginReceipt> {
  if (input.requestPacket && !options.providedAssets) throw new Error("Prepared request requires its supplied media inventory for origin admission");
  const origins = new Map<string, NativeAssetOriginReceipt>();
  for (const asset of input.assets.filter(row => ["source", "supporting-video", "image"].includes(row.role))) {
    const receipt = readNativeAssetOrigin(asset);
    sourcePolicy(asset, receipt, options); webOrigin(asset, receipt); reviewRights(receipt, input);
    origins.set(asset.file, receipt);
  }
  return origins;
}
