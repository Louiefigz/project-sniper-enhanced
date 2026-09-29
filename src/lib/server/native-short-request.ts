import { nativeReferenceInputs } from "./longform-reference-inputs";
import { resolveReferenceContext } from "@/app/api/producer/auto-edit/saved-plan-request";
import { parseAutoEditIntent } from "@/app/api/producer/auto-edit/stream";
import { nativeCatalogInventory } from "./native-catalog-inventory";
import { VISUAL_SOURCE_INSTRUCTIONS } from "@/lib/producer/visual-source-policy";
/** Prepare a local brief for the edit brain without invoking a provider. */
import { existsSync, lstatSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { SHORTS_LIBRARY } from "./reference-library-paths";
import path from "node:path";
import { canonicalJson, canonicalJsonSha256, fileSha256 } from "./auto-edit-hash";
import { loadDirectorCatalog, directorCatalogHash } from "./native-director-library";
import { AUTOMATIC_SHORT_DIRECTION, shortDirectionInstructions } from "@/lib/producer/short-direction";
import { validateIntent } from "@/lib/producer/intent-presets";
import { requireSourceSetAdmission, type AssetManifest } from "@/lib/producer/types";
import type { GuidedNativeRequestMarker } from "./guided-native-binding";
import { loadNativeRelatedStyleContext } from "./native-related-style-context";
import { validateExternalAuthorization } from
  "@/app/api/producer/auto-edit/visual-plan-media-receipt";
import { assertManifestExternalOrigins } from "./external-media-origin";

function observed(file: string) {
  const actual = realpathSync(file), info = lstatSync(actual);
  if (!info.isFile()) throw new Error("Native brief input must be a regular file");
  const sha256 = fileSha256(actual);
  if (!sha256) throw new Error("Native brief input disappeared during inspection");
  return { path: actual, sha256, sizeBytes: info.size };
}

function externalAuthorization(manifestPath: string, asset: Record<string, unknown>,
  sourceSha256: string) {
  const value = asset.authorizationEvidence;
  if (value === undefined || value === null) return null;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("External-media authorization evidence is malformed");
  }
  const pin = value as Record<string, unknown>;
  if (Object.keys(pin).sort().join("\0") !== "path\0sha256"
      || typeof pin.path !== "string" || typeof pin.sha256 !== "string") {
    throw new Error("External-media authorization evidence is malformed");
  }
  const receipt = observed(path.resolve(path.dirname(manifestPath), pin.path));
  if (receipt.sha256 !== pin.sha256) throw new Error("External-media authorization changed");
  validateExternalAuthorization(receipt.path, receipt.sha256, sourceSha256);
  return { path: receipt.path, sha256: receipt.sha256 };
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

/** Freeze external inventory without turning technical admission into use authority. */
export function nativeShortExternalInventory(manifestPath: string, manifest: AssetManifest) {
  assertManifestExternalOrigins(manifestPath, manifest);
  const assets = manifest.externalMedia ?? [];
  if (!Array.isArray(assets) || assets.length > 128) throw new Error("Invalid external-media inventory");
  const directory = path.dirname(manifestPath);
  const sourceSet = requireSourceSetAdmission(manifest);
  const sourceSetReceipt = observed(path.resolve(directory, sourceSet.receiptPath));
  if (sourceSetReceipt.sha256 !== sourceSet.receiptSha256) {
    throw new Error("External-media source-set receipt changed");
  }
  return assets.map((asset, index) => {
    const label = `externalMedia[${index}]`;
    if (typeof asset.id !== "string" || !asset.id || typeof asset.path !== "string"
        || typeof asset.originalPath !== "string" || !path.isAbsolute(asset.originalPath)
        || typeof asset.sourceSha256 !== "string" || typeof asset.sourceSizeBytes !== "number"
        || typeof asset.admissionReceiptPath !== "string"
        || typeof asset.admissionReceiptSha256 !== "string") {
      throw new Error(`${label} lacks exact admitted external-media identity`);
    }
    const file = observed(path.resolve(directory, asset.path));
    if (asset.sourceSha256 !== file.sha256 || asset.sourceSizeBytes !== file.sizeBytes) {
      throw new Error(`${label} changed since ingest`);
    }
    const receipt = observed(path.resolve(directory, asset.admissionReceiptPath));
    if (asset.admissionReceiptSha256 !== receipt.sha256) {
      throw new Error(`${label} admission receipt changed`);
    }
    const authorizationEvidence = externalAuthorization(
      manifestPath, asset, file.sha256);
    return { ...asset, ...file, modality: "external-media" as const,
      recordId: asset.id, sourceSha256: file.sha256, sourceSizeBytes: file.sizeBytes,
      sourceSetLane: "external" as const, sourceSetEvidence: receipt,
      admissionReceipt: receipt, authorizationEvidence,
      availability: authorizationEvidence
        ? "controller-authorized-for-local-review" as const
        : "prerequisite-awaiting-controller-authorization" as const };
  });
}

/** Available reference cases are retrieval context; the brain must inspect the actual frames. */
function referenceInventory(repo: string) {
  const root = path.join(repo, SHORTS_LIBRARY);
  const files = ["FORMAT_FOUNDATIONS.md", "expansion/CATALOG_MAP.md", "entries/ME02.md",
    "sequences/cases/SQ01.md", "sequences/cases/SQ02.md", "expansion/cases/DV01.md"];
  return files.map((file) => ({ ...observed(path.join(root, file)), purpose: file.includes("FORMAT")
    ? "Choose the viewing need and format; follow linked cases and contrasting examples"
    : "Starting reference context; inspect its cited individual images before adapting" }));
}

function handoff(directory: string, intent: ReturnType<typeof validateIntent>, guided?: GuidedNativeRequestMarker) {
  return `${VISUAL_SOURCE_INSTRUCTIONS}
Make a native 9:16 Short from this local request: ${path.join(directory, "SHORT-REQUEST.json")}.
${shortDirectionInstructions(intent.shortDirection)}
Read the complete CATALOG-INDEX.json and inspect candidate source files. Stage selected catalog adaptations using catalogFiles and mount them with data-composition-src; pin the upstream source hash and local implementation hash. Record current visualSources decisions for every canvas visual and extension. See docs/producer/VISUAL_SOURCE_POLICY.md for the receipt contract.
Read the transcript and inspect the supplied footage and linked reference frames before deciding the cut, title, geometry or supporting shots. Reuse current transcripts and the shared caption grouper. Preserve exact kept-word/source timing. Select a catalog title using catalogTitle and its mounted catalogFiles component, fill the canonical Director copy template, and explain why the hook makes the viewer want the payoff. Write the source-bound strategy version 3 with its measured and editorial pacing record and NativeShortProjectInput plan before building.
SHORT-REQUEST.json carries availableExternalMedia as controller inventory only. Those rows remain planning prerequisites unless the current visual-plan mediaAuthority supplies matching non-null controller authorization evidence; source-set or per-file admission never proves publication rights. Public-web discovery does not populate this inventory. The supported flow is identify, capture with origin evidence, place the reviewed bytes under external-media/, re-ingest, materialize a fresh visual context, and re-plan.
For a new produced/full edit, first save the accepted cut as producer/edit_plan.json and run ./sniper node --import tsx scripts/producer/visual-plan-context.ts <producer-dir>. Search the complete frozen catalog with ordinary_visual_plan_search.py, then author and allocate VISUAL-PLAN.json through scripts/producer/planner/visual_plan_cli.py. Use catalog_receipt_issuer_cli.py to satisfy required static source inspection for catalog candidates; it records unresolved dependency work but never executes catalog HTML or clears runtime qualification. Preserve its printed receipt authority through validate, fingerprints and binding. A source-present reference may then be selected as an adaptation candidate, but its whole-project route must be native-short and the project must stage a distinct project-owned implementation for the native gates. Run the CLI binding command and copy that exact binding, including catalogReceiptAuthority when present, into NativeShortProjectInput.visualPlan; the project writer freezes the same bytes and rejects drift. Add strategy.visualPlanApplication with every allocated opportunity/candidate in allocation order, its exact frame window and overlapping scene indexes, the executable visible IDs, and exact staged catalog bindings. The project writer rejects missing, partial, substituted or timing-inconsistent execution. Existing projects and bounded revisions without this artifact retain their current behavior.
When SELECTED-REFERENCE-VOCABULARY.json exists, treat it as planning research: identify each scene's viewer need, compare the inspected contenders in the matching family, and adapt the strongest supported option. Record a stable choiceId for every selected treatment; a scene may have more than one choice when it combines separate cards, transitions or text mechanisms. Preserve stable traits while varying flexible traits only when the new information benefits. Record the family, contender, composition anatomy, configuration, considered alternatives and any intentional signature/callback repetition. Do not pad a family, rotate effects arbitrarily or claim style/quality approval. When the file is absent, make no vocabulary-grounding claim.
When RELATED-STYLE-CONTEXT.json exists, honor its frozen group allocation or completed predecessor applications. Its choices explicitly use choiceKind vocabulary with familyId/contenderRef or choiceKind supplemental with catalogId; both carry anatomy, configuration and development, and a valid group may contain no vocabulary-derived choices. Compare composition and information development for every applicable sibling choice. Keep an intentional signature/callback only with a reason; do not call a different component ID meaningful variation when its composition and development are the same. Bind the exact related context and record every required comparison in styleApplication. Do not infer related work from global history.
Scout actual assets before committing the complete scene plan. Check every retained beat, exact source/cue, crop/layout, text lifetime, transition and hold against the brief, available footage and execution feasibility. A separate reviewer must inspect the current full plan, actual catalog implementations and source/reference images; visualSourceSelection must assess authentic catalog reuse and whether each reference/custom exception is justified, resolve material issues, and save a NativePrebuildReview receipt using src/lib/server/native-short-prebuild-review.ts: scope native-short-full-plan, nativeShortPrebuildPlanHash(project), reviewer provenance, every coverage assessment (reasoned not-applicable is allowed), pinned evidence and a ProducerReview stage plan/pass with zero material issues. Bind its canonical local path and byte SHA-256 as project.prebuildReview. Local strategy.review findings and an opening-only Director critique do not satisfy this gate. Any authored asset, cue, crop, motion or transition revision needs a fresh review. Only generated preparedSources/guidedBinding and the receipt reference are excluded from the creative hash; their existing validators remain mandatory. Recorded independence is a reviewer declaration, not cryptographic proof or a finished-playback claim. Standalone prepare-media may establish source feasibility but cannot claim a completed edit.
${guided ? `Save the visual-plan JSON with candidateHash, project and explicit assetResolutions [{sceneId,assetId,decisionId}]. Use node --import tsx scripts/producer/native-short.ts build-guided ${guided.producerDir} <visual-plan.json> for leased assembly against this current proposal; every required image must resolve before project publication.` : "Use scripts/producer/native-short.ts build for assembly"}${guided ? " Use" : " and"} studio/native_short_export.py for the local render, shared audio delivery, native capture/seek and encoded-picture checks. Keep this request's hash/source pins bound to the plan. Retain all failures and report stage times, memory, actual coverage and remaining human review.
The successful native exporter automatically records the checked visual allocation for future repetition control. If it reports a visual-usage-registration failure, preserve the export and recover with ./sniper node --import tsx scripts/producer/visual-plan-usage.ts register <producer-dir> <native-project> <checked-export>. The receipt sets humanApprovalClaim false and does not replace playback, the editable Studio handoff or human approval.
This packet authorizes no new provider transmission. Apply the user's current model/media permissions. Automatic means the edit brain selects the treatment; it is not a fixed layout preset.`;
}

function writeRequestFile(directory: string, name: string, content: string) {
  const file = path.join(directory, name);
  if (!existsSync(file)) {
    writeFileSync(file, content, { flag: "wx", mode: 0o600 });
    return;
  }
  if (readFileSync(file, "utf8") !== content) throw new Error("Stored native Short request changed");
}

/** Write a content-addressed request packet. It does not claim strategy or media work is done. */
export function prepareNativeShortRequest(input: { producerDir: string; intent: unknown; repo: string;
  manifestPath?: string; guidedProposal?: GuidedNativeRequestMarker; relatedStyleContextPath?: string }) {
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
  const visualCatalog = nativeCatalogInventory();
  const selected = nativeReferenceInputs(resolveReferenceContext(parseAutoEditIntent(intent as unknown as Record<string, unknown>)));
  const related = input.relatedStyleContextPath ? loadNativeRelatedStyleContext(input.relatedStyleContextPath) : null;
  if (related && selected.selected?.styleVocabularyAvailable !== true) {
    throw new Error("Related style planning requires a current selected reference vocabulary");
  }
  const packet = { catalog: { file: "CATALOG-INDEX.json", digest: canonicalJsonSha256(visualCatalog), total: visualCatalog.total }, schemaVersion: 1, scope: "local-native-short-request-awaiting-editorial-strategy", intent: { ...intent, shortDirection: request },
    ...(input.guidedProposal ? { guidedProposal: input.guidedProposal } : {}),
    manifest: observed(manifestPath), admission: { ...admission, receipt },
    sources: nativeShortSourceInventory(manifestPath, manifest), availableSupportingAssets: nativeShortSupportingInventory(manifestPath, manifest),
    availableExternalMedia: nativeShortExternalInventory(manifestPath, manifest),
    editorialInstructions: shortDirectionInstructions(request),
    selectedReference: selected.selected, selectedReferences: selected.pins.map(({ path, sha256 }) => ({ path, sha256 })),
    relatedStyleContext: related ? { source: related.source, groupId: related.record.groupId,
      currentOutputId: related.record.currentOutputId, referenceId: related.record.referenceId,
      vocabularySha256: related.record.vocabularySha256, planningMode: related.record.planningMode } : null,
    references: referenceInventory(input.repo), directorLibraryHash: directorCatalogHash(catalog),
    stages: ["inspect-source-and-references", "select-retained-passage", "inspect-retained-dialogue", "map-script-and-delivery-pacing",
      "choose-visual-representation", "scout-supporting-shots", "plan-scenes-and-treatment", "check-full-plan-feasibility",
      "independent-current-plan-review", "assemble", "export-and-check", "human-review"],
    providerCalls: 0, generatedMediaCalls: 0 };
  const hash = canonicalJsonSha256(packet), parent = path.join(input.producerDir, "native-shorts/requests"), directory = path.join(parent, hash);
  mkdirSync(parent, { recursive: true, mode: 0o700 });
  if (realpathSync(parent) !== parent) throw new Error("Native request directory must be canonical");
  const files = { ...selected.files,
    ...(related ? { "RELATED-STYLE-CONTEXT.json": canonicalJson(related.record) } : {}),
    "CATALOG-INDEX.json": canonicalJson(visualCatalog), "SHORT-REQUEST.json": canonicalJson(packet),
    "DIRECTOR-LIBRARY.json": canonicalJson(catalog), "AGENT-BRIEF.md": handoff(directory, intent, input.guidedProposal) };
  if (!existsSync(directory)) mkdirSync(directory, { mode: 0o700 });
  for (const [name, content] of Object.entries(files)) {
    writeRequestFile(directory, name, content);
  }
  return { status: "ready-for-local-strategy", directory, requestHash: hash, request,
    handoff: files["AGENT-BRIEF.md"], sourceCount: packet.sources.length, providerCalls: 0 };
}
