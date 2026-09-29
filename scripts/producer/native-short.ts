import { assertNativeMotionReviews } from "../../src/lib/server/native-motion-review";
/** Local native Shorts entry point; this command never invokes a model/provider. */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { assembleNativeShortHtml, readNativeShortProject, writeNativeShortProject } from "../../src/lib/server/native-short-project";
import { prepareNativeSourceMedia } from "../../src/lib/server/native-selected-sources";
import { assertNativeShortPrebuildReview, assertNativeLongPrebuildReview, assertNativeLongSectionPrebuildReview, nativeShortPrebuildPlanHash } from "../../src/lib/server/native-short-prebuild-review";
import { prepareNativeShortRequest } from "../../src/lib/server/native-short-request";
import { storedAutoEditIntent } from "../../src/app/api/producer/auto-edit/operator-intent-authority";
import { measureNativeShortPacing, nativePacingBindings, nativePacingVisualWindows } from "../../src/lib/server/native-short-pacing-observations";
import { buildNativeCanvas } from "../../src/lib/server/native-short-composition";
import { nativeAssetUseRevisionHash } from "../../src/lib/server/native-short-asset-use";
import { nativeStoryRevisionHash } from "../../src/lib/server/native-short-story";
import { bindNativeWebOrigin, writeNativeAssetOrigin } from "../../src/lib/server/native-short-asset-origin";
import { prepareGuidedNativeShortRequest } from "../../src/lib/server/guided-native-authority";
import { buildGuidedNativeProject, parseGuidedNativeVisualPlan } from "../../src/lib/server/guided-native-build";
import { observeCutPreviewFile } from "../../src/app/api/producer/auto-edit/cut-preview-receipt";
import { MAX_TREATMENT_REQUEST_BYTES, parseTreatmentRequestJson } from "./guided-treatment-json";
import { prepareNativeLongformRequest, checkNativeLongformRequest } from "../../src/lib/server/native-longform-request";
import { prepareNativeRelatedStyleGroup } from "../../src/lib/server/native-related-style-group";
import { inspectExternalMediaOrigin } from "../../src/lib/server/external-media-origin";
import { assertNativeBuildAuthority, nativeDraftCheck } from "../../src/lib/server/native-short-draft";
import { nativeShortLineage } from "../../src/lib/server/native-short-lineage";
import { stampStudioHostIds } from "../../src/lib/server/native-studio-host-stamp";
import { assertNativeRevealDeclarations } from "../../src/lib/server/native-reveal-declarations";
import { nativeCatalogFiles } from "../../src/lib/server/native-catalog-files";

const USAGE = "Usage: native-short.ts prepare <producer-directory> [--manifest <canonical asset_manifest.json>] | prepare-guided|prepare-longform <producer-directory> | prepare-related <producer-directory> <related-context.json> | prepare-related-group <group-draft.json> <new-group-directory> | check-longform <request-directory> | inspect-origin <external-media/ASSET.json> | prepare-media <plan.json> <new-media-directory> | build-guided <producer-dir> <visual-plan.json> | measure <plan.json> | build|build-draft <plan.json> <new-project> [--parent <project>] | check|check-export|check-draft <project> | check-long-review <review.json> <plan-hash> | check-long-section-review <review.json> <scope-hash> | origin|origin-web <input.json> <new-receipt.json> | studio-ids <authored.html> <new.html>";
/** Fixed in-process test seam only; parsed input cannot replace a service. */
export const nativeShortCommandServices = { buildGuided: buildGuidedNativeProject };

function guidedVisual(file: string) {
  if (!file || file.length > 4096 || /[\0\r\n]/u.test(file)) throw new Error("Guided visual plan path is invalid");
  const held = observeCutPreviewFile(path.resolve(file), MAX_TREATMENT_REQUEST_BYTES, true);
  return parseGuidedNativeVisualPlan(parseTreatmentRequestJson(new TextDecoder("utf-8", { fatal: true }).decode(held.bytes)));
}

/** Per-clip producer folders whose default source/asset_manifest.json is absent or linked name the
 * admitted manifest explicitly; prepareNativeShortRequest applies the same canonical/admission checks. */
function prepareWithManifest(producer: string, manifest: string) {
  const producerDir = path.resolve(producer);
  return prepareNativeShortRequest({ producerDir, intent: storedAutoEditIntent(producerDir), repo: process.cwd(),
    manifestPath: path.resolve(manifest) });
}

