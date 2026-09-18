/** Bind a native visual plan to the stored guided request and admitted inventory. */
import { lstatSync, realpathSync } from "node:fs";
import path from "node:path";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { objectValue } from "@/lib/producer/contracts/validation";
import { validateIntent } from "@/lib/producer/intent-presets";
import { AUTOMATIC_SHORT_DIRECTION } from "@/lib/producer/short-direction";
import { canonicalJsonSha256, fileSha256 } from "./auto-edit-hash";
import type { AssetManifest } from "@/lib/producer/types";
import { nativeShortSourceInventory, nativeShortSupportingInventory, prepareNativeShortRequest } from "./native-short-request";
import { readGuidedTreatmentProposal } from "./guided-proposal-store";
import { assertNativeShortIntent, type NativeShortProjectInput } from "./native-short-project";
import { nativeProposalPreparationAllowed } from "./guided-native-supporting";
import { guidedNativeRequestMarker } from "./guided-native-binding";

export interface GuidedNativeAuthority {
  intent: unknown;
  manifest: { path: string; sha256: string; value: Record<string, unknown> };
}

function normalizedIntent(value: unknown) {
  const intent = validateIntent(value);
  return { ...intent, shortDirection: intent.shortDirection ?? AUTOMATIC_SHORT_DIRECTION };
}

function fileIdentity(file: unknown, directory: string) {
  if (typeof file !== "string") throw new Error("Guided native inventory requires an admitted local path");
  const resolved = path.resolve(directory, file), canonical = realpathSync(resolved), info = lstatSync(canonical);
  if (canonical !== resolved || !info.isFile()) throw new Error("Guided native inventory path is not canonical");
  const sha256 = fileSha256(canonical);
  if (typeof sha256 !== "string" || !/^[a-f0-9]{64}$/u.test(sha256)) throw new Error("Guided native inventory lacks its admitted hash");
  return { path: canonical, sha256, sizeBytes: info.size };
}


function assertPacketManifest(packet: Record<string, unknown>, authority: GuidedNativeAuthority) {
  const manifest = authority.manifest, current = readCutPreviewObject(manifest.path);
  if (current.sha256 !== manifest.sha256 || canonicalJsonSha256(current.value) !== canonicalJsonSha256(manifest.value)
      || canonicalJsonSha256(packet.manifest) !== canonicalJsonSha256({ path: manifest.path,
        sha256: manifest.sha256, sizeBytes: current.sizeBytes })) throw new Error("Native request packet belongs to a different guided manifest");
  const admitted = manifest.value as unknown as AssetManifest;
  if (canonicalJsonSha256(packet.sources) !== canonicalJsonSha256(nativeShortSourceInventory(manifest.path, admitted))
      || canonicalJsonSha256(packet.availableSupportingAssets) !== canonicalJsonSha256(nativeShortSupportingInventory(manifest.path, admitted))) {
    throw new Error("Native request packet substituted the guided supplied inventory");
  }
  const admission = objectValue(manifest.value.sourceSetAdmission, "guided source-set admission");
  const receipt = fileIdentity(admission.receiptPath, path.dirname(manifest.path));
  if (receipt.sha256 !== admission.receiptSha256
      || canonicalJsonSha256(packet.admission) !== canonicalJsonSha256({ ...admission, receipt })) {
    throw new Error("Native request packet lost the guided source-set admission");
  }
}

/** Check before preparation and on both publication reads; a submitted packet is not authority. */
export function assertGuidedNativeAuthority(input: NativeShortProjectInput, authority: GuidedNativeAuthority): void {
  const ref = input.requestPacket;
  if (!ref) throw new Error("Guided native assembly requires its prepared request packet");
  if (!path.isAbsolute(ref.path) || realpathSync(ref.path) !== ref.path) throw new Error("Guided native request packet path is not canonical");
  const held = readCutPreviewObject(ref.path), packet = held.value;
  if (held.sha256 !== ref.sha256 || packet.schemaVersion !== 1
      || packet.scope !== "local-native-short-request-awaiting-editorial-strategy") throw new Error("Guided native request packet changed or has the wrong scope");
  const intent = normalizedIntent(authority.intent);
  if (canonicalJsonSha256(normalizedIntent(packet.intent)) !== canonicalJsonSha256(intent)) {
    throw new Error("Native request packet changed the authoritative guided intent");
  }
  assertNativeShortIntent(input, intent);
  assertPacketManifest(packet, authority);
}

/** Prepare against the actual guided manifest, including bootstrap inputs outside the default source folder. */
export function prepareGuidedNativeShortRequest(dir: string,
  dependencies: { readProposal?: typeof readGuidedTreatmentProposal } = {}) {
  const readProposal = dependencies.readProposal ?? readGuidedTreatmentProposal;
  const proposal = readProposal(dir), ctx = proposal.job.ctx;
  if (!nativeProposalPreparationAllowed(proposal.result)) throw new Error("Guided native preparation needs a supported native V9/V10 candidate");
  const result = prepareNativeShortRequest({ producerDir: ctx.dir, intent: ctx.intent,
    manifestPath: ctx.manifestPath, repo: process.cwd(), guidedProposal: guidedNativeRequestMarker(proposal) });
  const current = readProposal(dir);
  if (canonicalJsonSha256(current.job.ctx) !== canonicalJsonSha256(ctx)
      || canonicalJsonSha256(guidedNativeRequestMarker(current)) !== canonicalJsonSha256(guidedNativeRequestMarker(proposal))) {
    throw new Error("Guided proposal changed during native request preparation");
  }
  const packet = readCutPreviewObject(path.join(result.directory, "SHORT-REQUEST.json"));
  assertPacketManifest(packet.value, { intent: ctx.intent,
    manifest: { path: ctx.manifestPath, sha256: current.manifest.sha256, value: current.manifest.value } });
  return { ...result, proposalHash: proposal.proposalHash,
    ...("pendingRequirements" in proposal.result ? { pendingRequirements: proposal.result.pendingRequirements } : {}) };
}
