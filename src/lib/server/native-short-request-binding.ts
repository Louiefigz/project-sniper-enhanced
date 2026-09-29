/** Bind a native Short to the exact prepared request and its supplied inputs. */
import { readFileSync, realpathSync } from "node:fs";
import path from "node:path";
import { canonicalJsonSha256, fileSha256 } from "./auto-edit-hash";
import type { NativeAssetUseOptions } from "./native-short-asset-use";
import { assertNativeStyleApplication } from "./native-style-application";
import type { NativeShortProjectInput } from "./native-short-project";
import { AUTOMATIC_SHORT_DIRECTION, shortMediaPolicy } from "@/lib/producer/short-direction";
import { resolveLanes, validateIntent } from "@/lib/producer/intent-presets";
import { validateExternalAuthorization } from
  "@/app/api/producer/auto-edit/visual-plan-media-receipt";

interface FrozenPacketFile { path: string; sha256: string }
interface FrozenExternalMedia extends FrozenPacketFile {
  admissionReceipt: FrozenPacketFile;
  sourceSetEvidence: FrozenPacketFile;
  sourceSha256: string;
  authorizationEvidence: FrozenPacketFile | null;
}
interface NativeShortRequestPacket {
  [key: string]: unknown;
  schemaVersion: number;
  intent: ReturnType<typeof validateIntent>;
  sources: Array<FrozenPacketFile & { transcript: FrozenPacketFile | null }>;
  availableSupportingAssets: FrozenPacketFile[];
  availableExternalMedia?: FrozenExternalMedia[];
  selectedReferences: FrozenPacketFile[];
  relatedStyleContext: { source: FrozenPacketFile } | null;
}

export interface LegacyNativeShortReadAuthority {
  schemaVersion: 1;
  scope: "legacy-native-short-cold-read";
  projectPath: string;
  projectSha256: string;
  manifestSha256: string;
}

/** Current materialization cannot acquire legacy behavior by omitting its packet. */
export function assertCurrentNativeShortAuthority(input: NativeShortProjectInput): void {
  if (!input.requestPacket) {
    throw new Error("New native Short builds require the controller-prepared request packet; omission cannot select legacy behavior");
  }
}

/** Requestless historical bytes need an authority held outside the editable project. */
export function assertNativeShortReadAuthority(input: NativeShortProjectInput, directory: string,
  authority?: LegacyNativeShortReadAuthority): void {
  if (input.requestPacket) return;
  if (input.strategy.schemaVersion === 3) {
    throw new Error("Requestless native Short strategy version 3 has no historical read lane");
  }
  const projectPath = realpathSync(directory);
  const projectFile = path.join(projectPath, "SHORT-PROJECT.json");
  const manifestFile = path.join(projectPath, "PROJECT-MANIFEST.json");
  if (!authority || authority.schemaVersion !== 1 || authority.scope !== "legacy-native-short-cold-read"
      || authority.projectPath !== projectPath || authority.projectSha256 !== fileSha256(projectFile)
      || authority.manifestSha256 !== fileSha256(manifestFile)) {
    throw new Error("Historical requestless native Short requires external controller-owned cold-read authority");
  }
}

/** Prepared supplied-file identity cannot be broadened by an origin label. */
export function nativeAssetUseOptions(input: NativeShortProjectInput): NativeAssetUseOptions {
  const options: NativeAssetUseOptions = { required: input.strategy.schemaVersion === 3,
    expectedPolicy: shortMediaPolicy(input.request) };
  if (input.strategy.assetUse && input.strategy.schemaVersion !== 3) {
    throw new Error("Asset-use plans require native strategy version 3");
  }
  if (!input.requestPacket) return options;
  const ref = input.requestPacket;
  if (!path.isAbsolute(ref.path) || realpathSync(ref.path) !== ref.path
      || fileSha256(ref.path) !== ref.sha256) {
    throw new Error("Native request packet changed before asset-use validation");
  }
  const packet = JSON.parse(readFileSync(ref.path, "utf8")) as NativeShortRequestPacket;
  const supplied = [...packet.sources, ...(packet.availableSupportingAssets ?? [])];
  options.providedAssets = input.assets.filter(asset => supplied.some(row => row.path === asset.path
    && row.sha256 === asset.sha256)).map(({ file, sha256 }) => ({ file, sha256 }));
  return options;
}