function executeOperation(operation: string, input: string, destination: string, parent?: string) {
  if (operation === "prepare-related-group") {
    return prepareNativeRelatedStyleGroup(path.resolve(input), path.resolve(destination), process.cwd());
  }
  if (operation === "prepare-longform") return prepareNativeLongformRequest(path.resolve(input), process.cwd());
  if (operation === "check-longform") return checkNativeLongformRequest(path.resolve(input));
  if (operation === "inspect-origin") return inspectExternalMediaOrigin(path.resolve(input));
  if (operation === "prepare" || operation === "prepare-related") {
    const producerDir = path.resolve(input);
    return prepareNativeShortRequest({ producerDir, intent: storedAutoEditIntent(producerDir), repo: process.cwd(),
      ...(operation === "prepare-related" ? { relatedStyleContextPath: path.resolve(destination) } : {}) });
  } else if (operation === "prepare-guided") {
    return prepareGuidedNativeShortRequest(path.resolve(input));
  } else if (operation === "build-guided") {
    if (input.length > 4096 || /[\0\r\n]/u.test(input)) throw new Error("Guided producer directory path is invalid");
    return nativeShortCommandServices.buildGuided({ dir: path.resolve(input), visual: guidedVisual(destination) });
  } else if (operation === "measure") {
    const plan = JSON.parse(readFileSync(path.resolve(input), "utf8"));
    return { status: "observations-awaiting-editorial-pacing", ...nativePacingBindings(plan),
      prebuildPlanHash: nativeShortPrebuildPlanHash(plan), assetUseRevisionHash: nativeAssetUseRevisionHash(plan),
      storyRevisionHash: nativeStoryRevisionHash(plan), observations: measureNativeShortPacing(plan.canvas),
      visualWindows: nativePacingVisualWindows(plan, buildNativeCanvas(plan.canvas) + (plan.extension?.markup ?? "")),
      revealDeclarations: assertNativeRevealDeclarations(plan, nativeCatalogFiles(plan.catalogFiles)) };
  } else if (operation === "origin" || operation === "origin-web") {
    const record = JSON.parse(readFileSync(path.resolve(input), "utf8"));
    return operation === "origin" ? writeNativeAssetOrigin(record, destination) : bindNativeWebOrigin(record, destination);
  } else if (operation === "build" || operation === "build-draft" || operation === "prepare-media") {
    if (existsSync(path.resolve(destination))) throw new Error("Native build needs a new destination");
    const original = JSON.parse(readFileSync(path.resolve(input), "utf8"));
    // build requires a passing review; build-draft records the actual findings or pending review.
    const draft = operation === "prepare-media" ? undefined : assertNativeBuildAuthority(operation, original);
    if (parent) nativeShortLineage(parent, directory => readNativeShortProject(directory, {}, undefined, "draft"));
    const plan = prepareNativeSourceMedia(original, assembleNativeShortHtml(original),
      operation === "prepare-media" ? destination : `${destination}.sources`);
    if (operation === "prepare-media") return { status: "selected-sources-ready", preparedSources: plan.preparedSources,
      plan: original.preparedSources ? path.resolve(input) : path.resolve(destination, "prepared-plan.json") };
    if (draft) return { status: "built-review-draft-awaiting-native-qc", reviewState: "draft",
      ...writeNativeShortProject({ ...plan, draft }, destination, {}, { parent }) };
    return { status: "built-awaiting-native-qc", ...writeNativeShortProject(plan, destination, {}, { parent }) };
  }
  const plan = readNativeShortProject(path.resolve(input));
  return { status: "project-current", totalFrames: plan.canvas.totalFrames,
    request: plan.request, selectedTreatment: plan.strategy.selectedTreatment,
    prebuildReview: plan.prebuildReview ? "recorded-independent-plan-pass-not-playback-approval" : "legacy-unreviewed",
    story: plan.strategy.story ? "authored-obligations-checked-awaiting-whole-story-review" : "unplanned",
    assetUse: plan.strategy.assetUse ? "source-bound-decisions-checked-awaiting-editorial-review" : "legacy-unplanned",
    pacing: plan.strategy.pacing ? "declared-budgets-checked-awaiting-playback-review" : "legacy-unplanned" };
}

export async function executeNativeShortCommand(argv: string[]) {
  const [operation, input, destination] = argv;
  if (operation === "check-motion-reviews" && argv.length === 3) return assertNativeMotionReviews(path.resolve(input), path.resolve(destination));
  if (operation === "check-long-review" && argv.length === 3) return assertNativeLongPrebuildReview(path.resolve(input), destination);
  if (operation === "check-long-section-review" && argv.length === 3) return assertNativeLongSectionPrebuildReview(path.resolve(input), destination);
  if (operation === "check-export" && argv.length === 2) {
    const plan = readNativeShortProject(path.resolve(input));
    return assertNativeShortPrebuildReview(plan);
  }
  if (operation === "check-draft" && argv.length === 2) {
    return nativeDraftCheck(readNativeShortProject(path.resolve(input), {}, undefined, "draft"));
  }
  if (operation === "--help" && argv.length === 1) return { usage: USAGE };
  if (operation === "studio-ids" && argv.length === 3) {  // before hashing: Studio rewrites files that lack them
    const stamped = stampStudioHostIds(readFileSync(path.resolve(input), "utf8"));
    writeFileSync(path.resolve(destination), stamped, { flag: "wx", mode: 0o600 });
    return { status: "studio-ids-stamped", output: path.resolve(destination) };
  }
  if (operation === "prepare" && argv.length === 4 && argv[2] === "--manifest") return prepareWithManifest(input, argv[3]);
  if ((operation === "build" || operation === "build-draft") && argv.length === 5 && argv[3] === "--parent") {
    return executeOperation(operation, input, destination, path.resolve(argv[4]));
  }
  const withDestination = ["prepare-related", "prepare-related-group", "prepare-media", "build", "build-draft", "build-guided", "origin", "origin-web"].includes(operation);
  if (!input || !["prepare", "prepare-related", "prepare-related-group", "prepare-guided", "prepare-longform", "check-longform", "inspect-origin", "prepare-media", "measure", "build", "build-draft", "build-guided", "check", "origin", "origin-web"].includes(operation)
      || argv.length !== (withDestination ? 3 : 2)) throw new Error(USAGE);
  return executeOperation(operation, input, destination);
}

if (require.main === module) executeNativeShortCommand(process.argv.slice(2))
  .then(value => console.log(JSON.stringify(value))).catch((error: unknown) => {
    console.error(JSON.stringify({ ok: false, error: String(error).slice(0, 2048),
      recovery: "Preserve retained attempt/project files; an error is not rollback or publication approval." }));
    process.exitCode = 1;
  });
