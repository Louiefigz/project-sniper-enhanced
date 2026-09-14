/** Prepare a local brief for the edit brain without invoking a provider. */
import { existsSync, lstatSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import path from "node:path";
import { canonicalJson, canonicalJsonSha256, fileSha256 } from "./auto-edit-hash";
import { loadDirectorCatalog, directorCatalogHash } from "./native-director-library";
import { AUTOMATIC_SHORT_DIRECTION, shortDirectionInstructions } from "@/lib/producer/short-direction";
import { validateIntent } from "@/lib/producer/intent-presets";
import { requireSourceSetAdmission, type AssetManifest } from "@/lib/producer/types";
import type { GuidedNativeRequestMarker } from "./guided-native-binding";

function observed(file: string) {
  const actual = realpathSync(file), info = lstatSync(actual);
  if (!info.isFile()) throw new Error("Native brief input must be a regular file");
  return { path: actual, sha256: fileSha256(actual), sizeBytes: info.size };
}

/** Full footage/transcript inventory is available even when separate B-roll is absent. */
export function nativeShortSourceInventory(manifestPath: string, manifest: AssetManifest) {
  if (!Array.isArray(manifest.sources) || !manifest.sources.length || manifest.sources.length > 64) throw new Error("Short brief needs admitted source footage");
  return manifest.sources.map((source) => {
    const file = observed(source.path);
    if (!source.sourceSha256 || source.sourceSha256 !== file.sha256) throw new Error("Short source changed since ingest");
    const transcript = source.transcriptPath ? observed(path.resolve(path.dirname(manifestPath), source.transcriptPath)) : null;
    return { id: source.id, ...file, duration: source.duration, resolution: source.resolution, fps: source.fps,
      transcript, visualInspection: "pending", searchScope: "entire-admitted-source-including-outside-dialogue-cuts" };
  });
}

/** Freeze supplied supplemental bytes too; cached web media is not a supplied-file claim. */
export function nativeShortSupportingInventory(manifestPath: string, manifest: AssetManifest) {
  if (!Array.isArray(manifest.broll) || manifest.broll.length > 128) throw new Error("Invalid supplied B-roll inventory");
  return manifest.broll.map(asset => {
    if (typeof asset.path !== "string") throw new Error("Supplied B-roll requires a local admitted file");
    const file = observed(path.resolve(path.dirname(manifestPath), asset.path));
    if (asset.sourceSha256 !== file.sha256) throw new Error("Supplied B-roll changed since ingest or lacks its source hash");
    return { ...asset, ...file, visualInspection: "pending" };
  });
}

/** Available reference cases are retrieval context; the brain must inspect the actual frames. */
function referenceInventory(repo: string) {
  const root = path.join(repo, "docs/studies/shorts-visual-playbook");
  const files = ["FORMAT_FOUNDATIONS.md", "authentic-expansion/CATALOG_MAP.md", "entries/A02.md",
    "nate-sequences/cases/N27.md", "nate-sequences/cases/N26.md", "authentic-expansion/cases/CR07.md"];
  return files.map((file) => ({ ...observed(path.join(root, file)), purpose: file.includes("FORMAT")
    ? "Choose the viewing need and format; follow linked cases and contrasting examples"
    : "Starting reference context; inspect its cited individual images before adapting" }));
}

function handoff(directory: string, intent: ReturnType<typeof validateIntent>, guided?: GuidedNativeRequestMarker) {
  return `Make a native 9:16 Short from this local request: ${path.join(directory, "SHORT-REQUEST.json")}.
${shortDirectionInstructions(intent.shortDirection)}
Read the transcript and inspect the supplied footage and linked reference frames before deciding the cut, title, geometry or supporting shots. Reuse current transcripts and the shared caption grouper. Preserve exact kept-word/source timing. Fill the canonical Director template and explain why the hook makes the viewer want the payoff. Write the source-bound strategy version 3 with its measured and editorial pacing record and NativeShortProjectInput plan before building.
${guided ? `Save the visual-plan JSON with candidateHash, project and explicit assetResolutions [{sceneId,assetId,decisionId}]. Use node --import tsx scripts/producer/native-short.ts build-guided ${guided.producerDir} <visual-plan.json> for leased assembly against this current proposal; every required image must resolve before project publication.` : "Use scripts/producer/native-short.ts build for assembly"}${guided ? " Use" : " and"} studio/native_short_export.py for the local render, shared audio delivery, native capture/seek and encoded-picture checks. Keep this request's hash/source pins bound to the plan. Retain all failures and report stage times, memory, actual coverage and remaining human review.
This packet authorizes no new provider transmission. Apply the user's current model/media permissions. Automatic means the edit brain selects the treatment; it is not a fixed layout preset.`;
}

/** Write a content-addressed request packet. It does not claim strategy or media work is done. */
export function prepareNativeShortRequest(input: { producerDir: string; intent: unknown; repo: string; manifestPath?: string; guidedProposal?: GuidedNativeRequestMarker }) {
  const intent = validateIntent(input.intent);
  if (intent.mode !== "short") throw new Error("Native Short request requires short mode");
  const root = realpathSync(path.dirname(input.producerDir));
  const manifestPath = input.manifestPath ?? path.join(root, "source/asset_manifest.json");
  if (!path.isAbsolute(manifestPath) || realpathSync(manifestPath) !== manifestPath) throw new Error("Native request manifest path must be canonical");
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as AssetManifest;
  const admission = requireSourceSetAdmission(manifest);
  const receipt = observed(path.resolve(path.dirname(manifestPath), admission.receiptPath));
  if (receipt.sha256 !== admission.receiptSha256) throw new Error("Source-set admission receipt changed");
  const catalog = loadDirectorCatalog(), request = intent.shortDirection ?? AUTOMATIC_SHORT_DIRECTION;
  const packet = { schemaVersion: 1, scope: "local-native-short-request-awaiting-editorial-strategy", intent: { ...intent, shortDirection: request },
    ...(input.guidedProposal ? { guidedProposal: input.guidedProposal } : {}),
    manifest: observed(manifestPath), admission: { ...admission, receipt },
    sources: nativeShortSourceInventory(manifestPath, manifest), availableSupportingAssets: nativeShortSupportingInventory(manifestPath, manifest),
    editorialInstructions: shortDirectionInstructions(request),
    references: referenceInventory(input.repo), directorLibraryHash: directorCatalogHash(catalog),
    stages: ["inspect-source-and-references", "select-retained-passage", "inspect-retained-dialogue", "map-script-and-delivery-pacing",
      "choose-visual-representation", "plan-scenes-and-treatment", "scout-supporting-shots", "assemble", "export-and-check", "human-review"],
    providerCalls: 0, generatedMediaCalls: 0 };
  const hash = canonicalJsonSha256(packet), parent = path.join(input.producerDir, "native-shorts/requests"), directory = path.join(parent, hash);
  mkdirSync(parent, { recursive: true, mode: 0o700 });
  if (realpathSync(parent) !== parent) throw new Error("Native request directory must be canonical");
  const files = { "SHORT-REQUEST.json": canonicalJson(packet), "DIRECTOR-LIBRARY.json": canonicalJson(catalog), "AGENT-BRIEF.md": handoff(directory, intent, input.guidedProposal) };
  if (!existsSync(directory)) mkdirSync(directory, { mode: 0o700 });
  for (const [name, content] of Object.entries(files)) {
    const file = path.join(directory, name);
    if (existsSync(file)) {
      if (readFileSync(file, "utf8") !== content) throw new Error("Stored native Short request changed");
    } else writeFileSync(file, content, { flag: "wx", mode: 0o600 });
  }
  return { status: "ready-for-local-strategy", directory, requestHash: hash, request,
    handoff: files["AGENT-BRIEF.md"], sourceCount: packet.sources.length, providerCalls: 0 };
}