/** Enforce the stored intent and resolved lane ownership at assembly time. */
export function assertNativeShortIntent(input: NativeShortProjectInput, authority: unknown): void {
  const intent = validateIntent(authority), lanes = resolveLanes(intent.scope, intent.lanes);
  if (intent.music) throw new Error("Native dialogue export cannot silently omit requested music");
  if (intent.audioEnhance?.preset !== input.audioFinishing?.audioEnhance?.preset) {
    throw new Error("Native audio enhancement must match the prepared request; requested cleanup cannot be omitted or substituted");
  }
  const generated = { captions: input.canvas.captionGroups.length > 0,
    graphics: input.canvas.text.length + input.canvas.shapes.length > 0 || !!input.extension?.markup,
    motion: input.canvas.motion.length > 0 || !!input.extension?.motion,
    broll: input.strategy.supportingSearch.candidates.some(row => row.selected)
      || !!input.strategy.assetUse?.decisions.some(row => row.decision === "insert") };
  for (const [lane, used] of Object.entries(generated)) {
    if (used && lanes[lane as keyof typeof generated] !== "auto") {
      throw new Error(`Native project cannot override ${lane} lane ownership`);
    }
  }
  if (intent.mode !== "short" || canonicalJsonSha256(intent.shortDirection ?? AUTOMATIC_SHORT_DIRECTION)
      !== canonicalJsonSha256(input.request)) {
    throw new Error("Native plan changed the prepared style request or media policy");
  }
}

function verifyPacketInputs(input: NativeShortProjectInput, packet: NativeShortRequestPacket): void {
  for (const asset of input.assets.filter((row) => row.role === "source")) {
    if (!packet.sources.some((row: { sha256: string; path: string }) =>
      row.sha256 === asset.sha256 && row.path === asset.path)) {
      throw new Error("Native plan substituted the prepared source inventory");
    }
  }
  for (const source of packet.sources) {
    if (source.transcript && fileSha256(source.transcript.path) !== source.transcript.sha256) {
      throw new Error("Prepared transcript changed");
    }
  }
  for (const asset of packet.availableSupportingAssets ?? []) {
    if (asset.sha256 && fileSha256(asset.path) !== asset.sha256) {
      throw new Error("Prepared supplied B-roll changed");
    }
  }
  for (const asset of packet.availableExternalMedia ?? []) {
    if (asset.sha256 && fileSha256(asset.path) !== asset.sha256) {
      throw new Error("Prepared external-media inventory changed");
    }
    if (!asset.admissionReceipt || fileSha256(asset.admissionReceipt.path)
        !== asset.admissionReceipt.sha256) {
      throw new Error("Prepared external-media admission receipt changed");
    }
    if (!asset.sourceSetEvidence || fileSha256(asset.sourceSetEvidence.path)
        !== asset.sourceSetEvidence.sha256) {
      throw new Error("Prepared external-media source-set receipt changed");
    }
    if (asset.authorizationEvidence) {
      validateExternalAuthorization(asset.authorizationEvidence.path,
        asset.authorizationEvidence.sha256, asset.sourceSha256);
    }
  }
  for (const selected of packet.selectedReferences ?? []) {
    if (!path.isAbsolute(selected.path) || realpathSync(selected.path) !== selected.path
        || fileSha256(selected.path) !== selected.sha256) {
      throw new Error("Prepared selected-reference evidence changed");
    }
  }
}

/** Re-read the request, references, transcripts, group context, and style binding. */
export function verifyNativeShortRequest(input: NativeShortProjectInput, html?: string): void {
  if (!input.requestPacket) {
    if (input.strategy.styleApplication) throw new Error("Style application requires a prepared request packet");
    return;
  }
  const ref = input.requestPacket;
  if (!path.isAbsolute(ref.path) || realpathSync(ref.path) !== ref.path
      || fileSha256(ref.path) !== ref.sha256) {
    throw new Error("Native request packet changed before strategy execution");
  }
  const packet = JSON.parse(readFileSync(ref.path, "utf8")) as NativeShortRequestPacket;
  assertNativeShortIntent(input, packet.intent);
  if (["produced", "full"].includes(packet.intent?.scope)
      && (!input.visualPlan || !input.strategy.visualPlanApplication)) {
    throw new Error("New produced/full Native Short requires its visual plan and execution application");
  }
  if (packet.schemaVersion !== 1
      || canonicalJsonSha256(packet.intent.shortDirection) !== canonicalJsonSha256(input.request)) {
    throw new Error("Native plan changed the prepared style request");
  }
  verifyPacketInputs(input, packet);
  if (packet.relatedStyleContext) {
    const source = packet.relatedStyleContext.source;
    if (!source || !path.isAbsolute(source.path) || realpathSync(source.path) !== source.path
        || fileSha256(source.path) !== source.sha256) {
      throw new Error("Prepared related-style context changed");
    }
  }
  if (html !== undefined) assertNativeStyleApplication({ application: input.strategy.styleApplication,
    packet, requestPath: ref.path, html, scenes: input.strategy.scenes,
    catalogFiles: input.catalogFiles });
}
