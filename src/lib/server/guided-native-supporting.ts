/** Supplied inventory and pending requirements; never source rights or selected media authority. */
import path from "node:path";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { exactKeys, objectValue, sha256, stringValue } from "@/lib/producer/contracts/validation";
import { resolveLanes, validateIntent, validateLaneOverrides, SCOPES } from "@/lib/producer/intent-presets";
import { AUTOMATIC_SHORT_DIRECTION, shortMediaPolicy, type ShortMediaPolicy } from "@/lib/producer/short-direction";
import type { AssetManifest } from "@/lib/producer/types";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { nativeShortSupportingInventory } from "./native-short-request";

export interface NativeSupportingAsset {
  assetId: string; path: string; sha256: string; sizeBytes: number;
  kind: "image" | "video"; mime: "image/png" | "image/jpeg" | "image/webp" | null;
  width: number; height: number; admissionReceipt: { path: string; sha256: string };
  eligible: boolean; ineligibilityReason: string | null;
}
export interface NativeSupportingPolicy {
  schemaVersion: 1; scope: "supplied-native-supporting-inventory-not-selection-or-rights-approval";
  policy: ShortMediaPolicy; brollEnabled: boolean; assets: NativeSupportingAsset[];
}
export interface NativeAssetRequirement {
  sceneId: string; assetId: string; startFrame: number; endFrameExclusive: number;
  occurrenceIds: number[]; quote: string;
}

function positive(value: unknown, name: string, maximum = Number.MAX_SAFE_INTEGER): number {
  if (!Number.isSafeInteger(value) || Number(value) < 1 || Number(value) > maximum) throw new Error(`Native supplied ${name} must be a bounded positive integer`);
  return Number(value);
}

function supportingAsset(value: Record<string, unknown>, manifestPath: string): NativeSupportingAsset {
  if (value.kind !== "image" && value.kind !== "video") throw new Error("Native supplied inventory requires an admitted image/video kind");
  if (!Array.isArray(value.resolution) || value.resolution.length !== 2) throw new Error("Native supplied inventory requires admitted dimensions");
  const file = stringValue(value.path, "native supplied path", 4096), bytes = positive(value.sizeBytes, "bytes");
  if (value.sourceSizeBytes !== bytes) throw new Error("Native supplied bytes differ from their admission");
  const receiptPath = path.resolve(path.dirname(manifestPath), stringValue(value.admissionReceiptPath, "native supplied admission", 4096));
  const receipt = readCutPreviewObject(receiptPath);
  if (receipt.sha256 !== sha256(value.admissionReceiptSha256, "native supplied admission hash")) throw new Error("Native supplied admission receipt changed");
  // These are admitted-format eligibility hints; the v3 origin and actual visual review remain mandatory.
  const raster = { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp" } as const;
  const mime = raster[path.extname(file).toLowerCase() as keyof typeof raster] ?? null;
  const eligible = value.kind === "image" && mime !== null && bytes <= 1024 ** 3;
  return { assetId: stringValue(value.id, "native supporting asset ID", 160), path: file,
    sha256: sha256(value.sha256, "native supporting SHA"), sizeBytes: bytes, kind: value.kind, mime,
    width: positive(value.resolution[0], "width", 16384), height: positive(value.resolution[1], "height", 16384),
    admissionReceipt: { path: receiptPath, sha256: receipt.sha256 }, eligible,
    ineligibilityReason: eligible ? null : "Only supplied PNG, JPEG or WebP images up to one GiB are implemented in V10" };
}

/** Observe every supplied row from the actual saved manifest; unsupported formats remain visible gaps. */
export function buildNativeSupportingPolicy(input: { manifestPath: string; manifest: Record<string, unknown>; intent: unknown; target: Record<string, unknown> }): NativeSupportingPolicy {
  const intent = validateIntent(input.intent);
  if (intent.mode !== "short" || input.target.mode !== "short" || !SCOPES.includes(input.target.scope as typeof SCOPES[number])) throw new Error("Native supporting policy requires the accepted Short scope");
  const actual = resolveLanes(intent.scope, intent.lanes), accepted = resolveLanes(input.target.scope as typeof SCOPES[number], validateLaneOverrides(input.target.lanes));
  const assets = nativeShortSupportingInventory(input.manifestPath, input.manifest as unknown as AssetManifest)
    .map(value => supportingAsset(value, input.manifestPath));
  if (new Set(assets.map(row => row.assetId)).size !== assets.length) throw new Error("Native supporting inventory has ambiguous duplicate IDs");
  return { schemaVersion: 1, scope: "supplied-native-supporting-inventory-not-selection-or-rights-approval",
    policy: shortMediaPolicy(intent.shortDirection ?? AUTOMATIC_SHORT_DIRECTION), brollEnabled: actual.broll === "auto" && accepted.broll === "auto", assets };
}

/** Whole-record equality includes disallowed rows, paths, admission receipts and effective policy. */
export function assertNativeSupportingPolicy(value: unknown, expected: NativeSupportingPolicy): void {
  const row = objectValue(value, "native supporting policy"), keys = ["schemaVersion", "scope", "policy", "brollEnabled", "assets"];
  exactKeys(row, keys, keys, "native supporting policy");
  if (canonicalJsonSha256(row) !== canonicalJsonSha256(expected)) throw new Error("Native supporting policy differs from actual stored authority");
}

/** Call only after strict proposal reconstruction; pending asset work is not a generic blocker waiver. */
export function nativeProposalPreparationAllowed(result: {
  proposal: { schemaVersion: number }; blockers: unknown[]; candidate: Record<string, unknown> | null;
  pendingRequirements?: NativeAssetRequirement[];
}): boolean {
  if (result.blockers.length || result.candidate?.executionRoute !== "native-short-v1") return false;
  if (result.proposal.schemaVersion === 9) return result.pendingRequirements === undefined;
  const direction = result.candidate.nativeDirection as { proposalVersion?: number; assetRequirements?: NativeAssetRequirement[] } | undefined;
  return result.proposal.schemaVersion === 10 && direction?.proposalVersion === 10
    && Array.isArray(result.pendingRequirements) && Array.isArray(direction.assetRequirements)
    && canonicalJsonSha256(result.pendingRequirements) === canonicalJsonSha256(direction.assetRequirements);
}
