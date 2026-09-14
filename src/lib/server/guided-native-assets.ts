/** Resolve V10 required scene assets through existing source-bound v3 decisions. */
import { exactKeys, objectValue } from "@/lib/producer/contracts/validation";
import { shortMediaPolicy } from "@/lib/producer/short-direction";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { readNativeAssetOrigin } from "./native-short-asset-use-origins";
import type { NativeShortProjectInput } from "./native-short-project";
import type { NativeShortDirection } from "./guided-native-candidate";
import type { NativeSupportingPolicy, NativeAssetRequirement } from "./guided-native-supporting";

export interface GuidedNativeAssetResolution { sceneId: string; assetId: string; decisionId: string }
export interface ResolvedGuidedNativeAsset extends GuidedNativeAssetResolution {
  decisionHash: string; inventoryHash: string; originHash: string;
}
interface ResolutionContext {
  direction: NativeShortDirection;
  policy?: NativeSupportingPolicy;
  mappings?: GuidedNativeAssetResolution[];
}

function assertReadingHold(input: NativeShortProjectInput, requirement: NativeAssetRequirement,
  direction: NativeShortDirection, targetId: string): void {
  const scene = direction.scenes.find(row => row.direction.id === requirement.sceneId);
  const frames = scene?.direction.readingHoldFrames;
  const hold = input.strategy.pacing?.holds.find(row => row.targetId === targetId);
  if (!scene || scene.startFrame !== requirement.startFrame || scene.endFrameExclusive !== requirement.endFrameExclusive
      || !Number.isSafeInteger(frames) || !hold || hold.startFrame < requirement.startFrame
      || hold.endFrame > requirement.endFrameExclusive || hold.endFrame - hold.startFrame < frames!) {
    throw new Error("Guided supplied asset lacks its compiled scene's actual reading hold");
  }
  // The shared pacing gate checks this exact hold against the executable target and known motion.
}

function requireMappings(requirements: NativeAssetRequirement[], mappings: GuidedNativeAssetResolution[]): void {
  if (mappings.length !== requirements.length || mappings.length > 128) throw new Error("Guided required assets need exact complete resolution coverage");
  const pairs = new Set<string>(), decisions = new Set<string>();
  for (const value of mappings) {
    const row = objectValue(value, "guided asset resolution"), keys = ["sceneId", "assetId", "decisionId"];
    exactKeys(row, keys, keys, "guided asset resolution");
    if (keys.some(key => typeof row[key] !== "string" || !row[key] || String(row[key]).length > 160)) throw new Error("Guided asset resolution needs explicit identities");
    const pair = canonicalJsonSha256([row.sceneId, row.assetId]);
    if (pairs.has(pair) || decisions.has(String(row.decisionId))
        || !requirements.some(req => req.sceneId === row.sceneId && req.assetId === row.assetId)) throw new Error("Guided asset resolution duplicates or invents a scene, asset or decision");
    pairs.add(pair); decisions.add(String(row.decisionId));
  }
}

function resolveAsset(input: NativeShortProjectInput, requirement: NativeAssetRequirement,
  mapping: GuidedNativeAssetResolution, policy: NativeSupportingPolicy): ResolvedGuidedNativeAsset {
  const inventory = policy.assets.find(row => row.assetId === requirement.assetId);
  const decision = input.strategy.assetUse?.decisions.find(row => row.id === mapping.decisionId);
  if (!inventory?.eligible || inventory.kind !== "image" || !inventory.mime) throw new Error("Guided asset requirement lacks an eligible admitted raster image");
  if (!decision || decision.decision !== "insert" || !decision.selection) throw new Error("Required guided insertion needs an existing insert decision; no-insert cannot fulfill it");
  const use = decision.selection, asset = input.assets.find(row => row.file === use.assetFile);
  if (!asset || asset.role !== "image" || asset.path !== inventory.path || asset.sha256 !== inventory.sha256) throw new Error("Guided required asset differs from the selected admitted source path/hash");
  if (canonicalJsonSha256(decision.speech.occurrenceIds) !== canonicalJsonSha256(requirement.occurrenceIds)
      || decision.speech.text !== requirement.quote || decision.speech.startFrame < requirement.startFrame
      || decision.speech.endFrame > requirement.endFrameExclusive || use.startFrame < requirement.startFrame
      || use.endFrame > requirement.endFrameExclusive) throw new Error("Guided insertion changed its required scene, speech or display window");
  const scene = input.strategy.scenes.find(row => row.startFrame === requirement.startFrame && row.endFrame === requirement.endFrameExclusive);
  if (!scene?.visibleIds.includes(use.targetId) || !requirement.occurrenceIds.every(id => scene.occurrenceIds.includes(id))) throw new Error("Guided insert target is absent from the required strategy scene");
  if (!["image", "logo", "creator-image"].includes(use.kind) || use.audio !== "none" || use.sourceRange) throw new Error("Guided V10 currently executes supplied raster images without source audio");
  const origin = readNativeAssetOrigin(asset);
  if (origin.acquisition.kind !== "provided" || origin.record.mime !== inventory.mime
      || origin.record.sizeBytes !== inventory.sizeBytes || origin.record.media.width !== inventory.width
      || origin.record.media.height !== inventory.height
      || !origin.acquisition.evidence.some(row => canonicalJsonSha256(row) === canonicalJsonSha256(inventory.admissionReceipt))) {
    throw new Error("Guided required asset lost its admitted origin, dimensions or acquisition evidence");
  }
  return { ...mapping, decisionHash: canonicalJsonSha256(decision),
    inventoryHash: canonicalJsonSha256(inventory), originHash: canonicalJsonSha256(origin) };
}

/** Shared assembly separately validates v3 crop, claim, rights, target, policy and audio semantics. */
export function resolveGuidedNativeAssets(input: NativeShortProjectInput, context: ResolutionContext): ResolvedGuidedNativeAsset[] {
  const { direction, policy } = context, mappings = context.mappings ?? [];
  if (!Array.isArray(mappings)) throw new Error("Guided asset resolutions must be an explicit bounded list");
  if (direction.proposalVersion !== 10) {
    if (mappings.length || direction.assetRequirements !== undefined) throw new Error("Legacy V9 cannot adopt V10 external asset resolution");
    return [];
  }
  const requirements = direction.assetRequirements;
  if (!Array.isArray(requirements) || !policy || canonicalJsonSha256(policy.policy) !== canonicalJsonSha256(shortMediaPolicy(input.request))) throw new Error("Guided V10 lost its authoritative supporting inventory or media policy");
  requireMappings(requirements, mappings);
  if (requirements.length && (!policy.brollEnabled || policy.policy.placement !== "auto")) throw new Error("Guided required insertion cannot override B-roll ownership or disabled placement");
  return requirements.map(requirement => {
    const mapping = mappings.find(row => row.sceneId === requirement.sceneId && row.assetId === requirement.assetId)!;
    const resolved = resolveAsset(input, requirement, mapping, policy);
    const selection = input.strategy.assetUse!.decisions.find(row => row.id === mapping.decisionId)!.selection!;
    assertReadingHold(input, requirement, direction, selection.targetId);
    return resolved;
  });
}
