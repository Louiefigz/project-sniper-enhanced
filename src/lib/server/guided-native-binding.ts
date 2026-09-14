/** Persistent guided lineage and asset resolutions for shared native writer/cold replay. */
import path from "node:path";
import { realpathSync } from "node:fs";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { exactKeys, objectValue, sha256 } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { readGuidedTreatmentProposal } from "./guided-proposal-store";
import { assertGuidedNativeAuthority } from "./guided-native-authority";
import { assertGuidedNativeGeometry, guidedNativeSourceMedia } from "./guided-native-geometry";
import { nativeProposalPreparationAllowed } from "./guided-native-supporting";
import { resolveGuidedNativeAssets, type GuidedNativeAssetResolution, type ResolvedGuidedNativeAsset } from "./guided-native-assets";
import type { NativeShortProjectInput } from "./native-short-project";

export interface GuidedNativeRequestMarker {
  schemaVersion: 1; producerDir: string; proposalHash: string; evidenceHash: string; candidateHash: string;
}
export interface GuidedNativeProjectBinding {
  schemaVersion: 1; kind: "guided-native-proposal-binding";
  scope: "replayed-guided-lineage-and-asset-decisions-not-editorial-or-publication-approval";
  marker: GuidedNativeRequestMarker; proposalVersion: 9 | 10;
  authorityHash: string; nativePlanHash: string;
  resolutions: ResolvedGuidedNativeAsset[];
}
export interface NativeGuidedDependencies { readGuidedProposal?: typeof readGuidedTreatmentProposal }
export type GuidedNativeProposal = ReturnType<typeof readGuidedTreatmentProposal>;

/** This marker is frozen into the prepared packet before visual strategy exists. */
export function guidedNativeRequestMarker(proposal: GuidedNativeProposal): GuidedNativeRequestMarker {
  if (!nativeProposalPreparationAllowed(proposal.result) || !proposal.result.candidate) throw new Error("Guided native packet requires a supported reconstructed V9/V10 candidate");
  return { schemaVersion: 1, producerDir: realpathSync(proposal.job.ctx.dir), proposalHash: proposal.proposalHash,
    evidenceHash: canonicalJsonSha256(proposal.evidence), candidateHash: canonicalJsonSha256(proposal.result.candidate) };
}

/** Strict marker parsing cannot turn a guided packet into an ordinary editable native plan. */
function parseMarker(value: unknown): GuidedNativeRequestMarker {
  const row = objectValue(value, "guided request marker");
  const keys = ["schemaVersion", "producerDir", "proposalHash", "evidenceHash", "candidateHash"];
  exactKeys(row, keys, keys, "guided request marker");
  if (row.schemaVersion !== 1 || typeof row.producerDir !== "string" || !path.isAbsolute(row.producerDir)
      || realpathSync(row.producerDir) !== row.producerDir) throw new Error("Guided request marker lost its canonical producer directory");
  for (const key of ["proposalHash", "evidenceHash", "candidateHash"]) sha256(row[key], key);
  return row as unknown as GuidedNativeRequestMarker;
}

/** Ordinary old packets remain readable; a present guided marker is never optional. */
function preparedMarker(input: NativeShortProjectInput): GuidedNativeRequestMarker | null {
  const ref = input.requestPacket;
  if (!ref) return null;
  const packet = readCutPreviewObject(ref.path);
  if (packet.sha256 !== ref.sha256) throw new Error("Guided prepared packet changed");
  return Object.hasOwn(packet.value, "guidedProposal") ? parseMarker(packet.value.guidedProposal) : null;
}

/** A V10 guided output cannot shed all metadata and become plain native at its reserved location. */
export function assertGuidedNativeLocation(input: NativeShortProjectInput,
  options: { directory: string; legacyV9Read?: boolean }, dependencies: NativeGuidedDependencies = {}): void {
  const directory = options.legacyV9Read ? realpathSync(options.directory) : path.resolve(options.directory);
  const parent = path.dirname(directory);
  if (path.basename(parent) !== "native-development") return;
  const producerDir = path.dirname(parent), hash = path.basename(directory), marker = preparedMarker(input);
  if (!/^[a-f0-9]{64}$/u.test(hash) || realpathSync(producerDir) !== producerDir) throw new Error("Native guided output lost its canonical reserved location");
  if (marker) {
    if (marker.producerDir !== producerDir || marker.proposalHash !== hash) throw new Error("Guided packet belongs to another reserved proposal directory");
    return;
  }
  const proposal = (dependencies.readGuidedProposal ?? readGuidedTreatmentProposal)(producerDir);
  if (proposal.proposalHash !== hash) throw new Error("Native reserved project belongs to a superseded guided proposal");
  if (options.legacyV9Read && proposal.result.proposal.schemaVersion === 9 && !input.guidedBinding) return;
  throw new Error("Reserved guided native project lost its required prepared packet and persistent binding");
}

/** Save the complete native decision hash while keeping the packet's prior lineage independent. */
export function buildGuidedNativeBinding(input: NativeShortProjectInput, proposal: GuidedNativeProposal,
  mappings: GuidedNativeAssetResolution[] = []): GuidedNativeProjectBinding {
  const marker = preparedMarker(input), expected = guidedNativeRequestMarker(proposal);
  if (!marker || canonicalJsonSha256(marker) !== canonicalJsonSha256(expected)) throw new Error("Guided publication requires its current guided-marked prepared packet");
  const authority = { intent: proposal.job.ctx.intent,
    manifest: { path: proposal.job.ctx.manifestPath, sha256: proposal.manifest.sha256, value: proposal.manifest.value } };
  assertGuidedNativeAuthority(input, authority);
  const direction = assertGuidedNativeGeometry(proposal.result.candidate!,
    guidedNativeSourceMedia(input, proposal.manifest.value.sources), input.canvas.captionGroups,
    { candidateHash: marker.candidateHash, project: input });
  const resolutions = resolveGuidedNativeAssets(input, { direction, policy: proposal.evidence.nativeSupportingPolicy, mappings });
  const { guidedBinding: _binding, ...plan } = input; void _binding;
  return { schemaVersion: 1, kind: "guided-native-proposal-binding",
    scope: "replayed-guided-lineage-and-asset-decisions-not-editorial-or-publication-approval",
    marker, proposalVersion: proposal.result.proposal.schemaVersion as 9 | 10,
    authorityHash: canonicalJsonSha256(authority), nativePlanHash: canonicalJsonSha256(plan), resolutions };
}

/** Replay the current immutable lineage, including revisions that supersede an old proposal. */
export function assertGuidedNativeBinding(input: NativeShortProjectInput, dependencies: NativeGuidedDependencies = {}): void {
  const marker = preparedMarker(input);
  if (!marker && !input.guidedBinding) return;
  if (!marker || !input.guidedBinding) throw new Error("Guided native project lost its required persistent proposal binding");
  const row = objectValue(input.guidedBinding, "guided project binding");
  if (!Array.isArray(row.resolutions) || row.resolutions.length > 128) throw new Error("Guided native resolutions are missing or unbounded");
  const mappings = row.resolutions.map(value => {
    const resolution = objectValue(value, "stored guided resolution");
    return { sceneId: String(resolution.sceneId), assetId: String(resolution.assetId), decisionId: String(resolution.decisionId) };
  });
  const proposal = (dependencies.readGuidedProposal ?? readGuidedTreatmentProposal)(marker.producerDir);
  const expected = buildGuidedNativeBinding(input, proposal, mappings);
  if (canonicalJsonSha256(expected) !== canonicalJsonSha256(input.guidedBinding)) throw new Error("Guided native proposal, inventory or visual decision binding changed");
}
